#!/usr/bin/env python3
"""
95fen Seller Scraper

Открой страницу продавца в приложении 95fen, потом запускай:
    python main.py
    python main.py --max 500
    python main.py --check
"""

import argparse
import sys
from scraper.seller_scraper import SellerScraper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--max", type=int, default=200)
    args = parser.parse_args()

    scraper = SellerScraper()

    if args.check:
        scraper.check()
        return

    if not scraper.connect():
        sys.exit(1)

    scraper.run(max_products=args.max)


if __name__ == "__main__":
    main()
