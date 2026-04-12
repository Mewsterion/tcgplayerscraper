# Running TCGplayer Price Tracker

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
# Install uv (winget comes preinstalled on Windows 11)
winget install --id=astral-sh.uv -e

# Install Chrome if not already installed
winget install --id=Google.Chrome -e

# Install dependencies and run
uv sync
uv run python scraperpdf.py --serve
```

**Alternative (without winget):**
```powershell
# Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install Chrome from https://www.google.com/chrome/

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
- If Chrome isn't auto-detected (common on Windows), set the path in Settings > Chrome

## Commands
- `uv run python scraperpdf.py` -- scrape all tracked products (reads from `products.txt`)
- `uv run python scraperpdf.py --serve` -- start the web UI at http://127.0.0.1:5000
- `uv run python scraperpdf.py --serve --port 8080` -- web UI on custom port
- `uv run python scraperpdf.py --pdf` -- generate PDF report from existing DB data without scraping
- `./dev.sh` -- kill existing server and restart (macOS/Linux convenience script)

If already inside a `uv shell` or activated venv, you can drop the `uv run` prefix.

## Web Pages
- `/` -- Dashboard: reactive table with sortable columns, column visibility/reordering, instant search, bulk remove. Only shows tracked products by default ("Show all history" toggle for everything).
- `/product/<id>` -- Product Detail: stats cards, Chart.js price history, recent sales table, active listings table.
- `/manage` -- Manage Products: search 31k+ product catalog (multi-term, sealed filter), add/remove tracking, raw product list editor.
- `/schedules` -- Schedules: create/delete recurring scrape and catalog refresh jobs (daily, weekly, or cron).
- `/settings` -- Settings: configure proxies, parallel scraping, UA rotation, resume on failure, rate limiting, Chrome binary path.
- `/logs` -- Scrape Logs: view recent scrape history with status, timestamps, and error messages.

## API Endpoints

### Dashboard & Products
- `GET /api/dashboard` -- product data JSON (add `?show_all=1` to include untracked)
- `GET /api/product/<id>` -- single product detail + full price history
- `GET /api/csv` -- export latest data as CSV download
- `GET /api/pdf` -- generate and download PDF report

### Catalog & Tracking
- `GET /api/catalog/search?q=...&sealed=1` -- multi-term catalog search with optional sealed filter
- `POST /api/catalog/refresh` -- refresh catalog from tcgcsv.com API
- `GET /api/catalog/refresh/status` -- poll catalog refresh progress
- `GET /api/tracked` -- list tracked products with catalog info
- `POST /api/tracked/add` -- add product to tracking (body: `{"product_id": "..."}`)
- `POST /api/tracked/remove` -- remove product from tracking (body: `{"product_id": "..."}`)
- `GET /api/tracked/raw` -- raw contents of products.txt

### Scraping
- `POST /api/scrape` -- start background scrape
- `GET /api/scrape/status` -- poll scrape progress

### Schedules
- `GET /api/schedules` -- list active schedules and last run info
- `POST /api/schedules` -- create schedule (body: `{"job_type": "scrape"|"catalog_refresh", "mode": "daily"|"weekly"|"cron", ...}`)
- `DELETE /api/schedules/<id>` -- delete a schedule

### Settings
- `GET /api/settings` -- get current settings
- `POST /api/settings` -- save settings
- `GET /api/settings/proxies` -- get proxy list and count
- `POST /api/settings/proxies` -- save proxy list

### Logs
- `GET /api/logs?limit=200` -- recent scrape log entries
