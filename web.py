import json
import os
import threading
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

import scraperpdf
import catalog


def _lowest_ask(top_listings_json):
    """Extract lowest listing price from top_listings JSON string."""
    try:
        listings = json.loads(top_listings_json) if isinstance(top_listings_json, str) else (top_listings_json or [])
        if not listings:
            return None
        price = listings[0].get('price', '')
        price_str = str(price).replace('$', '').replace(',', '')
        return float(price_str)
    except Exception:
        return None

def _make_status(extra_fields=None):
    """Create a fresh status dict for background tasks."""
    status = {"running": False, "current": 0, "total": 0}
    if extra_fields:
        status.update(extra_fields)
    return status


def _make_progress_callback(status, name_key):
    """Create a progress callback that updates a shared status dict."""
    def callback(current, total, name):
        status["current"] = current
        status["total"] = total
        status[name_key] = name
    return callback


scrape_status = _make_status({"last_product": "", "failed": [], "succeeded": 0})
catalog_status = _make_status({"last_group": ""})


def _run_scrape_thread():
    scrape_status.update({"running": True, "current": 0, "total": 0, "last_product": "", "failed": [], "succeeded": 0})
    try:
        succeeded, failed = scraperpdf.run_scrape(
            progress_callback=_make_progress_callback(scrape_status, "last_product"),
            generate_pdf=False
        )
        scrape_status["succeeded"] = succeeded
        scrape_status["failed"] = failed
    except Exception as e:
        scrape_status["last_product"] = f"Error: {e}"
    finally:
        scrape_status["running"] = False


def _run_catalog_refresh_thread():
    catalog_status.update({"running": True, "current": 0, "total": 0, "last_group": ""})
    try:
        count = catalog.refresh_catalog(
            progress_callback=_make_progress_callback(catalog_status, "last_group")
        )
        catalog_status["last_group"] = f"Done: {count} products"
    except Exception as e:
        catalog_status["last_group"] = f"Error: {e}"
    finally:
        catalog_status["running"] = False


