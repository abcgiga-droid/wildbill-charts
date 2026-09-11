# New-chat starter (paste into a fresh chat)

I'm starting a new project in `~/Desktop/wildbill-charts/` (scaffolded: `app/`, `scripts/`, `docs/` with `SUMMARY.md` + `DATAFEED.md` — read those first).

Goal: stock chart app with TradingView lightweight-charts (NOT the TradingView widget iframe) + real market data, zero flicker when switching symbols.

Proven pattern (from `~/Desktop/watchlist101-click-process/own-chart/`, 30/30 flicker-free on mocks at `http://localhost:8902`):
- one `createChart()` + one candlestick + one volume series; switch via `setData()` only; click rows + ArrowDown/ArrowUp nav; preload all data.

Symbols (30): NVDA, MSFT, AAPL, AMZN, JPM, WMT, V, JNJ, PG, HD, KO, UNH, CSCO, CVX, IBM, CRM, AXP, GS, DIS, MCD, MRK, CAT, VZ, BA, AMGN, HON, NKE, SHW, MMM, TRV.

Please:
1. Read `~/Desktop/wildbill-charts/docs/SUMMARY.md` and `DATAFEED.md`.
2. Write `scripts/fetch_stooq.py` (no API key): fetch daily OHLC for all 30 from `https://stooq.com/q/d/l/?s={sym}.us&i=d`, convert to lightweight-charts format, save `app/data/{SYM}.json`, print per-symbol bar counts.
3. Build `app/index.html` + `app/app.js` modeling `../watchlist101-click-process/own-chart/` but loading real JSON from `./data/`, with header OHLC, Last/Chg% rows, click + ArrowDown/Up, resize handling.
4. Serve and verify: run a Playwright pass clicking all 30 rows with 2s dwell, log matches, screenshot each, confirm no blank/rebuild flicker.
5. Report matches + any symbols Stooq missed, and propose the intraday/live upgrade (Alpaca/Polygon) as follow-up.
