# Wildbill Charts — project summary (carried over from watchlist101 click-ops chat)

## Where we came from
- Started in `~/Desktop/tradingview-click-process/`: automated TradingView chart `CQ7TOVdR`, 16 symbols, 2s pauses, 16/16 via `scripts/click_robust.py` (row locator + `scroll_into_view_if_needed`, click at row x+55).
- Moved to `https://watchlist101.com/` in `~/Desktop/watchlist101-click-process/`: a TradingView `widgetembed` iframe with a 30-row watchlist (`NVDA…TRV`).
- First iframe pass `w101_click.py` (manual page coords) scored 1/30 (off-by-one-row); `w101_fix.py` (frame locator click) scored 30/30.
- Flicker investigation: `navs:[]` over 30 clicks proved NO reload; the widget tears down + rebuilds canvas/volume/header per symbol. Synthetic JS events scored 2/30 (widget needs trusted clicks). `force=True` clicks + `--disable-smooth-scrolling` removed scroll flicker only.
- Keyboard nav (`w101_kb_full.py`): 1 click on NVDA to focus `DIV.tree-LVUu4GCH`, then 29× ArrowDown — same rebuild flicker per switch.
- Conclusion: timing/pause changes can't fix it. Built own-chart proof in `own-chart/` with `lightweight-charts@4.2.0`: ONE chart instance, `setData()` per symbol, 30/30 (`run.json`), `http://localhost:8902`, zero rebuild flicker. Click-through demo `scripts/ownchart_show.py` also 30/30.

## New project: ~/Desktop/wildbill-charts/
Separate from click-ops. Goal: own charting (lightweight-charts) + real data service.
- `app/` — fresh chart app (to be built; do NOT reuse mock `data.js` prices as real).
- `scripts/` — data fetch/cron scripts.
- `docs/` — this file + DATAFEED.md + NEWCHAT.md.

## Data services to use (see docs/DATAFEED.md)
1. Stooq free CSV (no key): `https://stooq.com/q/d/l/?s=aapl.us&i=d` — daily OHLC, 30 symbols, cache in `app/data/`.
2. Optional: Alpaca / Polygon / TwelveData / Yahoo for intraday + live (keys needed).
3. Server: static `python3 -m http.server` (dev) → later FastAPI/Flask `/api/candles?symbol=AAPL&range=1y` proxy with cache.

## Next steps
1. Pick feed (start Stooq, no key).
2. (done) `scripts/fetch_stooq.py` + `app/` built and verified 30/30.

## Index constituents (done 2026-09-10)
- `scripts/fetch_constituents.py` (stdlib only: `urllib` + `json` + `html.parser` + `unittest`, no requests/pandas) pulls index members into `app/markets.js`.
- Sources: DOW30, NDQ100, SP500, ARKK, CRYPTO, ETF100, and XLI..XLE use static JSON files at `watchlist-static-files.web.app`; DOW30/NDQ100/SP500 fall back independently to their corresponding Wikipedia tables. Full membership is stored in `symbols`; only `priceSymbols` are staged from Yahoo. CRYPTO and ETF100 each have 100 price symbols. R2000 remains a local sample because the site has no equivalent list.
- Crash-proof: retries w/ backoff, per-list fault isolation (a failed list keeps its previous symbols), JSON/HTML cache at `app/.cache_constituents/` + `--offline` mode. `fetch_market.py` was patched to also ingest `var DOW30` so staged data covers the new official members (e.g. GOOGL).
- Run: `python3 scripts/fetch_constituents.py [--dry-run] [--offline] [--selftest]` (20 bundled unit tests, all passing).
- Result of first live run: DOW30=30 (official, GOOGL in / VZ out), NDQ100=102, SP500=503, 11 sector lists derived, locals untouched.
- Follow-up as needed: `python3 scripts/fetch_market.py` to stage `app/data/*.json` for the newly listed symbols; then re-run `scripts/verify.py`.
- 2026-09-10 Yahoo staging done on `/usr/bin/python3` (only interpreter with yfinance+pandas): 288/292 fresh + 3 alias rescues (`BRK.B`→`BRK-B`, `BF.B`→`BF-B`, `SQ`→`XYZ`), `EXAS` (ARKK, delisted) un-fetchable anywhere. Result: `app/data/` = 587 files, every market list 100% cached except EXAS. Patched `fetch_stooq._hist` fail-fast on Yahoo range errors + `YF_ALIASES`; see scripts.
