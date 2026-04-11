import csv
import json
import os
import sqlite3
import ssl
import time
import urllib.request

import scraperpdf

DB_FILE = scraperpdf.DB_FILE
PRODUCTS_FILE = scraperpdf.PRODUCTS_FILE
CSV_FILE = 'pokemon_all_products.csv'
API_BASE = 'https://tcgcsv.com/tcgplayer/3'

_base_dir = os.path.dirname(os.path.abspath(__file__))


def _db_path():
    return os.path.join(_base_dir, DB_FILE)


def _products_path():
    return os.path.join(_base_dir, PRODUCTS_FILE)


def _csv_path():
    return os.path.join(_base_dir, CSV_FILE)


SINGLE_CARD_EXT_KEYS = {'Number', 'Rarity', 'Card Type', 'HP', 'Stage', 'Attack 1'}


def _classify_product(ext_data):
    """Classify a product as 'sealed' or 'single' based on its extendedData fields."""
    if not ext_data:
        return 'sealed'
    ext_keys = {e['name'] for e in ext_data}
    if ext_keys & SINGLE_CARD_EXT_KEYS:
        return 'single'
    return 'sealed'


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def init_catalog_db():
    conn = sqlite3.connect(_db_path())
    conn.execute('''CREATE TABLE IF NOT EXISTS product_catalog (
        product_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        group_name TEXT,
        url TEXT,
        product_type TEXT DEFAULT 'sealed'
    )''')
    # Add product_type column if upgrading from older schema
    try:
        conn.execute('ALTER TABLE product_catalog ADD COLUMN product_type TEXT DEFAULT "sealed"')
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    conn.close()


def catalog_count():
    conn = sqlite3.connect(_db_path())
    count = conn.execute('SELECT COUNT(*) FROM product_catalog').fetchone()[0]
    conn.close()
    return count


def load_catalog_from_csv(csv_path=None):
    path = csv_path or _csv_path()
    if not os.path.isfile(path):
        return 0
    conn = sqlite3.connect(_db_path())
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            product_type = row.get('productType', 'sealed')
            rows.append((str(row['productId']), row['name'], row['groupName'], row['url'], product_type))
    conn.executemany(
        'INSERT OR REPLACE INTO product_catalog (product_id, name, group_name, url, product_type) VALUES (?, ?, ?, ?, ?)',
        rows
    )
    conn.commit()
    conn.close()
    return len(rows)


def refresh_catalog(progress_callback=None):
    """Fetch all products from tcgcsv.com and upsert into catalog DB.
    Also updates the local CSV cache. Returns total product count."""
    ctx = _ssl_ctx()

    with urllib.request.urlopen(f'{API_BASE}/groups', context=ctx) as r:
        groups = json.loads(r.read())['results']

    total_groups = len(groups)
    all_products = []

    for i, g in enumerate(groups, 1):
        gid = g['groupId']
        gname = g['name']
        if progress_callback:
            progress_callback(i, total_groups, gname)
        try:
            with urllib.request.urlopen(f'{API_BASE}/{gid}/products', context=ctx) as r:
                products = json.loads(r.read())['results']
            for p in products:
                all_products.append({
                    'productId': str(p['productId']),
                    'name': p['name'],
                    'groupName': gname,
                    'url': p['url'],
                    'productType': _classify_product(p.get('extendedData', [])),
                })
        except Exception as e:
            print(f"  Error fetching group {gname}: {e}")
        time.sleep(0.25)

    # Upsert into DB
    conn = sqlite3.connect(_db_path())
    for p in all_products:
        conn.execute(
            'INSERT OR REPLACE INTO product_catalog (product_id, name, group_name, url, product_type) VALUES (?, ?, ?, ?, ?)',
            (p['productId'], p['name'], p['groupName'], p['url'], p['productType'])
        )
    conn.commit()
    conn.close()

    # Update CSV cache
    csv_path = _csv_path()
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['productId', 'name', 'groupName', 'url', 'productType'])
        w.writeheader()
        w.writerows(all_products)

    return len(all_products)


def search_catalog(query, limit=50, sealed_only=False):
    """Search catalog by name, group, or product ID. Returns results with is_tracked flag."""
    tracked = get_tracked_ids()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    q = f'%{query}%'
    sql = '''SELECT product_id, name, group_name, url, product_type FROM product_catalog
             WHERE (name LIKE ? OR group_name LIKE ? OR product_id LIKE ?)'''
    params = [q, q, q]
    if sealed_only:
        sql += " AND product_type = 'sealed'"
    sql += ' ORDER BY name LIMIT ?'
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{
        'product_id': r['product_id'],
        'name': r['name'],
        'group_name': r['group_name'],
        'url': r['url'],
        'product_type': r['product_type'],
        'is_tracked': r['product_id'] in tracked,
    } for r in rows]


def get_tracked_ids():
    """Return set of tracked product ID strings from products.txt."""
    products = scraperpdf.load_products()
    ids = set()
    for entry in products:
        pid, _ = scraperpdf.normalize_product(entry)
        if pid:
            ids.add(pid)
    return ids


def get_tracked_products():
    """Return tracked products with catalog info (name, group)."""
    tracked = get_tracked_ids()
    if not tracked:
        return []
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    placeholders = ','.join('?' for _ in tracked)
    rows = conn.execute(
        f'SELECT product_id, name, group_name, url FROM product_catalog WHERE product_id IN ({placeholders})',
        list(tracked)
    ).fetchall()
    conn.close()

    catalog_map = {r['product_id']: dict(r) for r in rows}
    result = []
    for pid in sorted(tracked, key=lambda x: catalog_map.get(x, {}).get('name', 'Unknown')):
        if pid in catalog_map:
            result.append(catalog_map[pid])
        else:
            result.append({'product_id': pid, 'name': None, 'group_name': None, 'url': None})
    return result


def add_tracked_id(product_id):
    """Add a product ID to products.txt. Returns True if added, False if already tracked."""
    product_id = str(product_id).strip()
    tracked = get_tracked_ids()
    if product_id in tracked:
        return False
    path = _products_path()
    with open(path, 'a') as f:
        f.write(f'\n{product_id}')
    return True


def remove_tracked_id(product_id):
    """Remove a product ID from products.txt. Returns True if removed, False if not found."""
    product_id = str(product_id).strip()
    path = _products_path()
    if not os.path.isfile(path):
        return False

    with open(path, 'r') as f:
        lines = f.readlines()

    new_lines = []
    removed = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            new_lines.append(line)
            continue

        # Handle comma-separated lines
        parts = stripped.split(',')
        remaining = []
        for part in parts:
            part_stripped = part.strip()
            pid, _ = scraperpdf.normalize_product(part_stripped)
            if pid != product_id:
                remaining.append(part)
            else:
                removed = True

        if remaining:
            new_lines.append(','.join(remaining) + '\n')
        # If all parts removed, skip the line entirely

    if removed:
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w') as f:
            f.writelines(new_lines)
        os.replace(tmp_path, path)

    return removed
