"""Command line: python -m dop <command>."""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

from .generate import ROOT


def cmd_generate(_args):
    from .generate import generate
    out = generate()
    print(f"[generate] {out['snapshots']} schedules, activities {out['activities']}, "
          f"Day 1 TF (days) {[round(x) for x in out['day1_tf_days']]}")
    return 0


def cmd_pipeline(args):
    from .pipeline.run import run_pipeline
    return run_pipeline(ROOT, near_critical_days=args.near_critical)


def cmd_pptx(args):
    from .pptx_gen import build_pack
    path = build_pack(ROOT, args.data_date, args.pack)
    print(f"[pptx] {path.relative_to(ROOT)}")
    return 0


def cmd_pbip(args):
    from .pbip import DEFAULT_CSV_FOLDER, generate_pbip
    out = generate_pbip(ROOT, out_dir=args.out, csv_folder=args.csv_folder or DEFAULT_CSV_FOLDER)
    where = out["out_dir"]
    try:
        where = where.relative_to(ROOT)
    except ValueError:
        pass
    print(f"[pbip] {where}: {out['tables']} tables ({out['csv_tables']} from CSV), {out['measures']} measures, "
          f"{out['relationships']} relationships, {out['pages']} pages, {out['visuals']} visuals, {out['files']} files")
    return 0


def cmd_rdl(args):
    from .rdl import RDL_NAME, build_rdl
    out = ROOT / "powerbi" / RDL_NAME
    out.write_text(build_rdl(), encoding="utf-8", newline="\n")
    print(f"[rdl] {out.relative_to(ROOT)}")
    return 0


def cmd_run(args):
    t0 = time.perf_counter()
    rc = cmd_generate(args)
    rc = rc or cmd_pipeline(args)
    if rc:
        print("[run] pipeline gate FAILED; packs not produced")
        return rc
    from .pptx_gen import build_pack
    from .pipeline.run import latest_date
    dd = latest_date(ROOT)
    dl = ROOT / "docs" / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    for pack in ("monthly", "fortnightly"):
        p = build_pack(ROOT, dd, pack)
        shutil.copy2(p, dl / p.name)
        print(f"[pptx] {p.relative_to(ROOT)}")
    xl = ROOT / "output" / "xlsx" / f"DOP_controls_{dd}.xlsx"
    if xl.exists():
        shutil.copy2(xl, dl / xl.name)
    print(f"[run] all steps complete in {time.perf_counter() - t0:.1f} s")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dop", description="Destination Opening Programme schedule intelligence")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="build the fictional IMS: XER exports, registers, truth files")
    p = sub.add_parser("pipeline", help="parse XER, build the model, run quality checks and the reconciliation gate, write outputs")
    p.add_argument("--near-critical", type=int, default=10, help="near-critical threshold in working days")
    p = sub.add_parser("pptx", help="build an executive PowerPoint pack")
    p.add_argument("--data-date", required=True)
    p.add_argument("--pack", choices=["monthly", "fortnightly"], default="monthly")
    p = sub.add_parser("pbip", help="generate the Power BI project (PBIP) from the CSV star schema, DAX measures and theme")
    p.add_argument("--out", type=pathlib.Path, default=None, help="output folder (default: powerbi)")
    p.add_argument("--csv-folder", default=None,
                   help="default value of the CsvFolder parameter: a URL (read with Web.Contents) or a local folder "
                        "(read with File.Contents). Default: the repository's output/csv on GitHub")
    sub.add_parser("rdl", help="generate the paginated report (RDL): the reconciliation certificate")
    p = sub.add_parser("run", help="run everything")
    p.add_argument("--all", action="store_true", required=True)
    p.add_argument("--near-critical", type=int, default=10)
    args = ap.parse_args(argv)
    return {"generate": cmd_generate, "pipeline": cmd_pipeline, "pptx": cmd_pptx, "pbip": cmd_pbip,
            "rdl": cmd_rdl, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
