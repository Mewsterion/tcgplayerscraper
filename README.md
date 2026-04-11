# TCGplayer Daily Price Tracker

This Python tool tracks prices for sealed Pokemon (and other TCG) products on TCGplayer.com. It scrapes data for multiple products, stores history in a SQLite database, generates PDF reports, and includes a web UI for browsing and managing everything.

## Features

- **Multi-Product Tracking**: Track products by ID or URL via `products.txt` (one per line or comma-separated).
- **Product Catalog**: Built-in searchable catalog of 31,000+ Pokemon TCG products from tcgcsv.com. Search, add, and remove tracked products from the web UI.
- **Automated Data Scraping**: Uses Selenium with Chrome in headless mode. Captures dynamically loaded content and intercepts internal TCGplayer API calls via Chrome DevTools Protocol (CDP).
- **Recent Sales Data**: Captures the last 10 individual sale records (date, condition, price, qty) per product by intercepting TCGplayer's internal `mpapi.tcgplayer.com` sales endpoint.
- **Active Listings**: Fetches the lowest 6 active listings per product via TCGplayer's search API (POST), filtered to English-only, standard listing type, and within a reasonable price range of market value.
- **SQLite Storage**: All price history stored in `tcgplayer.db` with indexed queries for fast lookups.
- **Rate Limiting**: Configurable delays between requests, retry with exponential backoff, and automatic Chrome session rotation to avoid rate limits.
- **Web UI** (`--serve`):
  - **Dashboard** with searchable product table showing market price, lowest ask, last sale, price change, quantity, and total sold.
  - **Product detail pages** with stats, recent sales, active listings, and interactive Chart.js price history charts.
  - **Manage Products** page with catalog search, add/remove tracking, and bulk edit.
  - **Run Scrape** and **Download PDF** buttons with live progress tracking.
  - **Refresh Catalog** to pull latest products from tcgcsv.com API.
- **Combined PDF Report** (`TCGplayer_Combo_Report.pdf`):
  - Summary page with Market Price, day-over-day change, quantity, daily sales, average recent sale price, and lowest active ask — all color-coded.
  - Detail pages per product with latest data, recent sales table, active listings table, and a price history chart.
- **Automated Scheduling**: Runs via Windows Task Scheduler using the included `scrape.bat`.

## How It Works

TCGplayer does not expose sales history or active listings in a public API. This scraper works around that in two ways:

1. **Sales data** — After the page loads, Chrome's performance logs are scanned for the `mpapi.tcgplayer.com/v2/product/{id}/latestsales` XHR response and the body is extracted directly.
2. **Listings data** — TCGplayer's listing search API (`mp-search-api.tcgplayer.com`) requires a POST request with a filter body to return actual listing records (GET returns aggregations only). The script posts from the browser context so session cookies are included automatically.

## Setup & Installation

### 1. Prerequisites
- Python 3.9 or newer
- Google Chrome browser installed

### 2. Clone the Repository
```bash
git clone https://github.com/aaronentwistle/tcgplayerscraper.git
cd tcgplayerscraper
```

### 3. Install Required Libraries
```bash
pip install pandas matplotlib beautifulsoup4 selenium webdriver-manager fpdf2 flask
```

**Python 3.12+ only:** `distutils` was removed in 3.12. If you hit a `ModuleNotFoundError`:
```bash
pip install setuptools
```

## Configuration

Edit `products.txt` to add the product IDs you want to track. Supports bare IDs, full URLs, comma-separated values, and `#` comments:

```
# Sealed products
624679
668496, 672394, 528038

# Also accepts full URLs
https://www.tcgplayer.com/product/593355/
```

Scraping options can be configured at the top of `scraperpdf.py`:

```python
RECENT_SALES_COUNT = 10           # number of recent sales to capture
LISTING_COUNT = 6                 # number of lowest active listings to capture
MIN_LISTING_PRICE_PCT = 0.50      # filter listings below 50% of market price
DELAY_BETWEEN_REQUESTS = (2, 4)   # random delay range (seconds) between scrapes
RETRY_ATTEMPTS = 2                # retries on failure
SESSION_ROTATE_EVERY = 50         # restart Chrome every N products
```

## Usage

### Scrape Products
```bash
python scraperpdf.py
```
Scrapes all products in `products.txt`, stores data in SQLite, and generates the PDF report.

### Start the Web UI
```bash
python scraperpdf.py --serve
```
Opens a web dashboard at http://127.0.0.1:5000 where you can browse data, search the product catalog, manage tracked products, trigger scrapes, and download PDF reports.

### Generate PDF Only
```bash
python scraperpdf.py --pdf
```
Generates the PDF report from existing database data without scraping.

## Scheduling (Windows)

The included `scrape.bat` handles venv activation and logging. To schedule it daily:

1. Find your Python path: `where python`
2. Open Task Scheduler and create a new task, or use the command below (run as Administrator):

```cmd
schtasks /create /tn "TCGplayer Daily Report" /tr "D:\path\to\tcgplayer\scrape.bat" /sc DAILY /st 05:30
```

Completion timestamps are logged to `scraper_log.txt`.
