#!/usr/bin/env python3
"""fetch_constituents.py — Pull index constituent lists from Wikipedia into app/markets.js.

STDLIB ONLY (urllib + html.parser + unittest): no requests/pandas/bs4, so it
cannot crash on missing third-party packages in a bare venv.

Every index is fetched INDEPENDENTLY. A failure for one list keeps its previous
symbols from app/markets.js and never aborts the run.

Sources (Wikipedia, no API key):
  DOW30  https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies
  NDQ100 https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies
  SP500  https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
  XLI..XLE (10 GICS sector lists) are DERIVED from the SP500 table's "GICS Sector"
  column, so one page keeps the whole S&P family in sync.

Lists that are NOT on Wikipedia (ARKK, CRYPTO, ETF100, R2000) are carried over
unchanged from the current app/markets.js.

Usage:
  python3 scripts/fetch_constituents.py             # fetch live + rewrite app/markets.js
  python3 scripts/fetch_constituents.py --dry-run   # show what would change, write nothing
  python3 scripts/fetch_constituents.py --offline   # use cached HTML (no network)
  python3 scripts/fetch_constituents.py --selftest  # run bundled unit tests (no network)

Exit codes: 0 = ok (or only partial refresh), 1 = every refresh failed, 2 = abort.
"""
import argparse
import http.client
import html.parser
import json
import os
import re
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
UA = ("wildbill-charts-fetch_constituents/1.0 "
      "(local index-constituent collector; contact: project owner)")

SECTOR_MIN = 5  # minimum symbols a derived sector list must have to be accepted

WEB_SOURCES = {
    "DOW30": {
        "url": "https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies",
        "min": 20},
    "NDQ100": {
        "url": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
        "min": 60},
    "SP500": {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "min": 400},
}

# markets.js list id -> GICS sector as written on the S&P 500 page
SECTOR_LISTS = {
    "XLI": "Industrials",
    "XLV": "Health Care",
    "XLK": "Information Technology",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLU": "Utilities",
    "XLF": "Financials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
}

# Column headers are matched by substring, so renames/reorders survive.
SYMBOL_ALIASES = ("ticker", "symbol")
SECTOR_ALIASES = ("gics sector", "icb industry", "sector")

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
FOOT_RE = re.compile(r"\[\s*(?:citation\s*)?\d+\s*\]")

DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "app" / ".cache_constituents"


class FetchError(Exception):
    pass


class CacheMiss(Exception):
    pass


class ParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------
def fetch_url(url, timeout=45, tries=3):
    """GET url -> html text. Retries 5xx/429 with backoff, fails fast on 4xx."""
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise FetchError("HTTP %d" % r.status)
                data = r.read().decode("utf-8", "replace")
                if "<table" not in data:
                    raise FetchError("response contains no <table>")
                return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:
                break  # permanent (404/403/…): retrying won't help
        except (urllib.error.URLError, OSError, socket.timeout,
                http.client.HTTPException) as e:
            last = e
        if attempt + 1 < tries:
            time.sleep(2 ** attempt)
    raise FetchError("GET %s failed after %d tries: %s" % (url, tries, last))


def cache_path(cache_dir, cfg_id):
    return Path(cache_dir) / (cfg_id + ".html")


def load_cached(cache_dir, cfg_id):
    p = cache_path(cache_dir, cfg_id)
    if not p.exists():
        raise CacheMiss("no cached HTML for %s (run online once)" % cfg_id)
    return p.read_text(encoding="utf-8", errors="replace")


def save_cached(cache_dir, cfg_id, html_text):
    try:
        d = Path(cache_dir)
        d.mkdir(parents=True, exist_ok=True)
        cache_path(d, cfg_id).write_text(html_text, encoding="utf-8")
    except OSError as e:
        print("  ! cache write failed: %s" % e, flush=True)


def get_html(cfg_id, url, offline, cache_dir, fetcher):
    """Return page HTML. Online: fetch, cache, and on network failure fall
    back to cache with a warning. Offline: cache only (or CacheMiss)."""
    if offline:
        return load_cached(cache_dir, cfg_id)
    try:
        html_text = fetcher(url)
        save_cached(cache_dir, cfg_id, html_text)
        return html_text
    except Exception as e:  # network down? try yesterday's copy
        try:
            html_text = load_cached(cache_dir, cfg_id)
            print("  %s: %s -> using cached HTML" % (cfg_id, e), flush=True)
            return html_text
        except CacheMiss:
            raise


