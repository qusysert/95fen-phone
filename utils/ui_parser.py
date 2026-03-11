"""
ui_parser.py — Парсинг UI dump XML в данные товара.

UI dump содержит дерево всех элементов на экране телефона.
Каждый элемент имеет атрибуты: text, resource-id, class, bounds, content-desc.
"""

import re
from bs4 import BeautifulSoup
from models.product import Product, ProductPrice, ProductSpecs

# Бренды для распознавания
BRANDS = {
    "Nike": ["Nike", "耐克", "NIKE"],
    "Adidas": ["Adidas", "阿迪达斯", "ADIDAS", "adidas"],
    "Jordan": ["Jordan", "乔丹", "JORDAN", "Air Jordan", "AJ"],
    "Yeezy": ["Yeezy", "YEEZY", "椰子"],
    "New Balance": ["New Balance", "新百伦", "NB", "new balance"],
    "Puma": ["Puma", "彪马", "PUMA"],
    "Converse": ["Converse", "匡威", "CONVERSE"],
    "Vans": ["Vans", "范斯", "VANS"],
    "ASICS": ["ASICS", "亚瑟士", "Asics"],
    "Reebok": ["Reebok", "锐步"],
    "Li-Ning": ["Li-Ning", "李宁", "LI-NING", "LINING"],
    "Anta": ["Anta", "安踏", "ANTA"],
    "Under Armour": ["Under Armour", "安德玛", "UA"],
    "Gucci": ["Gucci", "古驰", "GUCCI"],
    "Louis Vuitton": ["Louis Vuitton", "路易威登", "LV"],
    "Balenciaga": ["Balenciaga", "巴黎世家"],
    "Supreme": ["Supreme", "SUPREME"],
}

# UI-элементы которые нужно игнорировать (навигация, кнопки)
SKIP_TEXTS = {
    "返回", "首页", "分享", "收藏", "购买", "加入购物车",
    "确定", "取消", "更多", "查看更多", "展开", "收起",
    "立即购买", "加入", "客服", "举报", "···", "...",
    "消息", "我的", "搜索", "发现", "关注",
}


def _is_junk_text(text: str) -> bool:
    """Возвращает True для мусорных строк (хеши картинок, системные строки Chrome)."""
    # Хеши CDN: "abc123...{16+hex}_{w}x{h}" или просто длинный hex
    if re.match(r'^[a-f0-9]{16,}_\d+x\d+$', text):
        return True
    # Параметры CDN
    if text in ("format,webp", "format,png", "format,jpg"):
        return True
    # URL страницы (не нужен в текстах)
    if text.startswith("h5.95fenapp.com/"):
        return True
    return False


def extract_texts_from_xml(xml: str) -> list[dict]:
    """Извлекает все тексты из UI dump XML."""
    soup = BeautifulSoup(xml, "lxml-xml")
    texts = []

    for node in soup.find_all("node"):
        text = (node.get("text") or "").strip()
        content_desc = (node.get("content-desc") or "").strip()
        value = text or content_desc

        if not value or len(value) < 1:
            continue

        if _is_junk_text(value):
            continue

        texts.append({
            "text": value,
            "resource_id": node.get("resource-id", ""),
            "class": node.get("class", ""),
            "bounds": node.get("bounds", ""),
        })

    return texts


def parse_texts_to_product(
    texts: list[dict], url: str, product_id: str
) -> Product:
    """Парсит список UI-текстов в модель Product."""

    product = Product(
        source_url=url,
        product_id=product_id,
        raw_data={"ui_texts": [t["text"] for t in texts]},
    )

    # === ЦЕНА ===
    _parse_price(texts, product)

    # === НАЗВАНИЕ ===
    _parse_title(texts, product)

    # === ХАРАКТЕРИСТИКИ ===
    _parse_specs(texts, product)

    # === ОПИСАНИЕ ===
    _parse_description(texts, product)

    # === ПРОДАВЕЦ ===
    _parse_seller(texts, product)

    return product


def _parse_price(texts: list[dict], product: Product):
    """Извлекает цену товара из текстов."""
    PROMO_NOISE = {"新人大礼包", "礼包", "优惠", "立减", "满减", "券", "红包"}
    prices_found = []
    text_list = [t["text"] for t in texts]

    for i, t in enumerate(texts):
        text = t["text"]

        # Случай 1: ¥XXXX в одном тексте (короткий, не маркетинговый)
        if len(text) <= 20 and not any(noise in text for noise in PROMO_NOISE):
            for match in re.finditer(r'[¥￥]\s*([\d,]+(?:\.\d{1,2})?)', text):
                try:
                    val = float(match.group(1).replace(",", ""))
                    if val >= 50:
                        prices_found.append(val)
                except ValueError:
                    pass

        # Случай 2: standalone ¥/￥ — следующий текст это число (разбитые узлы)
        if text.strip() in ("¥", "￥") and i + 1 < len(text_list):
            nxt = text_list[i + 1].strip().replace(",", "")
            if re.match(r'^\d+(?:\.\d{1,2})?$', nxt):
                try:
                    val = float(nxt)
                    if val >= 50:
                        prices_found.append(val)
                except ValueError:
                    pass

        # Случай 3: чистое число рядом с ценовым индикатором (окно ±3)
        if re.match(r'^\d{3,6}(?:\.\d{1,2})?$', text.strip()):
            context = text_list[max(0, i-3):i+4]
            price_indicators = {"到手价", "售价", "原价", "现价", "价格", "¥", "￥"}
            if any(ind in ctx for ctx in context for ind in price_indicators):
                try:
                    val = float(text.strip())
                    if val >= 50:
                        prices_found.append(val)
                except ValueError:
                    pass

        # Случай 4: resource-id содержит "price"
        if "price" in t["resource_id"].lower():
            for n in re.findall(r'\d{3,}(?:\.\d{1,2})?', text):
                try:
                    val = float(n)
                    if val >= 50:
                        prices_found.append(val)
                except ValueError:
                    pass

    if prices_found:
        prices_found = sorted(set(p for p in prices_found if 50 <= p <= 9_000_000))
        if prices_found:
            product.price.current = prices_found[0]


