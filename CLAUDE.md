# TCGplayer Price Tracker

## Project Overview
A Python scraper that tracks sealed Pokemon TCG product prices on TCGplayer.com. Includes a Flask web UI for browsing data, managing tracked products, and generating PDF reports.

## First-Time Setup

### macOS
```bash
# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Chrome if not already installed
# Download from https://www.google.com/chrome/ or:
brew install --cask google-chrome

# Install dependencies and run
uv sync
uv run python scraperpdf.py --serve
```

### Windows
```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install Chrome if not already installed
# Download from https://www.google.com/chrome/

# Install dependencies and run
uv sync
uv run python scraperpdf.py --serve
```

### Linux
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Chrome
sudo apt install chromium-browser  # Debian/Ubuntu
# or download from https://www.google.com/chrome/

# Install dependencies and run
uv sync
uv run python scraperpdf.py --serve
```

### Notes
- `uv sync` creates a `.venv` and installs all dependencies from `pyproject.toml`
- `products.txt` is auto-created from `products.txt.example` on first run
- The product catalog (31k+ products) auto-loads from `pokemon_all_products.csv` on first run, or fetches from the tcgcsv.com API if no CSV exists
- Chrome is only required for scraping. The web UI and PDF generation work without it.
- The scraper will check for Chrome and print a clear error if it's missing

## How to Run
- `uv run python scraperpdf.py` -- scrape all tracked products (reads from `products.txt`)
- `uv run python scraperpdf.py --serve` -- start the web UI at http://127.0.0.1:5000
- `uv run python scraperpdf.py --serve --port 8080` -- web UI on custom port
- `uv run python scraperpdf.py --pdf` -- generate PDF report from existing DB data without scraping

If already inside a `uv shell` or activated venv, you can drop the `uv run` prefix.

## Key Files
- `scraperpdf.py` -- core scraper, PDF generation, SQLite storage, CLI entry point
- `web.py` -- Flask web app (dashboard, product detail, manage products, API endpoints)
- `catalog.py` -- product catalog management (31k+ products from tcgcsv.com API, search, tracked product add/remove)
- `products.txt` -- tracked product IDs (one per line or comma-separated, supports comments with #). Gitignored; auto-created from `products.txt.example` on first run.
- `products.txt.example` -- sample products file, committed to repo
- `templates/` -- Jinja2 templates for the web UI (Alpine.js for reactivity, Pico CSS for styling, Chart.js for charts)
- `pyproject.toml` -- Python dependencies and project metadata
- `uv.lock` -- lockfile for reproducible installs

## Architecture
- **Storage**: SQLite (`tcgplayer.db`) with two tables: `price_history` (scraped data) and `product_catalog` (31k product catalog from tcgcsv.com)
- **Scraping**: Selenium headless Chrome with CDP network interception for sales/listings API data
- **Rate limiting**: configurable delays between requests, retry with backoff, Chrome session rotation every 50 products
- **Web**: Flask with background threading for scrapes and catalog refreshes. Alpine.js for reactive dashboard (sorting, column toggling, instant search). Pico CSS + Chart.js via CDN.
- **Products list**: `products.txt` is the source of truth for which products get scraped. Accepts bare IDs or full URLs.
- **Dashboard state**: Column visibility, sort order, and column arrangement are persisted to localStorage in the browser

## API Endpoints
- `GET /api/dashboard` -- product data as JSON for the reactive dashboard
- `GET /api/catalog/search?q=...` -- search product catalog (up to 50 results)
- `POST /api/scrape` -- start a background scrape
- `GET /api/scrape/status` -- poll scrape progress
- `GET /api/pdf` -- generate and download PDF report
- `GET /api/tracked` -- list all tracked products
- `POST /api/tracked/add` -- add product to tracking (body: `{"product_id": "..."}`)
- `POST /api/tracked/remove` -- remove product from tracking (body: `{"product_id": "..."}`)
- `GET /api/tracked/raw` -- raw contents of products.txt
- `POST /api/catalog/refresh` -- refresh catalog from tcgcsv.com API
- `GET /api/catalog/refresh/status` -- poll catalog refresh progress

## Dependencies
Managed via `pyproject.toml`. Core dependencies:
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
