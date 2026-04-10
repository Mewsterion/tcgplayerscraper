# --- Setup Note ---
# If you are using Python 3.12 or newer, you might see a "ModuleNotFoundError: No module named 'distutils'".
# This is because 'distutils' has been removed from recent Python versions.
# To fix this, please run the following command in your terminal before running the script:
# pip install setuptools

import json
import time
import re
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

URLS = [
    'https://www.tcgplayer.com/product/624679/',
    'https://www.tcgplayer.com/product/623628',
    'https://www.tcgplayer.com/product/565606',
    'https://www.tcgplayer.com/product/543846/',
    'https://www.tcgplayer.com/product/493975/',
    'https://www.tcgplayer.com/product/283389/',
    'https://www.tcgplayer.com/product/618893/',
    'https://www.tcgplayer.com/product/630686/',
    'https://www.tcgplayer.com/product/630689/',
    'https://www.tcgplayer.com/product/593324/',
    'https://www.tcgplayer.com/product/502000/',
    'https://www.tcgplayer.com/product/503313',
    'https://www.tcgplayer.com/product/644300',
    'https://www.tcgplayer.com/product/622770',
    'https://www.tcgplayer.com/product/653892',
    'https://www.tcgplayer.com/product/648365',
    'https://www.tcgplayer.com/product/501999'
]

# Number of recent sales to store per product
RECENT_SALES_COUNT = 10


class PDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, 'TCGplayer Daily Market Report', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')


def extract_product_id(url):
    m = re.search(r'/product/(\d+)', url)
    return m.group(1) if m else None


def get_recent_sales_from_network_logs(driver, product_id):
    """
    Parse Chrome performance logs (which capture all XHR/fetch activity) to find
    TCGplayer's internal sales API response. Must be called after page has loaded.
    Returns parsed JSON if found, else None.
    """
    try:
        logs = driver.get_log('performance')
    except Exception as e:
        print(f"  → Performance log unavailable: {e}")
        return None

    for log in logs:
        try:
            message = json.loads(log['message'])['message']
            if message.get('method') != 'Network.responseReceived':
                continue
            url = message.get('params', {}).get('response', {}).get('url', '')
            if 'sales' not in url.lower():
                continue
            if str(product_id) not in url:
                continue

            req_id = message['params']['requestId']
            body_result = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': req_id})
            body_text = body_result.get('body', '')
            if not body_text:
                continue
            data = json.loads(body_text)
            if data:
                print(f"  → Found sales data via network log: {url}")
                return data
        except Exception:
            continue

    return None


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


def scrape_product_data(url, driver):
    """
    Scrapes a TCGplayer product page. Tries multiple strategies to get recent sales.
    """
    try:
        product_id = extract_product_id(url)
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

        # --- Recent individual sales ---
        recent_sales = []

        # Strategy 1: Network log interception (most reliable if TCGplayer makes an XHR)
        if product_id:
            api_data = get_recent_sales_from_network_logs(driver, product_id)
            if api_data:
                recent_sales = parse_recent_sales_response(api_data)

        # Strategy 2: JS fetch from browser context (same-origin, cookies included)
        if not recent_sales and product_id:
            api_data = get_recent_sales_via_js(driver, product_id)
            if api_data:
                recent_sales = parse_recent_sales_response(api_data)

        # Strategy 3: Click the popup
        if not recent_sales:
            recent_sales = try_sales_popup(driver, wait)

        if recent_sales:
            print(f"  → Got {len(recent_sales)} recent sale records")
        else:
            print("  → No recent sales data retrieved")

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
        }

    except Exception as e:
        print(f"  ✗ Scrape error for {url}: {e}")
        return None, None


