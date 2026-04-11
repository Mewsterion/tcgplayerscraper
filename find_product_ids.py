"""
find_product_ids.py — One-time utility
Searches TCGplayer for each product name and extracts the product URL.
Outputs urls.txt and prints a Python-ready URLS list for scraperpdf.py.
"""

import re
import time
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------
# EDIT THIS LIST — paste your product names here
# ---------------------------------------------------------------
PRODUCT_NAMES = [
    "Destined Rivals Booster Box",
    "Journey Together Enhanced Booster Box",
    "Surging Sparks Booster Box",
    "Phantasmal Flames Booster Box",
    "Blooming Waters Premium Collection",
    "Paldean Fates Great Tusk ex & Iron Treads ex Premium Collection",
    "Unova Heavy Hitters Premium Collection",
    "First Partner Illustration Collection Series 1",
]
# ---------------------------------------------------------------

SEARCH_BASE = "https://www.tcgplayer.com/search/all/product?q={query}&view=grid"


def find_product_url(name, driver, wait):
    query = quote_plus(name)
    driver.get(SEARCH_BASE.format(query=query))

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/product/']")))
    except Exception:
        print(f"  ✗ No results loaded for: {name}")
        return None

    time.sleep(1)  # let results settle

    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/product/']")
    for link in links:
        href = link.get_attribute('href') or ''
        if 'code-card' in href.lower():
            continue
        m = re.search(r'tcgplayer\.com/product/(\d+)', href)
        if m:
            clean = f"https://www.tcgplayer.com/product/{m.group(1)}/"
            return clean

    print(f"  ✗ No product link found for: {name}")
    return None


if __name__ == '__main__':
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 20)

    results = []  # [(name, url)]

    try:
        for name in PRODUCT_NAMES:
            print(f"Searching: {name}")
            url = find_product_url(name, driver, wait)
            if url:
                print(f"  → {url}")
                results.append((name, url))
            else:
                results.append((name, None))
            print("-" * 40)
    finally:
        driver.quit()

    # Write urls_found.txt — paste-ready URLS list for scraperpdf.py
    with open('urls_found.txt', 'w') as f:
        f.write("URLS = [\n")
        for name, url in results:
            if url:
                f.write(f"    '{url}',  # {name}\n")
            else:
                f.write(f"    # NOT FOUND: {name}\n")
        f.write("]\n")

    # Also print to console
    print("\n\n# --- Copy this into scraperpdf.py ---")
    with open('urls_found.txt') as f:
        print(f.read())

    found = sum(1 for _, u in results if u)
    print(f"\nFound {found}/{len(PRODUCT_NAMES)} products. Saved to urls_found.txt")
