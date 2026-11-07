"""Record the 45-60 s walkthrough of the web dashboard as docs/screenshots/tour.gif and tour.mp4.

Serves docs/ on a free localhost port, drives Chromium (Playwright, 1280 x 720, video recording) through the
storyline: executive summary, the data date stepped through the last four updates so the float erosion is visible,
then the critical path, readiness, recovery, schedule quality (check D07 opened) and reconciliation tabs. A caption
bar names each step; captions are written from dashboard.json, so they always match the numbers on screen.
The video is converted with the ffmpeg binary bundled in imageio-ffmpeg (no separate install).

Usage:  .venv\\Scripts\\python.exe scripts\\record_tour.py [--fps 8] [--width 960]
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import json
import pathlib
import shutil
import subprocess
import sys
import threading
import time

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "screenshots"
TMP = ROOT / "output" / "tmp" / "tour"
W, H = 1280, 720
MAX_GIF = 8 * 1024 * 1024

CSS = """
#tour-cap { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 99999;
  max-width: 1120px; padding: 10px 18px; border-radius: 8px; background: rgba(15, 23, 42, .88); color: #fff;
  font: 600 17px/1.35 "Segoe UI", system-ui, sans-serif; box-shadow: 0 6px 24px rgba(0,0,0,.25);
  transition: opacity .25s; pointer-events: none; }
