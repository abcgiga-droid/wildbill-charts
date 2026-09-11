/* Wildbill charts: ONE chart instance, setData() per symbol AND per timeframe.
 * Preloaded ./data/{SYM}.json = {candles/vols daily, bars5m, bars1h} (fetch_stooq.py via yfinance).
 * Pill == candle interval: 5m/15m/30m/1H/1D/1W/1M. Aggregated client-side in <1ms (tf.js).
 * Click a row OR ArrowDown/ArrowUp to switch symbol. No fetch on click, no destroy/rebuild.
 */
(function () {
  var MKT = window.MARKETS;
  var SYMBOLS = MKT.LISTS[0].symbols.slice();   // current market's symbols
  var DATA = {};   // sym -> {candles, vols, bars5m, bars1h, source}
  var idx = 0, tf = "1D", current = MKT.LISTS[0].id;
  var chart, candles, volume, head, watchCount,
      rowEls = [], tfBtns = {}, mktPanel, mktToggle, mktEl, statusChip, statusText;
  var lineS, areaS, maS = {}, cur = { candles: [], sym: "" };
  var chartType = "candle", maOn = { 20: false, 50: false, 200: false }, scaleLog = false, scalePct = false;
  var sortKey = "none", sortDir = 1, QUOTE = {};   // QUOTE[sym] = {last, chg} for sorting
  var liveTimer = null, liveSeq = 0;   // delta-poll state (visible symbol only)

  // Merge bar lists by time key (new wins), ascending — mirrors fetch_stooq._merge
  function mergeByTime(old, add) {
    if (!add || !add.length) return old;
    var by = {}, i;
    for (i = 0; i < old.length; i++) by[old[i].time] = old[i];
    for (i = 0; i < add.length; i++) by[add[i].time] = add[i];
    var keys = Object.keys(by).sort();
    var out = [];
    for (i = 0; i < keys.length; i++) out.push(by[keys[i]]);
    return out;
  }

  // Delta fetch: match local tail, append only NEW dates (no full-history refetch).
  // Called on: boot (visible sym), select()/setTF() (debounced 300ms), 15s poll.
  function liveDelta(reason) {
    var sym = SYMBOLS[idx], d = DATA[sym];
    if (!d || !d.candles || !d.candles.length) return;
    var my = ++liveSeq;
    var sd = d.candles[d.candles.length - 1].time;
    var m = d.bars5m || [];
    var s5 = m.length ? m[m.length - 1].time : 0;
    fetch("/api/delta?symbol=" + encodeURIComponent(sym) +
          "&since_daily=" + encodeURIComponent(sd) + "&since_5m=" + s5)
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (q) {
        if (my !== liveSeq || SYMBOLS[idx] !== sym) return; // user moved on
        var grew = false;
        if (q.daily && q.daily.length) {
          d.candles = mergeByTime(d.candles, q.daily);
          d.vols = mergeByTime(d.vols, q.vols || []);
          grew = true;
        }
        if (q.intraday && q.intraday.length) {
          d.bars5m = mergeByTime(d.bars5m || [], q.intraday);
          grew = true;
        }
        if (grew) { paintRow(sym); render(false); }
        else if (typeof q.last === "number") {
          var c = d.candles, last = c[c.length - 1];
          if (last.close !== q.last) {
            last.close = q.last;
            if (last.high < q.last) last.high = q.last;
            if (last.low > q.last) last.low = q.last;
            QUOTE[sym] = { last: q.last,
              chg: ((q.last - c[c.length - 2].close) / c[c.length - 2].close) * 100 };
            render(false);
          }
        }
      })
      .catch(function () { /* offline / 502: keep cached bars */ });
  }

  function kickLive(reason) {
    if (liveTimer) clearTimeout(liveTimer);
    liveTimer = setTimeout(function () { liveDelta(reason); }, reason === "poll" ? 0 : 300);
  }

  function fmt(n) { return Number(n).toFixed(2); }
  function mkt() { return MKT.get(current); }

  function sma(bars, n) {
    var out = [];
    if (bars.length < n) return out;
    var sum = 0;
    for (var i = 0; i < bars.length; i++) {
      sum += bars[i].close;
      if (i >= n) sum -= bars[i - n].close;
      if (i >= n - 1) out.push({ time: bars[i].time, value: sum / n });
    }
    return out;
  }

  function loadData(mktId) {
    var lst = MKT.get(mktId);
    var pending = lst.symbols.filter(function (s) { return !DATA[s]; });
    if (!pending.length) return Promise.resolve(lst);
    return Promise.all(pending.map(function (sym) {
      return fetch("./data/" + sym + ".json")
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .then(function (j) { DATA[sym] = j; })
        .catch(function () { DATA[sym] = null; }); // staged, not fetched yet
    })).then(function () { return lst; });
  }

  function quoteVal(sym, key) {
    var q = QUOTE[sym];
    if (key === "sym") return sym;
    if (!q) return -Infinity;
    return key === "last" ? q.last : q.chg;
  }

  function reorderRows() {
    var activeSym = SYMBOLS[idx];
    var rowsBox = document.getElementById("rows");
    var bySym = {};
    rowEls.forEach(function (r) { bySym[r.dataset.symbol] = r; });
    rowsBox.innerHTML = "";
    rowEls = SYMBOLS.map(function (s) { rowsBox.appendChild(bySym[s]); return bySym[s]; });
    idx = SYMBOLS.indexOf(activeSym);
    applySearchFilter();
    render(false);
  }

  function applySort() {
    if (sortKey === "none") return;
    var dir = sortDir;
    SYMBOLS.sort(function (a, b) {
      var va = quoteVal(a, sortKey), vb = quoteVal(b, sortKey);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return a < b ? -1 : a > b ? 1 : 0;
    });
    reorderRows();
  }

  function syncSortBtns() {
    var btns = document.querySelectorAll("#sortbar button");
    for (var i = 0; i < btns.length; i++) {
      var k = btns[i].dataset.sort;
      var on = k === sortKey;
      btns[i].classList.toggle("sorted", on);
      var arrow = on ? (sortDir === 1 ? " ▲" : " ▼") : "";
      btns[i].textContent = (k === "sym" ? "Name" : k === "last" ? "Price" : "Chg%") + arrow;
    }
  }

  function setSort(key) {
    if (sortKey === key) {
      if (sortDir === 1) sortDir = -1;
      else { sortKey = "none"; sortDir = 1; }
    } else {
      sortKey = key;
      sortDir = key === "sym" ? 1 : -1;
    }
    if (sortKey === "none") {
      SYMBOLS = mkt().symbols.slice();
      reorderRows();
    } else {
      applySort();
    }
    syncSortBtns();
  }

  function applySearchFilter() {
    var search = document.getElementById("search");
    var q = search ? search.value.trim().toUpperCase() : "";
    var shown = 0;
    rowEls.forEach(function (r) {
      var hit = !q || r.dataset.symbol.indexOf(q) === 0;
      r.style.display = hit ? "" : "none";
      if (hit) shown++;
    });
    watchCount.textContent = "· " + (q ? shown + "/" + SYMBOLS.length : SYMBOLS.length);
  }

  function closePanel() {
    mktPanel.classList.remove("open");
    mktToggle.classList.remove("open");
  }

  function buildRows(lst) {
    var rowsBox = document.getElementById("rows");
    rowsBox.innerHTML = "";
    sortKey = "none"; sortDir = 1;
    syncSortBtns();
    rowEls = lst.symbols.map(function (sym) {
      var d = document.createElement("div");
      d.className = "row"; d.tabIndex = -1; d.dataset.symbol = sym;
      d.innerHTML = '<span class="sym">' + sym + '</span><span class="last">…</span><span class="chg"></span>';
      d.addEventListener("click", function () { select(SYMBOLS.indexOf(sym), true); });
      rowsBox.appendChild(d);
      return d;
    });
    watchCount.textContent = "· " + lst.symbols.length;
  }

  function loadMarket(mktId, force) {
    if (mktId === current && force) { current = mktId; }   // boot: init rows
    else if (mktId === current) { closePanel(); return; }  // click on active: just close
    else { current = mktId; }
    Array.prototype.forEach.call(mktEl, function (it) {
      it.classList.toggle("active", it.dataset.mkt === current);
    });
    closePanel();
    var lst = MKT.get(mktId);
    SYMBOLS = lst.symbols.slice();
    idx = 0;
    buildRows(lst);
    return loadData(mktId).then(function () {
      SYMBOLS.forEach(function (s) { if (DATA[s]) paintRow(s); });
      render(true);
      var cached = SYMBOLS.filter(function (s) { return DATA[s]; }).length;
      setChip(cached === SYMBOLS.length ? "ok" : "partial",
              lst.label + " · " + cached + "/" + SYMBOLS.length);
      return lst;
    });
  }

  function boot() {
    var el = document.getElementById("chart");
    chart = LightweightCharts.createChart(el, {
      layout: { background: { color: "#0b0e11" }, textColor: "#d1d4dc", attributionLogo: false },
      grid: { vertLines: { color: "rgba(42,46,57,0.5)" }, horzLines: { color: "rgba(42,46,57,0.5)" } },
      timeScale: { timeVisible: false },
      rightPriceScale: { borderVisible: false },
    });
    candles = chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", wickUpColor: "#26a69a", wickDownColor: "#ef5350", borderVisible: false });
    volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
    chart.priceScale("").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    lineS = chart.addLineSeries({ color: "#00acc1", lineWidth: 2, visible: false });
    areaS = chart.addAreaSeries({ lineColor: "#00acc1", topColor: "rgba(0,172,193,0.4)", bottomColor: "rgba(0,172,193,0.0)", lineWidth: 2, visible: false });
    maS = {
      20: chart.addLineSeries({ color: "#ff9800", lineWidth: 1, visible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
      50: chart.addLineSeries({ color: "#2962ff", lineWidth: 1, visible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }),
      200: chart.addLineSeries({ color: "#c2185b", lineWidth: 1, visible: false, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
    };

    head = document.getElementById("symbol-head");
    watchCount = document.getElementById("watch-count");
    statusChip = document.getElementById("status-chip");
    statusText = document.getElementById("status-text");
    // Timeframe pill bar
    var tfbar = document.getElementById("tfbar");
    window.TF.IDS.forEach(function (id) {
      var b = document.createElement("button");
      b.textContent = id;
      b.dataset.tf = id;
      b.className = id === tf ? "active" : "";
      b.addEventListener("click", function () { setTF(id); });
      tfbar.appendChild(b);
      tfBtns[id] = b;
    });
    // MARKETS hover dropdown (header)
    mktToggle = document.getElementById("hdr-mkt-toggle");
    mktPanel = document.getElementById("hdr-mkt-panel");
    var mktWrap = document.getElementById("hdr-mkt");
    var hoverTimer = null;
    function openPanel() {
      clearTimeout(hoverTimer);
      mktPanel.classList.add("open");
      mktToggle.classList.add("open");
    }
    function closePanel() {
      mktPanel.classList.remove("open");
      mktToggle.classList.remove("open");
    }
    function scheduleClose() {
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(closePanel, 250);
    }
    mktWrap.addEventListener("mouseenter", openPanel);
    mktWrap.addEventListener("mouseleave", scheduleClose);
    mktToggle.addEventListener("click", function () {
      mktPanel.classList.contains("open") ? closePanel() : openPanel();
    });
    MKT.LISTS.forEach(function (lst) {
      var it = document.createElement("div");
      it.className = "mkt-item" + (lst.id === current ? " active" : "");
      it.dataset.mkt = lst.id;
      it.innerHTML = '<span class="nm">' + lst.label + "</span><span class='badge'>" + lst.symbols.length + "</span>";
      it.addEventListener("click", function () { loadMarket(lst.id); });
      mktPanel.appendChild(it);
    });
    mktEl = mktPanel.querySelectorAll(".mkt-item");
    // Crosshair OHLC readout (TV-style): hover shows that bar's values
    chart.subscribeCrosshairMove(function (p) {
      if (!cur.candles.length) return;
      var b = p && p.time ? null : null;
      if (p && p.time) {
        for (var i = cur.candles.length - 1; i >= 0; i--) {
          if (cur.candles[i].time <= p.time) { b = cur.candles[i]; break; }
        }
        if (!b) b = cur.candles[0];
      } else {
        b = cur.candles[cur.candles.length - 1];
      }
      paintHead(cur.sym, b);
    });
    // Toolbox: chart type / SMA overlays / scale mode (all setData-free toggles)
    function syncBtns() {
      var tg = document.querySelectorAll("#typegrp button");
      for (var i = 0; i < tg.length; i++) tg[i].classList.toggle("active", tg[i].dataset.type === chartType);
      var mg = document.querySelectorAll("#maggrp button");
      for (var j = 0; j < mg.length; j++) mg[j].classList.toggle("active", !!maOn[mg[j].dataset.ma]);
      var sg = document.querySelectorAll("#scalegrp button");
      for (var k = 0; k < sg.length; k++) {
        var s = sg[k].dataset.scale;
        sg[k].classList.toggle("active", s === "log" ? scaleLog : scalePct);
      }
    }
    document.querySelectorAll("#typegrp button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        chartType = btn.dataset.type;
        candles.applyOptions({ visible: chartType === "candle" });
        lineS.applyOptions({ visible: chartType === "line" });
        areaS.applyOptions({ visible: chartType === "area" });
        syncBtns();
      });
    });
    document.querySelectorAll("#maggrp button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var n = btn.dataset.ma;
        maOn[n] = !maOn[n];
        maS[n].applyOptions({ visible: maOn[n] });
        refreshMAs();
        syncBtns();
      });
    });
    document.querySelectorAll("#scalegrp button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (btn.dataset.scale === "log") { scaleLog = !scaleLog; scalePct = false; }
        else { scalePct = !scalePct; scaleLog = false; }
        chart.priceScale("right").applyOptions({ mode: scaleLog ? 1 : scalePct ? 2 : 0 });
        syncBtns();
      });
    });
    // Sortable watchlist header: Name / Price / Chg% (click cycles asc→desc→market order)
    document.querySelectorAll("#sortbar button").forEach(function (btn) {
      btn.addEventListener("click", function () { setSort(btn.dataset.sort); });
    });
    // Symbol search: filter the current watchlist rows
    var search = document.getElementById("search");
    search.addEventListener("input", function () { applySearchFilter(); });

    document.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); select(idx + 1, false); }
      else if (e.key === "ArrowUp") { e.preventDefault(); select(idx - 1, false); }
    });

    function resize() { chart.applyOptions({ width: el.clientWidth, height: el.clientHeight }); }
    window.addEventListener("resize", resize);
    resize();

    // Load current market (DOW30) up front — cache = instant local swap, no flicker.
    loadMarket(current, true).then(function () {
      setChip("ok", "yfinance · daily+5m+1h");
      window.__ready = true;
      kickLive("boot");                       // match tail -> append new dates
      setInterval(function () {                // visible-symbol poll, 15s
        if (!document.hidden) kickLive("poll");
      }, 15000);
    }).catch(function (err) {
      setChip("off", "data load failed");
      head.textContent = "data load failed: " + err + " (run scripts/fetch_stooq.py, serve via http.server)";
      window.__ready = false;
    });
  }

  function setChip(state, text) {
    statusChip.className = "status-chip " + state;
    statusText.textContent = text;
  }

  function paintRow(sym) {
    var d = DATA[sym];
    if (!d || !d.candles || !d.candles.length) return;
    var c = d.candles, last = c[c.length - 1].close, prev = c[c.length - 2].close;
    var chg = ((last - prev) / prev) * 100;
    QUOTE[sym] = { last: last, chg: chg };
    var ri = SYMBOLS.indexOf(sym);
    if (ri < 0 || !rowEls[ri]) return;
    var row = rowEls[ri];
    row.querySelector(".last").textContent = fmt(last);
    var chgEl = row.querySelector(".chg");
    chgEl.textContent = (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%";
    chgEl.className = "chg " + (chg >= 0 ? "up" : "down");
  }

  function select(i, focusRow) {
    idx = (i + SYMBOLS.length) % SYMBOLS.length;
    render(focusRow);
    kickLive("select");
  }

  function setTF(id) {
    if (window.TF.IDS.indexOf(id) < 0) return;
    tf = id;
    Object.keys(tfBtns).forEach(function (k) { tfBtns[k].classList.toggle("active", k === tf); });
    chart.timeScale().applyOptions({ timeVisible: /m|H|D/.test(tf) });
    render(false);
    kickLive("tf");
  }

  function refreshMAs() {
    if (!cur.candles.length) return;
    ["20", "50", "200"].forEach(function (n) {
      var s = maS[n];
      if (!s) return;
      s.setData(maOn[n] ? sma(cur.candles, parseInt(n, 10)) : []);
      s.applyOptions({ visible: !!maOn[n] });
    });
  }

  function paintHead(sym, b) {
    var prev = cur.candles.length > 1 ? cur.candles[cur.candles.length - 2].close : b.open;
    var chg = ((b.close - prev) / prev) * 100;
    head.innerHTML = "<b>" + sym + "</b> <span class='meta'>[" + tf + "]</span> &nbsp; O " + fmt(b.open) + " H " + fmt(b.high) +
      " L " + fmt(b.low) + " C " + fmt(b.close) + " " +
      '<span class="' + (chg >= 0 ? "up" : "down") + '">' + (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%</span>";
  }

  function render(focusRow) {
    var sym = SYMBOLS[idx], d = DATA[sym];
    document.title = sym + " [" + tf + "] — " + mkt().label;
    if (!d || !d.candles || !d.candles.length) {
      head.innerHTML = "<b>" + sym + "</b><div class='meta'>not cached — run scripts/fetch_market.py</div>";
      return;
    }
    // NO destroy: aggregate preloaded bars + swap data in place, canvas stays mounted
    var s = window.TF.slice(d, tf);
    var c = s.candles, v = s.vols;
    if (!c.length) return;
    cur = { candles: c, sym: sym };
    candles.setData(c);
    volume.setData(v);
    lineS.setData(c.map(function (b) { return { time: b.time, value: b.close }; }));
    areaS.setData(c.map(function (b) { return { time: b.time, value: b.close }; }));
    refreshMAs();
    chart.timeScale().scrollToRealTime();
    paintHead(sym, c[c.length - 1]);
    rowEls.forEach(function (r, k) { r.classList.toggle("active", k === idx); });
    var active = rowEls[idx];
    active.scrollIntoView({ block: "nearest", behavior: "auto" });
    if (focusRow) active.focus({ preventScroll: true });
    document.title = sym + " " + fmt(c[c.length - 1].close) + " [" + tf + "] — " + mkt().label;
  }

  window.__select = function (i) { select(i, false); };
  window.__setTF = setTF;
  window.__setSort = setSort;
  window.__sortState = function () { return { key: sortKey, dir: sortDir }; };
  window.__tf = function () { return tf; };
  window.__market = function () { return current; };
  window.__markets = function () { return MKT.LISTS.map(function (l) { return l.id; }); };
  window.__symbols = function () { return SYMBOLS.slice(); };
  window.__data = DATA;
  window.__liveDelta = liveDelta;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
