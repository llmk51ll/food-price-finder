"""
Fetch online prices for grocery items and update Google Sheet.

Example cron (run daily at 7AM):
    0 7 * * * /usr/bin/python /path/to/fetch_prices.py

On Windows, use Task Scheduler to schedule the script.
"""

import os
import re
import urllib.parse
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ------------ CONFIG ------------
# Values can be overridden with environment variables for flexibility.
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "10NLm6vPypgpZdHaLoBsWoBq9I87NCzgq5oPCXgKxvTw")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Master Sheet")
NAME_COL = int(os.getenv("NAME_COL", "5"))  # E column: item name
STORE_COL = int(os.getenv("STORE_COL", "12"))  # L column: Online_Store
URL_COL = int(os.getenv("URL_COL", "13"))  # M column: Price_URL
PRICE_COL = int(os.getenv("PRICE_COL", "14"))  # N column: Current_Online_Price
CHROMEDRIVER = os.getenv("CHROMEDRIVER", r"D:\\Food project\\chromedriver-win64\\chromedriver.exe")
SERVICE_KEY = os.getenv("SERVICE_KEY", r"D:\\Food project\\SERVICE_KEY.json")

STORES = [
    {
        "name": "Japan Centre",
        "search": "https://www.japancentre.com/en/search?term={}",
        "list_selectors": [
            ".price",
            ".product__price",
            "[data-test='product-price']",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            "meta[property='product:price:amount']",
            ".price",
            ".product__price",
        ],
    },
    {
        "name": "H Mart UK",
        "search": "https://hmart.co.uk/shop/gb/search?controller=search&s={}",
        "list_selectors": [".price", "[itemprop='price']"],
        "detail_selectors": [
            "[itemprop='price']",
            "meta[property='product:price:amount']",
            ".price",
        ],
    },
    {
        "name": "Sous Chef",
        "search": "https://www.souschef.co.uk/search?q={}",
        "list_selectors": [
            ".price-item--regular",
            ".price",
            "[data-product-price]",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            "meta[property='product:price:amount']",
            ".price",
        ],
    },
    {
        "name": "Yutaka Shop",
        "search": "https://shop.yutaka.london/search?q={}",
        "list_selectors": [
            ".price",
            ".price__regular .price-item--regular",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            "meta[property='product:price:amount']",
            ".price",
        ],
    },
    {
        "name": "Wibrix",
        "search": "https://wibrix.co.uk/?s={}&post_type=product",
        "list_selectors": [
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
    },
    {
        "name": "Oriental Mart",
        "search": "https://www.orientalmart.co.uk/search?q={}",
        "list_selectors": [
            ".price",
            ".product-price",
            ".woocommerce-Price-amount",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            ".price",
            ".woocommerce-Price-amount",
        ],
    },
    {
        "name": "Wai Yee Hong",
        "search": "https://www.waiyeehong.com/search?keywords={}",
        "list_selectors": [".price", ".product-price"],
        "detail_selectors": ["meta[itemprop='price']", ".price"],
    },
    {
        "name": "WaNaHong",
        "search": "https://www.wanahong.co.uk/?s={}&post_type=product",
        "list_selectors": [
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
    },
    {
        "name": "Tradewinds Oriental",
        "search": "https://tradewindsorientalshop.co.uk/?s={}&post_type=product",
        "list_selectors": [
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
    },
    {
        "name": "Korea Foods",
        "search": "https://www.koreafoods.co.uk/?s={}&post_type=product",
        "list_selectors": [
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
        "detail_selectors": [
            "meta[itemprop='price']",
            ".woocommerce-Price-amount",
            ".price .amount",
        ],
    },
]


def parse_price(text: str) -> Optional[float]:
    """Strip currency symbols and convert to float when possible."""
    cleaned = re.sub(r"[^0-9.,]", "", text).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_price_from_soup(soup: BeautifulSoup, selectors: list[str]) -> Optional[float]:
    """Return the first price found using any selector in ``selectors``."""
    for sel in selectors:
        elem = soup.select_one(sel)
        if not elem:
            continue
        text = elem.get("content") or elem.get_text()
        price = parse_price(text)
        if price is not None:
            return price
    return None


def find_product_link(soup: BeautifulSoup, base: str) -> Optional[str]:
    """Find a probable product link on the search page."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(key in href.lower() for key in ["product", "products", "item", "shop"]):
            return urllib.parse.urljoin(base, href)
    first = soup.find("a", href=True)
    if first:
        return urllib.parse.urljoin(base, first["href"])
    return None


def authenticate_sheet():
    """Authenticate using service account credentials and return worksheet."""
    if not os.path.exists(SERVICE_KEY):
        raise FileNotFoundError(f"SERVICE_KEY file not found: {SERVICE_KEY}")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_KEY, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)


def fetch_from_store(
    name: str, store: dict, driver: Optional[webdriver.Chrome]
) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[webdriver.Chrome]]:
    """Search for ``name`` in ``store`` and return the price when found."""
    search_url = store["search"].format(urllib.parse.quote_plus(name))
    headers = {"User-Agent": "Mozilla/5.0"}

    # --- requests first ---
    try:
        response = requests.get(search_url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        product_url = find_product_link(soup, response.url)
        if product_url:
            try:
                detail = requests.get(product_url, timeout=10, headers=headers)
                detail_soup = BeautifulSoup(detail.text, "html.parser")
                price = extract_price_from_soup(detail_soup, store["detail_selectors"])
                if price is not None:
                    return store["name"], detail.url, price, driver
            except Exception:
                pass
        list_price = extract_price_from_soup(soup, store["list_selectors"])
        if list_price is not None:
            return store["name"], product_url or response.url, list_price, driver
    except Exception:
        pass

    # --- selenium fallback ---
    try:
        if driver is None:
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER), options=options)
        driver.get(search_url)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        product_url = find_product_link(soup, driver.current_url)
        if product_url:
            driver.get(product_url)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            price = extract_price_from_soup(soup, store["detail_selectors"])
            if price is not None:
                return store["name"], driver.current_url, price, driver
        list_price = extract_price_from_soup(soup, store["list_selectors"])
        if list_price is not None:
            return store["name"], driver.current_url, list_price, driver
    except Exception:
        pass

    return None, None, None, driver


def main():
    ws = authenticate_sheet()
    all_rows = ws.get_all_values()
    driver = None
    try:
        for idx, row in enumerate(all_rows[1:], start=2):  # skip header
            name = row[NAME_COL - 1].strip()
            if not name:
                continue
            store_name = url = price = None
            for store in STORES:
                store_name, url, price, driver = fetch_from_store(name, store, driver)
                if store_name:
                    ws.update_cell(idx, STORE_COL, store_name)
                    ws.update_cell(idx, URL_COL, url or "")
                    ws.update_cell(idx, PRICE_COL, price if price is not None else "")
                    print(f"Row {idx}, {name} -> {store_name}:{price}")
                    break
            else:
                ws.update_cell(idx, PRICE_COL, "N/A")
                print(f"Row {idx}, {name} -> N/A")
    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    main()

