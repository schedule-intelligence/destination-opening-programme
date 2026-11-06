"""Pipeline runner: parse -> model -> quality -> JSON -> reconciliation gate -> CSV / XLSX / reports."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time

import pandas as pd

from .dictionary import write_markdown
from .excel import write_workbook
from .export import build_dashboard_json, write_csvs, write_json, write_recon_report
from .load import load_all
from .model import build_model, snap_id
from .reconcile import reconcile

INTEGRITY_CHECKS = ("D09", "U02", "U03", "U04")


def latest_date(root: pathlib.Path) -> str:
    files = sorted((root / "data" / "xer").glob("DOP_UPD_*.xer"))
    return files[-1].stem.split("_")[-1]


def run_pipeline(root: pathlib.Path, near_critical_days: int = 10, json_path: pathlib.Path | None = None,
                 quiet: bool = False) -> int:
    t0 = time.perf_counter()
    say = (lambda *a: None) if quiet else print
    run_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bls, ups = load_all(root)
    say(f"[pipeline] parsed {len(ups)} updates + {len(bls)} baselines")
    m = build_model(root, bls, ups, run_ts, near_critical_days)
    js = build_dashboard_json(m, run_ts, near_critical_days)
    jpath = json_path or root / "docs" / "data" / "dashboard.json"
    staging = jpath.with_name(jpath.stem + ".staging.json")
    write_json(js, staging)
    on_disk = json.loads(staging.read_text(encoding="utf-8"))   # reconcile against what was actually written
    bl_ids = {str(s.project["proj_id"]): name for name, s in bls.items()}
    controls = []
    for s in ups:
        sid = snap_id(s.data_date)
        q = m["_quality"][sid]
        flagged = {i for c in INTEGRITY_CHECKS for i in q["offenders"][c]}
        controls += reconcile(s, m, on_disk, bl_ids, flagged)
    m["fact_reconciliation"] = pd.DataFrame(controls)
    failed = [c for c in controls if not c["passed"]]
    if failed:  # the gate: nothing downstream (CSV, XLSX, reports, dictionary) is published from a failed run
        for c in failed[:20]:
            print(f"  FAIL {c['snapshot_id']} {c['control_id']}: source={c['source_value']} model={c['model_value']} "
                  f"dashboard={c['dashboard_value']}")
        print(f"[pipeline] RECONCILIATION GATE FAILED ({len(failed)} controls); nothing published, "
              f"previous outputs left unchanged")
        staging.unlink(missing_ok=True)
        return 1
    for s in ups:
        sid = snap_id(s.data_date)
        cs = [c for c in controls if c["snapshot_id"] == sid]
        d = s.data_date.date().isoformat()
        js["snapshots"][d]["reconciliation"] = [{k: v for k, v in c.items() if k != "snapshot_id"} for c in cs]
        js["snapshots"][d]["summary"]["reconciled"] = all(c["passed"] for c in cs)
        js["snapshots"][d]["summary"]["controls_passed"] = sum(c["passed"] for c in cs)
        js["snapshots"][d]["summary"]["controls_total"] = len(cs)
        write_recon_report(cs, s, root / "output" / "reports" / f"reconciliation_{d}.md", m["_quality"][sid]["dq_score"])
        write_workbook(m, sid, cs, root / "output" / "xlsx" / f"DOP_controls_{d}.xlsx")
    write_json(js, jpath)
    staging.unlink(missing_ok=True)
    write_csvs(m, root / "output" / "csv")
    write_markdown(root / "DATA_DICTIONARY.md")
    say(f"[pipeline] reconciliation: {len(controls)}/{len(controls)} controls pass across {len(ups)} data dates")
    for s in m["fact_snapshot_summary"].itertuples():
        say(f"  {s.label} {s.data_date}  Day 1 {s.day1_forecast:%d-%b-%Y}  TF {s.day1_tf_d:+.0f} d  "
            f"DQ {s.dq_score:.0f} ({s.dq_rating})  critical {s.critical_count}")
    say(f"[pipeline] done in {time.perf_counter() - t0:.1f} s")
    return 0
