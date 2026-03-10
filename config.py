from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
SCREENSHOTS_DIR = OUTPUT_DIR / "screenshots"
PRODUCTS_DIR = OUTPUT_DIR / "products"
IMAGES_DIR = OUTPUT_DIR / "images"
PRODUCTS_JSON = OUTPUT_DIR / "products.json"

for d in [OUTPUT_DIR, SCREENSHOTS_DIR, PRODUCTS_DIR, IMAGES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 95fen
APP_PACKAGE = "com.jiuwu"
APP_ACTIVITY = "com.zhichao.module.mall.view.welcome.WelcomeActivity"
H5_BASE = "https://h5.95fenapp.com"

# Тайминги (секунды)
WAIT_PAGE_LOAD = 6       # ожидание загрузки страницы товара
WAIT_AFTER_SWIPE = 2     # ожидание после свайпа
WAIT_CAROUSEL = 1.5      # ожидание после свайпа карусели
WAIT_BETWEEN_PRODUCTS = 3  # пауза между товарами
MAX_SCROLLS = 4            # максимум прокруток вниз
MAX_CAROUSEL_PHOTOS = 15   # максимум фото в карусели
