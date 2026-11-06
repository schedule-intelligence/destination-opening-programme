"""Exporters: star-schema CSVs, the self-describing dashboard JSON and the reconciliation report."""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib

import numpy as np
import pandas as pd

from ..programme import (ASSETS, DAY1_ID, DAY1_TARGET, OWNER_LEADS, OWNERS, PACKAGES, PROGRAMME, WORKSTREAMS)
from .dictionary import as_records
from .narrative import snapshot_narrative
from .quality import CHECKS

ACT_COLS = ["activity_id", "status", "pct_duration", "pct_physical", "orig_dur_d", "rem_dur_d", "actual_start",
            "actual_finish", "start", "finish", "late_start", "late_finish", "total_float_d", "free_float_d",
            "is_critical", "is_near_critical", "is_longest_path", "bl0_start", "bl0_finish", "bl1_start", "bl1_finish",
            "bl_finish", "var_finish_bl0_d", "var_finish_bl1_d", "var_finish_bl_d", "prev_finish", "slip_vs_prev_d",
            "lookback_event", "lookback_achieved", "lookahead_start", "lookahead_finish", "lookahead",
            "planned_pct_bl", "constraint_type", "constraint_date", "dq_flags"]
DIM_ACT_COLS = ["activity_id", "activity_name", "activity_type", "is_milestone", "calendar_id", "wbs_id", "wbs_path",
                "asset_code", "workstream_code", "package_code", "owner_code", "phase", "interface_role",
                "readiness_gate", "first_snapshot_id", "in_bl0", "in_bl1"]


def jv(v):
    """JSON value: dates as YYYY-MM-DD, NaN/NaT -> None, numpy -> python."""
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        return None if pd.isna(v) else v.strftime("%Y-%m-%d")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if math.isnan(v):
            return None
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 1e12 else round(f, 3)
    return v


def recs(df: pd.DataFrame, cols=None) -> list[dict]:
    cols = cols or list(df.columns)
    return [{c: jv(r[c]) for c in cols} for r in df[cols].to_dict("records")]


def table(df: pd.DataFrame, cols) -> dict:
    return {"cols": cols, "rows": [[jv(r[c]) for c in cols] for r in df[cols].to_dict("records")]}


