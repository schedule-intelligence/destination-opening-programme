"""Reconciliation controls: the proof of a single trusted view.

For each data date every control is computed three independent ways:
* source    - from the raw XER string tables (no typing, no pandas model),
* model     - from the star-schema fact tables,
* dashboard - from docs/data/dashboard.json as written to disk.
All three must agree. The pipeline exits non-zero when any control fails (it is a gate, not a report)."""
from __future__ import annotations

import hashlib
from collections import Counter

from ..calendars import to_time
from ..cpm import schedule
from ..programme import DAY1_ID
from ..xer_model import network_from_frames
from .model import KEY_MILESTONES, snap_id

STATUSES = ["TK_Complete", "TK_Active", "TK_NotStart"]


def _raw_level(raw) -> dict:
    """task_id -> (level1, level2) from PROJWBS strings."""
    w = {r["wbs_id"]: r for r in raw["PROJWBS"]}

    def chain(wid):
        out = []
        while wid and wid in w:
            out.append(w[wid])
            wid = w[wid]["parent_wbs_id"]
        return list(reversed(out))[1:]
    lv = {}
    for t in raw["TASK"]:
        c = chain(t["wbs_id"])
        lv[t["task_code"]] = (c[0]["wbs_short_name"], c[1]["wbs_short_name"])
    return lv


def _wpc(rows):
    num = den = 0.0
    for r in rows:
        if r["task_type"] != "TT_Task" or not float(r["target_drtn_hr_cnt"] or 0):
            continue
        w = float(r["target_drtn_hr_cnt"])
        p = 100.0 if r["status_code"] == "TK_Complete" else 0.0 if r["status_code"] == "TK_NotStart" else \
            100.0 * (w - float(r["remain_drtn_hr_cnt"])) / w
        num, den = num + w * p, den + w
    return round(num / den, 2)


def source_values(sch, bl_ids: dict[str, str]) -> dict:
    raw = sch.raw
    T = raw["TASK"]
    lv = _raw_level(raw)
    by = {t["task_code"]: t for t in T}
    fin = lambda t: (t["act_end_date"] if t["status_code"] == "TK_Complete" else t["early_end_date"])[:10]
    v = {"R01": len(T)}
    c = Counter(t["status_code"] for t in T)
    for s in STATUSES:
        v[f"R02.{s}"] = c.get(s, 0)
    for a, n in Counter(lv[t["task_code"]][0] for t in T).items():
        v[f"R03.{a}"] = n
    for w, n in Counter(lv[t["task_code"]][1] for t in T).items():
        v[f"R04.{w}"] = n
    v["R05"] = len(raw["TASKPRED"])
    v["R06"] = sum(t["task_type"] in ("TT_Mile", "TT_FinMile") for t in T)
    v["R07"] = by[DAY1_ID]["early_end_date"][:10]
    v["R08"] = by[DAY1_ID]["late_end_date"][:10]
    for m in KEY_MILESTONES:
        v[f"R09.{m}"] = fin(by[m])
    v["R10"] = round(sum(float(t["remain_drtn_hr_cnt"] or 0) for t in T), 1)
    v["R11"] = _wpc(T)
    v["R12"] = sum(1 for t in T if t["status_code"] != "TK_Complete" and t["task_type"] != "TT_LOE"
                   and t["total_float_hr_cnt"] != "" and float(t["total_float_hr_cnt"]) <= 0)
    v["R13"] = raw["PROJECT"][0]["last_recalc_date"][:10]
    v["R14"] = bl_ids.get(raw["PROJECT"][0]["sum_base_proj_id"], "?")
    v["R15"] = hashlib.sha256(sch.path.read_bytes()).hexdigest()
    return v


def model_values(m: dict, sid: int) -> dict:
    fa = m["fact_activity_snapshot"]
    f = fa[fa.snapshot_id == sid].merge(m["dim_activity"], on="activity_id")
    v = {"R01": len(f)}
    for s in STATUSES:
        v[f"R02.{s}"] = int((f.status == s).sum())
    for a, n in f.asset_code.value_counts().items():
        v[f"R03.{a}"] = int(n)
    for w, n in f.workstream_code.value_counts().items():
        v[f"R04.{w}"] = int(n)
    fr = m["fact_relationship"]
    v["R05"] = int((fr.snapshot_id == sid).sum())
    v["R06"] = int(f.is_milestone.sum())
    d1 = f.set_index("activity_id")
    v["R07"] = d1.at[DAY1_ID, "finish"].strftime("%Y-%m-%d")
    v["R08"] = d1.at[DAY1_ID, "late_finish"].strftime("%Y-%m-%d")
    for k in KEY_MILESTONES:
        v[f"R09.{k}"] = d1.at[k, "finish"].strftime("%Y-%m-%d")
    v["R10"] = round(float((f.rem_dur_d * 8).sum()), 1)
    t = f[(f.activity_type == "TT_Task") & (f.orig_dur_d > 0)]
    v["R11"] = round(float((t.orig_dur_d * _pct(t)).sum() / t.orig_dur_d.sum()), 2)
    inc = f[(f.status != "TK_Complete") & (f.activity_type != "TT_LOE")]
    v["R12"] = int(inc.is_critical.sum())
    ds = m["dim_snapshot"].set_index("snapshot_id").loc[sid]
    v["R13"] = ds.data_date.isoformat()
    v["R14"] = ds.baseline_in_force
    v["R15"] = ds.sha256
    return v


