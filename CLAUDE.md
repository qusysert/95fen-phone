# CLAUDE.md — Парсер товаров 95fen через реальный Android-телефон

## СУТЬ

Парсер товаров с платформы **95fen (95分)** — китайский маркетплейс б/у кроссовок и брендовых вещей. У платформы **НЕТ веб-версии** — только мобильное приложение. Эмуляторы не работают (95fen их детектит).

**Подход:** реальный Android-телефон (Redmi Note 9, без root) подключён по USB. Через `uiautomator2` автоматизируем UI: открываем товар → читаем все тексты с экрана → делаем скриншоты фото → парсим в структурированный JSON.

Без root. Без Frida. Без перехвата трафика. Без эмулятора.

---

## ТЕКУЩЕЕ СОСТОЯНИЕ

- Телефон: **Redmi Note 9**, без root, USB-отладка включена
- На телефоне: приложение **95fen** (com.jiuwu) установлено и работает
- На хосте: **Ubuntu**, Python venv
- Код: написан, требует тестирования на реальных товарах и доработки парсинга

---

## КАК ЗАПУСТИТЬ

```bash
# 1. Настройка (один раз)
cd ~/python/95fen-phone
bash setup.sh
source venv/bin/activate

# 2. Проверить подключение телефона
adb devices                    # должен показать устройство
python main.py --check         # проверит телефон + 95fen

# 3. Парсинг одного товара
python main.py --url "https://h5.95fenapp.com/goods/detail?id=123456"

# 4. Парсинг списка товаров
python main.py --file urls.txt

# 5. Парсинг по ID
python main.py --url 123456
```

---

## СТРУКТУРА ПРОЕКТА

```
95fen-phone/
├── CLAUDE.md              # Этот файл
├── main.py                # CLI: --url, --file, --check, --delay, --no-screenshots
├── config.py              # Пути, таймауты
├── setup.sh               # Установка зависимостей
├── requirements.txt       # Python-пакеты
├── scraper/
│   ├── __init__.py
│   └── phone_scraper.py   # Главный модуль: UI автоматизация + парсинг
├── models/
│   ├── __init__.py
│   └── product.py         # Pydantic-модель товара
├── utils/
│   ├── __init__.py
│   ├── helpers.py         # normalize_url(), extract_product_id()
│   └── ui_parser.py       # Парсинг UI dump XML → данные товара
└── output/
    ├── products/           # JSON-файлы по каждому товару + общий products.json
    ├── screenshots/        # Скриншоты экранов (по папкам на товар)
    └── images/             # (зарезервировано)
```

---

## ТЕХНИЧЕСКИЕ ДЕТАЛИ

### 95fen
- **Пакет:** `com.jiuwu`
- **Launch Activity:** `com.zhichao.module.mall.view.welcome.WelcomeActivity`
- **Открыть товар:** `adb shell am start -a android.intent.action.VIEW -d "URL"`
- **Формат URL:** `https://h5.95fenapp.com/goods/detail?id=XXXXX`
- **Deep link:** `jiuwu://goods/detail?id=XXXXX`
- **Или просто ID:** `123456` → нормализуется в URL автоматически

### uiautomator2
- Работает **без root** — нужен только USB debugging
- При первом `u2.connect()` ставит ATX agent на телефон (автоматически)
- `d.dump_hierarchy()` → XML со всеми UI-элементами (тексты, ID, координаты)
- `d.screenshot(path)` → скриншот в PNG
- `d.swipe(x1, y1, x2, y2)` → свайп (прокрутка, карусель)
- `d.press("back")` → кнопка назад

### Алгоритм парсинга одного товара
1. `adb shell am start -a ... -d "URL"` → открыть товар
2. `time.sleep(5)` → ждём загрузки
3. `d.dump_hierarchy()` → XML с текстами первого экрана
4. `d.screenshot()` → скриншот
5. Свайп карусели фото влево → скриншот каждого фото (сравниваем хеши — когда совпадут, карусель кончилась)
6. Свайп страницы вниз → dump + скриншот (описание, характеристики)
7. Повторяем прокрутку 2-3 раза
8. Парсим все собранные тексты → Product
9. `d.press("back")` → возврат
10. Задержка 3 сек → следующий товар

### Извлечение данных из UI dump
UI dump — XML вида:
```xml
<node text="Nike Air Jordan 1 High OG" resource-id="com.jiuwu:id/tv_title" class="android.widget.TextView" bounds="[30,400][1050,460]" />
<node text="¥1299" resource-id="com.jiuwu:id/tv_price" class="android.widget.TextView" bounds="[30,470][300,520]" />
```

Из него извлекаем:
- **Название:** длинный текст с брендом или в верхней части экрана
- **Цена:** паттерн `¥XXX` или `￥XXX`
- **Характеристики:** тексты с ключевыми словами (码/size, 色/color, 新/condition)
- **Описание:** длинный текст после прокрутки
- **Бренд:** распознавание по словарю (Nike, Adidas, Jordan...)

### Формат результата
```json
{
  "product_id": "123456",
  "source_url": "https://h5.95fenapp.com/goods/detail?id=123456",
  "title": "Nike Air Jordan 1 Retro High OG 黑红配色",
  "description": "9.5成新，穿过两次...",
  "price": {"current": 1299.0, "original": 1599.0, "discount_percent": 18.8, "currency": "CNY"},
  "specs": {"size": "42.5 EU", "color": "黑红", "brand": "Nike", "condition": "9.5成新"},
  "local_images": ["output/screenshots/123456/photo_001.png", "..."],
  "scrape_method": "phone_scraper",
  "scraped_at": "2026-03-09T...",
  "raw_data": {"ui_texts": [...]}
}
```

---

## ВАЖНЫЕ КОМАНДЫ

```bash
# Телефон
adb devices
adb shell getprop ro.product.model
adb shell svc power stayon true          # не гасить экран
adb shell settings put system screen_off_timeout 600000

# 95fen
adb shell am start -n com.jiuwu/com.zhichao.module.mall.view.welcome.WelcomeActivity
adb shell am start -a android.intent.action.VIEW -d "https://h5.95fenapp.com/goods/detail?id=123456"
adb shell am force-stop com.jiuwu

# Отладка UI
adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml
adb shell screencap -p /sdcard/s.png && adb pull /sdcard/s.png
```

---

## ДЛЯ CLAUDE CODE

- **Рабочая директория:** `~/python/95fen-phone`
- **venv:** `source venv/bin/activate`
- **Телефон** подключён по USB — проверяй `adb devices`
- **Тестирование:** сначала `python main.py --check`, потом один товар по URL
- **Если парсинг неточный:** смотри `output/products/{id}/ui_texts.json` — там все сырые тексты с экрана, по ним можно улучшить эвристику
- **Скриншоты:** `output/screenshots/{id}/` — визуальная проверка что видит парсер