def _parse_title(texts: list[dict], product: Product):
    """Извлекает название товара."""
    candidates = []

    for t in texts:
        text = t["text"]
        rid = t["resource_id"]

        # Прямое совпадение по resource-id
        if any(k in rid.lower() for k in ["title", "name", "goods_name"]):
            if len(text) > 3:
                candidates.append((1000, text))
                continue

        # Пропускаем мусор
        if text in SKIP_TEXTS:
            continue
        if re.match(r'^[¥￥\d\.\s,]+$', text):
            continue
        if len(text) < 3:
            continue

        score = len(text)

        # Бонус за бренд
        for brand_name, keywords in BRANDS.items():
            if any(k in text for k in keywords):
                score += 100
                break

        # Бонус за "обувные" слова
        shoe_words = ["鞋", "靴", "拖鞋", "跑鞋", "板鞋", "篮球鞋", "运动鞋"]
        if any(w in text for w in shoe_words):
            score += 50

        # Штраф за слишком короткие или слишком длинные
        if len(text) < 5:
            score -= 30
        if len(text) > 100:
            score -= 20

        candidates.append((score, text))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        product.title = candidates[0][1]


def _parse_specs(texts: list[dict], product: Product):
    """Извлекает характеристики."""
    for t in texts:
        text = t["text"]
        rid = t["resource_id"]

        # --- Размер ---
        if not product.specs.size:
            if "size" in rid.lower() or "尺码" in rid:
                product.specs.size = text
            elif re.search(r'(\d{2}(?:\.\d)?)\s*(?:码|EU|US|CM|uk)', text, re.IGNORECASE):
                product.specs.size = text.strip()
            elif "码" in text or "尺码" in text:
                product.specs.size = text.strip()

        # --- Цвет ---
        if not product.specs.color:
            if "color" in rid.lower() or "颜色" in rid:
                product.specs.color = text
            elif any(k in text for k in ["色", "颜色", "配色", "colorway"]):
                if len(text) < 30:
                    product.specs.color = text.strip()

        # --- Состояние ---
        if not product.specs.condition:
            condition_kw = [
                "成新", "全新", "未使用", "几乎全新", "轻微使用",
                "二手", "闲置", "99新", "95新", "9成", "8成",
                "瑕疵", "磨损",
            ]
            if any(k in text for k in condition_kw):
                product.specs.condition = text.strip()

        # --- Бренд ---
        if not product.specs.brand:
            for brand_name, keywords in BRANDS.items():
                if any(k in text for k in keywords):
                    product.specs.brand = brand_name
                    break

        # --- Материал ---
        if not product.specs.material:
            material_kw = [
                "皮革", "网面", "帆布", "绒面", "麂皮", "织物", "合成",
                "leather", "canvas", "mesh", "suede", "knit",
            ]
            if any(k in text.lower() for k in material_kw):
                if len(text) < 30:
                    product.specs.material = text.strip()

        # --- Подлинность ---
        if not product.specs.authenticity:
            auth_kw = ["鉴定", "正品", "验证", "通过", "authentic"]
            if any(k in text.lower() for k in auth_kw):
                product.specs.authenticity = text.strip()


def _parse_description(texts: list[dict], product: Product):
    """Извлекает описание."""
    for t in texts:
        text = t["text"]
        rid = t["resource_id"]

        if "desc" in rid.lower() or "detail" in rid.lower():
            if len(text) > 10:
                product.description = text
                return

    # Резерв: длинный текст который не является названием
    for t in texts:
        text = t["text"]
        if len(text) > 30 and text != product.title:
            if not re.match(r'^[¥￥\d\.\s,]+$', text):
                if text not in SKIP_TEXTS:
                    product.description = text
                    return


def _parse_seller(texts: list[dict], product: Product):
    """Извлекает имя продавца."""
    for t in texts:
        rid = t["resource_id"]
        if any(k in rid.lower() for k in ["seller", "nick", "user_name", "shop"]):
            if len(t["text"]) > 1 and t["text"] not in SKIP_TEXTS:
                product.seller_name = t["text"]
                return
