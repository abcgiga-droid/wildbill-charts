"""Delta server: static app/ + live /api/* (stdlib only + yfinance).

Replaces `python3 -m http.server 8910`. History stays in app/data/*.json
(cron via scripts/fetch_stooq.py); this server returns ONLY the delta
(~5 daily rows + today's 1m bars) so navigate = match + append.
Run: /usr/bin/python3 server/server.py [--port 8910]
"""
import json
import time
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

try:
    import yfinance as yf
    HAVE_YF = True
except ImportError:
    HAVE_YF = False

YF_ALIASES = {"BF.B": "BF-B", "BRK.B": "BRK-B", "SQ": "XYZ"}
QUOTE_TTL = 10
_cache = {}
_lock = threading.Lock()
UP = "rgba(38,166,154,0.5)"
DOWN = "rgba(239,83,80,0.5)"


def _yf(sym):
    import yfinance as _m
    return _m.Ticker(YF_ALIASES.get(sym, sym))


def get_quote(sym):
    sym = sym.upper().strip()
    now = time.time()
    with _lock:
        if sym in _cache and now - _cache[sym][0] < QUOTE_TTL:
            hit = dict(_cache[sym][1])
            hit["cached"] = True
            return hit
    t = _yf(sym)
    price = float(t.fast_info.last_price)
    prev = None
    for k in ("regularMarketPreviousClose", "previousClose"):
        try:
            v = t.fast_info.get(k) if hasattr(t.fast_info, "get") else getattr(t.fast_info, k, None)
        except Exception:
            v = None
        if v:
            prev = float(v)
            break
    payload = {"symbol": sym, "price": round(price, 2),
               "prevClose": round(prev, 2) if prev else None,
               "time": int(now),
               "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "cached": False}
    with _lock:
        _cache[sym] = (now, payload)
    return payload


def get_delta(sym, since_daily="", since_5m=0):
    """Small delta: ~5 daily rows + today's 1m bars, filtered by since_*."""
    import pandas as pd
    sym = sym.upper().strip()
    t = _yf(sym)
    daily, vols, intra = [], [], []
    last = None
    try:
        df = t.history(period="5d", interval="1d", auto_adjust=False)
        if df is not None and not df.empty:
            for ts, row in df.iterrows():
                try:
                    o, h, l, c = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
                except (TypeError, ValueError, KeyError):
                    continue
                if not (o > 0 and h > 0 and l > 0 and c > 0):
                    continue
                d = pd.Timestamp(ts).strftime("%Y-%m-%d")
                if since_daily and d <= since_daily:
                    continue
                try:
                    vv = int(row.get("Volume", 0) or 0)
                except (TypeError, ValueError):
                    vv = 0
                daily.append({"time": d, "open": round(o, 2), "high": round(h, 2),
                              "low": round(l, 2), "close": round(c, 2)})
                vols.append({"time": d, "value": vv,
                             "color": UP if c >= o else DOWN})
                last = round(c, 2)
    except Exception as e:
        print(f"  delta {sym} daily miss: {e}", flush=True)
    try:
        m = t.history(period="1d", interval="1m", auto_adjust=False)
        if m is not None and not m.empty:
            for ts, row in m.iterrows():
                try:
                    o, h, l, c = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
                except (TypeError, ValueError, KeyError):
                    continue
                if not (o > 0 and h > 0 and l > 0 and c > 0):
                    continue
                epoch = int(pd.Timestamp(ts).tz_convert("UTC").timestamp())
                if epoch <= int(since_5m or 0):
                    continue
                try:
                    vv = int(row.get("Volume", 0) or 0)
                except (TypeError, ValueError):
                    vv = 0
                intra.append({"time": epoch, "open": round(o, 2), "high": round(h, 2),
                              "low": round(l, 2), "close": round(c, 2), "volume": vv})
            if intra:
                last = intra[-1]["close"]
    except Exception as e:
        print(f"  delta {sym} 1m miss: {e}", flush=True)
    if last is None:
        try:
            last = round(float(_yf(sym).fast_info.last_price), 2)
        except Exception:
            last = None
    return {"symbol": sym, "daily": daily, "vols": vols, "intraday": intra,
            "last": last,
            "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds")}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(APP_DIR), **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/health":
            return self._json({"ok": True, "yfinance": HAVE_YF,
                               "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        if parsed.path == "/api/quote":
            sym = (qs.get("symbol", [""])[0] or "").upper().strip()
            if not sym:
                return self._json({"error": "missing ?symbol="}, 400)
            if not HAVE_YF:
                return self._json({"error": "yfinance missing"}, 500)
            try:
                return self._json(get_quote(sym))
            except Exception as e:
                return self._json({"error": "quote miss: %s" % e}, 502)
        if parsed.path == "/api/delta":
            sym = (qs.get("symbol", [""])[0] or "").upper().strip()
            if not sym:
                return self._json({"error": "missing ?symbol="}, 400)
            if not HAVE_YF:
                return self._json({"error": "yfinance missing"}, 500)
            sd = qs.get("since_daily", [""])[0] or ""
            try:
                s5 = int(qs.get("since_5m", ["0"])[0] or 0)
            except ValueError:
                s5 = 0
            try:
                return self._json(get_delta(sym, sd, s5))
            except Exception as e:
                return self._json({"error": "delta miss: %s" % e}, 502)
        return super().do_GET()


def main():
    import sys
    port = 8910
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
        elif a == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
    if not HAVE_YF:
        print("WARNING: yfinance missing — /api/* will 500. Use /usr/bin/python3.", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("wildbill server on http://127.0.0.1:%d/ (static app/ + /api/quote + /api/delta)" % port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

