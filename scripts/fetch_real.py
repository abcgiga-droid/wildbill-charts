"""Fetch daily OHLC via real browser (Playwright) -> app/data/{SYM}.json.
Why browser: Stooq serves a JS PoW challenge to scripts; Yahoo 429s
datacenter urllib/curl but answers 200 to real Chromium. Paced + resumable.
Run: python3 scripts/fetch_real.py  (skips symbols already saved)
"""
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

SYMBOLS = ["NVDA","MSFT","AAPL","AMZN","JPM","WMT","V","JNJ","PG","HD","KO",
           "UNH","CSCO","CVX","IBM","CRM","AXP","GS","DIS","MCD","MRK","CAT",
           "VZ","BA","AMGN","HON","NKE","SHW","MMM","TRV"]
OUT = Path(__file__).resolve().parent.parent / "app" / "data"
OUT.mkdir(parents=True, exist_ok=True)
UP = "rgba(38,166,154,0.5)"
DOWN = "rgba(239,83,80,0.5)"

def yahoo_convert(sym, raw, source):
    r0 = (raw.get("chart") or {}).get("result", [None])[0]
    if not r0:
        raise RuntimeError(str(raw.get("chart", {}).get("error"))[:150])
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    O, H, L, C, V = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    candles, vols = [], []
    for i, t in enumerate(ts):
        try:
            o, h, l, c = O[i], H[i], L[i], C[i]
        except IndexError:
            continue
        if None in (o, h, l, c) or not (o > 0 and h > 0 and l > 0 and c > 0):
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            v = int(V[i] or 0)
        except (IndexError, TypeError, ValueError):
            v = 0
        candles.append({"time": d, "open": round(o,2), "high": round(h,2), "low": round(l,2), "close": round(c,2)})
        vols.append({"time": d, "value": v, "color": UP if c >= o else DOWN})
    if len(candles) < 30:
        raise RuntimeError(f"too few rows {len(candles)}")
    return {"symbol": sym, "source": source,
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "candles": candles, "vols": vols}

def fetch_yahoo(pg, sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5y"
    for attempt in range(5):
        r = pg.goto(url, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(1500)
        body = pg.evaluate("document.body.innerText")
        if r and r.status == 200 and body.strip().startswith("{"):
            return yahoo_convert(sym, json.loads(body), "yahoo")
        print(f"  {sym} try{attempt+1} status={r.status if r else None} len={len(body)}", flush=True)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError("yahoo failed x5")

def fetch_stooq(pg, sym):
    url = f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d"
    pg.goto(url, wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(12000)
    body = pg.evaluate("document.body.innerText")
    if body.startswith("Date") and len(body) > 100:
        candles, vols = [], []
        for row in csv.DictReader(io.StringIO(body)):
            try:
                o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            except (ValueError, KeyError, TypeError):
                continue
            if not (o > 0 and h > 0 and l > 0 and c > 0):
                continue
            t = row["Date"].strip()
            try:
                v = int(float(row.get("Volume") or 0))
            except ValueError:
                v = 0
            candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
            vols.append({"time": t, "value": v, "color": UP if c >= o else DOWN})
        if len(candles) >= 30:
            return {"symbol": sym, "source": "stooq",
                    "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "candles": candles, "vols": vols}
    raise RuntimeError(f"stooq challenge unsolved (len={len(body)})")

def main():
    todo = [s for s in SYMBOLS if not (OUT / f"{s}.json").exists()]
    print(f"todo={len(todo)} (skipping saved)", flush=True)
    ok = {"stooq": 0, "yahoo": 0}
    failed = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        pg = ctx.new_page()
        for n, sym in enumerate(todo):
            try:
                try:
                    payload = fetch_stooq(pg, sym)
                    ok["stooq"] += 1
                except Exception as e:
                    print(f"  {sym}: stooq miss ({e}) -> yahoo", flush=True)
                    payload = fetch_yahoo(pg, sym)
                    ok["yahoo"] += 1
                (OUT / f"{sym}.json").write_text(json.dumps(payload))
                c = payload["candles"]
                print(f"[{n+1}/{len(todo)}] {sym} {payload['source']} bars={len(c)} {c[0]['time']}..{c[-1]['time']} close={c[-1]['close']}", flush=True)
            except Exception as e:
                print(f"[{n+1}/{len(todo)}] {sym} MISS {e}", flush=True)
                failed.append(sym)
            time.sleep(3)
        b.close()
    print(f"DONE stooq={ok['stooq']} yahoo={ok['yahoo']} missed={failed or 'none'}", flush=True)
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
