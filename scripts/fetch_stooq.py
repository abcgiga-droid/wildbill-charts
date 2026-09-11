"""Fetch daily + intraday OHLC for 30 symbols -> app/data/{SYM}.json (INCREMENTAL merge).

Engine: yfinance (no API key).
  - daily:   Ticker.history(period="5y", interval="1d")   (~1255 bars)
  - 5m tier: Ticker.history(period="60d", interval="5m")  (~4.6k; Yahoo's 5m cap)
  - 1h tier: Ticker.history(period="730d", interval="1h") (~3.4k; depth for 1H view)

INCREMENTAL: each run loads the existing JSON (if any) and merges by time key,
so the local archive only grows — today's bar updates in place, history accrues.
Run daily via cron/launchd; 5m older than 60d can't be backfilled but is kept once saved.

Output per symbol: {"symbol","source":"yfinance","fetched",
  "candles":[{time YYYY-MM-DD,open,high,low,close}...], "vols":[...],
  "bars5m":[{time epoch-sec,open,high,low,close,volume}...],
  "bars1h":[{time epoch-sec,...}...]}
Run: python3 scripts/fetch_stooq.py. Requires: pip3 install yfinance
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

SYMBOLS = ["NVDA","MSFT","AAPL","AMZN","JPM","WMT","V","JNJ","PG","HD","KO",
           "UNH","CSCO","CVX","IBM","CRM","AXP","GS","DIS","MCD","MRK","CAT",
           "VZ","BA","AMGN","HON","NKE","SHW","MMM","TRV"]

OUT = Path(__file__).resolve().parent.parent / "app" / "data"
UP = "rgba(38,166,154,0.5)"
DOWN = "rgba(239,83,80,0.5)"

def _col(df, name):
    """Robust column getter for flat or MultiIndex (Price,Ticker) frames."""
    if name in df.columns:
        return df[name]
    for c in df.columns:
        if isinstance(c, tuple) and name in c:
            return df[c]
    raise KeyError(f"no {name} column in {list(df.columns)[:6]}")

# Yahoo rejects literal dots in US tickers ("BRK.B") but accepts the
# hyphen form ("BRK-B"); class-B share "BF.B" likewise. "SQ" (Block, old
# ticker) and "EXAS" (Exact Sciences, delisted) no longer exist on Yahoo —
# EXAS is dropped via failed-list report, SQ remapped to its successor XYZ.
# Aliases map display symbol -> fetch symbol; failures fall through to retry.
YF_ALIASES = {"BF.B": "BF-B", "BRK.B": "BRK-B", "SQ": "XYZ"}

def _yf_hist(sym, period, interval):
    return yf.Ticker(YF_ALIASES.get(sym, sym)).history(
        period=period, interval=interval, auto_adjust=False)

def _hist(sym, period, interval, tries=5):
    """Fetch one OHLCV frame with retry/backoff; raises after `tries`.
    Yahoo date-window errors (empty frame on FIRST try for a too-long range)
    are permanent — fail fast instead of burning retries."""
    last = None
    for a in range(tries):
        try:
            df = _yf_hist(sym, period, interval)
            if df is not None and not df.empty:
                return df
            last = RuntimeError("empty frame")
        except Exception as e:
            last = e
            if "must be within the last" in str(e):  # Yahoo range-window: permanent
                break
        if a == 0 and isinstance(last, RuntimeError) and str(last) == "empty frame":
            break  # range too long => every retry returns empty; don't wait
        wait = min(60, 5 * (2 ** a))
        print(f"  {sym} {interval} try{a+1}/{tries} miss ({last}) -> sleep {wait}s", flush=True)
        time.sleep(wait)
    raise last

def _bars_from(df):
    """Frame -> [{time epoch-sec UTC, open, high, low, close, volume}] (skips bad rows)."""
    io, ih, il, ic, iv = (_col(df, k) for k in ("Open", "High", "Low", "Close", "Volume"))
    out = []
    for ts, oo, hh, ll, cc, vv in zip(df.index, io, ih, il, ic, iv):
        try:
            oo, hh, ll, cc = float(oo), float(hh), float(ll), float(cc)
            vv = int(vv or 0)
        except (TypeError, ValueError):
            continue
        if not (oo > 0 and hh > 0 and ll > 0 and cc > 0):
            continue
        t = int(pd.Timestamp(ts).tz_convert("UTC").timestamp())
        out.append({"time": t, "open": round(oo,2), "high": round(hh,2),
                    "low": round(ll,2), "close": round(cc,2), "volume": vv})
    return out

def _merge(old, new):
    """Merge bar lists by time key (new wins); returns ascending-sorted list."""
    by = {b["time"]: b for b in (old or [])}
    for b in (new or []):
        by[b["time"]] = b
    return [by[k] for k in sorted(by)]

def fetch_one(sym):
    """Returns (candles, vols, fresh5m, fresh1h). Daily date-strings;
    intraday as UTC epoch seconds (lightweight-charts UTCTimestamp)."""
    ddf = _hist(sym, "5y", "1d")
    o, h, l, c, v = (_col(ddf, k) for k in ("Open", "High", "Low", "Close", "Volume"))
    candles, vols = [], []
    for ts, oo, hh, ll, cc in zip(ddf.index, o, h, l, c):
        try:
            oo, hh, ll, cc = float(oo), float(hh), float(ll), float(cc)
        except (TypeError, ValueError):
            continue
        if not (oo > 0 and hh > 0 and ll > 0 and cc > 0):
            continue
        d = pd.Timestamp(ts).strftime("%Y-%m-%d")
        candles.append({"time": d, "open": round(oo,2), "high": round(hh,2),
                        "low": round(ll,2), "close": round(cc,2)})
    if len(candles) < 30:
        raise RuntimeError(f"daily too few rows ({len(candles)})")
    for row, vv in zip(candles, v):
        try:
            vv = int(vv or 0)
        except (TypeError, ValueError):
            vv = 0
        vols.append({"time": row["time"], "value": vv,
                     "color": UP if row["close"] >= row["open"] else DOWN})
    fresh5m, fresh1h = [], []
    try:
        fresh5m = _bars_from(_hist(sym, "60d", "5m"))
    except Exception as e:
        print(f"  {sym}: 5m unavailable ({e}) — keep archived", flush=True)
    try:
        fresh1h = _bars_from(_hist(sym, "730d", "1h"))
    except Exception as e:
        print(f"  {sym}: 1h unavailable ({e}) — keep archived", flush=True)
    return candles, vols, fresh5m, fresh1h

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    failed = []
    for sym in SYMBOLS:
        fp = OUT / f"{sym}.json"
        prev = {}
        if fp.exists():
            try:
                prev = json.loads(fp.read_text())
            except (json.JSONDecodeError, OSError):
                prev = {}
        try:
            candles, vols, fresh5m, fresh1h = fetch_one(sym)
        except Exception as e:
            print(f"  {sym}: YFINANCE MISS ({e})", flush=True)
            failed.append(sym)
            continue
        bars5m = _merge(prev.get("bars5m"), fresh5m)
        bars1h = _merge(prev.get("bars1h"), fresh1h)
        payload = {"symbol": sym, "source": "yfinance",
                   "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "candles": candles, "vols": vols, "bars5m": bars5m, "bars1h": bars1h}
        fp.write_text(json.dumps(payload))
        total += len(candles)
        print(f"{sym:5s} daily={len(candles):4d} 5m={len(bars5m):5d}(+{len(fresh5m)}) 1h={len(bars1h):5d}(+{len(fresh1h)}) close={candles[-1]['close']}", flush=True)
        time.sleep(1)  # gentle pacing for Yahoo rate limiter
    print(f"\nDONE symbols={len(SYMBOLS)-len(failed)}/{len(SYMBOLS)} yfinance={len(SYMBOLS)-len(failed)} total_bars={total} missed={failed or 'none'}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
