# --- Setup Note ---
# If you are using Python 3.12 or newer, you might see a "ModuleNotFoundError: No module named 'distutils'".
# This is because 'distutils' has been removed from recent Python versions.
# To fix this, please run the following command in your terminal before running the script:
# pip install setuptools

import argparse
import json
import time
import re
import random
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import os
from datetime import datetime
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from fpdf import FPDF, XPos, YPos

PRODUCTS_FILE = 'products.txt'
DB_FILE = 'tcgplayer.db'
DEFAULT_PDF_OUTPUT = 'TCGplayer_Combo_Report.pdf'

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _db_path():
    return os.path.join(_BASE_DIR, DB_FILE)


_HISTORY_SELECT = '''SELECT date as Date, market_price as "Market Price", most_recent_sale as "Most Recent Sale",
    listed_median as "Listed Median", current_quantity as "Current Quantity",
    current_sellers as "Current Sellers", sold_yesterday as "Sold Yesterday",
    total_sold as "Total Sold", recent_sales as "Recent Sales", top_listings as "Top Listings",
    price_change as "Price Change", quantity_change as "Quantity Change",
    daily_sales as "Daily Sales"
FROM price_history WHERE product_id = ? ORDER BY id'''

# Fallback list used when products.txt does not exist
PRODUCTS = [
    624679,
    668496,
    672394,
    528038,
    593355,
    600518,
    654213,
    502000,
    247646,
    654137,
    # Accepts product IDs (e.g. 624679) or full URLs (e.g. 'https://www.tcgplayer.com/product/624679/')
]


def load_products():
    """Load products from PRODUCTS_FILE if it exists, otherwise use the hardcoded PRODUCTS list.
    Supports one entry per line, comma-separated entries, or a mix of both.
    Lines starting with # are ignored."""
    path = os.path.join(_BASE_DIR, PRODUCTS_FILE)
    if not os.path.isfile(path):
        return PRODUCTS
    entries = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            for part in line.split(','):
                part = part.strip()
                if part:
                    entries.append(part)
    return entries

# Number of recent sales / top listings to store per product
RECENT_SALES_COUNT = 10
LISTING_COUNT = 6

# Listings below this fraction of market price are almost certainly not the actual
# product — accessories, loose packs, opened shells, foreign variants, etc.
MIN_LISTING_PRICE_PCT = 0.50

# Rate limiting
DELAY_BETWEEN_REQUESTS = (2, 4)   # random delay range in seconds between scrapes
RETRY_ATTEMPTS = 2                 # number of retries on failure
RETRY_BACKOFF = 10                 # seconds to wait before first retry (doubles each attempt)
SESSION_ROTATE_EVERY = 50          # restart Chrome every N products

_UNICODE_REPLACEMENTS = {
    '\u2019': "'", '\u2018': "'",
    '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '-',
    '\u2026': '...',
}


def _sanitize_for_pdf(text):
    """Replace Unicode characters that Helvetica/Latin-1 can't render with ASCII equivalents."""
    for old, new in _UNICODE_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode('latin-1', errors='replace').decode('latin-1')


class PDF(FPDF):
    def normalize_text(self, text):
        text = _sanitize_for_pdf(text)
        return super().normalize_text(text)

    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, 'TCGplayer Daily Market Report', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')


def normalize_product(entry):
    """Accept a product ID (int or str) or a full TCGplayer URL.
    Returns (product_id, url) tuple."""
    s = str(entry).strip().rstrip('/')
    if s.isdigit():
        return s, f'https://www.tcgplayer.com/product/{s}/'
    m = re.search(r'/product/(\d+)', s)
    if m:
        return m.group(1), entry if isinstance(entry, str) else str(entry)
    return None, entry


def get_api_data_from_network_logs(driver, product_id):
    """
    Read Chrome performance logs ONCE and scan for both sales and listings API responses.
    Returns {'sales': data_or_none, 'listings': data_or_none}.
    NOTE: get_log('performance') clears the buffer — must only be called once per page load.
    """
    result = {'sales': None, 'listings': None}
    try:
        logs = driver.get_log('performance')
    except Exception as e:
        print(f"  → Performance log unavailable: {e}")
        return result

    # NOTE: The listings endpoint (mp-search-api) only returns actual listing items
    # via POST — GET requests return aggregation metadata only. So we only use
    # the network log for sales here; listings are always fetched via JS POST.
    pid = str(product_id)
    for log in logs:
        if result['sales']:
            break
        try:
            message = json.loads(log['message'])['message']
            if message.get('method') != 'Network.responseReceived':
                continue
            url = message.get('params', {}).get('response', {}).get('url', '')
            if pid not in url or 'sales' not in url.lower():
                continue

            req_id = message['params']['requestId']
            body_result = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': req_id})
            body_text = body_result.get('body', '')
            if not body_text:
                continue
            data = json.loads(body_text)
            if data:
                print(f"  → Sales via network log: {url}")
                result['sales'] = data
        except Exception:
            continue

    return result