# ---------------------------------------------------------------------------
# HTML table extraction (stdlib html.parser, frame stack => nested tables ok)
# ---------------------------------------------------------------------------
class _TableParser(html.parser.HTMLParser):
    """Collects every <table> as [rows][cells][text fragments]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)  # &amp; -> &
        self.tables = []            # finished tables
        self._frames = []           # stack of [table, current_row, current_cell]

    def _cur(self):
        return self._frames[-1] if self._frames else None

    def handle_starttag(self, tag, attrs):
        f = self._cur()
        if tag == "table":
            self._frames.append([[], None, None])
        elif tag == "tr" and f is not None:
            row = []
            f[0].append(row)
            f[1] = row
        elif tag in ("td", "th") and f is not None and f[1] is not None:
            cell = []
            f[1].append(cell)
            f[2] = cell

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            f = self._cur()
            if f:
                f[2] = None
        elif tag == "tr":
            f = self._cur()
            if f:
                f[1] = None
        elif tag == "table":
            f = self._frames.pop() if self._frames else None
            if f and f[0]:
                self.tables.append(f[0])

    def handle_data(self, data):
        f = self._cur()
        if f is not None and f[1] is not None and f[2] is not None:
            f[2].append(data)


def extract_tables(html_text):
    p = _TableParser()
    p.feed(html_text or "")
    p.close()
    return p.tables


def cell_text(cell):
    """Cell fragments -> one clean string (footnotes/entities/&nbsp; handled)."""
    t = "".join(cell)
    t = t.replace("\xa0", " ")
    t = FOOT_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" *\u2020\u2021")
    return t


def find_col(headers, aliases):
    """Index of the leftmost header cell containing any alias, else None."""
    for i, name in enumerate(headers):
        low = name.lower()
        for a in aliases:
            if a in low:
                return i
    return None


def clean_symbol(raw):
    """Normalize a ticker cell. Returns None if it is not a valid symbol."""
    if raw is None:
        return None
    s = raw.replace("\xa0", " ").strip(" *\u2020\u2021")
    s = FOOT_RE.sub("", s).strip()
    if not s or re.search(r"\s", s):       # multi-word -> not a ticker
        return None
    s = s.upper()
    if not SYMBOL_RE.match(s):
        return None
    return s


def parse_components(html_text, need_sector=False):
    """Best constituent table -> (ordered unique symbols, [(symbol, sector)]).
    Raises ParseError when no usable table is found."""
    tables = extract_tables(html_text)
    if not tables:
        raise ParseError("page has no <table> elements")
    best = None  # (row_count, row_index_of_symbol, header_index, symbol_col, sector_col, table)
    for tbl in tables:
        for hi in range(min(5, len(tbl))):
            headers = [cell_text(c).lower() for c in tbl[hi]]
            si = find_col(headers, SYMBOL_ALIASES)
            if si is None or si >= len(headers):
                continue
            seci = find_col(headers, SECTOR_ALIASES) if need_sector else None
            if need_sector and seci is None:
                continue
            n = len(tbl) - hi - 1
            if best is None or n > best[0]:
                best = (n, si, seci, hi, tbl)
    if best is None:
        raise ParseError("no table with a symbol column found")
    _, si, seci, hi, tbl = best
    symbols, records = [], []
    seen = set()
    for row in tbl[hi + 1:]:
        if len(row) <= si:
            continue
        sym = clean_symbol(cell_text(row[si]))
        if not sym or sym in seen:
            continue
        seen.add(sym)
        symbols.append(sym)
        sec = cell_text(row[seci]).strip() if (seci is not None and len(row) > seci) else ""
        records.append((sym, sec))
    return symbols, records


# ---------------------------------------------------------------------------
# app/markets.js read / write (keeps the exact same file shape the app uses)
# ---------------------------------------------------------------------------
_OBJ = re.compile(
    r'\{\s*id:\s*"([A-Za-z0-9_]+)"[^{}]*?label:\s*"(?:[^"\\]|\\.)*"[^{}]*?'
    r"symbols:\s*(\[[^\]]*\]|DOW30)[^{}]*?\}",
    re.S)
_VAR = re.compile(r"var\s+DOW30\s*=\s*(\[[^\]]*\])\s*;", re.S)
_TOKEN = re.compile(r'"([A-Z0-9.\-]{1,12})"')


def _sym_array(txt):
    return _TOKEN.findall(txt)


def read_markets(path):
    """Parse app/markets.js -> ordered list of
    {"id","label","staged","symbols"}. Raises ValueError if unusable."""
    p = Path(path)
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    var = _VAR.search(txt)
    dow = _sym_array(var.group(1)) if var else []
    lists = []
    for m in _OBJ.finditer(txt):
        obj, lid, raw = m.group(0), m.group(1), m.group(2)
        label_m = re.search(r'label:\s*"((?:[^"\\]|\\.)*)"', obj)
        label = label_m.group(1) if label_m else lid
        syms = _sym_array(raw) if raw.startswith("[") else list(dow)
        lists.append({"id": lid, "label": label,
                      "staged": "staged: true" in obj, "symbols": syms})
    if not lists:
        raise ValueError("markets.js parsed to zero lists")
    return lists


def render_markets_js(lists):
    """Ordered lists -> markets.js source text (one list per line, DOW30 as a var)."""
    counts = " ".join("%s=%d" % (l["id"], len(l["symbols"])) for l in lists)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "/* Wildbill Markets — index constituent lists.",
        " * DOW30 ships with data; every other list is staged: fetched on first",
        " * selection via scripts/fetch_market.py. THIS FILE IS GENERATED by",
        " * scripts/fetch_constituents.py from Wikipedia (List of Dow Jones",
        " * Industrial Average companies, List of NASDAQ-100 companies, List of",
        " * S&P 500 companies). Sector lists XLI..XLE are derived from the S&P",
        " * 500 table's \"GICS Sector\" column. Local-only: ARKK/CRYPTO/ETF100/R2000.",
        " * Generated: " + stamp,
        " * Counts: " + counts,
        " */",
        "var MARKETS = (function () {",
        '  "use strict";',
    ]
    dow = next((l for l in lists if l["id"] == "DOW30"), lists[0])
    out.append("  var DOW30 = %s;" % json.dumps(dow["symbols"]))
    out.append("  var LISTS = [")
    for l in lists:
        jid = json.dumps(l["id"])
        jlabel = json.dumps(l["label"])
        if l["id"] == "DOW30":
            out.append('    { id: %s, label: %s, symbols: DOW30 },' % (jid, jlabel))
        else:
            staged = "staged: true, " if l["staged"] else ""
            out.append("    { id: %s, label: %s, %ssymbols: %s }," %
                       (jid, jlabel, staged, json.dumps(l["symbols"])))
    out.append("  ];")
    out += [
        "  function get(id) {",
        "    for (var i = 0; i < LISTS.length; i++) if (LISTS[i].id === id) return LISTS[i];",
        "    return LISTS[0];",
        "  }",
        "  return { LISTS: LISTS, DOW30: DOW30, get: get };",
        "})();",
        'if (typeof window !== "undefined") window.MARKETS = MARKETS;',
        "",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Orchestration: fetch what we can, keep previous symbols for the rest
# ---------------------------------------------------------------------------
def diff_add_rem(old, new):
    so, sn = set(old), set(new)
    return sorted(sn - so), sorted(so - sn)


def build_lists(old_lists, offline=False, cache_dir=None, fetcher=fetch_url, mins=None):
    """old_lists: read_markets() result. Returns (final_lists, stats).

    stats = {"refreshed": [ids], "failed": [msg], "sp500": n_or_0}
    One list failing NEVER raises — it keeps its previous symbols.
    `mins` (optional) overrides per-list minimum row counts (tests use it)."""
    stats = {"refreshed": [], "failed": [], "sp500": 0}
    mins = mins or {}
    cache_dir = cache_dir or DEFAULT_CACHE
    old_by = {l["id"]: l for l in old_lists}
    fresh = {}          # list id -> new symbols
    sp500_records = []

    for lid, cfg in WEB_SOURCES.items():
        try:
            html_text = get_html(lid, cfg["url"], offline, cache_dir, fetcher)
            syms, recs = parse_components(html_text, need_sector=(lid == "SP500"))
        except Exception as e:  # network, parse, cache miss: never crash
            stats["failed"].append("%s: %s" % (lid, e))
            continue
        if len(syms) < mins.get(lid, cfg["min"]):
            stats["failed"].append(
                "%s: parsed %d symbols < min %d" % (lid, len(syms), cfg["min"]))
            continue
        fresh[lid] = syms
        if lid == "SP500":
            sp500_records = recs
            stats["sp500"] = len(syms)

    if sp500_records:
        by_sector = {}
        for sym, sec in sp500_records:
            by_sector.setdefault(sec, []).append(sym)
        for lid, gics in SECTOR_LISTS.items():
            if lid not in old_by:
                continue
            got = by_sector.get(gics, [])
            if len(got) < SECTOR_MIN:
                stats["failed"].append(
                    "%s: sector %r absent/small in SP500 table (%d)" % (lid, gics, len(got)))
                continue
            fresh[lid] = got

    final = []
    for l in old_lists:
        if l["id"] in fresh:
            final.append(dict(l, symbols=fresh[l["id"]]))
            stats["refreshed"].append(l["id"])
        else:
            final.append(dict(l))
    return final, stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Fetch index constituents from Wikipedia into app/markets.js")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would change, write nothing")
    ap.add_argument("--offline", action="store_true",
                    help="read cached HTML only (no network)")
    ap.add_argument("--selftest", action="store_true",
                    help="run bundled unit tests (no network) and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SelfTest)
        res = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if res.wasSuccessful() else 1

    root = Path(__file__).resolve().parent.parent
    markets_path = root / "app" / "markets.js"
    try:
        old = read_markets(markets_path)
    except ValueError as e:
        print("ABORT: %s" % e, flush=True)
        return 2
    if not old:
        print("ABORT: %s not found or unreadable" % markets_path, flush=True)
        return 2

    try:
        final, stats = build_lists(old, offline=args.offline, fetcher=fetch_url)
    except Exception as e:  # last-resort guard: never die mid-run
        print("UNEXPECTED: %r" % (e,), flush=True)
        import traceback
        traceback.print_exc()
        return 1

    print("\n== summary ==")
    for l in final:
        o = old[[i for i, x in enumerate(old) if x["id"] == l["id"]][0]]
        add, rem = diff_add_rem(o["symbols"], l["symbols"])
        tag = "OK  " if l["id"] in stats["refreshed"] else "keep"
        print("  %s %-6s %4d syms  (+%d -%d)  %s" %
              (tag, l["id"], len(l["symbols"]), len(add), len(rem), l["label"]))
    print("\n-- refreshed: %s" % (stats["refreshed"] or "none"))
    if stats["failed"]:
        print("-- failed (kept previous):")
        for f in stats["failed"]:
            print("    %s" % f)

    if args.dry_run:
        print("\n[dry-run] not writing app/markets.js")
        return 0 if stats["refreshed"] else 1

    try:
        markets_path.write_text(render_markets_js(final), encoding="utf-8")
    except OSError as e:
        print("WRITE FAILED: %s" % e, flush=True)
        return 1
    print("\nwrote app/markets.js (%d lists)" % len(final))
    return 0 if stats["refreshed"] else 1


# ---------------------------------------------------------------------------
# Bundled self-test  (python3 scripts/fetch_constituents.py --selftest)
# ---------------------------------------------------------------------------
class SelfTest(unittest.TestCase):
    """Offline tests: HTML parsing, symbol cleaning, sector derivation,
    fault isolation (network down), and a full markets.js round-trip."""

    @staticmethod
    def _dow_fixture(n=30):
        h = ("<table><tr><th>Company</th><th>Exchange</th><th>Symbol</th>"
             "<th>Sector</th><th>Date added</th></tr>")
        return h + "".join(
            "<tr><td>C%02d</td><td>NYSE</td><td>SY%02d</td><td>Industrials</td>"
            "<td>2020-01-01</td></tr>" % (i, i) for i in range(n)) + "</table>"

    @staticmethod
    def _ndq_fixture(n=80):
        h = ("<table><tr><th>Ticker</th><th>Company</th><th>ICB Industry<sup>[1]</sup></th>"
             "<th>ICB Subsector<sup>[1]</sup></th></tr>")
        return h + "".join(
            "<tr><td>ND%02d</td><td>C%02d</td><td>Technology</td><td>Software</td></tr>"
            % (i, i) for i in range(n)) + "</table>"

    @staticmethod
    def _sp500_fixture(rows):
        h = ("<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>"
             "<th>GICS Sub-Industry</th></tr>")
        return h + "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r
            for r in rows) + "</table>"

    @staticmethod
    def _sp500_rows():
        rows, i = [], 0
        for sec, n in {"Information Technology": 8, "Health Care": 6,
                       "Financials": 6, "Industrials": 6,
                       "Materials": 5, "Energy": 2}.items():
            for _ in range(n):
                rows.append(("T%03d" % i, "C%03d" % i, sec, "sub"))
                i += 1
        return rows

    @staticmethod
    def _old_text():
        return ('var MARKETS = (function () {\n'
                '  "use strict";\n'
                '  var DOW30 = ["NVDA","AAPL"];\n'
                '  var LISTS = [\n'
                '    { id: "DOW30", label: "DOW 30 Components", symbols: DOW30 },\n'
                '    { id: "NDQ100", label: "NDQ 100 Components", staged: true, symbols: ["NVDA"] },\n'
                '    { id: "SP500", label: "S&P 500 Components", staged: true, symbols: ["NVDA"] },\n'
                '    { id: "ARKK", label: "ARKK Components", staged: true, symbols: ["TSLA","COIN"] },\n'
                '    { id: "XLI", label: "XLI (Industrials)", staged: true, symbols: ["CAT"] },\n'
                '    { id: "XLE", label: "XLE (Energy)", staged: true, symbols: ["CVX"] },\n'
                '  ];\n'
                '  function get(id) {\n'
                '    for (var i = 0; i < LISTS.length; i++) if (LISTS[i].id === id) return LISTS[i];\n'
                '    return LISTS[0];\n'
                '  }\n'
                '  return { LISTS: LISTS, DOW30: DOW30, get: get };\n'
                '})();\n'
                'if (typeof window !== "undefined") window.MARKETS = MARKETS;\n')

    def _old(self, td):
        p = Path(td) / "markets.js"
        p.write_text(self._old_text())
        return read_markets(p)

    # -- parser ------------------------------------------------------------
    def test_extract_tables_entities_and_nbsp(self):
        html_text = ("<table><tr><th>Company</th><th>Symbol</th></tr>"
                     "<tr><td>Procter &amp; Gamble</td><td>PG</td></tr>"
                     "<tr><td>T. Rowe&nbsp;Price</td><td>TROW</td></tr></table>")
        t = extract_tables(html_text)
        self.assertEqual(cell_text(t[0][0][0]), "Company")
        self.assertEqual(cell_text(t[0][1][0]), "Procter & Gamble")
        self.assertEqual(cell_text(t[0][2][0]), "T. Rowe Price")

    def test_extract_tables_nested(self):
        html_text = ("<table><tr><td>out<table><tr><td>in</td></tr></table>"
                     "</td></tr></table>")
        t = extract_tables(html_text)
        self.assertEqual(len(t), 2)                       # both tables captured
        self.assertEqual(cell_text(t[0][0][0]), "in")     # inner extracted
        self.assertEqual(cell_text(t[1][0][0]), "out")    # outer cell kept

    def test_cell_text_footnotes_cleaned(self):
        html_text = ("<table><tr><th>ICB Industry<sup>[1]</sup></th>"
                     "<th>ICB Subsector<sup>[citation 2]</sup></th></tr></table>")
        t = extract_tables(html_text)
        self.assertEqual(cell_text(t[0][0][0]), "ICB Industry")
        self.assertEqual(cell_text(t[0][0][1]), "ICB Subsector")

    def test_clean_symbol(self):
        self.assertEqual(clean_symbol(" brk.b "), "BRK.B")
        self.assertEqual(clean_symbol("GOOGL"), "GOOGL")
        self.assertEqual(clean_symbol("A"), "A")
        self.assertIsNone(clean_symbol("Not A Ticker"))
        self.assertIsNone(clean_symbol(""))
        self.assertIsNone(clean_symbol(None))

    def test_parse_dow_shaped(self):
        syms, recs = parse_components(self._dow_fixture(30), need_sector=True)
        self.assertEqual(len(syms), 30)
        self.assertEqual(syms[0], "SY00")
        self.assertEqual(recs[2], ("SY02", "Industrials"))

    def test_parse_ndq_shaped_ticker_column(self):
        syms, recs = parse_components(self._ndq_fixture(80))
        self.assertEqual(len(syms), 80)
        self.assertEqual(syms[0], "ND00")

    def test_parse_sp500_sector_extraction(self):
        rows = [("NVDA", "Nvidia", "Information Technology", "Sem"),
                ("MSFT", "Microsoft", "Information Technology", "Soft"),
                ("UNH", "UnitedHealth", "Health Care", "Health")]
        syms, recs = parse_components(self._sp500_fixture(rows), need_sector=True)
        self.assertEqual(len(syms), 3)
        self.assertEqual(dict(recs)["NVDA"], "Information Technology")

    def test_parse_garbage_html_raises_cleanly(self):
        with self.assertRaises(ParseError):
            parse_components("<html><body>no table here</body></html>",
                             need_sector=True)


# -- fetch/cache -------------------------------------------------------
    def test_get_html_caches_and_falls_back(self):
        def ok(url):
            return "<table><tr><th>Symbol</th></tr><tr><td>XYZ</td></tr></table>"
        with tempfile.TemporaryDirectory() as td:
            html_text = get_html("SP500", "http://x", False, td, ok)
            self.assertIn("XYZ", html_text)
            self.assertTrue((Path(td) / "SP500.html").exists())

            def boom(url):
                raise FetchError("network down")
            self.assertEqual(get_html("SP500", "http://x", False, td, boom),
                             html_text)                      # cache fallback
            with self.assertRaises(CacheMiss):
                get_html("NDQ100", "http://x", True, td, boom)

    def test_fetch_url_wraps_refused(self):
        with self.assertRaises(FetchError):
            fetch_url("http://127.0.0.1:1/x", timeout=2, tries=1)

    # -- round trip + fault isolation --------------------------------------
    def test_read_render_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            old = self._old(td)
            self.assertEqual([l["id"] for l in old],
                             ["DOW30", "NDQ100", "SP500", "ARKK", "XLI", "XLE"])
            self.assertEqual(old[0]["symbols"], ["NVDA", "AAPL"])
            self.assertTrue(old[1]["staged"])
            p2 = Path(td) / "markets2.js"
            p2.write_text(render_markets_js(old))
            self.assertEqual(read_markets(p2), old)
            self.assertIn("window.MARKETS = MARKETS", p2.read_text())

    def test_all_fail_keeps_previous(self):
        with tempfile.TemporaryDirectory() as td:
            old = self._old(td)

            def boom(url):
                raise FetchError("simulated offline")
            final, stats = build_lists(old, fetcher=boom,
                                       cache_dir=Path(td) / "cache",
                                       mins={"DOW30": 2, "NDQ100": 70, "SP500": 10})
            self.assertEqual(stats["refreshed"], [])
            self.assertEqual(len(stats["failed"]), 3)
            self.assertEqual(final, old)  # nothing lost, nothing crashed

    def test_partial_failure_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            old = self._old(td)

            def fake(url):
                if "Dow_Jones" in url:
                    raise FetchError("down")
                if "NASDAQ" in url:
                    return self._ndq_fixture(80)
                return self._sp500_fixture(self._sp500_rows())
            final, stats = build_lists(old, fetcher=fake,
                                       cache_dir=Path(td) / "cache",
                                       mins={"DOW30": 2, "NDQ100": 70, "SP500": 10})
            by = {l["id"]: l["symbols"] for l in final}
            self.assertEqual(by["DOW30"], ["NVDA", "AAPL"])  # kept (failed)
            self.assertEqual(len(by["NDQ100"]), 80)          # refreshed
            self.assertEqual(len(by["SP500"]), 33)           # refreshed
            self.assertEqual(len(by["XLI"]), 6)              # sector derived
            self.assertEqual(by["XLE"], ["CVX"])             # Energy too small -> kept
            self.assertEqual(by["ARKK"], ["TSLA", "COIN"])   # local untouched
            self.assertEqual(stats["refreshed"], ["NDQ100", "SP500", "XLI"])

    def test_offline_without_cache_is_clean_failure(self):
        with tempfile.TemporaryDirectory() as td:
            old = self._old(td)
            final, stats = build_lists(old, offline=True, cache_dir=td,
                                       mins={"DOW30": 2, "NDQ100": 70, "SP500": 10})
            self.assertEqual(len(stats["failed"]), 3)
            self.assertEqual(final, old)


if __name__ == "__main__":
    sys.exit(main())