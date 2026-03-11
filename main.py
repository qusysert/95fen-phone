#!/usr/bin/env python3
"""
95fen Scraper

Использование:
    python main.py --url "https://95b.co/d/2AkKJ"
    python main.py --file urls.txt
"""

import argparse
import json
import time
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

from config import PRODUCTS_JSON, WAIT_BETWEEN_PRODUCTS, PRODUCTS_DIR
from models.product import Product
from utils.helpers import normalize_url, extract_product_id

console = Console()


def load_urls(file_path: str) -> list[str]:
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]Файл не найден: {file_path}[/red]")
        sys.exit(1)
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def save_all_products(products: list[Product]):
    data = [p.model_dump() for p in products]
    PRODUCTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    console.print(f"\n[green bold]Сохранено: {PRODUCTS_JSON}[/green bold]")


def print_summary(products: list[Product], total: int):
    table = Table(title="Итоги")
    table.add_column("", style="cyan")
    table.add_column("", style="green")
    table.add_row("Всего", str(total))
    table.add_row("Успешно", str(len(products)))
    table.add_row("С ценой", str(sum(1 for p in products if p.price.current)))
    table.add_row("С названием", str(sum(1 for p in products if p.title)))
    table.add_row("Фото", str(sum(len(p.local_images) for p in products)))
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="95fen Scraper")
    parser.add_argument("--url", nargs="+", help="URL или короткая ссылка товара (можно несколько)")
    parser.add_argument("--file", help="Файл со списком URL (один на строку)")
    parser.add_argument("--delay", type=float, default=WAIT_BETWEEN_PRODUCTS,
                        help=f"Пауза между товарами, сек (по умолчанию {WAIT_BETWEEN_PRODUCTS})")
    parser.add_argument("--crawl", action="store_true",
                        help="Режим краулера: рекурсивно парсить рекомендации")
    parser.add_argument("--max-items", type=int, default=50,
                        help="Максимум товаров при --crawl (по умолчанию 50)")
    parser.add_argument("--rec-count", type=int, default=3,
                        help="Сколько рекомендаций брать с каждой страницы (по умолчанию 3)")
    args = parser.parse_args()

    if not args.url and not args.file:
        parser.print_help()
        sys.exit(1)

    urls = []
    if args.url:
        urls.extend(args.url)
    if args.file:
        urls.extend(load_urls(args.file))

    if not urls:
        console.print("[red]Нет URL для парсинга[/red]")
        sys.exit(1)

    from scraper.browser_scraper import BrowserScraper
    scraper = BrowserScraper(headless=False)
    scraper.start()

    products = []

    if args.crawl:
        console.print(f"[bold]95fen Crawler: {len(urls)} стартовых URL, макс. {args.max_items} товаров[/bold]")

        visited: set[str] = set()
        # Пропускаем уже скачанные товары из предыдущих запусков
        for existing in PRODUCTS_DIR.iterdir() if PRODUCTS_DIR.exists() else []:
            if existing.is_dir():
                visited.add(existing.name)

        queue: list[str] = list(urls)
        total_attempted = 0

        try:
            while queue and len(products) < args.max_items:
                url = queue.pop(0)
                normalized = normalize_url(url)
                product_id = extract_product_id(normalized)

                if product_id and product_id in visited:
                    console.print(f"[dim]Пропуск (уже обработан): {product_id}[/dim]")
                    continue
                if product_id:
                    visited.add(product_id)

                total_attempted += 1
                console.print(f"\n{'=' * 50}")
                console.print(f"[bold cyan]Краулер [{len(products)+1}/{args.max_items}]: {url}[/bold cyan]")

                scraped = scraper.scrape(url, rec_count=args.rec_count)

                if scraped:
                    for product in scraped:
                        if product.title or product.price.current:
                            products.append(product)
                    label = scraped[0].title or '?'
                    console.print(f"[green]✓ {label} — {len(scraped)} вариант(ов)[/green]")
                else:
                    console.print("[red]✗ Не удалось[/red]")

                for rec_url in scraper.last_recommendations:
                    rec_id = extract_product_id(normalize_url(rec_url))
                    if rec_id and rec_id not in visited:
                        queue.append(rec_url)

                if queue and len(products) < args.max_items:
                    console.print(f"[dim]Пауза {args.delay}с... (очередь: {len(queue)})[/dim]")
                    time.sleep(args.delay)

        except KeyboardInterrupt:
            console.print("\n[yellow]Прервано пользователем[/yellow]")
        finally:
            scraper.stop()

        if products:
            save_all_products(products)
        print_summary(products, total_attempted)

    else:
        console.print(f"[bold]95fen Scraper: {len(urls)} товаров[/bold]")

        try:
            for i, url in enumerate(urls):
                console.print(f"\n{'=' * 50}")
                console.print(f"[bold cyan]{i + 1}/{len(urls)}: {url}[/bold cyan]")

                scraped = scraper.scrape(url)

                if scraped:
                    for product in scraped:
                        if product.title or product.price.current:
                            products.append(product)
                    label = scraped[0].title or '?'
                    console.print(f"[green]✓ {label} — {len(scraped)} вариант(ов)[/green]")
                else:
                    console.print("[red]✗ Не удалось[/red]")

                if i < len(urls) - 1:
                    console.print(f"[dim]Пауза {args.delay}с...[/dim]")
                    time.sleep(args.delay)

        except KeyboardInterrupt:
            console.print("\n[yellow]Прервано пользователем[/yellow]")
        finally:
            scraper.stop()

        if products:
            save_all_products(products)
        print_summary(products, len(urls))


if __name__ == "__main__":
    main()
