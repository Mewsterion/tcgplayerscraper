import json
import csv
import urllib.request
import time
import sys
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Get all Pokemon groups (categoryId 3)
print("Fetching Pokemon groups...")
with urllib.request.urlopen("https://tcgcsv.com/tcgplayer/3/groups", context=ctx) as r:
    groups = json.loads(r.read())["results"]
print(f"Found {len(groups)} groups")

all_products = []
for i, g in enumerate(groups):
    gid = g["groupId"]
    name = g["name"]
    print(f"[{i+1}/{len(groups)}] {name}...", end=" ", flush=True)
    try:
        with urllib.request.urlopen(f"https://tcgcsv.com/tcgplayer/3/{gid}/products", context=ctx) as r:
            products = json.loads(r.read())["results"]
        for p in products:
            all_products.append({
                "productId": p["productId"],
                "name": p["name"],
                "groupName": name,
                "url": p["url"],
            })
        print(f"{len(products)} products")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(0.25)

out = "pokemon_all_products.csv"
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["productId", "name", "groupName", "url"])
    w.writeheader()
    w.writerows(all_products)

print(f"\nDone! {len(all_products)} products -> {out}")
