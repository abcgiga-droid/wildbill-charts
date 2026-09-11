/* Timeframe = bar interval (TradingView-style): the pill sets BOTH the window
 * AND the candle size. All client-side on preloaded data (<1ms) — switching TF
 * is the same setData() swap as switching symbols. No network, no rebuild.
 *
 * Each candle's interval == the pill:
 *   5m  -> raw 5-minute bars, last ~5 sessions (detail window)
 *   15m -> 5m resampled ×3, last ~10 sessions
 *   30m -> 5m resampled ×6, last ~20 sessions
 *   1H  -> native 1-hour bars (2y depth), last ~2 months
 *   1D  -> daily bars, full ~5y archive (WINDOW 1500)
 *   1W  -> daily resampled to ISO weeks, full ~5y archive (WINDOW 300)
 *   1M  -> daily resampled to calendar months, full 5y (WINDOW 72)
 * Intraday times are UTC epoch seconds (UTCTimestamp); daily+ are YYYY-MM-DD.
 */
var TF = (function () {
  "use strict";
  var IDS = ["5m","15m","30m","1H","1D","1W","1M"];
  var SEC = {"5m":300,"15m":900,"30m":1800,"1H":3600};
  // How many bars back each pill shows (window matched to interval).
  // 1W/1D/1M windows are wide on purpose: the fetcher keeps ~5y of daily
  // history (~261 weekly, ~60 monthly bars), so these pills show the full
  // archive instead of clipping it to ~2y/6mo/5y-tails.
  var WINDOW = {"5m":390,"15m":340,"30m":400,"1H":350,"1D":1500,"1W":300,"1M":72};

  // Group epoch-second bars into N-second buckets: O=first,H=max,L=min,C=last,V=sum
  function resample(bars, step) {
    var out = [], cur = null;
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i], key = Math.floor(b.time / step) * step;
      if (!cur || cur.time !== key) {
        if (cur) out.push(cur);
        cur = { time: key, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume };
      } else {
        if (b.high > cur.high) cur.high = b.high;
        if (b.low < cur.low) cur.low = b.low;
        cur.close = b.close;
        cur.volume += b.volume;
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  // "YYYY-MM-DD" -> ISO week key "YYYY-Www"
  function weekKey(ds) {
    var d = new Date(ds + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() + 4 - ((d.getUTCDay() + 6) % 7));
    var y0 = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    var w = Math.ceil((((d - y0) / 86400000) + 1) / 7);
    return d.getUTCFullYear() + "-W" + (w < 10 ? "0" + w : w);
  }

  // Daily {candles,vols} (date-string times) -> weekly bars, Monday date as time
  function toWeekly(candles, vols) {
    var out = [], cur = null;
    for (var i = 0; i < candles.length; i++) {
      var b = candles[i], key = weekKey(b.time);
      var vol = vols[i] ? vols[i].value : 0;
      if (!cur || cur._k !== key) {
        if (cur) out.push(cur);
        cur = { _k: key, time: b.time, open: b.open, high: b.high, low: b.low,
                close: b.close, volume: vol };
      } else {
        if (b.high > cur.high) cur.high = b.high;
        if (b.low < cur.low) cur.low = b.low;
        cur.close = b.close;
        cur.volume += vol;
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  // Daily -> calendar-month bars, "YYYY-MM-01" as time
  function toMonthly(candles, vols) {
    var out = [], cur = null;
    for (var i = 0; i < candles.length; i++) {
      var b = candles[i], key = b.time.slice(0, 7);
      var vol = vols[i] ? vols[i].value : 0;
      if (!cur || cur._k !== key) {
        if (cur) out.push(cur);
        cur = { _k: key, time: key + "-01", open: b.open, high: b.high, low: b.low,
                close: b.close, volume: vol };
      } else {
        if (b.high > cur.high) cur.high = b.high;
        if (b.low < cur.low) cur.low = b.low;
        cur.close = b.close;
        cur.volume += vol;
      }
    }
    if (cur) out.push(cur);
    return out;
  }

  function toLC(bars) {
    var c = [], v = [];
    for (var i = 0; i < bars.length; i++) {
      var b = bars[i];
      c.push({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
      v.push({ time: b.time, value: b.volume,
               color: b.close >= b.open ? "rgba(38,166,154,0.5)" : "rgba(239,83,80,0.5)" });
    }
    return { candles: c, vols: v };
  }

  function tail(candles, vols, n) {
    n = Math.min(n, candles.length);
    return { candles: candles.slice(candles.length - n),
             vols: vols.slice(vols.length - n) };
  }

  // Main entry: symData = {candles, vols, bars5m[], bars1h[]}; returns {candles, vols, label}
  function slice(symData, tf) {
    var d = symData.candles, v = symData.vols,
        m = symData.bars5m || [], h = symData.bars1h || [];
    var w = WINDOW[tf] || 252, r;
    if (tf === "5m" || tf === "15m" || tf === "30m") {
      var step = SEC[tf];
      var rs = step === 300 ? m.slice() : resample(m, step);
      r = toLC(rs);
      var cut = Math.max(0, r.candles.length - w);
      r = { candles: r.candles.slice(cut), vols: r.vols.slice(cut) };
      r.label = r.candles.length + " × " + tf + " candles";
      return r;
    }
    if (tf === "1H") {
      r = toLC(h);
      var c2 = Math.max(0, r.candles.length - w);
      r = { candles: r.candles.slice(c2), vols: r.vols.slice(c2) };
      r.label = r.candles.length + " × 1H candles (2y depth)";
      return r;
    }
    if (tf === "1D") {
      r = tail(d, v, w);
      r.label = r.candles.length + " × daily candles";
      return r;
    }
    if (tf === "1W" || tf === "1M") {
      var agg = tf === "1W" ? toWeekly(d, v) : toMonthly(d, v);
      var lc = toLC(agg.map(function (b) { return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }; }));
      var c3 = Math.max(0, lc.candles.length - w);
      r = { candles: lc.candles.slice(c3), vols: lc.vols.slice(c3) };
      r.label = r.candles.length + " × " + (tf === "1W" ? "weekly" : "monthly") + " candles";
      return r;
    }
    r = tail(d, v, w);
    r.label = r.candles.length + " × daily candles";
    return r;
  }

  return { IDS: IDS, slice: slice, resample: resample, toWeekly: toWeekly, toMonthly: toMonthly };
})();
if (typeof window !== "undefined") window.TF = TF;