def get_listings_via_js(driver, product_id):
    """
    POST to TCGplayer's search API to retrieve active listing records.
    GET requests to this endpoint only return aggregation metadata — POST is required.
    Requests more than needed so the English filter has enough to work with after filtering.
    """
    url = f'https://mp-search-api.tcgplayer.com/v1/product/{product_id}/listings'
    body = {"from": 0, "size": LISTING_COUNT * 4, "sort": [{"field": "price", "order": "asc"}]}
    try:
        result = driver.execute_async_script("""
            const [url, body, callback] = [arguments[0], arguments[1], arguments[arguments.length - 1]];
            fetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                body: JSON.stringify(body)
            })
            .then(r => r.ok ? r.json() : null)
            .then(data => callback(data))
            .catch(() => callback(null));
        """, url, body)
        if result:
            print(f"  → Got listings via JS POST")
            return result
    except Exception:
        pass
    return None


def parse_listings_response(api_response, product_id=None, market_price=None):
    """
    Normalize a listings API response into a list of dicts:
      price, qty, condition, seller, verified (bool), direct (bool)
    Sorted lowest price first, capped at LISTING_COUNT.
    """
    if not api_response:
        return []

    if isinstance(api_response, list):
        items = api_response
    elif isinstance(api_response, dict):
        items = (api_response.get('results') or
                 api_response.get('data') or
                 api_response.get('listings') or
                 api_response.get('items') or [])
    else:
        return []

    # mp-search-api nests actual listing items inside results[0]['results']
    if items and isinstance(items[0], dict) and 'results' in items[0]:
        items = items[0].get('results') or []

    listings = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # Standard listings only — no lots, bundles, or "spoils and loot" entries
        if item.get('listingType', 'standard') != 'standard':
            continue

        # Language filter — languageId 1 = English on TCGplayer (more reliable than
        # the string field, which sellers often leave blank on foreign variants)
        lang_id = item.get('languageId')
        if lang_id is not None and lang_id != 1:
            continue
        # Also check the string field as a secondary guard
        lang = (item.get('language') or item.get('languageAbbreviation') or '').lower()
        if lang and lang not in ('english', 'en'):
            continue

        # Skip listings with seller-uploaded custom photos (dice-only, accessories, etc.)
        # customData is always present as {'images': []} — only filter when images non-empty
        custom_images = (item.get('customData') or {}).get('images') or []
        if custom_images:
            continue

        price = item.get('price') or item.get('sellerPrice') or ''

        # Price sanity check — listings below MIN_LISTING_PRICE_PCT of market price
        # are almost certainly not the actual product (accessories, opened shells, etc.)
        if market_price and price != '':
            try:
                price_num = float(str(price).replace('$', '').replace(',', ''))
                if price_num < market_price * MIN_LISTING_PRICE_PCT:
                    continue
            except (ValueError, TypeError):
                pass
        qty = item.get('quantity') or ''
        condition = item.get('condition') or 'Near Mint'
        seller = item.get('sellerName') or ''
        direct = bool(item.get('directSeller') or item.get('directProduct') or item.get('directListing'))
        verified = direct or bool(item.get('goldSeller') or item.get('verifiedSeller'))

        if price != '':
            listings.append({
                'price': price,
                'qty': qty,
                'condition': condition,
                'seller': seller,
                'verified': verified,
                'direct': direct,
            })

    # Sort by price ascending, return top N
    def price_key(l):
        try:
            return float(str(l['price']).replace('$', '').replace(',', ''))
        except Exception:
            return 9999999
    listings.sort(key=price_key)
    return listings[:LISTING_COUNT]


def get_recent_sales_via_js(driver, product_id):
    """
    Try to call TCGplayer's internal sales API endpoints from the browser context.
    Since we're already on their domain, session cookies are included automatically.
    """
    # Endpoint patterns to try — TCGplayer has changed these over time
    endpoints = [
        f'/api/product/{product_id}/latestsales?rows={RECENT_SALES_COUNT}&sellerStatus=Live&channel=0&minCondition=7',
        f'/api/product/{product_id}/latestsales?rows={RECENT_SALES_COUNT}',
        f'/api/v2/product/{product_id}/latestsales?rows={RECENT_SALES_COUNT}',
        f'/api/catalog/product/{product_id}/latestsales?rows={RECENT_SALES_COUNT}',
    ]

    for endpoint in endpoints:
        try:
            result = driver.execute_async_script("""
                const [url, callback] = [arguments[0], arguments[arguments.length - 1]];
                fetch(url, {
                    credentials: 'include',
                    headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
                })
                .then(r => r.ok ? r.json() : null)
                .then(data => callback(data))
                .catch(() => callback(null));
            """, endpoint)

            if result:
                print(f"  → Got sales via JS fetch: {endpoint}")
                return result
        except Exception:
            continue

    return None


