"""Headless verification of the web dashboard (docs/index.html).

Serves docs/ on a free localhost port, drives Chromium through every data date x compare-to
mode x tab (plus About), opens an activity drawer, exercises drill-down, search, sorting,
the DQ offender list and the theme toggle, and fails on any console error or page error.
Also checks that no tab scrolls horizontally at 360 px and captures the screenshots used in
the README into docs/screenshots/.

Usage:  .venv\\Scripts\\python.exe scripts\\verify_dashboard.py
Exit code 0 = pass, 1 = failures found.
"""
from __future__ import annotations

import functools
import http.server
import json
import pathlib
import re
import struct
import sys
import threading
import zlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SHOTS = DOCS / "screenshots"
TABS = ["exec", "ms", "cp", "if", "risk", "dq", "recon", "about"]
SHOT_NAMES = {"exec": "tab1_exec.png", "ms": "tab2_milestones.png", "cp": "tab3_critical.png",
              "if": "tab4_interfaces.png", "risk": "tab5_risks.png", "dq": "tab6_dq.png",
              "recon": "tab7_recon.png", "about": "tab8_about.png"}
CMPS = ["prev", "BL0", "BL1"]
CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fdate(iso: str) -> str:
    """2027-10-21 -> 21-Oct-2027 (the page's date format)."""
    y, m, d = iso[:10].split("-")
    return f"{d}-{MON[int(m) - 1]}-{y}"


def signed(n, unit: str = "") -> str:
    """Same signed format as the page: +3 / −7 (U+2212) / ±0."""
    n = round(float(n) * 10) / 10
    n = int(n) if n == int(n) else n
    s = ("+" if n > 0 else "−" if n < 0 else "±") + str(abs(n))
    return s + (" " + unit if unit else "")


def _confidential_pattern():
    """Same pattern as scripts/check_confidentiality.py (term list kept in the git-ignored file)."""
    lst = ROOT / ".confidential_terms.txt"
    if not lst.exists():
        return None
    names = [n.strip() for n in lst.read_text(encoding="utf-8").splitlines() if n.strip()]
    if not names:
        return None
    return re.compile("|".join(r"\b" + re.escape(n) + r"\b" for n in names), re.I)


def _png_rewrite(data: bytes, level: int, chunk: int) -> bytes:
    """Losslessly re-encode a PNG: same pixels, IDAT recompressed at `level`, split every `chunk` bytes."""
    sig, pos, chunks = data[:8], 8, []
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        chunks.append((data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]))
        pos += 12 + n
    raw = zlib.decompress(b"".join(body for typ, body in chunks if typ == b"IDAT"))
    comp = zlib.compress(raw, level)
    out, done = [sig], False
    for typ, body in chunks:
        if typ == b"IDAT":
            if done:
                continue
            done = True
            for i in range(0, len(comp), chunk):
                part = comp[i:i + chunk]
                out.append(struct.pack(">I", len(part)) + b"IDAT" + part + struct.pack(">I", zlib.crc32(b"IDAT" + part)))
        else:
            out.append(struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body)))
    return b"".join(out)


def scrub_png(path: pathlib.Path) -> bool:
    """Compressed image bytes can spell a confidential term by chance; re-encode until they do not.
    Returns False if no clean encoding was found."""
    pat = _confidential_pattern()
    if pat is None:
        return True
    data = path.read_bytes()
    if not pat.search(data.decode("utf-8", errors="ignore")):
        return True
    for level in (9, 8, 7, 6, 5, 4, 3, 2, 1):
        for chunk in (65536, 32768, 16384, 8192, 4093, 1021):
            cand = _png_rewrite(data, level, chunk)
            if not pat.search(cand.decode("utf-8", errors="ignore")):
                path.write_bytes(cand)
                return True
    return False


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the console readable
        pass


def serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(DOCS))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


