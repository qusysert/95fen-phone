"""
cdp_scraper.py — Получение HTML страницы из Chrome на телефоне
через Chrome DevTools Protocol (CDP) по USB.

Работает когда страница уже открыта в Chrome на телефоне.
Не требует root — только USB debugging.
"""

import json
import re
import subprocess
import time
from pathlib import Path

from bs4 import BeautifulSoup
from rich.console import Console

console = Console()

CDP_PORT = 9222
CDP_HOST = "http://localhost"


def _forward_cdp_port(serial: str) -> bool:
    """Пробрасывает CDP порт Chrome с телефона на хост."""
    result = subprocess.run(
        ["adb", "-s", serial, "forward", f"tcp:{CDP_PORT}",
         "localabstract:chrome_devtools_remote"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _get_tabs(serial: str) -> list[dict]:
    """Возвращает список открытых вкладок Chrome."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{CDP_HOST}:{CDP_PORT}/json")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        console.print(f"[red]CDP /json: {e}[/red]")
        return []


def _find_tab(tabs: list[dict], url_pattern: str) -> dict | None:
    """Ищет вкладку по паттерну URL."""
    for tab in tabs:
        if url_pattern in tab.get("url", ""):
            return tab
    return None


def _cdp_eval(ws_url: str, expression: str, timeout: int = 15) -> str | None:
    """Выполняет JS-выражение в странице через CDP WebSocket."""
    try:
        import websocket
        ws = websocket.create_connection(ws_url, timeout=timeout)
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
            }
        }))
        result = json.loads(ws.recv())
        ws.close()

        if "result" in result and "result" in result["result"]:
            return result["result"]["result"].get("value")
    except Exception as e:
        console.print(f"[red]CDP eval error: {e}[/red]")
    return None


def get_html_from_chrome(serial: str, url_pattern: str = "95fenapp.com") -> tuple[str | None, str | None]:
    """
    Получает отрендеренный HTML из Chrome на телефоне.
    Возвращает (html, page_url) или (None, None).
    """
    if not _forward_cdp_port(serial):
        console.print("[red]Не удалось пробросить CDP порт[/red]")
        return None, None

    time.sleep(0.5)
    tabs = _get_tabs(serial)
    if not tabs:
        console.print("[yellow]Chrome вкладки не найдены[/yellow]")
        return None, None

    tab = _find_tab(tabs, url_pattern)
    if not tab:
        console.print(f"[yellow]Вкладка с '{url_pattern}' не найдена. Доступные:[/yellow]")
        for t in tabs[:5]:
            console.print(f"  [dim]{t.get('url', '')[:80]}[/dim]")
        return None, None

    page_url = tab.get("url", "")
    ws_url = tab.get("webSocketDebuggerUrl", "")
    console.print(f"[dim]CDP: {page_url[:80]}[/dim]")

    if not ws_url:
        console.print("[red]webSocketDebuggerUrl отсутствует[/red]")
        return None, None

    html = _cdp_eval(ws_url, "document.documentElement.outerHTML")
    return html, page_url


def parse_95fen_html(html: str, page_url: str, product_id: str) -> dict:
    """
    Парсит HTML страницы товара 95fen и возвращает словарь с данными.
    Собирает весь текст + пытается извлечь ключевые поля.
    """
    soup = BeautifulSoup(html, "lxml")

    # Убираем скрипты и стили
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    # Весь текст с страницы (все видимые строки)
    all_texts = []
    seen = set()
    for el in soup.find_all(string=True):
        text = el.strip()
        if text and text not in seen and len(text) > 1:
            seen.add(text)
            all_texts.append(text)

    # Пробуем извлечь структурированные данные
    data = {
        "product_id": product_id,
        "source_url": page_url,
        "all_texts": all_texts,
        "title": None,
        "price": None,
        "original_price": None,
        "condition": None,
        "size": None,
        "color": None,
        "description": None,
        "seller": None,
    }

    full_text = "\n".join(all_texts)

    # Цена: ¥1299 или просто число рядом с символом
    price_matches = re.findall(r'[¥￥]\s*([\d,]+(?:\.\d{1,2})?)', full_text)
    if price_matches:
        prices = sorted(set(float(p.replace(",", "")) for p in price_matches))
        data["price"] = prices[0]
        if len(prices) > 1:
            data["original_price"] = prices[-1]

    # Состояние: X成新
    cond = re.search(r'(\d+(?:\.\d+)?成新|全新|几乎全新|二手)', full_text)
    if cond:
        data["condition"] = cond.group(0)

    # Размер
    size = re.search(r'(\d{2,3}(?:\.\d)?)\s*(?:码|EU|US|CM|uk)', full_text, re.IGNORECASE)
    if size:
        data["size"] = size.group(0)

    # Название: ищем длинный текст с брендом или из мета
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        t = title_tag.string.strip()
        if t and len(t) > 3 and "95fen" not in t.lower():
            data["title"] = t

    if not data["title"]:
        # Берём самый длинный осмысленный текст как кандидата
        candidates = [t for t in all_texts if 5 < len(t) < 120
                      and not re.match(r'^[\d\s¥￥.,]+$', t)]
        if candidates:
            data["title"] = max(candidates, key=len)

    return data