def try_sales_popup(driver, wait):
    """
    Attempt to find and click TCGplayer's recent sales popup trigger,
    then extract individual sale records from the modal.
    Returns list of sale dicts.
    """
    sales = []

    # Broad set of selectors to try for the trigger
    trigger_css = [
        "a.price-points__upper__header__popup",
        "[class*='sales-popup']",
        "[data-testid*='sales']",
        "a[href*='sales-history']",
        ".price-guide .view-all",
        "a.view-all-sales",
    ]
    trigger_xpath = [
        "//span[contains(text(),'Most Recent Sale')]/ancestor::tr//a",
        "//a[normalize-space()='View All']",
        "//button[contains(normalize-space(),'Sales History')]",
        "//a[contains(normalize-space(),'View Sales')]",
        "//*[contains(@class,'sales')]//a[contains(@class,'view') or contains(@class,'more')]",
    ]

    trigger = None
    for sel in trigger_css:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    trigger = el
                    break
            if trigger:
                break
        except Exception:
            continue

    if not trigger:
        for xpath in trigger_xpath:
            try:
                els = driver.find_elements(By.XPATH, xpath)
                for el in els:
                    if el.is_displayed() and el.is_enabled():
                        trigger = el
                        break
                if trigger:
                    break
            except Exception:
                continue

    if not trigger:
        print("  → No sales popup trigger found")
        return sales

    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", trigger)
        time.sleep(2)

        # Wait for a modal/popup to appear
        modal_selectors = "[role='dialog'], .tcg-modal, .sales-popup, .modal, .overlay, [class*='Modal'], [class*='Popup']"
        try:
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selectors)))
        except Exception:
            pass  # Continue anyway — the content might have changed without a traditional modal

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        modal = (
            soup.find(attrs={'role': 'dialog'}) or
            soup.find(class_=re.compile(r'modal|popup|overlay|dialog', re.I))
        )

        if modal:
            for row in modal.find_all('tr')[1:]:  # skip header
                cells = row.find_all('td')
                if len(cells) < 2:
                    continue
                sale = {
                    'date': cells[0].get_text(strip=True) if len(cells) > 0 else '',
                    'condition': cells[1].get_text(strip=True) if len(cells) > 1 else '',
                    'price': cells[2].get_text(strip=True) if len(cells) > 2 else '',
                    'qty': cells[3].get_text(strip=True) if len(cells) > 3 else '',
                }
                if sale['price']:
                    sales.append(sale)
            print(f"  → Got {len(sales)} sales from popup")
        else:
            print("  → Popup opened but no modal element found")

        # Try to close the modal
        for close_sel in ["[aria-label='close']", "[aria-label='Close']", ".modal__close", "button.close", ".tcg-modal__close"]:
            try:
                driver.find_element(By.CSS_SELECTOR, close_sel).click()
                break
            except Exception:
                continue

    except Exception as e:
        print(f"  → Popup interaction error: {e}")

    return sales


def parse_recent_sales_response(api_response):
    """
    Normalize the API response (which varies by endpoint) into a consistent list of dicts.
    """
    if not api_response:
        return []

    sales = []

    # Handle various response shapes
    if isinstance(api_response, list):
        items = api_response
    elif isinstance(api_response, dict):
        # Common shapes: {'results': [...]} or {'data': [...]} or {'sales': [...]}
        items = (api_response.get('results') or
                 api_response.get('data') or
                 api_response.get('sales') or
                 api_response.get('items') or [])
    else:
        return []

    for item in items[:RECENT_SALES_COUNT]:
        if not isinstance(item, dict):
            continue
        sale = {
            'date': (item.get('orderDate') or item.get('date') or item.get('soldAt') or ''),
            'condition': (item.get('condition') or item.get('conditionName') or item.get('printingName') or ''),
            'price': (item.get('purchasePrice') or item.get('price') or item.get('salePrice') or ''),
            'qty': (item.get('quantity') or item.get('qty') or 1),
        }
        if sale['price']:
            sales.append(sale)

    return sales