def create_app():
    app = Flask(__name__)

    # First-run: ensure catalog is populated
    scraperpdf.init_db()
    catalog.init_catalog_db()
    if catalog.catalog_count() == 0:
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), catalog.CSV_FILE)
        if os.path.isfile(csv_path):
            print("Loading product catalog from CSV...")
            count = catalog.load_catalog_from_csv(csv_path)
            print(f"Product catalog loaded: {count} products")
        else:
            print("No catalog data found. Fetching from tcgcsv.com API...")
            count = catalog.refresh_catalog(
                progress_callback=lambda c, t, g: print(f"  [{c}/{t}] {g}")
            )
            print(f"Product catalog loaded: {count} products")

    @app.route("/")
    def dashboard():
        products = scraperpdf.get_all_latest_from_db()
        for p in products:
            p['lowest_ask'] = _lowest_ask(p.get('top_listings'))
        q = request.args.get("q", "").strip().lower()
        if q:
            products = [p for p in products if q in p["product_name"].lower() or q in str(p["product_id"])]
        return render_template("dashboard.html", products=products, query=request.args.get("q", ""))

    @app.route("/product/<product_id>")
    def product_detail(product_id):
        detail = scraperpdf.get_product_detail(product_id)
        if not detail:
            return "Product not found", 404
        history = scraperpdf.get_product_history(product_id)
        history_data = []
        if history is not None and not history.empty:
            for _, row in history.iterrows():
                history_data.append(row.to_dict())
        return render_template("product_detail.html", product=detail, history=history_data)

    @app.route("/manage")
    def manage():
        products_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), scraperpdf.PRODUCTS_FILE)
        content = ""
        if os.path.isfile(products_path):
            with open(products_path, "r") as f:
                content = f.read()
        tracked_count = len(catalog.get_tracked_ids())
        catalog_total = catalog.catalog_count()
        return render_template("manage.html", content=content, tracked_count=tracked_count, catalog_count=catalog_total)

    @app.route("/manage", methods=["POST"])
    def manage_save():
        products_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), scraperpdf.PRODUCTS_FILE)
        content = request.form.get("content", "")
        with open(products_path, "w") as f:
            f.write(content)
        return redirect(url_for("manage", saved=1))

    # --- Dashboard API ---

    @app.route("/api/dashboard")
    def api_dashboard():
        products = scraperpdf.get_all_latest_from_db()
        for p in products:
            p['lowest_ask'] = _lowest_ask(p.get('top_listings'))
            # Drop bulky JSON fields not needed for the table
            p.pop('top_listings', None)
            p.pop('recent_sales', None)
        q = request.args.get("q", "").strip().lower()
        if q:
            products = [p for p in products if q in p["product_name"].lower() or q in str(p["product_id"])]
        return jsonify(products)

    # --- Scrape API ---

    @app.route("/api/scrape", methods=["POST"])
    def api_scrape():
        if scrape_status["running"]:
            return jsonify({"error": "Scrape already running"}), 409
        thread = threading.Thread(target=_run_scrape_thread, daemon=True)
        thread.start()
        return jsonify({"status": "started"})

    @app.route("/api/scrape/status")
    def api_scrape_status():
        return jsonify(scrape_status)

    @app.route("/api/pdf")
    def api_pdf():
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), scraperpdf.DEFAULT_PDF_OUTPUT)
        result = scraperpdf.generate_pdf_from_db(output_path=output_path)
        if not result:
            return jsonify({"error": "No data in database"}), 404
        return send_file(output_path, as_attachment=True, download_name="TCGplayer_Combo_Report.pdf")

    @app.route("/api/csv")
    def api_csv():
        products = scraperpdf.get_all_latest_from_db()
        if not products:
            return jsonify({"error": "No data in database"}), 404
        for p in products:
            p['lowest_ask'] = _lowest_ask(p.get('top_listings'))
            p.pop('top_listings', None)
            p.pop('recent_sales', None)
        import csv
        import io
        output = io.StringIO()
        fields = ['product_id', 'product_name', 'date', 'market_price', 'lowest_ask',
                  'most_recent_sale', 'listed_median', 'price_change', 'current_quantity',
                  'quantity_change', 'current_sellers', 'total_sold', 'daily_sales']
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(products)
        resp = app.response_class(output.getvalue(), mimetype='text/csv')
        resp.headers['Content-Disposition'] = 'attachment; filename=tcgplayer_export.csv'
        return resp

    # --- Catalog API ---

    @app.route("/api/catalog/search")
    def api_catalog_search():
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify([])
        sealed_only = request.args.get("sealed", "").lower() in ("1", "true")
        results = catalog.search_catalog(q, limit=50, sealed_only=sealed_only)
        return jsonify(results)

    @app.route("/api/catalog/refresh", methods=["POST"])
    def api_catalog_refresh():
        if catalog_status["running"]:
            return jsonify({"error": "Catalog refresh already running"}), 409
        thread = threading.Thread(target=_run_catalog_refresh_thread, daemon=True)
        thread.start()
        return jsonify({"status": "started"})

    @app.route("/api/catalog/refresh/status")
    def api_catalog_refresh_status():
        return jsonify(catalog_status)

    # --- Tracked Products API ---

    @app.route("/api/tracked")
    def api_tracked():
        return jsonify(catalog.get_tracked_products())

    @app.route("/api/tracked/add", methods=["POST"])
    def api_tracked_add():
        data = request.get_json()
        if not data or "product_id" not in data:
            return jsonify({"error": "product_id required"}), 400
        added = catalog.add_tracked_id(data["product_id"])
        return jsonify({"added": added})

    @app.route("/api/tracked/remove", methods=["POST"])
    def api_tracked_remove():
        data = request.get_json()
        if not data or "product_id" not in data:
            return jsonify({"error": "product_id required"}), 400
        removed = catalog.remove_tracked_id(data["product_id"])
        return jsonify({"removed": removed})

    @app.route("/api/tracked/raw")
    def api_tracked_raw():
        products_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), scraperpdf.PRODUCTS_FILE)
        content = ""
        if os.path.isfile(products_path):
            with open(products_path, "r") as f:
                content = f.read()
        return jsonify({"content": content})

    return app
