"""
seller_scraper.py — Парсер товаров со страницы продавца 95fen.

Алгоритм (из guide.md):
  1. Подключиться к телефону
  2. Прочитать экран: найти карточки com.jiuwu:id/clContainer через lxml
  3. Кликнуть по каждой новой → extract_detail() → назад
  4. Скроллить вниз → повторить
  5. Стоп: 5 скроллов без новых карточек или достигнут лимит
"""

import re
import time
import json
import random
import logging
import hashlib
import os
import subprocess
from datetime import datetime
from pathlib import Path
from lxml import etree
from rich.console import Console

from config import PRODUCTS_DIR, APP_PACKAGE

log = logging.getLogger("seller_scraper")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler("scrape.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
console = Console()

OUTPUT_FILE = Path("output/products.json")


class SellerScraper:
    def __init__(self):
        self.d = None
        self._serial = None
        self._sw = 1080
        self._sh = 2340

    # ─────────────────────────────────────────────
    #  Подключение
    # ─────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            import uiautomator2 as u2
        except ImportError:
            console.print("[red]pip install uiautomator2[/red]")
            return False

        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        devices = [l for l in result.stdout.splitlines()[1:] if "\tdevice" in l and "emulator" not in l]
        if not devices:
            console.print("[red]Телефон не найден[/red]")
            return False

        self._serial = devices[0].split("\t")[0]
        self.d = u2.connect(self._serial)

        info = self.d.info
        self._sw = info.get("displayWidth", 1080)
        self._sh = info.get("displayHeight", 2340)
        console.print(f"[green]Подключено: {info.get('productName', self._serial)} ({self._sw}x{self._sh})[/green]")

        # Экран не гасить
        self.d.shell("svc power stayon true")
        self.d.shell("settings put system screen_off_timeout 2147483647")

        # Watchers — автоматически закрывать системные попапы MIUI
        for text in ["允许", "同意", "确定", "跳过", "以后再说", "知道了"]:
            self.d.watcher.when(f'[text="{text}"]').click()
        self.d.watcher.start()

        return True

    def check(self):
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        devices = [l for l in result.stdout.splitlines()[1:] if "\tdevice" in l]
        if not devices:
            console.print("[red]Телефон не найден[/red]")
            return
        model = subprocess.run(["adb", "shell", "getprop", "ro.product.model"],
                                capture_output=True, text=True).stdout.strip()
        pkgs = subprocess.run(["adb", "shell", "pm", "list", "packages"],
                               capture_output=True, text=True).stdout
        app_ok = APP_PACKAGE in pkgs
        console.print(f"[green]Телефон: {model}[/green]")
        console.print(f"[{'green' if app_ok else 'red'}]95fen (com.jiuwu): {'установлен' if app_ok else 'НЕТ'}[/]")

    # ─────────────────────────────────────────────
    #  Поиск карточек товаров на экране
    # ─────────────────────────────────────────────

    def _dump(self) -> str | None:
        try:
            return self.d.dump_hierarchy()
        except Exception as e:
            log.warning(f"dump_hierarchy: {e}")
            return None

    # ─────────────────────────────────────────────
    #  Скачивание фото карусели
    # ─────────────────────────────────────────────

    def _list_media(self) -> set[str]:
        """Все медиафайлы в Download и DCIM (рекурсивно)."""
        r = subprocess.run(
            ["adb", "-s", self._serial, "shell",
             "find /sdcard/DCIM /sdcard/Download -type f \\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \\) 2>/dev/null"],
            capture_output=True, text=True,
        )
        return {f.strip() for f in r.stdout.splitlines() if f.strip()}

    def _adb_tap(self, x: int, y: int):
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "tap", str(x), str(y)],
            capture_output=True,
        )

    def _adb_long_press(self, x: int, y: int, ms: int = 1500):
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "swipe",
             str(x), str(y), str(x), str(y), str(ms)],
            capture_output=True,
        )

    def _adb_back(self):
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "keyevent", "4"],
            capture_output=True,
        )

    def _swipe_left(self):
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "swipe",
             str(int(self._sw * 0.85)), str(self._sh // 2),
             str(int(self._sw * 0.15)), str(self._sh // 2), "250"],
            capture_output=True,
        )
        time.sleep(1.5)

    def _longpress_and_save(self) -> bool:
        """Long press на центр экрана → ждём меню → тапаем '保存图片'."""
        cx, cy = self._sw // 2, self._sh // 2
        console.print("[dim]    Long press...[/dim]")
        self._adb_long_press(cx, cy, ms=1500)
        time.sleep(1.5)

        xml = self._dump()
        if not xml:
            return False

        root = etree.fromstring(xml.encode("utf-8"))
        for node in root.iter("node"):
            t = (node.get("text") or node.get("content-desc") or "").strip()
            if "保存图片" in t:
                bs = node.get("bounds", "")
                m  = re.findall(r'\d+', bs)
                if len(m) >= 4:
                    bx = (int(m[0]) + int(m[2])) // 2
                    by = (int(m[1]) + int(m[3])) // 2
                    console.print(f"[dim]    Тап '保存图片' @ ({bx},{by})[/dim]")
                    self._adb_tap(bx, by)
                    return True

        console.print("[yellow]    '保存图片' не найдено в меню[/yellow]")
        self._adb_back()
        return False

    def _pull_new_file(self, save_dir: Path, idx: int,
                       existing: set, seen_hash: set) -> str | None:
        """Ждёт новый медиафайл на телефоне и тянет его на хост."""
        time.sleep(3.0)
        new_files = self._list_media() - existing
        console.print(f"[dim]    Новых файлов: {len(new_files)}[/dim]")
        if not new_files:
            return None

        remote = sorted(new_files)[-1]
        existing.add(remote)
        ext   = Path(remote).suffix or ".jpg"
        local = str(save_dir / f"img_{idx:03d}{ext}")

        r = subprocess.run(
            ["adb", "-s", self._serial, "pull", remote, local],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            console.print(f"[red]    pull error: {r.stderr.strip()}[/red]")
            return None
        if not os.path.exists(local):
            return None

        with open(local, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()
        if h in seen_hash:
            os.remove(local)
            return None
        seen_hash.add(h)

        # Обрезаем верхние 10% (вотермарка) и конвертируем в RGB
        try:
            from PIL import Image
            with Image.open(local) as img:
                img.load()  # загружаем пиксели в память
                w, h_px = img.size
                crop_top = int(h_px * 0.10)
                img = img.crop((0, crop_top, w, h_px))
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")
            # Файл закрыт — теперь безопасно перезаписываем
            local_jpg = re.sub(r'\.[^.]+$', '.jpg', local)
            img.save(local_jpg, "JPEG", quality=95)
            if local_jpg != local:
                os.remove(local)
                local = local_jpg
        except Exception as e:
            console.print(f"[yellow]    crop error: {e}[/yellow]")

        return local

    def _download_images(self, product_id: str) -> list[str]:
        """
        1. Тап на фото (выше) → полноэкранный просмотр
        2. Long press → меню → 保存图片 → pull (главное фото)
        3. Свайп влево → читаем 卖家实拍图 1/N
        4. Для каждого из N: long press → 保存图片 → pull → свайп
        5. Back → выйти из просмотра. Back → выйти из карточки.
        """
        save_dir = PRODUCTS_DIR / product_id / "images"
        save_dir.mkdir(parents=True, exist_ok=True)

        existing  = self._list_media()
        seen_hash = set()
        paths     = []
        idx       = 1

        # Открываем полноэкранный просмотр
        console.print("[dim]  Открываем просмотр фото...[/dim]")
        self._adb_tap(self._sw // 2, int(self._sh * 0.15))
        time.sleep(2.0)

        # Главное фото
        if self._longpress_and_save():
            p = self._pull_new_file(save_dir, idx, existing, seen_hash)
            if p:
                paths.append(p)
                console.print(f"[dim]  Главное фото: {p}[/dim]")
                idx += 1

        # Свайп → доп. фото
        console.print("[dim]  Свайп к доп. фото...[/dim]")
        self._swipe_left()

        total = self._get_carousel_total()
        console.print(f"[dim]  Доп. фото: {total}[/dim]")

        for i in range(total):
            console.print(f"[dim]  Доп. фото {i+1}/{total}...[/dim]")
            if self._longpress_and_save():
                p = self._pull_new_file(save_dir, idx, existing, seen_hash)
                if p:
                    paths.append(p)
                    console.print(f"[dim]  Сохранено: {p}[/dim]")
                    idx += 1
            if i < total - 1:
                self._swipe_left()

        # Back — выходим из полноэкранного просмотра обратно в карточку товара
        console.print("[dim]  Выходим из просмотра...[/dim]")
        self._adb_back()
        time.sleep(1.0)

        console.print(f"[green]  Итого фото: {len(paths)}[/green]")
        return paths

    _CAPTCHA_KEYWORDS = [
        "验证", "滑动", "拼图", "人机验证", "安全验证", "请完成", "captcha", "滑块",
        "验证码", "请滑动", "拖动滑块", "完成验证", "点击验证", "安全检测",
        "请点击", "行为验证", "请按住", "智能验证",
    ]

    def _check_captcha(self, xml: str) -> bool:
        if not xml:
            return False
        return any(kw in xml for kw in self._CAPTCHA_KEYWORDS)

    _LOADER_CLASSES = {"android.widget.ProgressBar"}
    _LOADER_RID_KEYS = ("loading", "progress", "loader", "pbLoading", "pb_loading")

    def _wait_for_loader(self, timeout: int = 30):
        """Ждёт пока лоудер/спиннер исчезнет с экрана. Максимум timeout секунд."""
        for _ in range(timeout):
            xml = self._dump()
            if not xml:
                break
            root = etree.fromstring(xml.encode("utf-8"))
            found = False
            for node in root.iter("node"):
                cls = node.get("class", "")
                rid = node.get("resource-id", "").lower()
                if cls in self._LOADER_CLASSES:
                    found = True
                    break
                if any(k in rid for k in self._LOADER_RID_KEYS):
                    found = True
                    break
            if not found:
                return
            console.print("[dim]  Ждём загрузки...[/dim]")
            time.sleep(1)
        console.print("[yellow]  Лоудер не исчез за таймаут[/yellow]")

    def _captcha_check_and_wait(self) -> bool:
        """Делает dump, проверяет капчу, если есть — ждёт пока решат. Возвращает True если была капча."""
        xml = self._dump()
        if not self._check_captcha(xml or ""):
            return False
        console.print("\n[bold red]⚠ КАПЧА ОБНАРУЖЕНА[/bold red]")
        console.print("[yellow]Реши капчу на телефоне руками, потом нажми Enter здесь...[/yellow]")
        input()
        console.print("[green]Продолжаем...[/green]")
        return True

    def _wait_ready(self):
        """Ждёт исчезновения лоудера, затем проверяет капчу (повторяет если капча появилась после лоудера)."""
        self._wait_for_loader()
        while self._captcha_check_and_wait():
            self._wait_for_loader()

    def _wait_for_captcha_solved(self):
        console.print("\n[bold red]⚠ КАПЧА ОБНАРУЖЕНА[/bold red]")
        console.print("[yellow]Реши капчу на телефоне руками, потом нажми Enter здесь...[/yellow]")
        input()
        console.print("[green]Продолжаем...[/green]")
        time.sleep(2)

    def _find_cards(self) -> list[dict]:
        """Возвращает список карточек com.jiuwu:id/clContainer с экрана."""
        xml = self._dump()
        if not xml:
            return []

        root = etree.fromstring(xml.encode("utf-8"))
        content_top    = int(self._sh * 0.12)
        content_bottom = int(self._sh * 0.92)
        cards = []
        seen  = set()

        for node in root.iter("node"):
            if "clContainer" not in node.get("resource-id", ""):
                continue

            bs = node.get("bounds", "")
            if bs in seen:
                continue

            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bs)
            if not m:
                continue
            x1, y1, x2, y2 = int(m[1]), int(m[2]), int(m[3]), int(m[4])

            # Только в зоне контента
            if y1 < content_top or y2 > content_bottom:
                continue

            texts = []
            for child in node.iter("node"):
                t = (child.get("text") or "").strip()
                if not t:
                    continue
                # Убираем "д у б л и р о в а н н ы е" пробелы
                if re.match(r'^(.\s){3,}.$', t):
                    t = t.replace(" ", "")
                texts.append(t)

            if not texts:
                continue

            seen.add(bs)
            cards.append({
                "center": ((x1 + x2) // 2, (y1 + y2) // 2),
                "texts": texts,
                "key": bs,
            })

        return cards

    # ─────────────────────────────────────────────
    #  Извлечение данных со страницы товара
    # ─────────────────────────────────────────────

    def _get_carousel_total(self) -> int:
        """Делает свежий dump и ищет счётчик '卖家实拍图 X/N'."""
        xml = self._dump()
        if not xml:
            return 1
        root = etree.fromstring(xml.encode("utf-8"))
        for node in root.iter("node"):
            t = (node.get("text") or "").strip()
            # "卖家实拍图 1/3" или просто "1/3"
            m = re.search(r'(\d+)\s*/\s*(\d+)', t)
            if m:
                total = int(m.group(2))
                console.print(f"[dim]  Счётчик фото: '{t}' → итого {total}[/dim]")
                return total
        console.print("[yellow]  Счётчик фото не найден, считаем 1[/yellow]")
        return 1

    def _find_share_bounds(self, xml: str) -> str | None:
        """Ищет bounds кнопки «Поделиться» в XML по rid / content-desc / позиции."""
        root = etree.fromstring(xml.encode("utf-8"))

        # 1. По resource-id
        for node in root.iter("node"):
            rid = node.get("resource-id", "").lower()
            if any(kw in rid for kw in ("share", "ivshare", "iv_share", "btnshare")):
                return node.get("bounds", "")

        # 2. По content-desc
        for node in root.iter("node"):
            cd = (node.get("content-desc") or "").strip()
            if any(kw in cd for kw in ("分享", "Share", "share", "转发", "分享商品")):
                return node.get("bounds", "")

        # 3. Самый правый кликабельный/ImageView в верхней полосе экрана
        candidates = []
        for node in root.iter("node"):
            bs = node.get("bounds", "")
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bs)
            if not m:
                continue
            x1, y1, x2, y2 = int(m[1]), int(m[2]), int(m[3]), int(m[4])
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            if cx < self._sw * 0.7 or cy > self._sh * 0.13:
                continue
            cls = node.get("class", "")
            if node.get("clickable") == "true" or "ImageView" in cls or "Button" in cls:
                candidates.append((cx, bs))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            return candidates[0][1]

        return None

    def _read_clipboard(self) -> str | None:
        """Читает буфер обмена через uiautomator2 (ATX-агент обходит ограничения Android 10+)."""
        try:
            text = self.d.clipboard
            console.print(f"[dim]  Clipboard: {text!r}[/dim]")
            if text:
                m = re.search(r'https?://\S+', text)
                if m:
                    return m.group(0).strip()
                # Может быть весь текст и есть ссылка (без https)
                return text.strip() or None
        except Exception as e:
            log.warning(f"clipboard read via u2: {e}")
        return None

    def _get_product_url(self, xml: str) -> str | None:
        """
        1. Находит кнопку «Поделиться» на текущем экране.
        2. Тапает её → ждёт диалог шаринга.
        3. В диалоге ищет «复制链接» → тапает → читает буфер обмена.
        4. Закрывает диалог (Back) и возвращает URL.
        """
        share_bounds = self._find_share_bounds(xml)
        if not share_bounds:
            console.print("[yellow]  Кнопка поделиться не найдена[/yellow]")
            return None

        m = re.findall(r'\d+', share_bounds)
        sx = (int(m[0]) + int(m[2])) // 2
        sy = (int(m[1]) + int(m[3])) // 2
        console.print(f"[dim]  Тап «Поделиться» @ ({sx},{sy})[/dim]")
        self._adb_tap(sx, sy)
        time.sleep(2.5)

        xml2 = self._dump()
        if not xml2:
            self._adb_back()
            return None

        root2 = etree.fromstring(xml2.encode("utf-8"))

        # Ищем «复制链接» в диалоге (текст или content-desc)
        copy_link_tapped = False
        for node in root2.iter("node"):
            t = (node.get("text") or node.get("content-desc") or "").strip()
            if "复制链接" in t or ("复制" in t and "链接" in t):
                bs2 = node.get("bounds", "")
                m2 = re.findall(r'\d+', bs2)
                if len(m2) >= 4:
                    tx = (int(m2[0]) + int(m2[2])) // 2
                    ty = (int(m2[1]) + int(m2[3])) // 2
                    console.print(f"[dim]  Тап '复制链接' @ ({tx},{ty})[/dim]")
                    self._adb_tap(tx, ty)
                    time.sleep(2.0)   # ждём копирования в буфер
                    copy_link_tapped = True
                break

        url = None

        if copy_link_tapped:
            # Диалог закрывается сам после копирования — back не нужен
            url = self._read_clipboard()
        else:
            # 复制链接 не найдена — ищем URL прямо в XML диалога и закрываем диалог
            for node in root2.iter("node"):
                t = (node.get("text") or "").strip()
                m_url = re.search(r'https?://\S+', t)
                if m_url:
                    url = m_url.group(0)
                    break
            self._adb_back()
            time.sleep(1.0)

        if url:
            url = url.rstrip("\x00").strip()
            console.print(f"[dim]  URL товара: {url}[/dim]")
        else:
            console.print("[yellow]  URL товара не найден[/yellow]")

        return url

    def _open_popup(self) -> tuple[list[dict], str | None]:
        """
        Тапает tvAttributes → открывает попап вариантов.
        Возвращает (кандидаты, текст_изначально_выбранного).
        Попап остаётся открытым после возврата.
        """
        # Ждём пока tvAttributes появится на странице (страница может ещё грузиться)
        attr_bounds = None
        for attempt in range(6):
            xml = self._dump()
            if xml:
                root = etree.fromstring(xml.encode("utf-8"))
                for node in root.iter("node"):
                    if "tvAttributes" in node.get("resource-id", ""):
                        attr_bounds = node.get("bounds", "")
                        break
            if attr_bounds:
                break
            console.print(f"[dim]  tvAttributes не найден, ждём... ({attempt+1}/6)[/dim]")
            time.sleep(1.5)

        if not attr_bounds:
            console.print("[yellow]  tvAttributes не найден, попап не открываем[/yellow]")
            return [], None

        m = re.findall(r'\d+', attr_bounds)
        ax = (int(m[0]) + int(m[2])) // 2
        ay = (int(m[1]) + int(m[3])) // 2
        self._adb_tap(ax, ay)
        time.sleep(2.0)

        xml2 = self._dump()
        if not xml2:
            return [], None

        root2 = etree.fromstring(xml2.encode("utf-8"))

        _NOT_VARIANT = {"确认", "取消", "关闭", ""}
        candidates = []
        initial_selected = None

        for node in root2.iter("node"):
            if "tvGoodSize" not in node.get("resource-id", ""):
                continue
            t = (node.get("text") or "").strip()
            if not t or t in _NOT_VARIANT:
                continue
            if node.get("selected") == "true":
                initial_selected = t
            candidates.append({"text": t, "bounds": node.get("bounds", ""), "price": None})

        console.print(f"[dim]  Попап: {len(candidates)} кандидатов, выбран: {initial_selected}[/dim]")
        return candidates, initial_selected

    def _tap_confirm(self):
        """Ищет кнопку «确认» в попапе и тапает её."""
        xml = self._dump()
        if not xml:
            return
        root = etree.fromstring(xml.encode("utf-8"))
        for node in root.iter("node"):
            if (node.get("text") or "").strip() == "确认":
                bm = re.findall(r'\d+', node.get("bounds", ""))
                if len(bm) >= 4:
                    cx2 = (int(bm[0]) + int(bm[2])) // 2
                    cy2 = (int(bm[1]) + int(bm[3])) // 2
                    console.print(f"[dim]  Тап «确认» @ ({cx2},{cy2})[/dim]")
                    self._adb_tap(cx2, cy2)
                break

    def _extract_all_variants(self) -> list[dict]:
        """
        Алгоритм:
        1. Открыть попап, запомнить initial_selected.
        2. Сразу обработать initial_selected (уже выбран → 确认 → парсить).
        3. Переоткрыть попап, сканировать оставшихся кандидатов:
           - Пропускаем initial_selected (уже обработан).
           - Тапаем остальных: если selected сменился → доступен → 确认 → парсить → переоткрыть.
           - Не сменился → недоступен.
        """
        candidates, initial_selected = self._open_popup()
        self._wait_ready()

        if not candidates:
            detail = self._extract_detail()
            return [detail] if detail else []

        results    = []
        popup_open = True

        def _confirm_and_extract(variant_text: str) -> dict | None:
            nonlocal popup_open
            self._tap_confirm()
            popup_open = False
            self._wait_ready()
            detail = self._extract_detail()
            if detail:
                detail["variant"] = variant_text
                base_id = detail.get("product_id") or f"item_{int(time.time())}"
                safe_var = re.sub(r'[^\w]', '_', variant_text)[:20]
                detail["product_id"] = f"{base_id}_{safe_var}"
            return detail

        # Шаг 1: обрабатываем initial_selected — он уже выбран, сразу 确認
        if initial_selected:
            console.print(f"\n[cyan]  Вариант (default): {initial_selected}[/cyan]")
            detail = _confirm_and_extract(initial_selected)
            if detail:
                results.append(detail)

        # Шаг 2: переоткрываем попап и ищем остальные доступные варианты
        candidates, _ = self._open_popup()
        self._wait_ready()
        popup_open = True
        last_selected = initial_selected

        for i, c in enumerate(candidates):
            # Пропускаем уже обработанный вариант
            if c["text"] == initial_selected:
                console.print(f"[dim]  ✓ '{c['text']}' уже обработан[/dim]")
                continue

            m = re.findall(r'\d+', c["bounds"])
            if len(m) < 4:
                continue

            tx = (int(m[0]) + int(m[2])) // 2
            ty = (int(m[1]) + int(m[3])) // 2
            self._adb_tap(tx, ty)
            time.sleep(0.8)

            xml = self._dump()
            if not xml:
                continue

            root = etree.fromstring(xml.encode("utf-8"))
            new_selected = next(
                ((node.get("text") or "").strip()
                 for node in root.iter("node")
                 if "tvGoodSize" in node.get("resource-id", "")
                 and node.get("selected") == "true"),
                None,
            )

            if new_selected and new_selected != last_selected:
                last_selected = new_selected
                console.print(f"\n[cyan]  Вариант: {new_selected}[/cyan]")
                detail = _confirm_and_extract(new_selected)
                if detail:
                    results.append(detail)
                # Переоткрываем попап если есть ещё кандидаты
                if i + 1 < len(candidates):
                    candidates, _ = self._open_popup()
                    self._wait_ready()
                    popup_open = True
            else:
                console.print(f"[dim]  ✗ '{c['text']}' недоступен[/dim]")

        if popup_open:
            self._adb_back()
            time.sleep(0.5)

        return results

    def _extract_detail(self) -> dict:
        """Читает страницу товара по известным resource-id."""
        self._wait_ready()
        xml = self._dump()
        if not xml:
            return {}

        root = etree.fromstring(xml.encode("utf-8"))

        # Собираем все узлы с текстом
        nodes = []
        for node in root.iter("node"):
            t = (node.get("text") or "").strip()
            if not t:
                continue
            nodes.append({
                "text": t,
                "rid":  node.get("resource-id", ""),
                "bounds": node.get("bounds", ""),
            })


        def first(rid_key):
            return next((n["text"] for n in nodes if rid_key in n["rid"]), None)

        def all_texts(rid_key):
            return [n["text"] for n in nodes if rid_key in n["rid"]]

        # Цена: tvGoodPrice внутри tv_price (чистое число)
        price = None
        raw_price = first("tv_price")
        if raw_price:
            try:
                price = float(raw_price.replace(",", ""))
            except ValueError:
                pass

        # Характеристики: tvOptionDesc (значения) + tvOptionTitle (названия)
        # Идут парами: сначала все desc, потом все title — совмещаем по порядку
        descs  = all_texts("tvOptionDesc")
        titles = all_texts("tvOptionTitle")
        specs  = {t: d for t, d in zip(titles, descs) if t != "主货号"}

        # Атрибуты из tvAttributes (цвет, размер, комплект) — убираем лишние пробелы
        attributes = first("tvAttributes")
        if attributes:
            attributes = re.sub(r'\s+', ' ', attributes).strip()

        # URL товара через кнопку «Поделиться»
        product_url = self._get_product_url(xml)

        # product_id: из URL (id=XXXXX) или из заголовка
        product_id = None
        if product_url:
            m_id = re.search(r'[?&]id=(\d+)', product_url)
            if m_id:
                product_id = m_id.group(1)
        if not product_id:
            product_id = re.sub(r'[^\w]', '_', first("tvGoodTitle") or "")[:40] or f"item_{int(time.time())}"

        # Скачиваем фото карусели
        photos = self._download_images(product_id)

        result = {
            "product_id":  product_id,
            "url":         product_url,
            "title":       first("tvGoodTitle"),
            "price":       price,
            "condition":   first("tvGoodsInfo"),
            "attributes":  attributes,
            "specs":       specs,
            "images":      photos,
            "scraped_at":  datetime.now().isoformat(),
        }

        return result

    # ─────────────────────────────────────────────
    #  Главный цикл
    # ─────────────────────────────────────────────

    def run(self, max_products: int = 200):
        """
        Парсит все товары со страницы продавца открытой на телефоне.
        Следует паттерну из guide.md: find_cards → click → extract → back → scroll.
        """
        console.print("[bold]Начинаем парсинг. Страница продавца должна быть открыта.[/bold]\n")

        products     = []
        visited      = set()   # ключи уже обработанных карточек
        no_new_count = 0       # скроллы без новых карточек

        while len(products) < max_products and no_new_count < 5:

            # Ждём лоудер + капча перед каждой итерацией
            self._wait_ready()

            cards     = self._find_cards()
            new_cards = [c for c in cards if c["key"] not in visited]

            if not new_cards:
                no_new_count += 1
                console.print(f"[dim]Нет новых карточек ({no_new_count}/5), скроллим...[/dim]")
                self.d.swipe(self._sw // 2, int(self._sh * 0.75),
                             self._sw // 2, int(self._sh * 0.25), duration=0.4)
                time.sleep(random.uniform(1.5, 2.5))
                continue

            no_new_count = 0

            for card in new_cards:
                if len(products) >= max_products:
                    break

                visited.add(card["key"])
                cx, cy = card["center"]

                preview = " | ".join(card["texts"][:3])
                console.print(f"\n[cyan]#{len(products)+1}[/cyan] {preview}")

                self.d.click(cx, cy)

                # Ждём загрузки карточки, лоудера и возможной капчи
                self._wait_ready()

                details = self._extract_all_variants()

                for detail in details:
                    products.append(detail)
                    log.info(
                        f"#{len(products)}: {(detail.get('title') or '?')[:50]} "
                        f"[{detail.get('variant', '')}] "
                        f"— ¥{detail.get('price', '?')} | {detail.get('condition', '')}"
                    )

                # Выходим из карточки товара обратно на страницу продавца
                self._adb_back()
                time.sleep(random.uniform(1.5, 2.5))

            # Checkpoint каждые 10 товаров
            if len(products) % 10 == 0 and products:
                self._save(products)

            # Скролл вниз
            self.d.swipe(self._sw // 2, int(self._sh * 0.75),
                         self._sw // 2, int(self._sh * 0.25), duration=0.4)
            time.sleep(random.uniform(1.0, 2.0))

        self._save(products)
        console.print(f"\n[bold green]Готово: {len(products)} товаров → {OUTPUT_FILE}[/bold green]")

    def _save(self, products: list[dict]):
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps(products, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
