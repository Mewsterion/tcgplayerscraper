# --- Setup Note ---
# If you are using Python 3.12 or newer, you might see a "ModuleNotFoundError: No module named 'distutils'".
# This is because 'distutils' has been removed from recent Python versions.
# To fix this, please run the following command in your terminal before running the script:
# pip install setuptools

import pandas as pd
import matplotlib.pyplot as plt
import os
from datetime import datetime
import re
from bs4 import BeautifulSoup

# --- Using the more standard Selenium setup that was working reliably ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# --- Import for PDF Generation ---
from fpdf import FPDF, XPos, YPos

# --- Configuration ---
# Add as many product URLs as you want to this list
URLS = [
    'https://www.tcgplayer.com/product/624679/',
    'https://www.tcgplayer.com/product/623628',
    'https://www.tcgplayer.com/product/565606',
    'https://www.tcgplayer.com/product/543846/',
    'https://www.tcgplayer.com/product/493975/',
    'https://www.tcgplayer.com/product/283389/',
]

class PDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.cell(0, 10, 'TCGplayer Daily Market Report', 0, 0, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def scrape_product_data(url, driver):
    """
    Scrapes a single TCGplayer product page for the required data.
    """
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "section.product-details__price-guide")))
        
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # --- Data Extraction ---
        product_name_element = soup.find('h1', class_='product-details__name')
        product_name = product_name_element.text.strip() if product_name_element else "Unknown Product"
        
        price_guide_section = soup.find('section', class_='price-guide__points')
        
        market_price, most_recent_sale, listed_median, current_quantity, current_sellers = ('N/A',) * 5

        if price_guide_section:
            # --- Restored working scraping logic ---
            # For Market Price
            mp_label = price_guide_section.find('span', class_='price-points__upper__header__title')
            if mp_label and 'Market Price' in mp_label.text:
                mp_row = mp_label.find_parent('tr')
                if mp_row:
                    mp_value = mp_row.find('span', class_='price-points__upper__price')
                    if mp_value:
                        market_price = mp_value.text.strip()

            # For Most Recent Sale
            mrs_label = price_guide_section.find('span', string=lambda t: t and 'Most Recent Sale' in t.strip())
            if mrs_label:
                mrs_row = mrs_label.find_parent('tr')
                if mrs_row:
                    mrs_value = mrs_row.find('span', class_='price-points__upper__price')
                    if mrs_value:
                        most_recent_sale = mrs_value.text.strip()

            # For the lower section data (Median, Quantity, Sellers)
            def get_lower_value(label):
                label_element = price_guide_section.find('span', class_='text', string=lambda t: t and label in t.strip())
                if label_element:
                    # Find the parent td, then the next sibling td, then the span inside that
                    value_td = label_element.find_parent('td').find_next_sibling('td')
                    if value_td:
                         value_element = value_td.find('span', class_='price-points__lower__price')
                         if value_element:
                            return value_element.text.strip()
                return 'N/A'
            
            listed_median = get_lower_value('Listed Median:')

            # Quantity and Sellers can be in the same row, handle that specifically
            quantity_seller_row = price_guide_section.find('span', class_='text', string=lambda t: t and 'Current Quantity:' in t.strip())
            if quantity_seller_row:
                parent_row = quantity_seller_row.find_parent('tr')
                if parent_row:
                    price_spans = parent_row.find_all('span', class_='price-points__lower__price')
                    if len(price_spans) >= 1:
                        current_quantity = price_spans[0].text.strip()
                    if len(price_spans) >= 2:
                        current_sellers = price_spans[1].text.strip()
                    else: # If sellers is not in the same row, find it separately
                        current_sellers = get_lower_value('Current Sellers:')
            else: # Fallback if the structure is different
                current_quantity = get_lower_value('Current Quantity:')
                current_sellers = get_lower_value('Current Sellers:')


        return product_name, {
            "Date": datetime.now().strftime('%Y-%m-%d'),
            "Market Price": market_price,
            "Most Recent Sale": most_recent_sale,
            "Listed Median": listed_median,
            "Current Quantity": current_quantity,
            "Current Sellers": current_sellers
        }
    except Exception as e:
        print(f"An error occurred during scraping {url}: {e}")
        return None, None

