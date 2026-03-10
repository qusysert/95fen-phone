#!/usr/bin/env python3
"""
95fen Phone Scraper — Парсер товаров через реальный Android-телефон.

Использование:
    python main.py --check                           # проверка подключения
    python main.py --url 123456                      # один товар по ID
    python main.py --url "https://h5.95fenapp.com/goods/detail?id=123456"
    python main.py --file urls.txt                   # список товаров
    python main.py --file urls.txt --delay 5         # с паузой 5 сек
"""

import argparse
import json
import time
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

from config import PRODUCTS_JSON, WAIT_BETWEEN_PRODUCTS
from models.product import Product
from utils.helpers import normalize_url
from scraper.phone_scraper import PhoneScraper

console = Console()


def load_urls(file_path: str) -> list[str]:
    """Загружает URL из файла (один на строку, # = комментарий)."""
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]Файл не найден: {file_path}[/red]")
        sys.exit(1)

    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(normalize_url(line))
    return urls


def check_phone(scraper: PhoneScraper):
    """Диагностика подключения."""
    console.print("[bold]Проверка подключения...[/bold]\n")
    status = scraper.check()

    table = Table()
    table.add_column("Компонент", style="cyan")
    table.add_column("Статус")

    table.add_row("ADB", "[green]OK[/green]" if status["adb"] else "[red]НЕТ[/red]")
    table.add_row("Телефон", status["phone"] or "[red]не найден[/red]")
    table.add_row(
        "95fen (com.jiuwu)",
        "[green]установлен[/green]" if status["app_installed"] else "[red]НЕТ[/red]",
    )
    table.add_row(
        "uiautomator2",
        "[green]OK[/green]" if status["u2"] else "[yellow]не готов[/yellow]",
    )

    console.print(table)

    if not status["u2"]:
        console.print("\n[yellow]Для инициализации uiautomator2:[/yellow]")
        console.print("  python -m uiautomator2 init")

    if not status["app_installed"]:
        console.print("\n[yellow]Установи 95fen на телефон из магазина приложений[/yellow]")

    if all([status["adb"], status["phone"], status["app_installed"], status["u2"]]):
        console.print("\n[bold green]Всё готово! Можно парсить.[/bold green]")
        console.print("  python main.py --url 123456")


def save_all_products(products: list[Product]):
    """Сохраняет общий products.json."""
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
    table.add_row("Скриншотов", str(sum(len(p.local_images) for p in products)))
    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        description="95fen Phone Scraper — парсер через реальный телефон"
    )
    parser.add_argument("--url", help="URL, ID товара или deeplink")
    parser.add_argument("--file", help="Файл со списком URL/ID (один на строку)")
    parser.add_argument("--check", action="store_true", help="Проверка подключения")
    parser.add_argument(
        "--delay", type=float, default=WAIT_BETWEEN_PRODUCTS,
        help=f"Пауза между товарами, сек (по умолчанию {WAIT_BETWEEN_PRODUCTS})",
    )
    args = parser.parse_args()

    scraper = PhoneScraper()

    # --check
    if args.check:
        check_phone(scraper)
        return

    # Нужен --url или --file
    if not args.url and not args.file:
        parser.print_help()
        console.print("\n[yellow]Укажи --url, --file или --check[/yellow]")
        sys.exit(1)

    # Собираем URL
    urls = []
    if args.url:
        urls.append(normalize_url(args.url))
    if args.file:
        urls.extend(load_urls(args.file))

    if not urls:
        console.print("[red]Нет URL для парсинга[/red]")
        sys.exit(1)

    console.print(f"[bold]95fen Phone Scraper: {len(urls)} товаров[/bold]")

    # Подключаемся
    if not scraper.connect():
        sys.exit(1)

    # Парсим
    products = []

    try:
        for i, url in enumerate(urls):
            console.print(f"\n{'=' * 50}")
            console.print(f"[bold cyan]{i + 1}/{len(urls)}: {url}[/bold cyan]")

            product = scraper.scrape(url)

            if product and (product.title or product.price.current):
                products.append(product)
                title = product.title or "?"
                price = product.price.current or "?"
                console.print(f"[green]✓ {title} — ¥{price}[/green]")
            else:
                console.print(f"[red]✗ Не удалось[/red]")

            if i < len(urls) - 1:
                console.print(f"[dim]Пауза {args.delay}с...[/dim]")
                time.sleep(args.delay)

    except KeyboardInterrupt:
        console.print("\n[yellow]Прервано пользователем[/yellow]")

    finally:
        scraper.cleanup()

    if products:
        save_all_products(products)

    print_summary(products, len(urls))


if __name__ == "__main__":
    main()
