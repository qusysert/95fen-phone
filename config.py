from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
PRODUCTS_DIR = OUTPUT_DIR / "products"
IMAGES_DIR = OUTPUT_DIR / "images"
PRODUCTS_JSON = OUTPUT_DIR / "products.json"

for d in [OUTPUT_DIR, PRODUCTS_DIR, IMAGES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

H5_BASE = "https://h5.95fenapp.com"
WAIT_BETWEEN_PRODUCTS = 3