def update_data(product_name, new_data):
    """
    Updates the CSV file for a specific product and calculates changes.
    """
    if not new_data or not product_name:
        return None
    
    safe_filename = "".join(c for c in product_name if c.isalnum() or c in (' ', '_')).rstrip()
    csv_file = f"{safe_filename}.csv"
        
    df_new = pd.DataFrame([new_data])
    
    if os.path.exists(csv_file):
        df_old = pd.read_csv(csv_file)
        if len(df_old) > 0:
            last_entry = df_old.iloc[-1]
            # Calculate Price Change
            last_price = pd.to_numeric(str(last_entry.get('Market Price', '0')).replace('$', ''), errors='coerce')
            new_price = pd.to_numeric(str(new_data['Market Price']).replace('$', ''), errors='coerce')
            if pd.notna(last_price) and pd.notna(new_price):
                 new_data['Price Change'] = new_price - last_price
            else:
                 new_data['Price Change'] = 0
            
            # Calculate Quantity Change
            last_qty = pd.to_numeric(str(last_entry.get('Current Quantity', '0')).replace(',', ''), errors='coerce')
            new_qty = pd.to_numeric(str(new_data.get('Current Quantity', '0')).replace(',', ''), errors='coerce')
            if pd.notna(last_qty) and pd.notna(new_qty):
                new_data['Quantity Change'] = new_qty - last_qty
            else:
                new_data['Quantity Change'] = 0
                
        df_combined = pd.concat([df_old, df_new], ignore_index=True)
    else:
        new_data['Price Change'] = 0
        new_data['Quantity Change'] = 0
        df_combined = df_new

    df_combined.to_csv(csv_file, index=False)
    return df_combined

