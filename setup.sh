#!/bin/bash
set -e

echo "=== 95fen Phone Scraper: установка ==="

sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv adb

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=== Готово ==="
echo ""
echo "Активация:  source venv/bin/activate"
echo "Проверка:   python main.py --check"
echo "Парсинг:    python main.py --url 123456"
echo ""
echo "Не забудь:"
echo "  1. Включить USB-отладку на телефоне"
echo "  2. Подключить телефон по USB"
echo "  3. Подтвердить доверие к компьютеру на телефоне"
echo "  4. Установить 95fen на телефон"