def scrape_product_data(product_id, url, driver):
    """
    Scrapes a TCGplayer product page. Tries multiple strategies to get recent sales.
    """
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "section.product-details__price-guide")))
        time.sleep(2)

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # --- Product name ---
        product_name_el = soup.find('h1', class_='product-details__name')
        if not product_name_el:
            product_name_el = soup.find('h1')
        product_name = product_name_el.text.strip() if product_name_el else "Unknown Product"

        # --- Price guide section ---
        price_guide = soup.find('section', class_='price-guide__points')
        market_price = most_recent_sale = listed_median = current_quantity = current_sellers = 'N/A'

        if price_guide:
            # Market Price — find the first upper header row
            for title_span in price_guide.find_all('span', class_='price-points__upper__header__title'):
                if 'Market Price' in title_span.get_text():
                    row = title_span.find_parent('tr')
                    if row:
                        val = row.find('span', class_='price-points__upper__price')
                        if val:
                            market_price = val.text.strip()
                    break

            # Most Recent Sale
            mrs_label = price_guide.find('span', string=lambda t: t and 'Most Recent Sale' in t.strip())
            if mrs_label:
                row = mrs_label.find_parent('tr')
                if row:
                    val = row.find('span', class_='price-points__upper__price')
                    if val:
                        most_recent_sale = val.text.strip()

            def get_lower(label_text):
                el = price_guide.find('span', class_='text', string=lambda t: t and label_text in t.strip())
                if el:
                    sib = el.find_parent('td')
                    if sib:
                        sib = sib.find_next_sibling('td')
                    if sib:
                        val = sib.find('span', class_='price-points__lower__price')
                        if val:
                            return val.text.strip()
                return 'N/A'

            listed_median = get_lower('Listed Median:')

            # Quantity & Sellers (may be on the same row)
            qty_el = price_guide.find('span', class_='text', string=lambda t: t and 'Current Quantity:' in t.strip())
            if qty_el:
                row = qty_el.find_parent('tr')
                if row:
                    spans = row.find_all('span', class_='price-points__lower__price')
                    current_quantity = spans[0].text.strip() if len(spans) >= 1 else 'N/A'
                    current_sellers = spans[1].text.strip() if len(spans) >= 2 else get_lower('Current Sellers:')
            else:
                current_quantity = get_lower('Current Quantity:')
                current_sellers = get_lower('Current Sellers:')

        # --- Sales data section (Sold Yesterday, Total Sold) ---
        # TCGplayer's page has multiple possible structures for this section.
        # We try every table row in the whole document looking for these labels,
        # rather than relying on a specific section class.
        sold_yesterday = 'N/A'
        total_sold = 'N/A'

        # Try the dedicated sales-data section first
        for section_class in ['sales-data', 'sales-data__section', 'product-sales-data']:
            sales_section = soup.find('section', class_=section_class)
            if not sales_section:
                sales_section = soup.find('div', class_=section_class)
            if sales_section:
                for row in sales_section.find_all('tr'):
                    tds = row.find_all('td')
                    if len(tds) < 2:
                        continue
                    label = tds[0].get_text(strip=True)
                    val_el = tds[1].find('span')
                    value = val_el.text.strip() if val_el else tds[1].get_text(strip=True)
                    if re.search(r'Total Sold', label, re.I):
                        total_sold = value
                    elif re.search(r'Sold (Yesterday|Today|Last\s*24)', label, re.I):
                        sold_yesterday = value
                break  # Found a section, stop looking

        # Fallback: scan ALL table rows for these labels
        if total_sold == 'N/A' and sold_yesterday == 'N/A':
            for row in soup.find_all('tr'):
                tds = row.find_all('td')
                if len(tds) < 2:
                    continue
                label = tds[0].get_text(strip=True)
                val_el = tds[1].find('span')
                value = val_el.text.strip() if val_el else tds[1].get_text(strip=True)
                if re.search(r'Total Sold', label, re.I) and total_sold == 'N/A':
                    total_sold = value
                if re.search(r'Sold (Yesterday|Today|Last\s*24)', label, re.I) and sold_yesterday == 'N/A':
                    sold_yesterday = value

        print(f"  → {product_name}: Market={market_price}, MRS={most_recent_sale}, "
              f"Qty={current_quantity}, TotalSold={total_sold}, SoldYday={sold_yesterday}")

        # --- Recent sales + active listings ---
        recent_sales = []
        top_listings = []

        # Sales: network log interception first, JS fetch fallback
        if product_id:
            log_data = get_api_data_from_network_logs(driver, product_id)
            if log_data['sales']:
                recent_sales = parse_recent_sales_response(log_data['sales'])
        if not recent_sales and product_id:
            api_data = get_recent_sales_via_js(driver, product_id)
            if api_data:
                recent_sales = parse_recent_sales_response(api_data)
        if not recent_sales:
            recent_sales = try_sales_popup(driver, wait)

        # Listings: always use JS POST (GET endpoint returns aggregations only)
        if product_id:
            mp_num = None
            try:
                mp_num = float(str(market_price).replace('$', '').replace(',', ''))
            except (ValueError, TypeError):
                pass
            api_data = get_listings_via_js(driver, product_id)
            if api_data:
                top_listings = parse_listings_response(api_data, product_id=product_id, market_price=mp_num)

        print(f"  → {len(recent_sales)} sale records, {len(top_listings)} listings captured")

        return product_name, {
            "Date": datetime.now().strftime('%Y-%m-%d'),
            "Market Price": market_price,
            "Most Recent Sale": most_recent_sale,
            "Listed Median": listed_median,
            "Current Quantity": current_quantity,
            "Current Sellers": current_sellers,
            "Sold Yesterday": sold_yesterday,
            "Total Sold": total_sold,
            "Recent Sales": json.dumps(recent_sales) if recent_sales else '[]',
            "Top Listings": json.dumps(top_listings) if top_listings else '[]',
        }

    except Exception as e:
        print(f"  ✗ Scrape error for {url}: {e}")
        return None, None


