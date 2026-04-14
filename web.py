import json
import os
import threading
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import scraperpdf
import catalog
import settings as app_settings


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

# Track last scheduled run results
schedule_last_run = {
    "scrape": {"time": None, "result": None},
    "catalog_refresh": {"time": None, "result": None},
}


def _scheduled_scrape():
    """Run scrape as a scheduled job."""
    schedule_last_run["scrape"]["time"] = datetime.now().isoformat()
    try:
        _run_scrape_thread()
        schedule_last_run["scrape"]["result"] = f"OK: {scrape_status.get('succeeded', 0)} succeeded"
    except Exception as e:
        schedule_last_run["scrape"]["result"] = f"Error: {e}"


def _scheduled_catalog_refresh():
    """Run catalog refresh as a scheduled job."""
    schedule_last_run["catalog_refresh"]["time"] = datetime.now().isoformat()
    try:
        _run_catalog_refresh_thread()
        schedule_last_run["catalog_refresh"]["result"] = f"OK: {catalog_status.get('last_group', '')}"
    except Exception as e:
        schedule_last_run["catalog_refresh"]["result"] = f"Error: {e}"


JOB_FUNCTIONS = {
    "scrape": _scheduled_scrape,
    "catalog_refresh": _scheduled_catalog_refresh,
}


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
        scraperpdf.log_scrape(None, "error", f"Scrape thread crashed: {e}")
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

    # Initialize scheduler with SQLite persistence
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), scraperpdf.DB_FILE)
    scheduler = BackgroundScheduler(
        jobstores={'default': SQLAlchemyJobStore(url=f'sqlite:///{db_path}')},
    )
    scheduler.start()

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
        return render_template("product_detail.html", product_id=product_id)

    @app.route("/api/product/<product_id>")
    def api_product_detail(product_id):
        detail = scraperpdf.get_product_detail(product_id)
        if not detail:
            return jsonify({"error": "Product not found"}), 404
        # Sanitize bytes values
        for k, v in detail.items():
            if isinstance(v, bytes):
                detail[k] = 0.0
        history = scraperpdf.get_product_history(product_id)
        history_data = []
        if history is not None and not history.empty:
            for _, row in history.iterrows():
                d = row.to_dict()
                for k, v in d.items():
                    if isinstance(v, bytes):
                        d[k] = 0.0
                history_data.append(d)
        return jsonify({"product": detail, "history": history_data})

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
            # Sell-through rate: daily sales / current listings quantity
            daily = p.get('daily_sales') or 0
            qty = p.get('current_quantity') or 0
            try:
                daily, qty = float(daily), float(qty)
                p['sell_through_rate'] = round((daily / qty) * 100, 1) if qty > 0 else 0.0
            except (ValueError, TypeError):
                p['sell_through_rate'] = 0.0
            # Drop bulky JSON fields not needed for the table
            p.pop('top_listings', None)
            p.pop('recent_sales', None)
            # Sanitize any non-JSON-serializable values (e.g. bytes from corrupted DB rows)
            for k, v in p.items():
                if isinstance(v, bytes):
                    p[k] = 0.0
        # Filter to tracked products unless show_all is set
        show_all = request.args.get("show_all", "").lower() in ("1", "true")
        if not show_all:
            tracked = catalog.get_tracked_ids()
            if tracked:
                products = [p for p in products if str(p['product_id']) in tracked]
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
                  'quantity_change', 'current_sellers', 'total_sold', 'daily_sales',
                  'sell_through_rate']
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

    # --- Scrape Log ---

    @app.route("/logs")
    def logs_page():
        return render_template("logs.html")

    @app.route("/api/logs")
    def api_logs():
        limit = request.args.get("limit", 200, type=int)
        logs = scraperpdf.get_scrape_logs(limit=limit)
        return jsonify(logs)

    # --- Schedules ---

    @app.route("/schedules")
    def schedules_page():
        return render_template("schedules.html")

    @app.route("/api/schedules")
    def api_schedules_list():
        jobs = []
        for job in scheduler.get_jobs():
            trigger = job.trigger
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            # Extract cron fields from trigger
            cron_str = str(trigger)
            job_type = job.id.split('_', 1)[0] if '_' in job.id else job.id
            jobs.append({
                "id": job.id,
                "job_type": job_type,
                "schedule": cron_str,
                "next_run": next_run,
            })
        return jsonify({"jobs": jobs, "last_run": schedule_last_run})

    @app.route("/api/schedules", methods=["POST"])
    def api_schedules_create():
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        job_type = data.get("job_type")
        if job_type not in JOB_FUNCTIONS:
            return jsonify({"error": f"Invalid job_type. Must be one of: {list(JOB_FUNCTIONS.keys())}"}), 400

        mode = data.get("mode", "cron")
        try:
            if mode == "daily":
                hour = int(data.get("hour", 5))
                minute = int(data.get("minute", 0))
                trigger = CronTrigger(hour=hour, minute=minute)
            elif mode == "weekly":
                day_of_week = data.get("day_of_week", "mon")
                hour = int(data.get("hour", 5))
                minute = int(data.get("minute", 0))
                trigger = CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)
            elif mode == "cron":
                expr = data.get("expression", "").strip()
                if not expr:
                    return jsonify({"error": "Cron expression required"}), 400
                parts = expr.split()
                if len(parts) != 5:
                    return jsonify({"error": "Cron expression must have 5 fields (minute hour day month day_of_week)"}), 400
                trigger = CronTrigger(
                    minute=parts[0], hour=parts[1], day=parts[2],
                    month=parts[3], day_of_week=parts[4]
                )
            else:
                return jsonify({"error": "Invalid mode. Must be daily, weekly, or cron"}), 400
        except Exception as e:
            return jsonify({"error": f"Invalid schedule: {e}"}), 400

        job_id = f"{job_type}_{uuid.uuid4().hex[:8]}"
        scheduler.add_job(
            JOB_FUNCTIONS[job_type],
            trigger=trigger,
            id=job_id,
            replace_existing=False,
        )
        return jsonify({"created": job_id})

    @app.route("/api/schedules/<job_id>", methods=["DELETE"])
    def api_schedules_delete(job_id):
        try:
            scheduler.remove_job(job_id)
            return jsonify({"deleted": job_id})
        except Exception:
            return jsonify({"error": "Job not found"}), 404

    # --- Settings ---

    @app.route("/settings")
    def settings_page():
        return render_template("settings.html")

    @app.route("/api/settings")
    def api_settings_get():
        return jsonify(app_settings.load_settings())

    @app.route("/api/settings", methods=["POST"])
    def api_settings_save():
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        # Merge with defaults to ensure all keys exist
        current = app_settings.load_settings()
        current.update(data)
        app_settings.save_settings(current)
        return jsonify(current)

    @app.route("/api/settings/proxies")
    def api_settings_proxies_get():
        content = app_settings.load_proxies_raw()
        proxies = app_settings.load_proxies()
        return jsonify({"content": content, "count": len(proxies)})

    @app.route("/api/settings/proxies", methods=["POST"])
    def api_settings_proxies_save():
        data = request.get_json()
        if not data or "content" not in data:
            return jsonify({"error": "content required"}), 400
        app_settings.save_proxies(data["content"])
        proxies = app_settings.load_proxies()
        return jsonify({"saved": True, "count": len(proxies)})

    return app
