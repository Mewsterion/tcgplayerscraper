# TCGplayer Price Tracker

## Project Overview
A Python scraper that tracks sealed Pokemon TCG product prices on TCGplayer.com. Includes a Flask web UI for browsing data, managing tracked products, and generating PDF reports.

See [RUN.md](RUN.md) for platform-specific setup instructions, commands, and API endpoint reference.

## How to Run
- `uv run python scraperpdf.py` -- scrape all tracked products (reads from `products.txt`)
- `uv run python scraperpdf.py --serve` -- start the web UI at http://127.0.0.1:5000
- `uv run python scraperpdf.py --serve --port 8080` -- web UI on custom port
- `uv run python scraperpdf.py --pdf` -- generate PDF report from existing DB data without scraping

## Key Files
- `scraperpdf.py` -- core scraper, PDF generation, SQLite storage, CLI entry point
- `web.py` -- Flask web app (dashboard, product detail, manage products, API endpoints)
- `catalog.py` -- product catalog management (31k+ products from tcgcsv.com API, search, tracked product add/remove)
- `products.txt` -- tracked product IDs (one per line or comma-separated, supports comments with #). Gitignored; auto-created from `products.txt.example` on first run.
- `templates/` -- Jinja2 templates for the web UI (Alpine.js for reactivity, Pico CSS for styling, Chart.js for charts)
- `pyproject.toml` -- Python dependencies and project metadata

## Architecture
- **Storage**: SQLite (`tcgplayer.db`) with two tables: `price_history` (scraped data) and `product_catalog` (31k product catalog from tcgcsv.com)
- **Scraping**: Selenium headless Chrome with CDP network interception for sales/listings API data
- **Rate limiting**: configurable delays between requests, retry with backoff, Chrome session rotation every 50 products
- **Web**: Flask with background threading for scrapes and catalog refreshes. Alpine.js for reactive dashboard (sorting, column toggling, instant search). Pico CSS + Chart.js via CDN.
- **Products list**: `products.txt` is the source of truth for which products get scraped. Accepts bare IDs or full URLs.
- **Dashboard state**: Column visibility, sort order, and column arrangement are persisted to localStorage in the browser

## Dependencies
Managed via `pyproject.toml`. Install with `uv sync`.
```
pandas matplotlib beautifulsoup4 selenium webdriver-manager fpdf2 flask setuptools
```

## Important Notes
- The scraper uses `ssl.CERT_NONE` for tcgcsv.com API calls (required by that API)
- Chrome must be installed for Selenium scraping to work (the app checks and warns if missing)
- Generated files (*.pdf, *.db, *.csv) are gitignored
- `products.txt` is gitignored -- each user has their own tracked products
- The web app auto-loads the product catalog from `pokemon_all_products.csv` on first run, or fetches from API if no CSV exists
- When modifying the dashboard template, the reactive features use Alpine.js -- data is fetched from `/api/dashboard` and rendered client-side