def init_db():
    """Create the price_history table if it doesn't exist."""
    conn = sqlite3.connect(_db_path())
    conn.execute('''CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        date TEXT NOT NULL,
        market_price TEXT,
        most_recent_sale TEXT,
        listed_median TEXT,
        current_quantity TEXT,
        current_sellers TEXT,
        sold_yesterday TEXT,
        total_sold TEXT,
        recent_sales TEXT,
        top_listings TEXT,
        price_change REAL DEFAULT 0.0,
        quantity_change REAL DEFAULT 0.0,
        daily_sales REAL DEFAULT 0.0
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_product_id ON price_history(product_id)')
    conn.commit()
    conn.close()


def update_data(product_id, product_name, new_data):
    """
    Append new data to the SQLite database and compute day-over-day changes.
    Returns a DataFrame of the product's full history.
    """
    if not new_data or not product_name:
        return None

    new_data['Price Change'] = 0.0
    new_data['Quantity Change'] = 0.0
    new_data['Daily Sales'] = 0.0

    def to_num(val):
        return pd.to_numeric(str(val).replace('$', '').replace(',', ''), errors='coerce')

    conn = sqlite3.connect(_db_path())

    # Get previous row for day-over-day calculations
    prev = conn.execute(
        'SELECT market_price, current_quantity, total_sold FROM price_history WHERE product_id = ? ORDER BY id DESC LIMIT 1',
        (str(product_id),)
    ).fetchone()

    if prev:
        last_price, new_price = to_num(prev[0]), to_num(new_data['Market Price'])
        if pd.notna(last_price) and pd.notna(new_price):
            new_data['Price Change'] = new_price - last_price

        last_qty, new_qty = to_num(prev[1]), to_num(new_data['Current Quantity'])
        if pd.notna(last_qty) and pd.notna(new_qty):
            new_data['Quantity Change'] = new_qty - last_qty

        last_sold, new_sold = to_num(prev[2]), to_num(new_data.get('Total Sold', 0))
        if pd.notna(last_sold) and pd.notna(new_sold) and new_sold >= last_sold:
            new_data['Daily Sales'] = new_sold - last_sold

    conn.execute(
        '''INSERT INTO price_history
           (product_id, product_name, date, market_price, most_recent_sale, listed_median,
            current_quantity, current_sellers, sold_yesterday, total_sold,
            recent_sales, top_listings, price_change, quantity_change, daily_sales)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            str(product_id),
            product_name,
            new_data['Date'],
            new_data['Market Price'],
            new_data['Most Recent Sale'],
            new_data['Listed Median'],
            new_data['Current Quantity'],
            new_data['Current Sellers'],
            new_data['Sold Yesterday'],
            new_data['Total Sold'],
            new_data.get('Recent Sales', '[]'),
            new_data.get('Top Listings', '[]'),
            new_data['Price Change'],
            new_data['Quantity Change'],
            new_data['Daily Sales'],
        )
    )
    conn.commit()

    df = pd.read_sql_query(_HISTORY_SELECT, conn, params=(str(product_id),))
    conn.close()
    return df