def create_combo_pdf_report(all_products_data):
    """
    Creates a single combined PDF report for all products with an enhanced summary.
    """
    if not all_products_data:
        print("No data collected to generate a report.")
        return

    pdf = PDF()
    
    # --- Create Enhanced Summary Page ---
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(0, 10, 'Daily Report Summary', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.set_font('Helvetica', '', 12)
    pdf.cell(0, 10, f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.ln(10)

    # Summary Table Headers
    pdf.set_font('Helvetica', 'B', 8)
    pdf.cell(80, 10, 'Product Name', 1, align='C')
    pdf.cell(25, 10, 'Market Price', 1, align='C')
    pdf.cell(20, 10, 'Change', 1, align='C')
    pdf.cell(20, 10, 'Quantity', 1, align='C')
    pdf.cell(20, 10, 'Qty Chg', 1, align='C')
    pdf.cell(25, 10, 'Listed Median', 1, 1, align='C')

    # Summary Table Data
    pdf.set_font('Helvetica', '', 8)
    for product_info in all_products_data:
        latest = product_info['latest']
        pdf.cell(80, 10, product_info['name'][:50], 1) # Truncate long names
        
        # Market Price Cell
        pdf.cell(25, 10, latest['Market Price'], 1, align='R')
        
        # Price Change Cell
        price_change = latest.get('Price Change', 0)
        if price_change > 0:
            pdf.set_text_color(34, 139, 34) # Forest Green
            change_str = f"+${price_change:.2f}"
        elif price_change < 0:
            pdf.set_text_color(220, 20, 60) # Crimson
            change_str = f"-${abs(price_change):.2f}"
        else:
            change_str = "$0.00"
        pdf.cell(20, 10, change_str, 1, align='R')
        pdf.set_text_color(0, 0, 0) # Reset color

        # Current Quantity Cell
        pdf.cell(20, 10, str(latest['Current Quantity']), 1, align='R')

        # Quantity Change Cell
        qty_change = latest.get('Quantity Change', 0)
        if qty_change > 0:
            pdf.set_text_color(34, 139, 34) # Green
            qty_change_str = f"+{int(qty_change)}"
        elif qty_change < 0:
            pdf.set_text_color(220, 20, 60) # Red
            qty_change_str = f"{int(qty_change)}"
        else:
            qty_change_str = "0"
        pdf.cell(20, 10, qty_change_str, 1, align='R')
        pdf.set_text_color(0, 0, 0) # Reset color

        # Listed Median Cell
        pdf.cell(25, 10, latest['Listed Median'], 1, 1, align='R')


    # --- Create a Detailed Page for Each Product ---
    for product_info in all_products_data:
        product_name = product_info['name']
        df = product_info['history']
        latest_data = product_info['latest']

        safe_filename = "".join(c for c in product_name if c.isalnum() or c in (' ', '_')).rstrip()
        chart_image_path = f'{safe_filename}_chart.png'

        # --- Create Enhanced Matplotlib Chart ---
        df['Date'] = pd.to_datetime(df['Date'])
        df_sorted = df.sort_values('Date')
        
        price_cols = ['Market Price', 'Most Recent Sale', 'Listed Median']
        for col in price_cols:
            df_sorted[col] = pd.to_numeric(df_sorted[col].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce')
        
        count_cols = ['Current Quantity', 'Current Sellers']
        for col in count_cols:
            df_sorted[col] = pd.to_numeric(df_sorted[col].astype(str).str.replace(',', ''), errors='coerce')
        
        df_sorted['7-Day Avg'] = df_sorted['Market Price'].rolling(window=7, min_periods=1).mean()

        plt.style.use('seaborn-v0_8-whitegrid')
        fig, ax1 = plt.subplots(figsize=(10, 5))
        
        ax1.plot(df_sorted['Date'], df_sorted['Market Price'], label='Market Price', marker='o', linestyle='-', zorder=5)
        ax1.plot(df_sorted['Date'], df_sorted['7-Day Avg'], label='7-Day Avg', linestyle='--', color='orange', zorder=4)
        ax1.scatter(df_sorted['Date'], df_sorted['Most Recent Sale'], label='Recent Sale', color='red', marker='x', zorder=10, alpha=0.8)
        ax1.set_ylabel('Price (USD)')
        ax1.tick_params(axis='x', rotation=45)
        
        ax2 = ax1.twinx()
        ax2.bar(df_sorted['Date'], df_sorted['Current Sellers'], label='Sellers', color='lightblue', alpha=0.6, width=0.5)
        ax2.set_ylabel('Number of Sellers')

        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(lines + lines2, labels + labels2, loc='upper left')

        plt.title(f'Detailed History for {product_name}')
        plt.tight_layout()
        plt.savefig(chart_image_path)
        plt.close()

        # --- Add a new page to the PDF for this product ---
        pdf.add_page()
        
        pdf.set_font('Helvetica', 'B', 16)
        pdf.multi_cell(0, 10, product_name, 0, 'C')
        pdf.ln(5)
        
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 10, 'Latest Data Point', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font('Helvetica', '', 11)
        # Exclude change values from the detailed page summary
        data_to_show = {k: v for k, v in latest_data.items() if 'Change' not in k}
        for key, value in data_to_show.items():
            pdf.cell(50, 8, f"{key}:", new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.cell(0, 8, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(5)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x()+190, pdf.get_y()) # Horizontal line
        pdf.ln(5)


        pdf.image(chart_image_path, x=None, y=None, w=190)
        
        os.remove(chart_image_path)

    # --- Save the final combined PDF ---
    pdf_file_path = "TCGplayer_Combo_Report.pdf"
    pdf.output(pdf_file_path)
    print(f"Successfully generated combo report: {pdf_file_path}")

if __name__ == '__main__':
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    
    all_products_data = []

    try:
        for url in URLS:
            print(f"Scraping data for: {url}")
            product_name, scraped_data = scrape_product_data(url, driver)
            
            if scraped_data and product_name != "Unknown Product":
                print("Scraped Data:", scraped_data)
                full_dataset = update_data(product_name, scraped_data)
                
                all_products_data.append({
                    'name': product_name,
                    'latest': scraped_data,
                    'history': full_dataset
                })
            else:
                print(f"Could not retrieve data for {url}")
            print("-" * 20)
        
        if all_products_data:
            create_combo_pdf_report(all_products_data)

    finally:
        driver.quit()