def _pct(t):
    import numpy as np
    w = t.orig_dur_d
    return np.where(t.status == "TK_Complete", 100.0, np.where(t.status == "TK_NotStart", 0.0,
                                                                  100.0 * (w - t.rem_dur_d) / w))


def dashboard_values(js: dict, date: str) -> dict:
    snap = js["snapshots"][date]
    cols = snap["acts"]["cols"]
    rows = [dict(zip(cols, r)) for r in snap["acts"]["rows"]]
    acols = js["activities"]["cols"]
    dim = {r[acols.index("activity_id")]: dict(zip(acols, r)) for r in js["activities"]["rows"]}
    v = {"R01": len(rows)}
    c = Counter(r["status"] for r in rows)
    for s in STATUSES:
        v[f"R02.{s}"] = c.get(s, 0)
    for a, n in Counter(dim[r["activity_id"]]["asset_code"] for r in rows).items():
        v[f"R03.{a}"] = n
    for w, n in Counter(dim[r["activity_id"]]["workstream_code"] for r in rows).items():
        v[f"R04.{w}"] = n
    v["R05"] = len(snap["rels"]["rows"])
    v["R06"] = sum(1 for r in rows if dim[r["activity_id"]]["is_milestone"])
    by = {r["activity_id"]: r for r in rows}
    v["R07"] = by[DAY1_ID]["finish"]
    v["R08"] = by[DAY1_ID]["late_finish"]
    for k in KEY_MILESTONES:
        v[f"R09.{k}"] = by[k]["finish"]
    v["R10"] = round(sum(r["rem_dur_d"] * 8 for r in rows), 1)
    num = den = 0.0
    for r in rows:
        if dim[r["activity_id"]]["activity_type"] != "TT_Task" or not r["orig_dur_d"]:
            continue
        w = r["orig_dur_d"]
        p = 100.0 if r["status"] == "TK_Complete" else 0.0 if r["status"] == "TK_NotStart" else \
            100.0 * (w - r["rem_dur_d"]) / w
        num, den = num + w * p, den + w
    v["R11"] = round(num / den, 2)
    v["R12"] = sum(1 for r in rows if r["status"] != "TK_Complete" and dim[r["activity_id"]]["activity_type"] != "TT_LOE"
                   and r["is_critical"])
    meta = next(s for s in js["meta"]["snapshots"] if s["data_date"] == date)
    v["R13"] = meta["data_date"]
    v["R14"] = meta["baseline_in_force"]
    v["R15"] = meta["sha256"]
    return v


NAMES = {"R01": "Activity count", "R02": "Activities by status", "R03": "Activities by asset",
         "R04": "Activities by workstream", "R05": "Relationship count", "R06": "Milestone count",
         "R07": "Day 1 early finish", "R08": "Day 1 late finish", "R09": "Key milestone finish",
         "R10": "Sum of remaining duration (h)", "R11": "Weighted % complete", "R12": "Critical activity count",
         "R13": "Data date", "R14": "Baseline reference", "R15": "Source file SHA-256",
         "R16": "Engine re-schedule matches P6 dates"}


def engine_reschedule_control(sch, flagged: set) -> dict:
    """R16: re-run the CPM engine on the parsed XER; every activity not flagged by a data-integrity check must
    reproduce the exported early finish, remaining start, late finish, total float and longest-path flag."""
    net = network_from_frames(sch.fr)
    s = schedule(net)
    checked = matched = 0
    for r in sch.fr["TASK"].itertuples():
        if r.task_code in flagged:
            continue
        checked += 1
        e = s.acts[r.task_code]
        tf = None if r.total_float_hr_cnt is None else int(r.total_float_hr_cnt)
        ok = to_time(r.early_end_date) == e.ef and tf == e.tf and (r.driving_path_flag == "Y") == e.longest_path
        if r.status_code != "TK_Complete":
            ok = ok and to_time(r.restart_date) == e.rs and to_time(r.late_end_date) == e.lf
        matched += ok
    return {"checked": checked, "matched": matched, "excluded": sorted(flagged)}


def reconcile(sch, m: dict, js: dict, bl_ids: dict, flagged: set) -> list[dict]:
    sid = snap_id(sch.data_date)
    date = sch.data_date.date().isoformat()
    src, mod, dash = source_values(sch, bl_ids), model_values(m, sid), dashboard_values(js, date)
    out = []
    for key in sorted(set(src) | set(mod) | set(dash), key=lambda k: (k.split(".")[0], k)):
        cid = key.split(".")[0]
        sv, mv, dv = src.get(key), mod.get(key), dash.get(key)
        if all(isinstance(x, (int, float)) for x in (sv, mv, dv)):
            delta = round(max(abs(sv - mv), abs(sv - dv)), 4)
            ok = delta <= 0.01
        else:
            delta = None if sv == mv == dv else "mismatch"
            ok = sv == mv == dv and sv is not None
        label = NAMES[cid] + (f" - {key.split('.', 1)[1]}" if "." in key else "")
        out.append(dict(snapshot_id=sid, control_id=key, control=label, source_value=sv, model_value=mv,
                        dashboard_value=dv, delta=delta, passed=bool(ok)))
    r16 = engine_reschedule_control(sch, flagged)
    out.append(dict(snapshot_id=sid, control_id="R16", control=NAMES["R16"] +
                    (f" (excl. {len(r16['excluded'])} integrity-flagged)" if r16["excluded"] else ""),
                    source_value=r16["checked"], model_value=r16["matched"], dashboard_value=r16["matched"],
                    delta=r16["checked"] - r16["matched"], passed=r16["checked"] == r16["matched"]))
    return out
