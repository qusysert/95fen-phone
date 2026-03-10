import re
from urllib.parse import urlparse, parse_qs
from config import H5_BASE

# Домены коротких ссылок 95fen
SHORT_URL_DOMAINS = {"95b.co"}


def resolve_short_url(url: str) -> str:
    """Разворачивает короткую ссылку через HTTP редирект."""
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.url
    except Exception:
        return url


def normalize_url(url: str) -> str:
    """Нормализует любой формат ссылки 95fen в H5 URL."""
    url = url.strip()

    if url.startswith("jiuwu://"):
        match = re.search(r'id[=/](\d+)', url)
        if match:
            return f"{H5_BASE}/goods/detail?id={match.group(1)}"

    if url.isdigit():
        return f"{H5_BASE}/goods/detail?id={url}"

    if not url.startswith("http"):
        url = "https://" + url

    # Разворачиваем короткие ссылки (95b.co и т.п.)
    parsed = urlparse(url)
    if parsed.netloc in SHORT_URL_DOMAINS:
        from rich.console import Console
        Console().print(f"[dim]Разворачиваем короткую ссылку: {url}[/dim]")
        url = resolve_short_url(url)

    return url


def extract_product_id(url: str) -> str | None:
    """Извлекает ID товара из URL."""
    url = url.strip()
    if url.isdigit():
        return url

    parsed = urlparse(url)

    # Проверяем query params основного URL
    params = parse_qs(parsed.query)
    for key in ["id", "goodsId", "goods_id", "productId", "product_id", "spuId"]:
        if key in params:
            return params[key][0]

    # Проверяем фрагмент (#/pages/newDetail/index?id=XXX)
    # urlparse кладёт всё после # в .fragment
    if parsed.fragment:
        frag = parsed.fragment
        if '?' in frag:
            frag_params = parse_qs(frag.split('?', 1)[1])
            for key in ["id", "goodsId", "goods_id", "productId", "product_id", "spuId"]:
                if key in frag_params:
                    return frag_params[key][0]

    # Паттерн в пути
    path_match = re.search(r'/(?:goods|product|detail|item)/(\d+)', parsed.path)
    if path_match:
        return path_match.group(1)

    # Любой длинный числовой id в URL (≥10 цифр)
    long_id = re.search(r'[?&=#/](\d{10,})', url)
    if long_id:
        return long_id.group(1)

    if url.startswith("jiuwu://"):
        match = re.search(r'id[=/](\d+)', url)
        if match:
            return match.group(1)

    return None
