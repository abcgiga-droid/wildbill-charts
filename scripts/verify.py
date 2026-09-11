"""Playwright pass: all 30 symbols x all 10 timeframes, log matches, screenshot each TF.
Also checks no blank chart and no rebuild (canvas count constant across switches).
Run: python3 scripts/verify.py [--url http://localhost:8910] [--dwell 0.6] [--tf-only 1D]
"""
import json, sys, time
from pathlib import Path

URL = "http://localhost:8910"
DWELL = 0.6
TF_ONLY = None
for a in sys.argv[1:]:
    if a.startswith("--url"): URL = a.split("=",1)[1]
    if a.startswith("--dwell"): DWELL = float(a.split("=",1)[1])
    if a.startswith("--tf-only"): TF_ONLY = a.split("=",1)[1]

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "app" / "shots"
SHOT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width":1280,"height":800})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_function("window.__ready === true", timeout=120000)
    n = pg.evaluate("window.__symbols().length")
    tfs = pg.evaluate("window.TF.IDS")
    if TF_ONLY:
        tfs = [TF_ONLY]
    n5 = pg.evaluate("window.__data.NVDA.bars5m.length")
    print(f"symbols={n} timeframes={tfs} bars5m/sym={n5}")
    assert n == 30, "DOW30 expected at boot"
    same_canvas = True
    first_canvases = None
    results, tfshots = [], []
    for tfi, tf in enumerate(tfs):
        pg.click(f"#tfbar button[data-tf='{tf}']")
        time.sleep(0.4)
        cur = pg.evaluate("window.__tf()")
        assert cur == tf, f"tf did not stick: {cur}"
        for i in range(n):
            sym = pg.evaluate(f"window.__symbols()[{i}]")
            pg.click(f".row[data-symbol='{sym}']")
            time.sleep(DWELL)
            title = pg.title() if callable(getattr(pg, "title", None)) else pg.title
            canvases = pg.evaluate("document.querySelectorAll('#chart canvas').length")
            # lightweight-charts v4 renders ~7 canvases; no-rebuild = count CONSTANT.
            if first_canvases is None:
                first_canvases = canvases
            elif canvases != first_canvases:
                same_canvas = False
            match = title.startswith(sym + " ") and (f"[{tf}]" in title)
            blank = pg.evaluate("(()=>{const c=document.querySelector('#chart canvas');return !c||c.width===0||c.height===0})()")
            nbars = pg.evaluate("(()=>{const h=document.getElementById('symbol-head').innerText;const m=h.match(/(\\d+) ×|daily bars/);return h.split('\\n').pop()})()")
            results.append({"symbol": sym, "tf": tf, "title": title, "match": match, "canvases": canvases, "blank": blank, "head": nbars})
            if i < 3 or not (match and not blank):
                print(f"{tf:>3} {i:02d} {sym:5s} match={match} blank={blank} {nbars}")
            if tfi == 0:
                pg.screenshot(path=str(SHOT / f"{i:02d}_{sym}.png"))
        pg.screenshot(path=str(SHOT / f"tf_{tf}.png"))
        tfshots.append(f"tf_{tf}.png")
    # keyboard nav check from top
    pg.evaluate("window.__select(0)")
    time.sleep(0.5)
    for _ in range(3):
        pg.keyboard.press("ArrowDown"); time.sleep(0.4)
    kb_title = pg.title() if callable(getattr(pg, "title", None)) else pg.title
    print(f"kb-nav after 0+3xDown: {kb_title!r} (expect AMZN)")
    (ROOT / "app" / "run.json").write_text(json.dumps({"clicks": results}, indent=1))
    ok = sum(1 for r in results if r["match"] and not r["blank"])
    print(f"\n{ok}/{len(results)} symbol×tf matches, no-rebuild={same_canvas}, pageerrors={errs or 'none'}")
    print(f"shots -> {SHOT}, log -> app/run.json")
    b.close()
