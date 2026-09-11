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

  function fmt(n) { return Number(n).toFixed(2); }
  function mkt() { return MKT.get(current); }

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

  function closePanel() {
    mktPanel.classList.remove("open");
    mktToggle.classList.remove("open");
  }

  function buildRows(lst) {
    var rowsBox = document.getElementById("rows");
    rowsBox.innerHTML = "";
    rowEls = lst.symbols.map(function (sym) {
      var d = document.createElement("div");
      d.className = "row"; d.tabIndex = -1; d.dataset.symbol = sym;
      d.innerHTML = '<span class="sym">' + sym + '</span><span class="last">…</span><span class="chg"></span>';
      d.addEventListener("click", function () { select(lst.symbols.indexOf(sym), true); });
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
      layout: { background: { color: "#0b0e11" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "rgba(42,46,57,0.5)" }, horzLines: { color: "rgba(42,46,57,0.5)" } },
      timeScale: { timeVisible: false },
      rightPriceScale: { borderVisible: false },
    });
    candles = chart.addCandlestickSeries({ upColor: "#26a69a", downColor: "#ef5350", wickUpColor: "#26a69a", wickDownColor: "#ef5350", borderVisible: false });
    volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
    chart.priceScale("").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

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
    // Symbol search: filter the current watchlist rows
    var search = document.getElementById("search");
    search.addEventListener("input", function () {
      var q = search.value.trim().toUpperCase();
      var shown = 0;
      rowEls.forEach(function (r, k) {
        var hit = !q || r.dataset.symbol.indexOf(q) === 0;
        r.style.display = hit ? "" : "none";
        if (hit) shown++;
      });
      watchCount.textContent = "· " + (q ? shown + "/" + SYMBOLS.length : SYMBOLS.length);
    });

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
    var row = rowEls[SYMBOLS.indexOf(sym)];
    row.querySelector(".last").textContent = fmt(last);
    var chgEl = row.querySelector(".chg");
    chgEl.textContent = (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%";
    chgEl.className = "chg " + (chg >= 0 ? "up" : "down");
  }

  function select(i, focusRow) {
    idx = (i + SYMBOLS.length) % SYMBOLS.length;
    render(focusRow);
  }

  function setTF(id) {
    if (window.TF.IDS.indexOf(id) < 0) return;
    tf = id;
    Object.keys(tfBtns).forEach(function (k) { tfBtns[k].classList.toggle("active", k === tf); });
    chart.timeScale().applyOptions({ timeVisible: /m|H|D/.test(tf) });
    render(false);
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
    candles.setData(c);
    volume.setData(v);
    chart.timeScale().scrollToRealTime();
    var b = c[c.length - 1], prev = c[c.length - 2].close;
    var chg = ((b.close - prev) / prev) * 100;
    head.innerHTML = "<b>" + sym + "</b> <span class='meta'>[" + tf + "]</span> &nbsp; O " + fmt(b.open) + " H " + fmt(b.high) +
      " L " + fmt(b.low) + " C " + fmt(b.close) + " " +
      '<span class="' + (chg >= 0 ? "up" : "down") + '">' + (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%</span>";
    rowEls.forEach(function (r, k) { r.classList.toggle("active", k === idx); });
    var active = rowEls[idx];
    active.scrollIntoView({ block: "nearest", behavior: "auto" });
    if (focusRow) active.focus({ preventScroll: true });
    document.title = sym + " " + fmt(b.close) + " [" + tf + "] — " + mkt().label;
  }

  window.__select = function (i) { select(i, false); };
  window.__setTF = setTF;
  window.__tf = function () { return tf; };
  window.__market = function () { return current; };
  window.__markets = function () { return MKT.LISTS.map(function (l) { return l.id; }); };
  window.__symbols = function () { return SYMBOLS.slice(); };
  window.__data = DATA;

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
