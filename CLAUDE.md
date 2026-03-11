# CLAUDE.md — Парсер товаров 95fen

## СУТЬ

Парсер товаров с платформы **95fen (95分)** — китайский маркетплейс б/у кроссовок и брендовых вещей. Парсинг через браузерную автоматизацию Playwright на хосте (H5-версия сайта).

---

## КАК ЗАПУСТИТЬ

```bash
cd ~/python/95fen-phone
source venv/bin/activate

# Один товар
python main.py --url "https://95b.co/d/2AkKJ"

# Несколько товаров
python main.py --url "https://95b.co/d/2AkKJ" "https://95b.co/d/2Z69d"

# Список из файла
python main.py --file urls.txt
```

---

## СТРУКТУРА ПРОЕКТА

```
95fen-phone/
├── main.py                # CLI: --url, --file, --delay
├── config.py              # Пути, таймауты
├── setup.sh               # Установка зависимостей
├── requirements.txt       # Python-пакеты
├── scraper/
│   └── browser_scraper.py # Playwright: открывает H5, кликает варианты, скачивает фото
├── models/
│   └── product.py         # Pydantic-модель товара
├── utils/
│   └── helpers.py         # normalize_url(), extract_product_id()
└── output/
    ├── products/           # JSON по каждому товару/варианту
    ├── images/             # Скачанные фото (по папкам на товар)
    └── products.json       # Общий список всех товаров
```

---

## ТЕХНИЧЕСКИЕ ДЕТАЛИ

### Браузер
- Playwright Chromium, headless=False (чтобы видеть и решать капчу вручную)
- Мобильный viewport 390x844, mobile user-agent
- Капча: ждёт `input()` от пользователя

### Варианты товара
- Кнопка `#same_style_rec_sku_change_info` открывает попап выбора варианта
- Два формата: `.same__style__modal__beauty__item` (аксессуары, с ценой) и `.same__style__modal__size__item` (обувь, только размер)
- Доступные варианты: нет класса `disable`
- Перед кликом ждём исчезновения лоадера `#fen95-loading-wrap`
- URL варианта: `базовый_url&sku=label`

### Изображения
- Селектор: `taro-image-core.preview__main__img:not(.rotateX)`
- Оригинальное разрешение: убираем `?x-oss-process=...` из URL
- Скачиваем напрямую с CDN через urllib

### Формат результата
```json
{
  "product_id": "114121607311526399_v01",
  "source_url": "https://h5.95fenapp.com/#/pages/newDetail/index?id=...&sku=...",
  "title": "TIFFANY & CO. ...",
  "price": {"current": 1283.0, "currency": "CNY"},
  "specs": {"size": "银色 L 原盒装", "color": "银色", "condition": "9成新"},
  "local_images": ["output/images/.../v01/img_001.jpg"],
  "scraped_at": "2026-..."
}
```
