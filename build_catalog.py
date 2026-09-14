#!/usr/bin/env python3
"""Ежечасная пересборка catalog.json из Ozon Seller API.

Источники: snapshot.json (имена/фото/sku/ранг), tags.json (категории/марки).
Цены и наличие тянутся живьём из обоих магазинов; из дублей выбирается
листинг с МЕНЬШЕЙ ценой. Запускается в GitHub Actions каждый час.
"""
import json
import os
import ssl
import sys
import time
import urllib.request

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context()

HERE = os.path.dirname(os.path.abspath(__file__))
STORES = [
    ("s2", os.environ["OZON_S2_ID"], os.environ["OZON_S2_KEY"]),
    ("s1", os.environ["OZON_S1_ID"], os.environ["OZON_S1_KEY"]),
]


def api(cid, key, path, body):
    req = urllib.request.Request("https://api-seller.ozon.ru" + path,
        data=json.dumps(body).encode(),
        headers={"Client-Id": cid, "Api-Key": key, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            raise
    raise SystemExit("Ozon API: исчерпаны попытки")


def fetch_store(cid, key):
    prices, cursor = {}, ""
    while True:
        r = api(cid, key, "/v5/product/info/prices",
                {"filter": {"visibility": "ALL"}, "limit": 1000, "cursor": cursor})
        items = r.get("items") or []
        for it in items:
            p = it.get("price") or {}
            def num(x):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return 0.0
            k = it["offer_id"].strip().upper().replace(" ", "")
            cands = [v for v in (num(p.get("marketing_price")),
                                 num(p.get("marketing_seller_price")),
                                 num(p.get("price"))) if v > 0]
            prices[k] = {"price": min(cands) if cands else 0.0, "old": num(p.get("old_price"))}
        cursor = r.get("cursor") or ""
        if not cursor or not items:
            break
    stock, last_id = {}, ""
    while True:
        r = api(cid, key, "/v3/product/list",
                {"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": 1000})
        items = r["result"]["items"]
        for it in items:
            k = it["offer_id"].strip().upper().replace(" ", "")
            stock[k] = bool(it.get("has_fbo_stocks") or it.get("has_fbs_stocks")) and not it.get("archived")
        last_id = r["result"].get("last_id", "")
        if not last_id or not items:
            break
    return prices, stock


def main():
    snap = json.load(open(os.path.join(HERE, "snapshot.json"), encoding="utf-8"))
    tags = json.load(open(os.path.join(HERE, "tags.json"), encoding="utf-8"))
    live = {}
    for sid, cid, key in STORES:
        live[sid] = fetch_store(cid, key)
    out = []
    for k, e in snap.items():
        best = None
        for sid in ("s2", "s1"):
            if sid not in e:
                continue
            p = live[sid][0].get(k)
            if not p or p["price"] <= 0:
                continue
            in_stock = live[sid][1].get(k, False)
            cand = {"price": int(p["price"]), "old": int(p["old"]) if p["old"] > p["price"] else None,
                    "sku": e[sid]["sku"], "in_stock": in_stock}
            if best is None or (cand["in_stock"], -cand["price"]) > (best["in_stock"], -best["price"]):
                best = cand
        if best is None:
            continue
        t = tags.get(k, {"cat": "parts", "sub": "other_part", "brands": []})
        out.append({
            "art": e["art"], "name": e["name"],
            "price": best["price"], "old": best["old"],
            "disc": round(100 - best["price"] * 100 / best["old"]) if best["old"] else None,
            "stock": e.get("rank", 0) if best["in_stock"] else 0,
            "url": f"https://www.ozon.ru/product/{best['sku']}/",
            "img": e["img"], "store": 2 if "s2" in e else 1,
            "cat": t["cat"], "sub": t["sub"], "brands": t["brands"],
        })
    out.sort(key=lambda x: (-x["stock"], x["price"]))
    path = os.path.join(HERE, "catalog.json")
    new = json.dumps(out, ensure_ascii=False)
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if new != old:
        open(path, "w", encoding="utf-8").write(new)
        print(f"catalog.json обновлён: {len(out)} позиций")
    else:
        print("изменений нет")


if __name__ == "__main__":
    sys.exit(main())
