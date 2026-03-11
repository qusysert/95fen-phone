#!/bin/bash
set -e

echo "=== 95fen Scraper: установка ==="

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

echo ""
echo "=== Готово ==="
echo "Активация: source venv/bin/activate"
echo "Запуск:    python main.py --url 'https://95b.co/d/2AkKJ'"
