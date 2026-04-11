# TCGplayer Daily Price Tracker

This Python script automates the process of tracking prices for sealed Pokemon (and other TCG) products on TCGplayer.com. It runs daily, scrapes data for multiple products, records the history in CSV files, and generates a combined PDF report with visualizations and a summary of the day's market activity.

The live project can be found on GitHub: [https://github.com/mewsterion/tcgplayerscraper](https://github.com/mewsterion/tcgplayerscraper)

## Features

- **Multi-Product Tracking**: Track multiple products by adding their TCGplayer URLs to the `URLS` list.
- **Automated Data Scraping**: Uses Selenium with Chrome in headless mode. Captures dynamically loaded content and intercepts internal TCGplayer API calls via Chrome DevTools Protocol (CDP).
- **Recent Sales Data**: Captures the last 10 individual sale records (date, condition, price, qty) per product by intercepting TCGplayer's internal `mpapi.tcgplayer.com` sales endpoint.
- **Active Listings**: Fetches the lowest 6 active listings per product via TCGplayer's search API (POST), filtered to English-only, standard listing type, and within a reasonable price range of market value — eliminating Korean/Portuguese variants, loose packs, opened shells, dice-only listings, and other irrelevant entries.
- **Historical Data Logging**: Saves daily data to individual `.csv` files per product, building a historical price database over time.
- **Combined PDF Report** (`TCGplayer_Combo_Report.pdf`):
  - **Summary page** with Market Price, day-over-day change, quantity, daily sales, average recent sale price, and lowest active ask — all color-coded.
  - **Detail pages** per product with latest data, recent individual sales table, active listings table (with Direct/Verified seller status), and a price history chart.
  - **Charts** showing Market Price, 7-day moving average, most recent sale, average of last 10 sales, daily sales volume, and active seller count.
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
git clone https://github.com/mewsterion/tcgplayerscraper.git
cd tcgplayerscraper
```

### 3. Install Required Libraries
```bash
pip install pandas matplotlib beautifulsoup4 selenium webdriver-manager fpdf2
```

**Python 3.12+ only:** `distutils` was removed in 3.12. If you hit a `ModuleNotFoundError`:
```bash
pip install setuptools
```

## Configuration

Open `scraperpdf.py` and edit the top section:

```python
URLS = [
    'https://www.tcgplayer.com/product/624679/',
    'https://www.tcgplayer.com/product/623628',
    # Add more product URLs here
]

RECENT_SALES_COUNT = 10   # number of recent sales to capture
LISTING_COUNT = 6         # number of lowest active listings to capture
MIN_LISTING_PRICE_PCT = 0.50  # filter listings below 50% of market price
```

## Running the Script

```bash
python scraperpdf.py
```

The script will:
1. Launch a headless Chrome browser with CDP network tracking enabled.
2. Visit each URL, scrape page data, and intercept API responses for sales and listings.
3. Append today's data to each product's `.csv` file.
4. Generate `TCGplayer_Combo_Report.pdf`.

## Scheduling (Windows)

The included `scrape.bat` handles venv activation and logging. To schedule it daily:

1. Find your Python path: `where python`
2. Open Task Scheduler and create a new task, or use the command below (run as Administrator):

```cmd
schtasks /create /tn "TCGplayer Daily Report" /tr "D:\path\to\tcgplayer\scrape.bat" /sc DAILY /st 05:30
```

Completion timestamps are logged to `scraper_log.txt`.
