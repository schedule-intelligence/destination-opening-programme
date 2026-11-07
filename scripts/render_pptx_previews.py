"""Render the PowerPoint packs to PDF and PNG for visual review, and refresh the README slide previews.

Converts both packs for the latest data date with LibreOffice (headless), rasterises every page with PyMuPDF into
output/tmp/render/ (git-ignored, for review), and copies the preview slides used in the README to
docs/screenshots/pptx_*.png.

Usage:  .venv\\Scripts\\python.exe scripts\\render_pptx_previews.py [--width 1600]
LibreOffice is found via the SOFFICE environment variable or the usual install paths.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

import pymupdf as fitz

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "tmp" / "render"
SHOTS = ROOT / "docs" / "screenshots"
PREVIEWS = {"monthly": [1, 2, 7, 8, 11, 13], "fortnightly": [1]}
PREFIX = {"monthly": "pptx_monthly", "fortnightly": "pptx_flash"}
CANDIDATES = [r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
              "/usr/bin/soffice", "/usr/local/bin/soffice",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"]


def find_soffice() -> str:
    env = os.environ.get("SOFFICE")
    for c in ([env] if env else []) + CANDIDATES:
        if c and pathlib.Path(c).exists():
            return c
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    sys.exit("LibreOffice (soffice) not found: install it or set SOFFICE")


def latest_date() -> str:
    packs = sorted((ROOT / "output" / "pptx").glob("DOP_monthly_pack_*.pptx"))
    if not packs:
        sys.exit("no packs in output/pptx: run python -m dop run --all first")
    return packs[-1].stem.rsplit("_", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1600, help="PNG width in pixels for the review images")
    ap.add_argument("--preview-width", type=int, default=1280, help="PNG width for the README previews")
    args = ap.parse_args()
    soffice, dd = find_soffice(), latest_date()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"monthly": ROOT / "output" / "pptx" / f"DOP_monthly_pack_{dd}.pptx",
             "fortnightly": ROOT / "output" / "pptx" / f"DOP_fortnightly_flash_{dd}.pptx"}
    profile = (OUT / "lo_profile").resolve().as_uri()  # private profile: no first-run dialogs, no lock clash
    for pack, src in files.items():
        subprocess.run([soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore", "--nolockcheck",
                        "--convert-to", "pdf", "--outdir", str(OUT), str(src)],
                       check=True, capture_output=True, timeout=300)
        pdf = OUT / (src.stem + ".pdf")
        with fitz.open(pdf) as doc:
            for i, page in enumerate(doc, 1):
                zoom = args.width / page.rect.width
                page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(OUT / f"{PREFIX[pack]}_{i:02d}.png")
                if i in PREVIEWS[pack]:
                    pz = args.preview_width / page.rect.width
                    page.get_pixmap(matrix=fitz.Matrix(pz, pz)).save(SHOTS / f"{PREFIX[pack]}_{i:02d}.png")
            print(f"[render] {src.name}: {len(doc)} pages -> {OUT.relative_to(ROOT)}")
    print(f"[render] previews -> {SHOTS.relative_to(ROOT)}: "
          + ", ".join(f"{PREFIX[p]}_{i:02d}.png" for p, ii in PREVIEWS.items() for i in ii))
    return 0


if __name__ == "__main__":
    sys.exit(main())
