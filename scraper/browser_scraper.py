"""
browser_scraper.py — Парсинг товаров 95fen через Playwright (браузер на хосте).

Открывает H5 страницу товара в Chromium, ждёт загрузки,
извлекает данные и скачивает картинки напрямую с CDN.
Если появляется капча — ждёт пока пользователь решит вручную.
Если есть варианты (размер/комплектация) — кликает каждый и собирает отдельно.
"""

import json
import re
import time
import hashlib
import urllib.parse
import urllib.request
from pathlib import Path

from rich.console import Console

from models.product import Product
from utils.helpers import normalize_url, extract_product_id
from config import PRODUCTS_DIR, IMAGES_DIR

console = Console()

# Мобильный user-agent — получаем мобильную версию сайта
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 10; Redmi Note 9) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

# Признаки капчи в DOM
CAPTCHA_SELECTORS = [
    "iframe[src*='captcha']",
    "iframe[src*='recaptcha']",
    ".captcha",
    "#captcha",
    "[class*='captcha']",
    "[class*='verify']",
    "taro-text-core[class*='verify']",
]


class BrowserScraper:
    """Парсер товаров 95fen через Playwright."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self.last_recommendations: list[str] = []

    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MOBILE_UA,
            device_scale_factor=2,
        )
        self._context.set_default_timeout(30_000)

    def stop(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def scrape(self, url: str, rec_count: int = 0) -> list[Product]:
        """Возвращает список продуктов (несколько если есть варианты).

        rec_count > 0 — извлекать рекомендации (доступны через self.last_recommendations).
        """
        if not self._browser:
            self.start()

        self.last_recommendations = []

        normalized = normalize_url(url)
        product_id = extract_product_id(normalized) or hashlib.md5(url.encode()).hexdigest()[:8]
        console.print(f"[cyan]Товар: {product_id}[/cyan]")
        console.print(f"[dim]→ {normalized[:80]}[/dim]")

        prod_dir = PRODUCTS_DIR / product_id
        prod_dir.mkdir(parents=True, exist_ok=True)
        img_dir = IMAGES_DIR / product_id
        img_dir.mkdir(parents=True, exist_ok=True)

        page = self._context.new_page()
        try:
            return self._scrape_page(page, normalized, product_id, prod_dir, img_dir, rec_count=rec_count)
        finally:
            page.close()

    def _scrape_page(self, page, url: str, product_id: str, prod_dir: Path, img_dir: Path, rec_count: int = 0) -> list[Product]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            pass  # продолжаем — _wait_for_content дождётся рендера
        self._wait_for_content(page)
        self._handle_captcha(page)

        # Базовые данные (название, цена, фото, тексты)
        data = self._extract_data(page, url)
        if not data or not (data.get("title") or data.get("price") or data.get("image_urls")):
            console.print("[red]Не удалось извлечь данные — возможно страница не загрузилась[/red]")
            return []

        console.print(f"[dim]  Название: {(data.get('title') or '')[:60]}[/dim]")
        console.print(f"[dim]  Цена: {data.get('price')}  Фото: {len(data.get('image_urls', []))}[/dim]")

        # Сохраняем сырые данные
        (prod_dir / "raw_data.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Извлекаем рекомендации если нужно (до клика по вариантам — попап не перекрывает DOM)
        if rec_count > 0:
            self.last_recommendations = self._extract_recommendations(page, rec_count)
            if self.last_recommendations:
                console.print(f"[dim]  Рекомендации: {len(self.last_recommendations)}[/dim]")

        # Проверяем наличие вариантов
        variants = self._scrape_variants(page, data, product_id, prod_dir, img_dir)
        if variants:
            console.print(f"[green]  Собрано вариантов: {len(variants)}[/green]")
            return variants

        # Нет вариантов — один товар
        local_images = self._download_images(data.get("image_urls", []), img_dir)
        product = self._build_product(product_id, url, data, local_images)

        (prod_dir / "product.json").write_text(
            json.dumps(product.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return [product]

    def _wait_for_content(self, page):
        # Ждём пока появятся фото карусели товара
        try:
            page.wait_for_function(
                """() => document.querySelectorAll(
                    'taro-image-core.preview__main__img:not(.rotateX)'
                ).length > 0""",
                timeout=20_000,
            )
        except Exception:
            # Запасной вариант — ждём хотя бы цену
            try:
                page.wait_for_function(
                    "() => document.body.innerText.length > 1000",
                    timeout=10_000,
                )
            except Exception:
                pass
        time.sleep(1.5)

    def _handle_captcha(self, page):
        has_captcha = False
        for sel in CAPTCHA_SELECTORS:
            try:
                if page.locator(sel).count() > 0:
                    has_captcha = True
                    break
            except Exception:
                pass
        try:
            body = page.inner_text("body")
            if any(w in body for w in ["验证", "captcha", "robot", "verify"]):
                has_captcha = True
        except Exception:
            pass

        if has_captcha:
            console.print("[bold yellow]⚠ Обнаружена капча! Решите её в браузере и нажмите Enter...[/bold yellow]")
            input()
            time.sleep(2)
            self._wait_for_content(page)

    def _extract_data(self, page, url: str) -> dict | None:
        try:
            data = page.evaluate("""() => {
                // ── Картинки карусели ──────────────────────────────────────────
                const imgUrls = [];
                const seen = new Set();
                document.querySelectorAll('taro-image-core.preview__main__img:not(.rotateX)').forEach(imgEl => {
                    const src = imgEl.getAttribute('src');
                    if (!src) return;
                    const clean = src.split('?')[0];
                    if (!seen.has(clean)) { seen.add(clean); imgUrls.push(clean); }
                });

                // ── Все текстовые узлы ─────────────────────────────────────────
                const allTexts = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                    const t = node.textContent.trim();
                    if (t.length > 1) allTexts.push(t);
                }

                // ── Цена ───────────────────────────────────────────────────────
                let price = null;
                for (const el of document.querySelectorAll('[class*="price"],[class*="Price"]')) {
                    const m = el.innerText.match(/[\\d,]+(?:\\.\\d{1,2})?/);
                    if (m && parseFloat(m[0].replace(',','')) >= 50) {
                        price = parseFloat(m[0].replace(',',''));
                        break;
                    }
                }
                if (!price) {
                    const m = document.body.innerText.match(/¥\\s*([\\d,]+(?:\\.\\d{1,2})?)/);
                    if (m) price = parseFloat(m[1].replace(',',''));
                }

                // ── Название ───────────────────────────────────────────────────
                let title = null;
                const titleSelectors = [
                    '[class*="goodsName"],[class*="goods-name"],[class*="goods_name"]',
                    '[class*="title"],[class*="Title"]',
                    '[class*="name"],[class*="Name"]',
                ];
                for (const sel of titleSelectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        const t = el.innerText.trim();
                        if (t.length > 8 && !t.includes('95分App') && !t.includes('领¥')) {
                            if (!title || t.length > title.length) title = t;
                        }
                    }
                    if (title) break;
                }

                return {
                    all_texts: [...new Set(allTexts)],
                    image_urls: imgUrls,
                    price: price,
                    title: title,
                };
            }""")

            texts = data.get("all_texts", [])
            full_text = "\n".join(texts)

            if not data.get("price"):
                m = re.search(r'¥\s*([\d,]+(?:\.\d{1,2})?)', full_text)
                if m:
                    data["price"] = float(m.group(1).replace(",", ""))

            cond = re.search(r'(\d+(?:\.\d+)?成新|全新|未使用)', full_text)
            data["condition"] = cond.group(0) if cond else None

            size = re.search(r'(\d{2,3}(?:\.\d)?)\s*(?:码|EU|US)', full_text, re.IGNORECASE)
            data["size"] = size.group(0) if size else None

            color_match = re.search(r'(银色|黑色|白色|红色|蓝色|金色|粉色|灰色|绿色|棕色)', full_text)
            data["color"] = color_match.group(0) if color_match else None

            if not data.get("title"):
                candidates = [t for t in texts if 10 < len(t) < 120
                              and not re.match(r'^[\d\s¥.,]+$', t)
                              and '95' not in t and 'App' not in t]
                if candidates:
                    data["title"] = max(candidates, key=len)

            return data

        except Exception as e:
            console.print(f"[red]Ошибка извлечения данных: {e}[/red]")
            return None

    def _scrape_variants(self, page, base_data: dict, product_id: str, prod_dir: Path, img_dir: Path) -> list[Product]:
        """Кликает все доступные варианты товара и собирает данные для каждого."""
        selector_btn = page.locator('#same_style_rec_sku_change_info')
        if selector_btn.count() == 0:
            return []

        selector_btn.click()
        time.sleep(0.8)

        # Один из двух возможных селекторов элементов вариантов
        for item_selector in (
            '.same__style__modal__beauty__item:not(.disable)',
            '.same__style__modal__size__item:not(.disable)',
        ):
            count = page.locator(item_selector).count()
            if count > 0:
                break
        else:
            # Нет доступных вариантов — подтверждаем текущий выбор и парсим как обычный товар
            console.print("[dim]  Нет доступных вариантов — подтверждаем текущий[/dim]")
            confirm_btn = page.locator('.same__style__sure__button')
            if confirm_btn.count() > 0:
                confirm_btn.click()
                time.sleep(1.5)
            else:
                try:
                    page.locator('.popup-close-icon').first.click()
                except Exception:
                    pass
            return []

        console.print(f"[cyan]  Вариантов в наличии: {count}[/cyan]")

        products = []
        for i in range(count):
            if i > 0:
                # Ждём пока исчезнет loading overlay
                try:
                    page.wait_for_function(
                        "() => !document.querySelector('#fen95-loading-wrap') || "
                        "document.querySelector('#fen95-loading-wrap').style.display === 'none' || "
                        "getComputedStyle(document.querySelector('#fen95-loading-wrap')).display === 'none'",
                        timeout=10_000,
                    )
                except Exception:
                    pass
                selector_btn.click()
                time.sleep(0.8)

            item = page.locator(item_selector).nth(i)
            item_texts = item.locator('taro-text-core').all_inner_texts()

            # Первый текст — label варианта ("银色 L 原盒装" или "37")
            # Второй текст (если есть и содержит цифры) — цена
            variant_label = item_texts[0].strip() if item_texts else f"вариант_{i+1}"
            price_text = item_texts[1].strip() if len(item_texts) > 1 else ""
            pm = re.search(r'[\d,]+(?:\.\d{1,2})?', price_text)
            variant_price = float(pm.group(0).replace(',', '')) if pm else base_data.get("price")

            console.print(f"[dim]  [{i+1}/{count}] {variant_label} — ¥{variant_price}[/dim]")

            item.click()
            time.sleep(0.4)
            confirm_btn = page.locator('.same__style__sure__button')
            if confirm_btn.count() > 0:
                confirm_btn.click()
            time.sleep(1.5)

            # URL: базовый + sku=label для уникальности в отчёте
            base_url = base_data.get("source_url", "")
            sku_param = urllib.parse.quote(variant_label, safe="")
            sep = "&" if ("?" in base_url.split("#", 1)[-1]) else "?"
            variant_url = base_url + sep + "sku=" + sku_param

            # Фото
            image_urls = page.evaluate("""() => {
                const imgUrls = [];
                const seen = new Set();
                document.querySelectorAll('taro-image-core.preview__main__img:not(.rotateX)').forEach(imgEl => {
                    const src = imgEl.getAttribute('src');
                    if (!src) return;
                    const clean = src.split('?')[0];
                    if (!seen.has(clean)) { seen.add(clean); imgUrls.push(clean); }
                });
                return imgUrls;
            }""")

            variant_img_dir = img_dir / f"v{i+1:02d}"
            variant_img_dir.mkdir(parents=True, exist_ok=True)
            local_images = self._download_images(image_urls, variant_img_dir)

            variant_id = f"{product_id}_v{i+1:02d}"
            product = Product(
                product_id=variant_id,
                source_url=variant_url,
                raw_data={**base_data, "variant_label": variant_label},
                scrape_method="browser_scraper",
            )
            product.title = base_data.get("title") or ""
            product.price.current = variant_price
            product.specs.condition = base_data.get("condition")
            product.specs.color = base_data.get("color")
            product.specs.size = variant_label
            product.specs.extra["variant_label"] = variant_label
            product.image_urls = image_urls
            product.local_images = local_images

            variant_dir = prod_dir / f"v{i+1:02d}"
            variant_dir.mkdir(parents=True, exist_ok=True)
            (variant_dir / "product.json").write_text(
                json.dumps(product.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            products.append(product)

        return products

    def _extract_recommendations(self, page, limit: int = 3) -> list[str]:
        """Извлекает goodsId первых N товаров из блока рекомендаций."""
        # Скроллим вниз порциями — блок рекомендаций lazy-loaded (~4 высоты экрана)
        for step in range(1, 5):
            page.evaluate(f"window.scrollBy(0, 844)")
            time.sleep(0.6)
        time.sleep(0.5)

        ids = page.evaluate("""(limit) => {
            const items = document.querySelectorAll('.goods__item__wrap[id^="item_"]');
            const result = [];
            for (const el of items) {
                const gid = el.id.replace('item_', '');
                if (/^\d+$/.test(gid)) result.push(gid);
                if (result.length >= limit) break;
            }
            return result;
        }""", limit)
        return [f"https://h5.95fenapp.com/#/pages/newDetail/index?id={gid}" for gid in ids]

    def _build_product(self, product_id: str, url: str, data: dict, local_images: list[str]) -> Product:
        product = Product(
            product_id=product_id,
            source_url=url,
            raw_data=data,
            scrape_method="browser_scraper",
        )
        product.title = data.get("title") or ""
        if data.get("price"):
            product.price.current = data["price"]
        product.specs.condition = data.get("condition")
        product.specs.size = data.get("size")
        product.specs.color = data.get("color")
        product.description = data.get("description")
        product.image_urls = data.get("image_urls", [])
        product.local_images = local_images
        return product

    def _download_images(self, urls: list[str], img_dir: Path) -> list[str]:
        if not urls:
            return []

        paths = []
        seen_hashes: set[str] = set()

        for i, url in enumerate(urls):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": MOBILE_UA, "Referer": "https://h5.95fenapp.com/"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()

                h = hashlib.md5(data).hexdigest()
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)

                ct = resp.headers.get("Content-Type", "")
                if "webp" in ct or url.endswith(".webp"):
                    ext = ".webp"
                elif "png" in ct or url.endswith(".png"):
                    ext = ".png"
                else:
                    ext = ".jpg"

                path = img_dir / f"img_{len(paths) + 1:03d}{ext}"
                path.write_bytes(data)
                paths.append(str(path))
                console.print(f"[dim]  img {len(paths)}: {path.name} ({len(data)//1024}KB)[/dim]")

            except Exception as e:
                console.print(f"[dim]  Ошибка скачивания {url[:60]}: {e}[/dim]")

        console.print(f"[green]  Скачано {len(paths)} фото[/green]")
        return paths