def get_all_latest_from_db():
    """Return a list of dicts with the latest row per product_id."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT p.product_id, p.product_name, p.date, p.market_price, p.most_recent_sale,
               p.listed_median, p.current_quantity, p.current_sellers, p.total_sold,
               p.top_listings, p.price_change, p.quantity_change, p.daily_sales
        FROM price_history p
        INNER JOIN (
            SELECT product_id, MAX(id) as max_id
            FROM price_history GROUP BY product_id
        ) latest ON p.id = latest.max_id
        ORDER BY p.product_name
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_product_history(product_id):
    """Return full history DataFrame for a single product."""
    conn = sqlite3.connect(_db_path())
    df = pd.read_sql_query(_HISTORY_SELECT, conn, params=(str(product_id),))
    conn.close()
    return df


def get_product_detail(product_id):
    """Return the latest row for a single product as a dict, or None."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM price_history WHERE product_id = ? ORDER BY id DESC LIMIT 1',
        (str(product_id),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def generate_pdf_from_db(output_path=None):
    """Generate the PDF report from existing DB data without scraping."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row

    # Get distinct product IDs
    rows = conn.execute('''
        SELECT p.product_id, p.product_name FROM price_history p
        INNER JOIN (
            SELECT product_id, MAX(id) as max_id
            FROM price_history GROUP BY product_id
        ) latest ON p.id = latest.max_id
        ORDER BY p.product_name
    ''').fetchall()

    if not rows:
        conn.close()
        print("No data in database.")
        return None

    # Load all history in one connection
    all_products_data = []
    for row in rows:
        pid = row['product_id']
        name = _sanitize_for_pdf(row['product_name'])
        df = pd.read_sql_query(_HISTORY_SELECT, conn, params=(str(pid),))
        if df is not None and not df.empty:
            all_products_data.append({
                'name': name,
                'latest': df.iloc[-1].to_dict(),
                'history': df
            })
    conn.close()

    if all_products_data:
        create_combo_pdf_report(all_products_data, output_path=output_path)
        return True
    return None


def _compute_avg_recent_sale(recent_sales_json):
    """Parse recent sales JSON and return average price as float, or None."""
    try:
        sales = json.loads(recent_sales_json) if isinstance(recent_sales_json, str) else recent_sales_json
        if not sales:
            return None
        prices = []
        for s in sales:
            p = s.get('price', '')
            p_num = pd.to_numeric(str(p).replace('$', '').replace(',', ''), errors='coerce')
            if pd.notna(p_num):
                prices.append(p_num)
        return sum(prices) / len(prices) if prices else None
    except Exception:
        return None


def create_combo_pdf_report(all_products_data, output_path=None):
    """Generate the combined PDF report."""
    if not all_products_data:
        print("No data collected.")
        return

    pdf = PDF()

    # --- Summary page ---
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(0, 10, 'Daily Report Summary', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.ln(10)

    def parse_listings_json(raw):
        try:
            return json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            return []

    def lowest_listing_price(listings):
        """Return the lowest listed price as a float, or None."""
        for l in listings:
            try:
                return float(str(l.get('price', '')).replace('$', '').replace(',', ''))
            except Exception:
                continue
        return None

    # Table header
    cols = [
        (62, 'Product Name'),
        (20, 'Market $'),
        (20, 'Change'),
        (18, 'Qty'),
        (14, 'Qty Chg'),
        (16, 'Sold/Day'),
        (20, 'Avg Sale'),
        (20, 'Low Ask'),
    ]
    pdf.set_font('Helvetica', 'B', 7)
    for w, txt in cols:
        is_last = txt == cols[-1][1]
        pdf.cell(w, 8, txt, 1, align='C',
                 new_x=XPos.LMARGIN if is_last else XPos.RIGHT,
                 new_y=YPos.NEXT if is_last else YPos.TOP)

    pdf.set_font('Helvetica', '', 7)
    for prod in all_products_data:
        latest = prod['latest']

        pdf.cell(62, 8, prod['name'][:44], 1)
        pdf.cell(20, 8, str(latest.get('Market Price', 'N/A')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        pc = float(latest.get('Price Change', 0) or 0)
        pdf.set_text_color(34, 139, 34) if pc > 0 else (pdf.set_text_color(220, 20, 60) if pc < 0 else None)
        pdf.cell(20, 8, f"{'+' if pc > 0 else ''}${pc:.2f}", 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_text_color(0, 0, 0)

        pdf.cell(18, 8, str(latest.get('Current Quantity', 'N/A')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        qc = int(float(latest.get('Quantity Change', 0) or 0))
        pdf.set_text_color(34, 139, 34) if qc > 0 else (pdf.set_text_color(220, 20, 60) if qc < 0 else None)
        pdf.cell(14, 8, f"{'+' if qc > 0 else ''}{qc}", 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_text_color(0, 0, 0)

        ds = int(float(latest.get('Daily Sales', 0) or 0))
        pdf.cell(16, 8, str(ds), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        avg = _compute_avg_recent_sale(latest.get('Recent Sales', '[]'))
        avg_str = f"${avg:.2f}" if avg is not None else 'N/A'
        pdf.cell(20, 8, avg_str, 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        listings = parse_listings_json(latest.get('Top Listings', '[]'))
        low_ask = lowest_listing_price(listings)
        low_ask_str = f"${low_ask:.2f}" if low_ask is not None else 'N/A'
        pdf.cell(20, 8, low_ask_str, 1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- Per-product detail pages ---
    for prod in all_products_data:
        df = prod['history'].copy()
        df['Date'] = pd.to_datetime(df['Date'])
        df.sort_values('Date', inplace=True)

        def to_num_col(col):
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False),
                    errors='coerce'
                )

        for col in ['Market Price', 'Most Recent Sale', 'Listed Median',
                    'Current Quantity', 'Current Sellers', 'Total Sold', 'Daily Sales']:
            to_num_col(col)

        df['7-Day Avg'] = df['Market Price'].rolling(window=7, min_periods=1).mean()

        # Compute avg recent sale for each row
        if 'Recent Sales' in df.columns:
            df['Avg Recent Sale'] = df['Recent Sales'].apply(_compute_avg_recent_sale)
        else:
            df['Avg Recent Sale'] = None

        # Chart
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax1 = plt.subplots(figsize=(10, 5))

        ax1.plot(df['Date'], df['Market Price'], 'o-', label='Market Price', zorder=5)
        ax1.plot(df['Date'], df['7-Day Avg'], '--', color='orange', label='7-Day Avg', zorder=4)
        ax1.scatter(df['Date'], df['Most Recent Sale'], c='red', marker='x', label='Most Recent Sale', zorder=10, alpha=0.8)

        if df['Avg Recent Sale'].notna().any():
            ax1.plot(df['Date'], df['Avg Recent Sale'], ':', color='purple', label=f'Avg Last {RECENT_SALES_COUNT} Sales', zorder=6)

        ax1.set_ylabel('Price (USD)')
        ax1.tick_params(axis='x', rotation=45)

        ax2 = ax1.twinx()
        ax2.bar(df['Date'], df['Daily Sales'], label='Daily Sales', color='mediumseagreen', alpha=0.6, width=0.5)
        ax2.bar(df['Date'], df['Current Sellers'], label='Sellers', color='lightblue', alpha=0.6, width=-0.5, align='edge')
        ax2.set_ylabel('Quantity / Sellers')

        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(lines + lines2, labels + labels2, loc='upper left', fontsize=7)

        plt.title(f'{prod["name"]}')
        plt.tight_layout()

        safe_name = "".join(c for c in prod['name'] if c.isalnum() or c in (' ', '_')).rstrip()
        chart_path = f"{safe_name}_chart.png"
        plt.savefig(chart_path)
        plt.close()

        # PDF page
        pdf.add_page()
        pdf.set_font('Helvetica', 'B', 14)
        pdf.multi_cell(0, 10, prod['name'], align='C')
        pdf.ln(3)

        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 8, "Today's Data", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('Helvetica', '', 10)

        latest = prod['latest']
        display_fields = [
            ('Date', latest.get('Date', 'N/A')),
            ('Market Price', latest.get('Market Price', 'N/A')),
            ('Most Recent Sale', latest.get('Most Recent Sale', 'N/A')),
            ('Listed Median', latest.get('Listed Median', 'N/A')),
            ('Current Quantity', latest.get('Current Quantity', 'N/A')),
            ('Current Sellers', latest.get('Current Sellers', 'N/A')),
            ('Sold Yesterday', latest.get('Sold Yesterday', 'N/A')),
            ('Total Sold', latest.get('Total Sold', 'N/A')),
            ('Daily Sales (calc)', int(float(latest.get('Daily Sales', 0) or 0))),
        ]

        avg = _compute_avg_recent_sale(latest.get('Recent Sales', '[]'))
        if avg is not None:
            display_fields.append((f'Avg of Last {RECENT_SALES_COUNT} Sales', f'${avg:.2f}'))

        for key, val in display_fields:
            pdf.cell(55, 7, f"{key}:", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(0, 7, str(val), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Recent individual sales table
        recent_sales = []
        try:
            rs_raw = latest.get('Recent Sales', '[]')
            recent_sales = json.loads(rs_raw) if isinstance(rs_raw, str) else rs_raw
        except Exception:
            pass

        if recent_sales:
            pdf.ln(3)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.cell(0, 7, f'Last {len(recent_sales)} Individual Sales', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font('Helvetica', 'B', 8)
            pdf.cell(50, 6, 'Date', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(55, 6, 'Condition', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(45, 6, 'Price', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(40, 6, 'Qty', 1, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font('Helvetica', '', 8)
            for sale in recent_sales:
                pdf.cell(50, 6, str(sale.get('date', ''))[:20], 1, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(55, 6, str(sale.get('condition', ''))[:25], 1, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(45, 6, str(sale.get('price', '')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(40, 6, str(sale.get('qty', '')), 1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Active listings table
        top_listings = []
        try:
            tl_raw = latest.get('Top Listings', '[]')
            top_listings = json.loads(tl_raw) if isinstance(tl_raw, str) else (tl_raw or [])
        except Exception:
            pass

        if top_listings:
            pdf.ln(3)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.cell(0, 7, f'Top {len(top_listings)} Active Listings (Lowest Price First)', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font('Helvetica', 'B', 8)
            pdf.cell(30, 6, 'Price', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(15, 6, 'Qty', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(45, 6, 'Condition', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(65, 6, 'Seller', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(35, 6, 'Status', 1, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font('Helvetica', '', 8)
            for listing in top_listings:
                price_str = str(listing.get('price', 'N/A'))
                if not price_str.startswith('$'):
                    try:
                        price_str = f"${float(price_str):.2f}"
                    except Exception:
                        pass
                status = 'Direct' if listing.get('direct') else ('Verified' if listing.get('verified') else 'Standard')
                pdf.cell(30, 6, price_str, 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(15, 6, str(listing.get('qty', '')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(45, 6, str(listing.get('condition', ''))[:22], 1, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(65, 6, str(listing.get('seller', ''))[:30], 1, new_x=XPos.RIGHT, new_y=YPos.TOP)
                if listing.get('direct'):
                    pdf.set_text_color(0, 100, 200)
                elif listing.get('verified'):
                    pdf.set_text_color(34, 139, 34)
                pdf.cell(35, 6, status, 1, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(0, 0, 0)

        pdf.ln(3)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(3)
        pdf.image(chart_path, x=None, y=None, w=190)
        os.remove(chart_path)

    out = output_path or DEFAULT_PDF_OUTPUT
    pdf.output(out)
    print(f"Report generated: {out}")


def create_driver():
    """Create and return a fresh Chrome driver with CDP network tracking."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    options.add_argument('--window-size=1920,1080')
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(60)
    driver.execute_cdp_cmd('Network.enable', {})
    return driver


def scrape_with_retry(product_id, url, driver):
    """Attempt to scrape a product, retrying with backoff on failure."""
    for attempt in range(1 + RETRY_ATTEMPTS):
        name, data = scrape_product_data(product_id, url, driver)
        if data and name and name != "Unknown Product":
            return name, data
        if attempt < RETRY_ATTEMPTS:
            wait = RETRY_BACKOFF * (2 ** attempt)
            print(f"  ↻ Retry {attempt + 1}/{RETRY_ATTEMPTS} in {wait}s...")
            time.sleep(wait)
    return None, None


def run_scrape(progress_callback=None, generate_pdf=True):
    """Run the full scrape pipeline. Returns (succeeded_count, failed_list).

    progress_callback: optional callable(current, total, product_name) for live status updates.
    generate_pdf: if True, generate the PDF report after scraping.
    """
    init_db()
    products = load_products()
    total = len(products)
    print(f"Loaded {total} products")

    driver = create_driver()
    all_products_data = []
    failed = []

    try:
        for i, entry in enumerate(products, 1):
            product_id, url = normalize_product(entry)
            if product_id is None:
                print(f"\n[{i}/{total}]  ✗ Could not parse product: {entry}")
                if progress_callback:
                    progress_callback(i, total, f"Skipped: {entry}")
                continue

            print(f"\n[{i}/{total}] Scraping: {url}")
            if progress_callback:
                progress_callback(i, total, f"Scraping {product_id}...")
            name, data = scrape_with_retry(product_id, url, driver)

            if data and name:
                df = update_data(product_id, name, data)
                if df is not None and not df.empty:
                    all_products_data.append({
                        'name': _sanitize_for_pdf(name),
                        'latest': df.iloc[-1].to_dict(),
                        'history': df
                    })
                if progress_callback:
                    progress_callback(i, total, name)
            else:
                print(f"  ✗ Failed: {url}")
                failed.append(entry)
                if progress_callback:
                    progress_callback(i, total, f"Failed: {product_id}")
            print("-" * 40)

            # Session rotation
            if i % SESSION_ROTATE_EVERY == 0 and i < total:
                print(f"\n--- Rotating Chrome session (after {i} products) ---")
                driver.quit()
                time.sleep(3)
                driver = create_driver()

            # Delay between requests
            if i < total:
                delay = random.uniform(*DELAY_BETWEEN_REQUESTS)
                time.sleep(delay)

        if generate_pdf and all_products_data:
            create_combo_pdf_report(all_products_data)

        print(f"\nDone: {len(all_products_data)} succeeded, {len(failed)} failed")
        if failed:
            print(f"Failed products: {failed}")

        return len(all_products_data), failed

    finally:
        driver.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TCGplayer Price Tracker')
    parser.add_argument('--serve', action='store_true', help='Start the web interface')
    parser.add_argument('--port', type=int, default=5000, help='Port for the web interface (default: 5000)')
    parser.add_argument('--pdf', action='store_true', help='Generate PDF from existing DB data without scraping')
    args = parser.parse_args()

    init_db()

    if args.serve:
        from web import create_app
        app = create_app()
        app.run(debug=True, port=args.port)
    elif args.pdf:
        result = generate_pdf_from_db()
        if not result:
            print("No data in database. Run a scrape first.")
    else:
        run_scrape()