def update_data(product_name, new_data):
    """
    Append new data to the product CSV and compute day-over-day changes.
    """
    if not new_data or not product_name:
        return None

    safe_name = "".join(c for c in product_name if c.isalnum() or c in (' ', '_')).rstrip()
    csv_file = f"{safe_name}.csv"

    new_data['Price Change'] = 0.0
    new_data['Quantity Change'] = 0.0
    new_data['Daily Sales'] = 0.0

    def to_num(val):
        return pd.to_numeric(str(val).replace('$', '').replace(',', ''), errors='coerce')

    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        if not df_old.empty:
            last = df_old.iloc[-1]

            last_price, new_price = to_num(last.get('Market Price', 0)), to_num(new_data['Market Price'])
            if pd.notna(last_price) and pd.notna(new_price):
                new_data['Price Change'] = new_price - last_price

            last_qty, new_qty = to_num(last.get('Current Quantity', 0)), to_num(new_data['Current Quantity'])
            if pd.notna(last_qty) and pd.notna(new_qty):
                new_data['Quantity Change'] = new_qty - last_qty

            last_sold = to_num(last.get('Total Sold', 0))
            new_sold = to_num(new_data.get('Total Sold', 0))
            if pd.notna(last_sold) and pd.notna(new_sold) and new_sold >= last_sold:
                new_data['Daily Sales'] = new_sold - last_sold

        df_combined = pd.concat([df_old, pd.DataFrame([new_data])], ignore_index=True)
    else:
        df_combined = pd.DataFrame([new_data])

    df_combined.to_csv(csv_file, index=False)
    return df_combined


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


def create_combo_pdf_report(all_products_data):
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

    # Table header
    cols = [
        (72, 'Product Name'),
        (22, 'Market $'),
        (22, 'Change'),
        (20, 'Qty'),
        (15, 'Qty Chg'),
        (18, 'Sold/Day'),
        (21, 'Avg Sale'),
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

        pdf.cell(72, 8, prod['name'][:50], 1)
        pdf.cell(22, 8, str(latest.get('Market Price', 'N/A')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        pc = float(latest.get('Price Change', 0) or 0)
        pdf.set_text_color(34, 139, 34) if pc > 0 else (pdf.set_text_color(220, 20, 60) if pc < 0 else None)
        pdf.cell(22, 8, f"{'+' if pc > 0 else ''}${pc:.2f}", 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_text_color(0, 0, 0)

        pdf.cell(20, 8, str(latest.get('Current Quantity', 'N/A')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        qc = int(float(latest.get('Quantity Change', 0) or 0))
        pdf.set_text_color(34, 139, 34) if qc > 0 else (pdf.set_text_color(220, 20, 60) if qc < 0 else None)
        pdf.cell(15, 8, f"{'+' if qc > 0 else ''}{qc}", 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_text_color(0, 0, 0)

        ds = int(float(latest.get('Daily Sales', 0) or 0))
        pdf.cell(18, 8, str(ds), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)

        avg = _compute_avg_recent_sale(latest.get('Recent Sales', '[]'))
        avg_str = f"${avg:.2f}" if avg is not None else 'N/A'
        pdf.cell(21, 8, avg_str, 1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

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
            pdf.cell(60, 6, 'Condition', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(40, 6, 'Price', 1, align='C', new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(40, 6, 'Qty', 1, align='C', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font('Helvetica', '', 8)
            for sale in recent_sales:
                pdf.cell(50, 6, str(sale.get('date', ''))[:20], 1, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(60, 6, str(sale.get('condition', ''))[:25], 1, new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(40, 6, str(sale.get('price', '')), 1, align='R', new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(40, 6, str(sale.get('qty', '')), 1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(3)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(3)
        pdf.image(chart_path, x=None, y=None, w=190)
        os.remove(chart_path)

    pdf.output("TCGplayer_Combo_Report.pdf")
    print("Report generated: TCGplayer_Combo_Report.pdf")


if __name__ == '__main__':
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    options.add_argument('--window-size=1920,1080')

    # Performance logging captures all XHR/fetch network activity — needed for sales API interception
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

    # Enable network tracking via CDP before any navigation
    driver.execute_cdp_cmd('Network.enable', {})

    all_products_data = []

    try:
        for url in URLS:
            print(f"\nScraping: {url}")
            name, data = scrape_product_data(url, driver)

            if data and name and name != "Unknown Product":
                df = update_data(name, data)
                if df is not None and not df.empty:
                    all_products_data.append({
                        'name': name,
                        'latest': df.iloc[-1].to_dict(),
                        'history': df
                    })
            else:
                print(f"  ✗ Failed: {url}")
            print("-" * 40)

        if all_products_data:
            create_combo_pdf_report(all_products_data)

    finally:
        driver.quit()
