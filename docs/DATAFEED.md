# Data feed options for wildbill-charts (lightweight-charts needs {time,open,high,low,close} + volume)

## Recommended start: Stooq free CSV (no API key)
- Daily: `https://stooq.com/q/d/l/?s=aapl.us&i=d` → Date,Open,High,Low,Close,Volume
- 30 symbols map: NVDA→nvda.us, MSFT→msft.us, AAPL→aapl.us, AMZN→amzn.us, JPM→jpm.us, WMT→wmt.us, V→v.us, JNJ→jnj.us, PG→pg.us, HD→hd.us, KO→ko.us, UNH→unh.us, CSCO→csco.us, CVX→cvx.us, IBM→ibm.us, CRM→crm.us, AXP→axp.us, GS→gs.us, DIS→dis.us, MCD→mcd.us, MRK→mrk.us, CAT→cat.us, VZ→vz.us, BA→ba.us, AMGN→amgn.us, HON→hon.us, NKE→nke.us, SHW→shw.us, MMM→mmm.us, TRV→trv.us
- Intraday: `&i=5` (5-min, limited history) or `&i=15,30,60,90`.
- Script: `scripts/fetch_stooq.py` loops symbols, converts Date→UNIX time, writes `app/data/SYM.json` as `{candles:[...], vols:[...]}`. Run daily via cron/launchd. Cache = no flicker (local swap, same as mock run).

## Upgrade paths
| Use case | Service | Notes |
|---|---|---|
| Intraday US stocks, free tier | Alpaca Market Data (`\(ALPACA_KEY/SECRET`) | `GET /v2/stocks/{sym}/bars?timeframe=1Day|5Min`, 15-min delay free, good docs |
| Pro daily+intraday | Polygon.io (`POLYGON_KEY`) | `GET /v2/aggs/ticker/AAPL/range/1/day/...`, generous free stocks tier |
| Quick intraday, no broker | TwelveData (`TWELVE_KEY`) | `GET /time_series?symbol=AAPL&interval=1day`, small free quota |
| No key, casual | Yahoo chart API | `https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=1y`, unofficial, rate-limited |
| Crypto (if added) | Binance/Coinbase public | free OHLC, no key |

## Architecture
- Dev: static files + `python3 -m http.server` (like own-chart :8902 now).
- Next: tiny proxy `GET /api/candles?symbol=AAPL&range=1y` (FastAPI/Flask) that serves cache, refreshes in background, so the chart swap stays `setData()`-instant and never waits on network.
- Live (later): websocket/MQTT or 15s poll → `series.update({time,close...})` on the mounted series (no rebuild).

## lightweight-charts wiring (keep from own-chart/app.js)
- `createChart()` ONCE; `addCandlestickSeries` + `addHistogramSeries` ONCE.
- Switch = `candles.setData(json.candles); volume.setData(json.vols); timeScale().scrollToRealTime()` — verified 30/30 flicker-free on mocks.
