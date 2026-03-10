"""
phone_scraper.py — Парсинг товаров 95fen через реальный Android-телефон.

Подключается по USB, управляет UI через uiautomator2,
извлекает данные из dump_hierarchy() и делает скриншоты.
"""

import re
import time
import subprocess
import os
import hashlib
import json
from pathlib import Path
from rich.console import Console

from models.product import Product
from utils.helpers import normalize_url, extract_product_id
from utils.ui_parser import extract_texts_from_xml, parse_texts_to_product
from config import (
    SCREENSHOTS_DIR, PRODUCTS_DIR, IMAGES_DIR,
    APP_PACKAGE, APP_ACTIVITY,
    WAIT_PAGE_LOAD, WAIT_AFTER_SWIPE, WAIT_CAROUSEL,
    MAX_SCROLLS, MAX_CAROUSEL_PHOTOS,
)

console = Console()


class PhoneScraper:
    """Парсер товаров через реальный телефон + UI автоматизация."""

    def __init__(self):
        self.device = None
        self._ready = False
        self._serial = None
        self._screen_w = 1080
        self._screen_h = 2340

    # ──────────────────────────────────────────────
    #  Подключение
    # ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Подключиться к телефону."""
        if self._ready:
            return True

        try:
            import uiautomator2 as u2
        except ImportError:
            console.print("[red]pip install uiautomator2[/red]")
            return False

        # Проверяем ADB
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        devices = [
            l for l in result.stdout.splitlines()[1:]
            if "\tdevice" in l and "emulator" not in l.lower()
        ]
        if not devices:
            console.print("[red]Телефон не найден. Проверь USB и USB-отладку.[/red]")
            return False

        self._serial = devices[0].split("\t")[0]
        console.print(f"[cyan]Устройство: {self._serial}[/cyan]")

        try:
            self.device = u2.connect(self._serial)
            info = self.device.info
            console.print(f"[green]Подключено: {info.get('productName', self._serial)}[/green]")
        except Exception as e:
            console.print(f"[red]u2.connect() ошибка: {e}[/red]")
            console.print("[dim]Попробуй: python -m uiautomator2 init[/dim]")
            return False

        # Запоминаем размер экрана
        info = self.device.info
        self._screen_w = info.get("displayWidth", 1080)
        self._screen_h = info.get("displayHeight", 2340)

        # Определяем touch-устройство (ищем /dev/input/eventX с ABS_MT_POSITION_X=0x0035)
        self._touch_dev = self._find_touch_device()

        # Экран не гасить
        subprocess.run(["adb", "-s", self._serial, "shell", "svc", "power", "stayon", "true"], capture_output=True)
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "settings", "put", "system", "screen_off_timeout", "600000"],
            capture_output=True,
        )

        # Разблокировать
        if not info.get("screenOn", True):
            self.device.screen_on()
            time.sleep(0.5)
            self._adb_swipe(0.5, 0.8, 0.5, 0.2)
            time.sleep(1)

        self._ready = True
        return True

    def check(self) -> dict:
        """Диагностика: телефон, ADB, приложение."""
        status = {"adb": False, "phone": None, "app_installed": False, "u2": False}

        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        devices = [l for l in result.stdout.splitlines()[1:] if "\tdevice" in l]
        status["adb"] = len(devices) > 0

        if status["adb"]:
            model = subprocess.run(
                ["adb", "shell", "getprop", "ro.product.model"],
                capture_output=True, text=True,
            )
            status["phone"] = model.stdout.strip()

            pkgs = subprocess.run(
                ["adb", "shell", "pm", "list", "packages"],
                capture_output=True, text=True,
            )
            status["app_installed"] = APP_PACKAGE in pkgs.stdout

            try:
                import uiautomator2 as u2
                d = u2.connect()
                d.info
                status["u2"] = True
            except Exception:
                pass

        return status

    # ──────────────────────────────────────────────
    #  Парсинг одного товара
    # ──────────────────────────────────────────────

    def scrape(self, url: str) -> Product | None:
        """Парсит один товар: открывает → читает UI → скриншотит → возвращает Product."""
        if not self._ready and not self.connect():
            return None

        # --- 1. Нормализуем URL (резолвим короткие ссылки) ---
        normalized = normalize_url(url)
        console.print(f"[dim]→ {normalized}[/dim]")

        product_id = extract_product_id(normalized) or extract_product_id(url) or hashlib.md5(url.encode()).hexdigest()[:8]
        console.print(f"[cyan]Товар: {product_id}[/cyan]")

        # Папки
        shot_dir = SCREENSHOTS_DIR / product_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        prod_dir = PRODUCTS_DIR / product_id
        prod_dir.mkdir(parents=True, exist_ok=True)

        # Открываем H5 URL в браузере
        result = subprocess.run(
            ["adb", "-s", self._serial, "shell", "am", "start",
             "-a", "android.intent.action.VIEW", "-d", normalized],
            capture_output=True, text=True,
        )
        console.print(f"[dim]  adb: {result.stdout.strip() or 'ok'}[/dim]")
        time.sleep(WAIT_PAGE_LOAD)

        # --- 2. Читаем тексты (первый экран) ---
        xml = self._dump()
        if not xml:
            console.print("[yellow]Пусто — жду ещё...[/yellow]")
            time.sleep(4)
            xml = self._dump()
        if not xml:
            console.print("[red]UI dump не удался[/red]")
            self._go_back()
            return None

        texts_all = extract_texts_from_xml(xml)
        console.print(f"[dim]  Экран 1: {len(texts_all)} текстов[/dim]")

        # Определяем количество фото в карусели из текстов (паттерн "1/9")
        carousel_total = self._detect_carousel_count(texts_all)
        console.print(f"[dim]  Фото в карусели: {carousel_total}[/dim]")

        # --- 3. Скачиваем фото карусели через long press → "Скачать" ---
        img_dir = IMAGES_DIR / product_id
        img_dir.mkdir(parents=True, exist_ok=True)
        photo_paths = self._download_carousel_images(img_dir, carousel_total)
        console.print(f"[dim]  Скачано фото: {len(photo_paths)}[/dim]")

        # Фильтр системного мусора Chrome
        CHROME_NOISE = {
            "Веб-версия", "Перейти на главную страницу", "Подключение защищено",
            "Новая вкладка", "Настройка и управление Google Chrome",
            "Обзор.", "Назад", "Главный экран", "Не беспокоить",
            "SIM-карта отсутствует.", "Надежный сигнал Wi-Fi.",
        }
        texts_all = [
            t for t in texts_all
            if t["text"] not in CHROME_NOISE
            and not t["text"].startswith("Посмотреть ")
            and not t["text"].startswith("Уведомление ")
            and not t["text"].startswith("Зарядка батареи")
            and not re.match(r'^\d{1,2}:\d{2}$', t["text"])
        ]
        console.print(f"[dim]  Итого текстов: {len(texts_all)}[/dim]")
        console.print("[dim]  -> " + " | ".join(t["text"][:25] for t in texts_all[:12]) + "[/dim]")

        # --- 5. Сохраняем сырые тексты ---
        (prod_dir / "ui_texts.json").write_text(
            json.dumps(texts_all, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # --- 6. Парсим ---
        product = parse_texts_to_product(texts_all, normalized, product_id)
        product.local_images = photo_paths

        # Сохраняем JSON товара
        product_path = prod_dir / "product.json"
        product_path.write_text(
            json.dumps(product.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # --- 7. Назад ---
        self._go_back()

        return product

    # ──────────────────────────────────────────────
    #  Вспомогательные методы
    # ──────────────────────────────────────────────

    def _find_touch_device(self) -> str:
        """Находит /dev/input/eventX тачскрина по наличию ABS_MT_POSITION_X (0x0035)."""
        result = subprocess.run(
            ["adb", "-s", self._serial, "shell", "getevent -p 2>/dev/null"],
            capture_output=True, text=True,
        )
        current_dev = "/dev/input/event3"  # fallback
        for line in result.stdout.splitlines():
            if line.startswith("add device"):
                current_dev = line.split(":")[-1].strip()
            elif "0035" in line:
                console.print(f"[dim]  Touch device: {current_dev}[/dim]")
                return current_dev
        return current_dev

    def _dump(self) -> str | None:
        """UI dump."""
        try:
            return self.device.dump_hierarchy()
        except Exception as e:
            console.print(f"[red]dump_hierarchy: {e}[/red]")
            return None

    # Устройство ввода тачскрина (определяется автоматически при connect)
    _touch_dev: str = "/dev/input/event3"

    def _adb_swipe(self, fx: float, fy: float, tx: float, ty: float, duration_ms: int = 300):
        """Свайп с относительными координатами (0.0–1.0)."""
        self._adb_swipe_abs(
            int(fx * self._screen_w), int(fy * self._screen_h),
            int(tx * self._screen_w), int(ty * self._screen_h),
            duration_ms,
        )

    def _adb_swipe_abs(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
        """Свайп через adb shell input swipe."""
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "swipe",
             str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            capture_output=True,
        )

    def _adb_tap(self, x: int, y: int):
        """Тап по координатам."""
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "tap", str(x), str(y)],
            capture_output=True,
        )

    def _adb_long_press(self, x: int, y: int, duration_ms: int = 1500):
        """Долгое нажатие — свайп на месте."""
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "swipe",
             str(x), str(y), str(x), str(y), str(duration_ms)],
            capture_output=True,
        )

    def _get_current_package(self) -> str:
        """Возвращает пакет приложения на переднем плане."""
        result = subprocess.run(
            ["adb", "-s", self._serial, "shell",
             "dumpsys", "window", "windows"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                m = re.search(r'([a-z][a-z0-9_.]+)/[^\s}]+', line)
                if m:
                    return m.group(1)
        return ""

    def _click_open_app_btn(self) -> bool:
        """Кликает кнопку '打开App' в браузере. Возвращает True если нашёл/кликнул."""
        # Шаг 1: пробуем найти через UI dump (иногда работает)
        xml = self._dump()
        if xml:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(xml, "lxml-xml")
            for node in soup.find_all("node"):
                text = (node.get("text") or node.get("content-desc") or "").strip()
                if "打开App" in text or "打开" in text:
                    bounds = node.get("bounds", "")
                    m = re.findall(r'\d+', bounds)
                    if len(m) >= 4:
                        cx = (int(m[0]) + int(m[2])) // 2
                        cy = (int(m[1]) + int(m[3])) // 2
                        console.print(f"[dim]  Tap '打开App' via UI dump: ({cx}, {cy})[/dim]")
                        subprocess.run(
                            ["adb", "-s", self._serial, "shell", "input", "tap", str(cx), str(cy)],
                            capture_output=True,
                        )
                        return True

        # Шаг 2: кликаем по координатам баннера (веб-элемент, не виден в UI dump)
        # Баннер "打开App" в Chrome: правый край экрана, ниже адресной строки
        # Chrome address bar: ~155px от верха, баннер ~80px высотой → центр y≈195
        # Кнопка справа: x≈(screen_w * 0.88)
        cx = int(self._screen_w * 0.88)
        cy = 195
        console.print(f"[dim]  Tap '打开App' по координатам: ({cx}, {cy})[/dim]")
        subprocess.run(
            ["adb", "-s", self._serial, "shell", "input", "tap", str(cx), str(cy)],
            capture_output=True,
        )
        # Не знаем сработало ли — возвращаем True, caller проверит пакет
        return True

    def _detect_carousel_count(self, texts: list[dict]) -> int:
        """Определяет количество фото в карусели из текстов типа '1/9'."""
        for t in texts:
            m = re.match(r'^1\s*/\s*(\d+)$', t["text"].strip())
            if m:
                return int(m.group(1))
        return MAX_CAROUSEL_PHOTOS

    def _list_downloads(self) -> set[str]:
        """Возвращает список файлов в /sdcard/Download/."""
        result = subprocess.run(
            ["adb", "-s", self._serial, "shell", "ls", "/sdcard/Download/"],
            capture_output=True, text=True,
        )
        return {f.strip() for f in result.stdout.splitlines() if f.strip()}

    def _click_download_menu_item(self) -> bool:
        """Ищет и кликает кнопку 'Скачать/Download image' в контекстном меню Chrome."""
        time.sleep(0.8)
        xml = self._dump()
        if not xml:
            return False

        from bs4 import BeautifulSoup as BS
        soup = BS(xml, "lxml-xml")
        download_kw = ["下载", "скачать", "сохранить", "download", "save image", "save"]
        for node in soup.find_all("node"):
            text = (node.get("text") or node.get("content-desc") or "").strip().lower()
            if any(kw in text for kw in download_kw):
                bounds = node.get("bounds", "")
                m = re.findall(r'\d+', bounds)
                if len(m) >= 4:
                    cx = (int(m[0]) + int(m[2])) // 2
                    cy = (int(m[1]) + int(m[3])) // 2
                    console.print(f"[dim]    клик '{node.get('text', '')}' @ ({cx},{cy})[/dim]")
                    self._adb_tap(cx, cy)
                    return True
        return False

    def _download_carousel_images(self, save_dir: Path, total_photos: int) -> list[str]:
        """
        Для каждого фото в карусели:
          1. Long press → "Скачать изображение"
          2. Pull из /sdcard/Download/ в save_dir
          3. Свайп к следующему фото
        Останавливается по счётчику или совпадению хеша.
        """
        img_x = self._screen_w // 2
        img_y = 555  # центр области изображения в браузере

        swipe_from_x = int(self._screen_w * 0.85)
        swipe_to_x   = int(self._screen_w * 0.15)

        existing_files = self._list_downloads()
        downloaded_hashes: set[str] = set()
        paths: list[str] = []

        # Один тап в начале — открываем full-screen вьювер
        console.print(f"[dim]  Открываем full-screen вьювер...[/dim]")
        self._adb_tap(img_x, img_y)
        time.sleep(1.5)

        for i in range(total_photos):
            console.print(f"[dim]  Фото {i + 1}/{total_photos}: long press → download...[/dim]")

            # Long press на полноразмерное фото → контекстное меню
            self._adb_long_press(img_x, self._screen_h // 2)

            # Ищем "Скачать"
            if not self._click_download_menu_item():
                console.print(f"[yellow]  Кнопка скачать не найдена, пропуск[/yellow]")
                # Закрываем меню тапом в угол
                self._adb_tap(50, 50)
                time.sleep(0.5)
            else:
                # Ждём загрузки файла
                time.sleep(2.5)

                new_files = self._list_downloads() - existing_files
                if new_files:
                    fname = sorted(new_files)[-1]  # последний новый файл
                    existing_files.add(fname)
                    ext = Path(fname).suffix or ".jpg"
                    local_path = str(save_dir / f"img_{i + 1:03d}{ext}")

                    result = subprocess.run(
                        ["adb", "-s", self._serial, "pull",
                         f"/sdcard/Download/{fname}", local_path],
                        capture_output=True, text=True,
                    )
                    if os.path.exists(local_path):
                        with open(local_path, "rb") as f:
                            h = hashlib.md5(f.read()).hexdigest()
                        if h in downloaded_hashes:
                            console.print("[dim]  Хеш совпал — все фото скачаны[/dim]")
                            os.remove(local_path)
                            break
                        downloaded_hashes.add(h)
                        paths.append(local_path)
                        console.print(f"[green]  Сохранено: {local_path}[/green]")
                    else:
                        console.print(f"[red]  pull failed: {result.stderr.strip()}[/red]")
                else:
                    console.print("[yellow]  Новых файлов нет, пропуск[/yellow]")

            # Свайп к следующему фото (внутри full-screen вьювера)
            if i < total_photos - 1:
                self._adb_swipe_abs(swipe_from_x, self._screen_h // 2, swipe_to_x, self._screen_h // 2, duration_ms=400)
                time.sleep(1.2)

        return paths

    def _swipe_carousel(self, save_dir: Path) -> list[str]:
        """Свайпит карусель фото и скриншотит каждое."""
        paths = []
        prev_hash = None

        for i in range(MAX_CAROUSEL_PHOTOS):
            # Свайп влево в верхней части экрана (карусель)
            self._adb_swipe(0.8, 0.25, 0.2, 0.25, duration_ms=300)
            time.sleep(WAIT_CAROUSEL)

            path = str(save_dir / f"photo_{i + 2:03d}.png")
            self.device.screenshot(path)

            # Сравниваем хеши — когда совпадут, карусель кончилась
            with open(path, "rb") as f:
                cur_hash = hashlib.md5(f.read()).hexdigest()

            if cur_hash == prev_hash:
                os.remove(path)
                break

            prev_hash = cur_hash
            paths.append(path)

        if paths:
            console.print(f"[dim]  Карусель: {len(paths)} фото[/dim]")

        return paths

    def _go_back(self):
        """Нажать кнопку назад."""
        try:
            self.device.press("back")
            time.sleep(1.5)
        except Exception:
            pass

    def cleanup(self):
        """Возвращает экран в нормальное состояние."""
        try:
            subprocess.run(
                ["adb", "shell", "svc", "power", "stayon", "false"],
                capture_output=True,
            )
        except Exception:
            pass