def write_csvs(m: dict, out_dir: pathlib.Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in m.items():
        if name.startswith("_") or not isinstance(df, pd.DataFrame):
            continue
        d = df.copy()
        for c in d.columns:
            if d[c].dtype == object:
                d[c] = [x.strftime("%Y-%m-%d %H:%M") if isinstance(x, dt.datetime) else
                        x.isoformat() if isinstance(x, dt.date) else x for x in d[c]]
        d.to_csv(out_dir / f"{name}.csv", index=False, lineterminator="\n")


def build_dashboard_json(m: dict, run_ts: str, near_critical_days: int) -> dict:
    m["near_critical_days"] = near_critical_days
    ds = m["dim_snapshot"]
    snaps = {}
    fa = m["fact_activity_snapshot"]
    quality = m["_quality"]
    for s in ds.itertuples():
        sid = s.snapshot_id
        f = fa[fa.snapshot_id == sid]
        rel = m["fact_relationship"][m["fact_relationship"].snapshot_id == sid]
        summ = m["fact_snapshot_summary"].set_index("snapshot_id").loc[sid].to_dict()
        q = quality[sid]
        snaps[s.data_date.isoformat()] = {
            "summary": {k: jv(v) for k, v in summ.items()},
            "acts": table(f, ACT_COLS),
            "rels": {"cols": ["pred", "succ", "type", "lag_d", "driving"],
                     "rows": [[r.pred_id, r.succ_id, r.rel_type, jv(r.lag_d), bool(r.is_driving)] for r in rel.itertuples()]},
            "milestones": recs(m["fact_milestone_trend"][m["fact_milestone_trend"].snapshot_id == sid].drop(columns="snapshot_id")),
            "interfaces": recs(m["fact_interface"][m["fact_interface"].snapshot_id == sid].drop(columns="snapshot_id")),
            "readiness": recs(m["fact_readiness"][m["fact_readiness"].snapshot_id == sid].drop(columns="snapshot_id")),
            "dcma": [{k: jv(v) if k != "offenders" else v for k, v in c.items()} for c in q["checks"]],
            "dq": {"score": q["dq_score"], "rating": q["dq_rating"]},
            "owner_scorecard": [{k: jv(v) for k, v in o.items()} for o in q["owner_scorecard"]],
            "risks": recs(m["fact_risk"][m["fact_risk"].snapshot_id == sid].drop(columns="snapshot_id")),
            "narrative": snapshot_narrative(m, sid),
        }
    latest = ds[ds.is_latest].iloc[0]
    return {
        "schema_version": "1.0",
        "meta": {
            "programme": PROGRAMME, "generated_utc": run_ts, "synthetic": True,
            "disclaimer": "Fictional programme and data. Schedules are produced by a custom CPM engine that follows "
                          "Primavera P6 conventions and are exported in P6 XER format; no Primavera P6 licence was used.",
            "engine": "DOP CPM engine 1.0 (P6 conventions: retained logic, lags on successor calendar, TF = LF - EF)",
            "day1_id": DAY1_ID, "day1_target": DAY1_TARGET.isoformat(), "near_critical_days": near_critical_days,
            "latest": latest.data_date.isoformat(),
            "snapshots": recs(ds.drop(columns=["run_timestamp"])),
            "assets": ASSETS, "workstreams": WORKSTREAMS, "packages": PACKAGES,
            "owners": {k: {"name": v, "role": OWNER_LEADS[k]} for k, v in OWNERS.items()} |
                      {"UNASSIGNED": {"name": "Owner code missing", "role": "Programme Controls Manager"}},
            "calendars": recs(m["dim_calendar"]),
            "checks": [dict(check_id=c[0], check_name=c[1], group=c[2], kind=c[3], threshold=c[4], weight=c[5],
                            definition=c[6], playbook=c[7]) for c in CHECKS],
        },
        "definitions": as_records(),
        "activities": table(m["dim_activity"], DIM_ACT_COLS),
        "wbs": recs(m["dim_wbs"], ["wbs_id", "wbs_code", "wbs_name", "level", "parent_wbs_id", "path"]),
        "snapshots": snaps,
        "trends": {"summary": recs(m["fact_snapshot_summary"]), "s_curve": recs(m["fact_s_curve"]),
                   "milestones": recs(m["fact_milestone_trend"])},
        "decisions": recs(m["fact_decision"]), "changes": recs(m["fact_change"]),
        "scenarios": recs(m["fact_scenario"]),
        "lineage": [
            {"step": "P6 XER export", "detail": "DOP_UPD_<date>.xer + DOP_BL0/BL1.xer (data/xer)"},
            {"step": "Generic XER parser", "detail": "dop/xer.py: every %T table, typed by P6 field convention"},
            {"step": "CPM re-schedule + quality", "detail": "dop/cpm.py, dop/pipeline/quality.py: DCMA 14 + update discipline"},
            {"step": "Star schema", "detail": "dop/pipeline/model.py -> output/csv (Power BI)"},
            {"step": "Reconciliation gate", "detail": "dop/pipeline/reconcile.py: XER = model = dashboard JSON, else exit 1"},
            {"step": "Outputs", "detail": "docs/data/dashboard.json, output/xlsx, output/pptx"},
        ],
        "governance_docs": [
            {"title": "Design", "path": "DESIGN.md"},
            {"title": "Design decisions", "path": "DESIGN_DECISIONS.md"},
            {"title": "Scheduling framework", "path": "governance/SCHEDULING_FRAMEWORK.md"},
            {"title": "Planning & reporting calendar", "path": "governance/PLANNING_REPORTING_CALENDAR.md"},
            {"title": "RACI", "path": "governance/RACI.md"},
            {"title": "Reporting standards", "path": "governance/REPORTING_STANDARDS.md"},
            {"title": "Schedule owner playbook", "path": "governance/SCHEDULE_OWNER_PLAYBOOK.md"},
            {"title": "Data dictionary", "path": "DATA_DICTIONARY.md"},
            {"title": "Power BI build guide", "path": "POWERBI.md"},
        ],
    }


def write_json(js: dict, path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(js, separators=(",", ":"), ensure_ascii=False), encoding="utf-8", newline="\n")


def write_recon_report(controls: list[dict], sch, path: pathlib.Path, dq: float):
    ok = all(c["passed"] for c in controls)
    lines = [f"# Reconciliation report: {sch.data_date.date().isoformat()}", "",
             f"Source: `{sch.name}` (SHA-256 `{sch.sha256[:16]}...`)  ",
             f"Result: **{'PASS' if ok else 'FAIL'}**, {sum(c['passed'] for c in controls)}/{len(controls)} controls  ",
             f"DQ score: {dq}", "",
             "| Control | Source (XER) | Model (CSV) | Dashboard (JSON) | Delta | Result |", "|---|---|---|---|---|---|"]
    for c in controls:
        sv = str(c["source_value"])
        if c["control_id"] == "R15":
            sv = sv[:16] + "..."
        mv = str(c["model_value"])[:19] + ("..." if c["control_id"] == "R15" else "")
        dv = str(c["dashboard_value"])[:19] + ("..." if c["control_id"] == "R15" else "")
        lines.append(f"| {c['control_id']} {c['control']} | {sv} | {mv} | {dv} | {c['delta'] if c['delta'] is not None else ''} | "
                     f"{'pass' if c['passed'] else 'FAIL'} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