#tour-cap .k { color: #5eead4; margin-right: 8px; }
.tour-hl { outline: 3px solid #f59e0b !important; outline-offset: 3px; border-radius: 4px; }
"""


def fdate(iso: str) -> str:
    return dt.date.fromisoformat(iso[:10]).strftime("%d-%b-%Y")


def signed(n) -> str:
    n = round(float(n))
    return ("+" if n > 0 else "−" if n < 0 else "±") + str(abs(n))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(DOCS)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


def captions(data: dict) -> dict:
    meta, trends = data["meta"], {t["data_date"]: t for t in data["trends"]["summary"]}
    latest = meta["latest"]
    s = data["snapshots"][latest]["summary"]
    rec = next((x for x in data["scenarios"] if x.get("recommended")), None)
    dq = next((c for c in data["snapshots"][latest]["dcma"] if c["check_id"] == "D07"), {})
    cap = {"exec": (f"Executive summary · {fdate(latest)}", f"Day 1 forecast {fdate(s['day1_forecast'])}, "
                    f"{signed(s['day1_tf_d'])} wd of float; two decisions recover it")}
    for d in [m["data_date"] for m in meta["snapshots"]][-4:]:
        t = trends.get(d, {})
        cap[d] = (f"Data date {fdate(d)}", f"Day 1 total float {signed(t.get('day1_tf_d', 0))} wd · "
                  f"baseline {t.get('baseline', '')}")
    cap["cp"] = ("Critical path", f"{s['longest_path_count']} activities on the longest path to Day 1; "
                 f"{s['critical_count']} critical, {s['near_critical_count']} near-critical")
    cap["if"] = ("Interfaces & readiness", "Construction complete is not ready to operate: the gap per asset")
    opts = " + ".join(o.strip() for o in str(rec["options"]).split(",")) if rec else ""
    cap["risk"] = ("Risks, decisions & recovery", (f"Options rescheduled by the CPM engine; {opts} "
                                                  f"recommended ({signed(rec['day1_tf_d'])} wd)") if rec else
                   "Recovery options rescheduled by the CPM engine")
    cap["dq"] = ("Schedule quality", f"DCMA 14 + update discipline; D07 negative float: "
                 f"{dq.get('count', 0)} activities, with owners")
    cap["recon"] = ("Reconciliation", f"{s['controls_passed']} of {s['controls_total']} controls: "
                    "source XER = model = dashboard")
    return cap


def record(url: str, cap: dict, data: dict) -> tuple[pathlib.Path, float]:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    dates = [m["data_date"] for m in data["meta"]["snapshots"]]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, color_scheme="light",
                                  record_video_dir=str(TMP), record_video_size={"width": W, "height": H})
        t0 = time.monotonic()
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("window.__DOP_READY === true", timeout=30000)
        page.add_style_tag(content=CSS)
        page.evaluate("() => { const d = document.createElement('div'); d.id = 'tour-cap'; document.body.appendChild(d); }")

        def say(key):
            k, txt = cap[key]
            page.evaluate("([k, t]) => { const d = document.getElementById('tour-cap'); "
                          "d.innerHTML = '<span class=\"k\"></span>'; d.firstChild.textContent = k; "
                          "d.appendChild(document.createTextNode(t)); }", [k + " ·", txt])

        def highlight(sel):
            page.evaluate("s => { const e = document.querySelector(s); if (e) { e.classList.add('tour-hl'); "
                          "setTimeout(() => e.classList.remove('tour-hl'), 900); } }", sel)
            page.wait_for_timeout(450)

        def tab(t, key, hold=2400, scroll=420):
            # scroll in jumps, not smoothly: an animated scroll changes every pixel of every GIF frame
            highlight(f"#tab-{t}")
            page.click(f"#tab-{t}")
            page.wait_for_function(f"(window.__DOP_RENDERED || '').startsWith('{t}|')", timeout=10000)
            page.evaluate("() => window.scrollTo(0, 0)")
            say(key)
            page.wait_for_timeout(hold)
            if scroll:
                page.evaluate(f"() => window.scrollTo(0, {scroll})")
                page.wait_for_timeout(2600)

        page.select_option("#sel-dd", dates[-1])
        page.evaluate("() => window.scrollTo(0, 0)")
        say("exec")
        start = time.monotonic() - t0                       # trim the blank page load from the video
        page.wait_for_timeout(5000)
        for d in dates[-4:]:                                # S3 -> S6: float erodes, turns negative, recovers partly
            highlight("#sel-dd")
            page.select_option("#sel-dd", d)
            page.wait_for_function(f"(window.__DOP_RENDERED || '').indexOf('|{d}|') > 0", timeout=10000)
            say(d)
            page.wait_for_timeout(2200)
        tab("cp", "cp")
        tab("if", "if")
        tab("risk", "risk", scroll=520)
        tab("dq", "dq", scroll=0)
        row = '#t-dcma tr[data-check="D07"]'
        page.locator(row).scroll_into_view_if_needed()
        highlight(row)
        page.click(row)
        page.wait_for_timeout(1500)
        page.evaluate("() => { const o = document.getElementById('dq-off'); if (o) o.scrollIntoView({block: 'center'}); }")
        page.wait_for_timeout(3600)
        tab("recon", "recon", hold=2800, scroll=380)
        page.wait_for_timeout(1500)
        video = page.video.path()
        ctx.close()
        browser.close()
    return pathlib.Path(video), start


def convert(webm: pathlib.Path, start: float, fps: int, width: int) -> None:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    OUT.mkdir(parents=True, exist_ok=True)
    gif, mp4 = OUT / "tour.gif", OUT / "tour.mp4"
    # flat UI colours need no dithering, and dither noise differs frame to frame, which defeats GIF compression
    for f, wd in ((fps, width), (fps, 880), (max(6, fps - 2), 880), (6, 800), (5, 720)):
        vf = (f"fps={f},scale={wd}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
              f"[s1][p]paletteuse=dither=none:diff_mode=rectangle")
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(webm), "-vf", vf, str(gif)],
                       check=True)
        if gif.stat().st_size <= MAX_GIF:
            break
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(webm), "-vf", f"scale={W}:-2",
                    "-c:v", "libx264", "-crf", "28", "-preset", "slow", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", str(mp4)], check=True)
    print(f"[tour] {gif.relative_to(ROOT)} {gif.stat().st_size / 1e6:.1f} MB · {mp4.relative_to(ROOT)} "
          f"{mp4.stat().st_size / 1e6:.1f} MB")


def duration(path: pathlib.Path) -> float:
    out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--width", type=int, default=960)
    args = ap.parse_args()
    data = json.loads((DOCS / "data" / "dashboard.json").read_text(encoding="utf-8"))
    httpd, url = serve()
    try:
        webm, start = record(url, captions(data), data)
    finally:
        httpd.shutdown()
    convert(webm, start, args.fps, args.width)
    d = duration(OUT / "tour.mp4")
    size = (OUT / "tour.gif").stat().st_size
    print(f"[tour] duration {d:.1f} s; GIF {'within' if size <= MAX_GIF else 'OVER'} the 8 MB limit")
    return 0 if 45 <= d <= 60 and size <= MAX_GIF else 1


if __name__ == "__main__":
    sys.exit(main())
