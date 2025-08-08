"""
Fetch online prices for grocery items and update Google Sheet.

Example cron (run daily at 7AM):
    0 7 * * * /usr/bin/python /path/to/fetch_prices.py

On Windows, use Task Scheduler to schedule the script.
"""

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

# ---------- CONFIG（先定義常數！）----------
SPREADSHEET_ID   = "10NLm6vPypgpZdHaLoBsWoBq9I87NCzgq5oPCXgKxvTw"
WORKSHEET_NAME   = "Master Sheet"     # 工作表名稱
NAME_COL         = 5                  # E 欄：商品名稱
STORE_COL        = 12                 # L 欄：Online_Store
URL_COL          = 13                 # M 欄：Price_URL
PRICE_COL        = 14                 # N 欄：Current_Online_Price
CHROMEDRIVER     = r"D:\Food project\chromedriver-win64\chromedriver.exe"
SERVICE_KEY      = r"D:\Food project\SERVICE_KEY.json"

# ---------- 認證 + 開啟工作表（之後再呼叫） ----------
def authenticate_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_KEY, scope)
    client = gspread.authorize(creds)  # 建立 gspread Client（一定要先有它）
    sh     = client.open_by_key(SPREADSHEET_ID)  # 用 spreadsheet ID 開表
    ws     = sh.worksheet(WORKSHEET_NAME)        # 指定分頁
    return ws

WORKSHEET_NAME   = "Master Sheet"            # 工作表
NAME_COL         = 5    # E  商品名稱
STORE_COL        = 12   # L  Online_Store (auto)
URL_COL          = 13   # M  Price_URL    (auto)
PRICE_COL        = 14   # N  Current_Online_Price (auto)
CHROMEDRIVER     = r"D:\Food project\chromedriver-win64\chromedriver.exe"          # 本機路徑
SERVICE_KEY      = r"D:\Food project\SERVICE_KEY.json"           # GCP 服務帳戶金鑰

STORES = [
    {"name":"Japan Centre",
     "search":"https://www.japancentre.com/search?q={}",
     "selector":".product__price"},
    {"name":"Oseyo",
     "search":"https://oseyo.co.uk/search?q={}",
     "selector":".price-item--regular"},
    {"name":"H Mart UK",
     "search":"https://hmart.co.uk/search?query={}",
     "selector":".price"},
    {"name":"Sous Chef",
     "search":"https://www.souschef.co.uk/search?q={}",
     "selector":".ProductItem__Price"},
    {"name":"Yutaka Shop",
     "search":"https://shop.yutaka.london/search?q={}",
     "selector":".price"},
    {"name":"Wibrix",
     "search":"https://wibrix.co.uk/?s={}",
     "selector":".woocommerce-Price-amount"},
    {"name":"Oriental Mart",
     "search":"https://www.orientalmart.co.uk/search?q={}",
     "selector":".price"},
    {"name":"Wai Yee Hong",
     "search":"https://www.waiyeehong.com/search?q={}",
     "selector":".price"},
    {"name":"WaNaHong",
     "search":"https://www.wanahong.co.uk/search?q={}",
     "selector":".price"},
    {"name":"Wing Yip",
     "search":"https://wingyip.com/search?q={}",
     "selector":".price"},
    {"name":"Tradewinds",
     "search":"https://tradewindsorientalshop.co.uk/search?q={}",
     "selector":".price"},
    {"name":"Korea Foods",
     "search":"https://www.koreafoods.co.uk/?s={}",
     "selector":".woocommerce-Price-amount"}
]


def parse_price(text: str) -> Optional[float]:
    """Strip currency symbols and convert to float when possible."""
    cleaned = re.sub(r"[^0-9.,]", "", text)
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def authenticate_sheet():
    """Authenticate using service account credentials and return worksheet."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_KEY, scope)
    client = gspread.authorize(creds)
    return client.open(WORKSHEET_NAME).worksheet(WORKSHEET_NAME)


def fetch_from_store(name: str, store: dict, driver: Optional[webdriver.Chrome]) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[webdriver.Chrome]]:
    """Try requests, then fallback to selenium."""
    url = store["search"].format(urllib.parse.quote_plus(name))
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        elem = soup.select_one(store["selector"])
        if elem and elem.get_text(strip=True):
            price = parse_price(elem.get_text())
            return store["name"], response.url, price, driver
    except Exception:
        pass

    # fallback to selenium
    try:
        if driver is None:
            options = Options()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER), options=options)
        driver.get(url)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        elem = soup.select_one(store["selector"])
        if elem and elem.get_text(strip=True):
            price = parse_price(elem.get_text())
            return store["name"], driver.current_url, price, driver
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
                    ws.update_cell(idx, URL_COL, url)
                    ws.update_cell(idx, PRICE_COL, price if price is not None else "N/A")
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
