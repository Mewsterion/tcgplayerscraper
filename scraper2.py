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

class PDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, 'TCGplayer Daily Market Report', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def _to_numeric(val):
    """Strip $ and commas, convert to float"""
    return pd.to_numeric(str(val).replace('$', '').replace(',', ''), errors='coerce')

def _get_text(elem, selector, attr=None):
    """Safe soup element extraction"""
    found = elem.find(selector, attr) if attr else elem.find(selector)
    return found.text.strip() if found else 'N/A'

def scrape_product_data(url, driver):
    """Scrape TCGplayer product page"""
    try:
        driver.get(url)
        import time
        time.sleep(3)  # Initial render delay
        
        # Wait for multiple critical elements
        wait = WebDriverWait(driver, 45)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "section[class*='price']")))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Debug: Save HTML to file for inspection
        # with open('debug_page.html', 'w', encoding='utf-8') as f:
        #     f.write(str(soup))
        
        product_name = _get_text(soup, 'h1', {'class_': 'product-details__name'})
        if product_name == 'N/A':
            # Fallback: Try any h1
            h1 = soup.find('h1')
            product_name = h1.text.strip() if h1 else "Unknown Product"
        
        print(f"  → Product: {product_name}")
        
        pg_sec = soup.find('section', class_='price-guide__points')
        data = {
            "Date": datetime.now().strftime('%Y-%m-%d'),
            "Market Price": 'N/A',
            "Most Recent Sale": 'N/A',
            "Listed Median": 'N/A',
            "Current TCGplayer Listed Quantity": 'N/A',
            "Current Sellers": 'N/A'
        }

        if pg_sec:
            print("  → Found price-guide section")
            # Market Price
            mp_label = pg_sec.find('span', class_='price-points__upper__header__title', string=lambda t: t and 'Market Price' in t)
            if mp_label:
                mp_val = mp_label.find_parent('tr').find('span', class_='price-points__upper__price')
                if mp_val: data["Market Price"] = mp_val.text.strip()
            
            # Most Recent Sale
            mrs_label = pg_sec.find('span', string=lambda t: t and 'Most Recent Sale' in t)
            if mrs_label:
                mrs_val = mrs_label.find_parent('tr').find('span', class_='price-points__upper__price')
                if mrs_val: data["Most Recent Sale"] = mrs_val.text.strip()
            
            # Helper for lower section values
            def get_lower(label):
                lbl = pg_sec.find('span', class_='text', string=lambda t: t and label in t)
                if lbl:
                    val_td = lbl.find_parent('td').find_next_sibling('td')
                    if val_td:
                        val_span = val_td.find('span', class_='price-points__lower__price')
                        if val_span: return val_span.text.strip()
                return 'N/A'
            
            data["Listed Median"] = get_lower('Listed Median:')
            
            # Quantity & Sellers (can be in same row)
            qty_label = pg_sec.find('span', class_='text', string=lambda t: t and 'Current Quantity:' in t)
            if qty_label:
                row = qty_label.find_parent('tr')
                spans = row.find_all('span', class_='price-points__lower__price')
                if spans:
                    data["Current TCGplayer Listed Quantity"] = spans[0].text.strip()
                    data["Current Sellers"] = spans[1].text.strip() if len(spans) > 1 else get_lower('Current Sellers:')
            else:
                data["Current TCGplayer Listed Quantity"] = get_lower('Current Quantity:')
                data["Current Sellers"] = get_lower('Current Sellers:')
        else:
            print("  ✗ No price-guide__points section found")
        
        print(f"  → Market Price: {data['Market Price']}")
        return product_name, data
    except Exception as e:
        print(f"Scrape error {url}: {e}")
        return None, None

def update_data(product_name, new_data):
    """Update CSV with change calculations"""
    if not new_data or not product_name:
        return None
    
    csv_file = f"{''.join(c for c in product_name if c.isalnum() or c in (' ', '_')).rstrip()}.csv"
    new_data.update({'Price Change': 0, 'Quantity Change': 0})

    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        if not df_old.empty:
            last = df_old.iloc[-1]
            
            # Price change
            last_price, new_price = _to_numeric(last.get('Market Price', 0)), _to_numeric(new_data['Market Price'])
            if pd.notna(last_price) and pd.notna(new_price):
                new_data['Price Change'] = new_price - last_price
            
            # Quantity change
            last_qty, new_qty = _to_numeric(last.get('Current TCGplayer Listed Quantity', 0)), _to_numeric(new_data['Current TCGplayer Listed Quantity'])
            if pd.notna(last_qty) and pd.notna(new_qty):
                new_data['Quantity Change'] = new_qty - last_qty
        
        df_combined = pd.concat([df_old, pd.DataFrame([new_data])], ignore_index=True)
    else:
        df_combined = pd.DataFrame([new_data])

    df_combined.to_csv(csv_file, index=False)
    return df_combined