class Collector:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.context = "load"

    def attach(self, page) -> None:
        page.on("console", lambda m: self.errors.append(f"[{self.context}] console.{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"[{self.context}] pageerror: {e}"))
        page.on("requestfailed", lambda r: self.errors.append(
            f"[{self.context}] request failed: {r.url} ({r.failure})"))


def wait_ready(page) -> None:
    page.wait_for_function("window.__DOP_READY === true", timeout=30000)


def activate(page, tab: str, dd: str | None = None, cmp: str | None = None) -> None:
    page.click(f"#tab-{tab}")
    want = f"{tab}|{dd}|{cmp}" if dd and cmp else None
    if want:
        page.wait_for_function(f"window.__DOP_RENDERED === {want!r}", timeout=10000)
    else:
        page.wait_for_function(f"(window.__DOP_RENDERED || '').startsWith({tab + '|'!r})", timeout=10000)


def no_hscroll(page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    data = json.loads((DOCS / "data" / "dashboard.json").read_text(encoding="utf-8"))
    latest_dd = data["meta"]["latest"]
    lsum = data["snapshots"][latest_dd]["summary"]
    acols = data["activities"]["cols"]
    act_type = {r[acols.index("activity_id")]: r[acols.index("activity_type")] for r in data["activities"]["rows"]}
    httpd, url = serve()
    col = Collector()
    checks: list[str] = []
    failures: list[str] = []
    external: set[str] = set()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            # ---------------------------------------------------------------- full sweep (light)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
            page = ctx.new_page()
            col.attach(page)
            page.on("request", lambda r: external.add(r.url) if not r.url.startswith("http://127.0.0.1") else None)
            page.goto(url, wait_until="networkidle")
            wait_ready(page)
            if not page.evaluate("typeof Chart !== 'undefined'"):
                failures.append("Chart.js did not load from the pinned CDN URL")
            scripts = page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
            links = page.eval_on_selector_all("link[rel=stylesheet][href]", "els => els.map(e => e.href)")
            if scripts != [CHART_JS] or links:
                failures.append(f"external resources must be exactly the pinned Chart.js: scripts={scripts} styles={links}")

            # ---------------------------------------------------------------- numbers vs dashboard.json
            hdr = page.inner_text("header .facts")
            meta_l = next(m for m in data["meta"]["snapshots"] if m["data_date"] == latest_dd)
            for want, what in ((fdate(latest_dd), "data date"), (meta_l["baseline_in_force"], "baseline"),
                               (meta_l["baseline_file"], "baseline file"), ("Reconciled ✓", "reconciled badge"),
                               (meta_l["source_file"], "source file"), (meta_l["sha256"][:8], "file hash"),
                               (f"{lsum['dq_score']:g}/100", "DQ score"), (lsum["dq_rating"], "DQ rating"),
                               (fdate(data["meta"]["generated_utc"]), "generated date"), ("UTC", "generated time")):
                if str(want) not in hdr:
                    failures.append(f"header is missing the {what} ({want!r}): {hdr!r}")
            hero = " ".join(page.inner_text("#p-exec .hero").split())
            for want, what in ((fdate(lsum["day1_forecast"]), "Day 1 forecast"), (signed(lsum["day1_tf_d"], "wd"), "Day 1 total float"),
                               (signed(lsum["day1_var_bl0_d"], "cd"), "Day 1 vs BL0"), (signed(lsum["day1_var_bl1_d"], "cd"), "Day 1 vs BL1"),
                               (f"{lsum['critical_count']} critical", "critical count"),
                               (f"{lsum['near_critical_count']} near-critical", "near-critical count"),
                               (f"{lsum['longest_path_count']} on the longest path", "longest-path count")):
                if want not in hero:
                    failures.append(f"executive summary does not show the {what} from dashboard.json ({want!r})")
            open_dec = [x["decision_id"] for x in data["decisions"] if x["status"] == "Open"]
            asks = page.inner_text("#p-exec .asks")
            for d in open_dec:
                if d not in asks:
                    failures.append(f"open decision {d} missing from the first screen")
            checks.append(f"header and executive numbers match dashboard.json (Day 1 {fdate(lsum['day1_forecast'])}, "
                          f"TF {lsum['day1_tf_d']} wd, DQ {lsum['dq_score']}, critical {lsum['critical_count']}, decisions {', '.join(open_dec)})")
            # first screen: status, risk and the decision ask all start within the 1440 x 900 viewport
            boxes = page.evaluate("""() => ['#p-exec .hero .headline', '#p-exec .hero .tiles', '#p-exec .asks .ask',
                '#p-exec .asks .reco', '#p-exec section.card.c7 h3'].map(s => { const e = document.querySelector(s);
                if (!e) return [s, null]; const r = e.getBoundingClientRect(); return [s, Math.round(r.top), Math.round(r.bottom)]; })""")
            for sel, top, *rest in boxes:
                if top is None:
                    failures.append(f"first screen element missing: {sel}")
                elif (rest[0] if sel != "#p-exec section.card.c7 h3" else top) > 900:
                    failures.append(f"first screen: {sel} is below the 900 px fold (top {top}, bottom {rest[0]})")
            tl = page.evaluate("(() => { const t = document.getElementById('tablist'); return t.scrollWidth - t.clientWidth; })()")
            if tl > 0:
                failures.append(f"tab bar overflows by {tl}px at 1440 px: not every tab is visible")
            checks.append("first screen at 1440x900: headline, Day 1 tiles, decision asks, recommendation and RAG title above the fold; all 8 tabs visible")
            dates = page.eval_on_selector_all("#sel-dd option", "els => els.map(e => e.value)")
            checks.append(f"data dates in selector: {len(dates)}")
            if len(dates) != 6:
                failures.append(f"expected 6 data dates, found {len(dates)}")
            renders = 0
            for dd in dates:
                col.context = f"dd={dd}"
                page.select_option("#sel-dd", dd)
                for cmp in CMPS:
                    col.context = f"dd={dd} cmp={cmp}"
                    page.select_option("#sel-cmp", cmp)
                    for tab in TABS:
                        col.context = f"dd={dd} cmp={cmp} tab={tab}"
                        activate(page, tab, dd, cmp)
                        renders += 1
                        if page.locator(f"#p-{tab} .err").count():
                            failures.append(f"render error shown: {col.context}")
                        canvases = page.locator(f"#p-{tab} canvas").count()
                        sowhats = page.locator(f"#p-{tab} .sowhat").count()
                        if canvases and sowhats < canvases:
                            failures.append(f"{col.context}: {canvases} charts but {sowhats} so-what lines")
                    if cmp == "BL1":
                        activate(page, "recon", dd, cmp)
                        mism = page.evaluate("window.__DOP_RECON_MISMATCH")
                        if mism:
                            failures.append(f"browser recompute mismatches at {dd}: {mism}")
                rec = page.inner_text("#h-rec")
                if "Reconciled" not in rec:
                    failures.append(f"header not reconciled at {dd}: {rec}")
            checks.append(f"tab renders: {renders} (6 dates x 3 compare modes x {len(TABS)} tabs)")

            # ---------------------------------------------------------------- interactions
            latest = dates[-1]
            col.context = "interactions"
            page.select_option("#sel-dd", latest)
            page.select_option("#sel-cmp", "BL1")
            activate(page, "exec")
            # keyboard tab navigation
            page.focus("#tab-exec")
            page.keyboard.press("ArrowRight")
            page.wait_for_function("(window.__DOP_RENDERED || '').startsWith('ms|')")
            page.keyboard.press("End")
            page.wait_for_function("(window.__DOP_RENDERED || '').startsWith('about|')")
            page.keyboard.press("Home")
            page.wait_for_function("(window.__DOP_RENDERED || '').startsWith('exec|')")
            if page.get_attribute("#tab-exec", "aria-selected") != "true" or page.evaluate("document.activeElement.id") != "tab-exec":
                failures.append("keyboard Home did not select and focus the first tab")
            roving = page.eval_on_selector_all("#tablist [role=tab]", "els => els.filter(e => e.tabIndex === 0).length")
            if roving != 1:
                failures.append(f"tablist should expose exactly one tab stop, found {roving}")
            checks.append("keyboard tab navigation (ArrowRight / End / Home) works with one roving tab stop")
            # compare-to really changes the variances (explorer row for Day 1 vs the JSON)
            d1 = data["meta"]["day1_id"]
            acts = data["snapshots"][latest_dd]["acts"]
            d1row = dict(zip(acts["cols"], next(r for r in acts["rows"] if r[acts["cols"].index("activity_id")] == d1)))
            page.evaluate("document.getElementById('explorer').open = true")
            page.fill("#x-q", d1)
            seen = {}
            for cmp, fld in (("prev", "slip_vs_prev_d"), ("BL0", "var_finish_bl0_d"), ("BL1", "var_finish_bl1_d")):
                page.select_option("#sel-cmp", cmp)
                page.wait_for_function(f"(window.__DOP_RENDERED || '').endsWith('|{cmp}')")
                cell = " ".join(page.inner_text("#x-t tbody tr:first-child td:nth-child(10)").split())
                seen[cmp] = cell
                if cell != signed(d1row[fld], "cd"):
                    failures.append(f"compare-to {cmp}: Day 1 variance shows {cell!r}, JSON {fld} = {d1row[fld]}")
                ref = page.get_attribute("#p-exec .tile.is-ref", "class") or ""
                lab = page.inner_text("#p-exec .tile.is-ref .lab") if ref else ""
                if {"prev": "last period", "BL0": "BL0", "BL1": "BL1"}[cmp] not in lab:
                    failures.append(f"compare-to {cmp}: highlighted Day 1 tile is {lab!r}")
            if len(set(seen.values())) < 3:
                failures.append(f"compare-to did not change the variance column: {seen}")
            page.fill("#x-q", "")
            page.select_option("#sel-cmp", "BL1")
            page.wait_for_function("(window.__DOP_RENDERED || '').endsWith('|BL1')")
            checks.append(f"compare-to changes Day 1 variance: prev {seen.get('prev')}, BL0 {seen.get('BL0')}, BL1 {seen.get('BL1')} (match JSON)")
            # drill-down through the RAG matrix and the drill selector
            page.click('#p-exec button.rc[data-drill-asset="DAR"][data-drill-ws="CON"]')
            crumbs = page.inner_text("#crumbs")
            if "Dune Arena" not in crumbs or "Construction" not in crumbs:
                failures.append(f"drill-down breadcrumb wrong: {crumbs!r}")
            level = page.get_attribute("#sel-drill", "data-level")
            opts = page.eval_on_selector_all("#sel-drill option", "els => els.map(e => e.value).filter(Boolean)")
            if level == "pkg" and opts:
                page.select_option("#sel-drill", opts[0])
            else:
                failures.append(f"drill selector should offer WBS packages after asset > workstream, got level {level!r}")
            for tab in TABS:
                activate(page, tab)
            rows_scoped = page.locator("#x-t tbody tr").count()
            n_crumbs = page.locator("#crumbs li").count()
            if n_crumbs != 4:
                failures.append(f"breadcrumb should show Programme > asset > workstream > package, has {n_crumbs} items")
            # drill to activity level (opens the drawer), then walk back up the breadcrumb
            acts_opt = page.eval_on_selector_all("#sel-drill option", "els => els.map(e => e.value).filter(Boolean)")
            if page.get_attribute("#sel-drill", "data-level") == "act" and acts_opt:
                page.select_option("#sel-drill", acts_opt[0])
                page.wait_for_selector("#drawer:not([hidden])")
                page.keyboard.press("Escape")
                if page.locator("#crumbs li").count() != 5 or page.locator("#x-t tbody tr").count() != 1:
                    failures.append("activity-level drill did not give a 5-level breadcrumb and one explorer row")
            page.click('#crumbs [data-crumb="asset"]')
            if page.locator("#crumbs li").count() != 2 or page.get_attribute("#sel-drill", "data-level") != "ws":
                failures.append("breadcrumb click on the asset did not step back to asset level")
            checks.append(f"drill-down DAR > CON > {opts[0] if opts else '?'} ({rows_scoped} explorer rows) > activity; breadcrumb steps back to asset")
            page.click('#crumbs [data-crumb="programme"]')
            if page.locator("#crumbs li").count() != 1:
                failures.append("breadcrumb click on Programme did not clear the drill-down")
            # explorer: search + sort + drawer
            page.evaluate("document.getElementById('explorer').open = true")
            page.fill("#x-q", "DAR-CON")
            n_search = page.locator("#x-t tbody tr").count()
            page.click('#x-t th button[data-sort="total_float_d"]')
            page.click('#x-t th button[data-sort="total_float_d"]')
            checks.append(f"search 'DAR-CON' rows: {n_search}; sort by TF toggled")
            if n_search < 1:
                failures.append("search returned no rows")
            page.click("#x-t tbody tr:first-child button[data-act]")
            page.wait_for_selector("#drawer:not([hidden])")
            dtext = page.text_content("#drawer") or ""
            for must in ("Predecessors", "Successors", "History across the six updates", "Codes"):
                if must not in dtext:
                    failures.append(f"drawer missing section: {must}")
            if page.locator("#drawer table").count() < 2:
                failures.append("drawer should hold relationship and history tables")
            hist_rows = page.locator("#drawer table[class=t]").last.locator("tbody tr").count()
            if hist_rows != len(dates):
                failures.append(f"drawer history should list {len(dates)} updates, lists {hist_rows}")
            if page.evaluate("document.activeElement.id") != "dr-close":
                failures.append("focus did not move into the drawer on open")
            for _ in range(30):
                page.keyboard.press("Tab")
            if not page.evaluate("!!document.activeElement.closest('#drawer')"):
                failures.append("focus escaped the open drawer (no focus trap)")
            # navigate within the drawer to a predecessor/successor
            first_id = page.inner_text("#dr-title")
            link = page.locator("#drawer table button[data-act]").first
            if link.count():
                link.click()
                if page.inner_text("#dr-title") == first_id:
                    failures.append("selecting a related activity in the drawer did not open it")
            page.keyboard.press("Escape")
            page.wait_for_selector("#drawer", state="hidden")
            checks.append(f"activity drawer: predecessors, successors, {hist_rows}-update history, focus trapped, related activity opens, Escape closes")
            page.fill("#x-q", "")
            # DQ offenders -> drawer
            activate(page, "dq")
            page.click('#t-dcma tr[data-check="D07"]')
            off = page.locator("#dq-off button[data-act]")
            if off.count() == 0:
                failures.append("no offenders listed for D07")
            else:
                off.first.click()
                page.wait_for_selector("#drawer:not([hidden])")
                page.click("#dr-close")
            checks.append(f"DQ check D07 offenders: {off.count()} buttons")
            # an N/A check (D10, no resources in the IMS) shows "–" for value, threshold, count and score, never 0 or 1
            d10 = page.locator('#t-dcma tr[data-check="D10"] td').all_inner_texts()
            if len(d10) < 7 or any(d10[i].strip() != "–" for i in (2, 3, 5, 6)):
                failures.append(f"D10 (N/A) must show '–' for value, threshold, count and score: {d10}")
            else:
                checks.append("N/A check D10 shows '–' for value, threshold, count and score")
            # level of effort on the longest path is tagged as the U07 defect and links to the check
            activate(page, "cp")
            tag = page.locator("#p-cp .loe-tag")
            lp_loe = [a for a in data["snapshots"][latest]["acts"]["rows"]
                      if dict(zip(data["snapshots"][latest]["acts"]["cols"], a)).get("is_longest_path")
                      and act_type.get(dict(zip(data["snapshots"][latest]["acts"]["cols"], a))["activity_id"]) == "TT_LOE"]
            if lp_loe and tag.count() != len(lp_loe):
                failures.append(f"{len(lp_loe)} LOE activities on the longest path but {tag.count()} 'LOE · U07' tags")
            elif tag.count():
                tag.first.click()
                page.wait_for_function("(window.__DOP_RENDERED || '').startsWith('dq|')", timeout=10000)
                if page.get_attribute('#p-dq tr[data-check="U07"]', "aria-pressed") != "true":
                    failures.append("the LOE · U07 tag does not open check U07 on the Schedule quality tab")
                else:
                    checks.append(f"LOE on the longest path tagged 'LOE · U07' ({tag.count()}); the tag opens check U07")
            # scrolling tables end on a whole row (no row cut in half at the first view), on every tab
            cut = []
            for tab in TABS:
                activate(page, tab)
                page.evaluate("window.scrollTo(0,0)")
                cut += [f"{tab}: {x}" for x in page.evaluate("""() => { const bad = [];
                    for (const p of document.querySelectorAll('[role=tabpanel]')) {
                      if (p.hidden) continue;
                      for (const b of p.querySelectorAll('.tw[data-max]')) {
                        if (b.scrollHeight <= b.clientHeight + 1) continue;
                        const top = b.getBoundingClientRect().top + b.clientTop, bottom = top + b.clientHeight;
                        for (const r of b.querySelectorAll('tbody tr')) { const q = r.getBoundingClientRect();
                          if (q.top < bottom - 2 && q.bottom > bottom + 2) bad.push(b.getAttribute('aria-label')); }
                      } } return bad; }""")]
            if cut:
                failures.append(f"scrolling tables cut a row in half: {cut}")
            else:
                checks.append("scrolling tables end on a whole row on every tab")
            # every tab is visible at 1280 px (the tour and most laptop screens), not only at 1440 px
            page.set_viewport_size({"width": 1280, "height": 720})
            tl1280 = page.evaluate("(() => { const t = document.getElementById('tablist'); return t.scrollWidth - t.clientWidth; })()")
            page.set_viewport_size({"width": 1440, "height": 900})
            if tl1280 > 0:
                failures.append(f"tab bar overflows by {tl1280}px at 1280 px: the last tab is cut off")
            else:
                checks.append("all 8 tabs visible at 1280 px")
            # interfaces matrix filter + workstream view
            activate(page, "if")
            cell = page.locator("#p-if button.rc[data-if-g]").first
            if cell.count():
                cell.click()
            page.select_option("#if-dim", "ws")
            # theme toggle round trip
            page.click("#theme-btn")
            activate(page, "exec")
            dark = page.evaluate("document.documentElement.getAttribute('data-theme')")
            page.click("#theme-btn")
            checks.append(f"theme toggle -> {dark} -> light")

            # ---------------------------------------------------------------- screenshots (light)
            col.context = "screenshots"
            page.goto(url + f"#tab=exec&dd={latest}&cmp=BL1", wait_until="networkidle")
            page.reload(wait_until="networkidle")  # fresh state: no drill, default views
            wait_ready(page)
            for tab in TABS:
                activate(page, tab, latest, "BL1")
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=str(SHOTS / SHOT_NAMES[tab]))
            ctx.close()

            # ---------------------------------------------------------------- dark mode
            col.context = "dark"
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
            page = ctx.new_page()
            col.attach(page)
            page.goto(url + "#tab=exec", wait_until="networkidle")
            wait_ready(page)
            page.wait_for_function("(window.__DOP_RENDERED || '').startsWith('exec|')")
            bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            if bg.replace(" ", "") != "rgb(15,23,42)":
                failures.append(f"dark mode background not applied: {bg}")
            page.screenshot(path=str(SHOTS / "exec_dark.png"))
            for tab in TABS:
                activate(page, tab)
            ctx.close()

            # ---------------------------------------------------------------- mobile 360 px
            col.context = "mobile"
            ctx = browser.new_context(viewport={"width": 360, "height": 780}, color_scheme="light",
                                      device_scale_factor=2, is_mobile=True, has_touch=True)
            page = ctx.new_page()
            col.attach(page)
            page.goto(url + "#tab=exec", wait_until="networkidle")
            wait_ready(page)
            for tab in TABS:
                activate(page, tab)
                over = no_hscroll(page)
                if over > 0:
                    failures.append(f"horizontal page scroll at 360 px on tab {tab}: {over}px")
            activate(page, "exec")
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(SHOTS / "exec_mobile.png"), full_page=True)
            checks.append("360 px: no horizontal page scroll on any tab")
            ctx.close()

            # ---------------------------------------------------------------- print media
            col.context = "print"
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            col.attach(page)
            page.goto(url + "#tab=ms", wait_until="networkidle")
            wait_ready(page)
            page.emulate_media(media="print")
            hidden = page.evaluate("getComputedStyle(document.querySelector('.controls')).display")
            if hidden != "none":
                failures.append("print CSS does not hide the controls")
            checks.append("print media hides controls")
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    other = sorted(u for u in external if u != CHART_JS and not u.startswith("data:"))
    if other or CHART_JS not in external:
        failures.append(f"network requests outside localhost must be only the pinned Chart.js; saw {sorted(external)}")
    checks.append("only external request: " + CHART_JS)

    for png in sorted(SHOTS.glob("*.png")):
        if not scrub_png(png):
            failures.append(f"could not produce a clean encoding of {png.name}")
    checks.append("screenshots pass the confidential-term byte scan")

    failures = col.errors + failures
    print("Dashboard verification")
    for c in checks:
        print("  ok  ", c)
    print(f"  screenshots: {', '.join(sorted(p.name for p in SHOTS.glob('*.png')))}")
    if failures:
        print(f"FAILED: {len(failures)} problem(s)")
        for f in failures[:60]:
            print("  !!  ", f)
        return 1
    print("PASSED: zero console errors and zero page errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
