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

## Commands
- `uv run python scraperpdf.py` -- scrape all tracked products (reads from `products.txt`)
- `uv run python scraperpdf.py --serve` -- start the web UI at http://127.0.0.1:5000
- `uv run python scraperpdf.py --serve --port 8080` -- web UI on custom port
- `uv run python scraperpdf.py --pdf` -- generate PDF report from existing DB data without scraping

If already inside a `uv shell` or activated venv, you can drop the `uv run` prefix.

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