def create_combo_pdf_report(all_products_data):
    """Generate combined PDF report"""
    if not all_products_data:
        print("No data to report.")
        return

    pdf = PDF()
    pdf.add_page()
    
    # Summary header
    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(0, 10, 'Daily Report Summary', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.ln(10)

    # Table header
    pdf.set_font('Helvetica', 'B', 8)
    for w, txt in [(95, 'Product Name'), (30, 'Market Price'), (30, 'Change'), 
                   (25, 'Quantity'), (20, 'Qty Chg')]:
        pdf.cell(w, 8, txt, 1, align='C', new_x=XPos.RIGHT if txt != 'Qty Chg' else XPos.LMARGIN, 
                 new_y=YPos.TOP if txt != 'Qty Chg' else YPos.NEXT)

    # Summary rows
    pdf.set_font('Helvetica', '', 8)
    for prod in all_products_data:
        latest = prod['latest']
        pdf.cell(95, 8, prod['name'][:60], 1)
        pdf.cell(30, 8, latest['Market Price'], 1, align='R')
        
        # Price change with color
        pc = latest.get('Price Change', 0)
        pdf.set_text_color(34, 139, 34) if pc > 0 else pdf.set_text_color(220, 20, 60) if pc < 0 else None
        pdf.cell(30, 8, f"{'+' if pc > 0 else ''}{'-' if pc < 0 else ''}${abs(pc):.2f}", 1, align='R')
        pdf.set_text_color(0, 0, 0)
        
        pdf.cell(25, 8, str(latest['Current TCGplayer Listed Quantity']), 1, align='R')
        
        # Qty change with color
        qc = latest.get('Quantity Change', 0)
        pdf.set_text_color(34, 139, 34) if qc > 0 else pdf.set_text_color(220, 20, 60) if qc < 0 else None
        pdf.cell(20, 8, f"{'+' if qc > 0 else ''}{int(qc)}", 1, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)

    # Detailed pages
    for prod in all_products_data:
        df = prod['history'].copy()
        df['Date'] = pd.to_datetime(df['Date'])
        df.sort_values('Date', inplace=True)
        
        # Convert numeric columns
        for col in ['Market Price', 'Most Recent Sale', 'Listed Median']:
            df[col] = _to_numeric(df[col])
        for col in ['Current TCGplayer Listed Quantity', 'Current Sellers']:
            if col in df.columns:
                df[col] = _to_numeric(df[col])
        
        df['7-Day Avg'] = df['Market Price'].rolling(7, min_periods=1).mean()

        # Chart
        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax1 = plt.subplots(figsize=(10, 5))
        ax1.plot(df['Date'], df['Market Price'], 'o-', label='Market Price', zorder=5)
        ax1.plot(df['Date'], df['7-Day Avg'], '--', color='orange', label='7-Day Avg', zorder=4)
        ax1.scatter(df['Date'], df['Most Recent Sale'], c='red', marker='x', label='Recent Sale', zorder=10, alpha=0.8)
        ax1.set_ylabel('Price (USD)')
        ax1.tick_params(axis='x', rotation=45)
        
        ax2 = ax1.twinx()
        ax2.bar(df['Date'], df['Current TCGplayer Listed Quantity'], color='mediumseagreen', alpha=0.6, width=0.5, label='Listed Qty')
        ax2.bar(df['Date'], df['Current Sellers'], color='lightblue', alpha=0.6, width=-0.5, align='edge', label='Sellers')
        ax2.set_ylabel('Quantity / Sellers')

        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(lines + lines2, labels + labels2, loc='upper left')

        plt.title(f'History: {prod["name"]}')
        plt.tight_layout()
        chart_path = f"{''.join(c for c in prod['name'] if c.isalnum() or c in (' ', '_')).rstrip()}_chart.png"
        plt.savefig(chart_path)
        plt.close()

        # PDF page
        pdf.add_page()
        pdf.set_font('Helvetica', 'B', 16)
        pdf.multi_cell(0, 10, prod['name'], align='C')
        pdf.ln(5)
        
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 10, 'Latest Data Point', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('Helvetica', '', 11)
        
        for k, v in {k: v for k, v in prod['latest'].items() if 'Change' not in k}.items():
            pdf.cell(50, 8, f"{k}:")
            pdf.cell(0, 8, str(v), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.ln(5)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(5)
        pdf.image(chart_path, x=None, y=None, w=190)
        os.remove(chart_path)

    pdf.output("TCGplayer_Combo_Report.pdf")
    print("Report generated: TCGplayer_Combo_Report.pdf")

if __name__ == '__main__':
    opts = webdriver.ChromeOptions()
    # opts.add_argument('--headless=new')  # Temporarily disable headless for debugging
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--log-level=3')
    opts.add_experimental_option('excludeSwitches', ['enable-logging'])
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    opts.add_argument('--window-size=1920,1080')
    
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
    all_products_data = []

    try:
        for url in URLS:
            print(f"\nScraping: {url}")
            name, data = scrape_product_data(url, driver)
            
            if data and name != "Unknown Product":
                print(f"Scraped: {data}")
                df = update_data(name, data)
                if df is not None and not df.empty:
                    all_products_data.append({
                        'name': name,
                        'latest': df.iloc[-1].to_dict(),
                        'history': df
                    })
            else:
                print(f"Failed: {url}")
            print("-" * 40)
        
        if all_products_data:
            create_combo_pdf_report(all_products_data)
    finally:
        driver.quit()