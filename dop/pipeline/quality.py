"""Schedule quality: DCMA 14-point assessment plus update-discipline checks, DQ score and owner scorecard.

Computed only from parsed XER content (independent of the generator), so tests can compare the results
with the generator's truth files.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import pandas as pd

from ..cpm import HARD_CONSTRAINTS, critical_path_test, schedule
from ..xer_model import DEFAULT_FINISH_CODE, network_from_frames

H = 8
PROJECT_START = "PRG-D1R-M000"

# id, name, group, kind, threshold, weight, definition, owner fix (playbook anchor)
CHECKS = [
    ("D01", "Missing logic", "DCMA", "pct_max", 5.0, 10, "Incomplete tasks/milestones without a predecessor or successor (project start and Day 1 excluded)", "missing-logic"),
    ("D02", "Leads (negative lags)", "DCMA", "count_max", 0, 6, "Relationships with a negative lag to an incomplete successor", "leads"),
    ("D03", "Lags", "DCMA", "pct_max", 5.0, 4, "Share of relationships (incomplete successor) with a positive lag", "lags"),
    ("D04", "Relationship types (FS)", "DCMA", "pct_min", 90.0, 4, "Share of relationships that are Finish-to-Start", "relationship-types"),
    ("D05", "Hard constraints", "DCMA", "pct_max", 5.0, 8, "Share of incomplete activities with MSO/MFO/SNLT/FNLT/Start On/Finish On", "hard-constraints"),
    ("D06", "High float (> 44 d)", "DCMA", "pct_max", 5.0, 5, "Share of incomplete activities with total float above 44 working days", "high-float"),
    ("D07", "Negative float", "DCMA", "count_max", 0, 10, "Incomplete activities with total float below zero", "negative-float"),
    ("D08", "High duration (> 44 d)", "DCMA", "pct_max", 5.0, 5, "Share of incomplete tasks with original duration above 44 working days", "high-duration"),
    ("D09", "Invalid dates", "DCMA", "count_max", 0, 10, "Actual dates after the data date, or forecast dates before it", "invalid-dates"),
    ("D10", "Resources", "DCMA", "na", None, 0, "Not applicable: the IMS is not resource-loaded (time-based integration schedule)", "resources"),
    ("D11", "Missed tasks", "DCMA", "pct_max", 5.0, 5, "Share of tasks due by the data date (baseline finish) that finished late or are not finished", "missed-tasks"),
    ("D12", "Critical path test", "DCMA", "pass", None, 6, "Adding 600 working days to a longest-path task moves Day 1 by the same amount", "critical-path-test"),
    ("D13", "CPLI", "DCMA", "ratio_min", 0.95, 5, "Critical Path Length Index = (critical path length + Day 1 total float) / critical path length", "cpli"),
    ("D14", "BEI", "DCMA", "ratio_min", 0.95, 5, "Baseline Execution Index = tasks completed / tasks due by the data date", "bei"),
    ("U01", "Out-of-sequence progress", "Update discipline", "count_max", 0, 4, "Started although an FS predecessor is not complete (or an SS predecessor not started)", "out-of-sequence"),
    ("U02", "Actuals after data date", "Update discipline", "count_max", 0, 0, "Actual start/finish later than the data date (also counted in D09)", "invalid-dates"),
    ("U03", "Remaining duration on completed", "Update discipline", "count_max", 0, 2, "Completed activities that still carry remaining duration", "remaining-on-complete"),
    ("U04", "Progress without actual start", "Update discipline", "count_max", 0, 2, "Physical % or consumed duration recorded with no actual start", "progress-without-start"),
    ("U05", "Missing activity codes", "Update discipline", "count_max", 0, 2, "Activities without Workstream, Asset or Owner code", "missing-codes"),
    ("U06", "Duplicate names", "Update discipline", "count_max", 0, 1, "Activities sharing a name within the same asset (WBS level 1)", "duplicate-names"),
    ("U07", "LOE driving work / critical", "Update discipline", "count_max", 0, 1, "Level-of-effort activities with successors, on the longest path or with TF <= 0", "loe"),
    ("U08", "Data date matches cut-off", "Update discipline", "pass", None, 1, "Project data date equals the cut-off in the reporting calendar", "data-date"),
    ("U09", "Stale in-progress", "Update discipline", "count_max", 0, 2, "In progress in both periods with no change in remaining duration or % complete", "stale"),
    ("U10", "SF relationships", "Update discipline", "count_max", 0, 1, "Start-to-Finish relationships (incomplete successor)", "relationship-types"),
    ("U11", "Missing from baseline", "Update discipline", "count_max", 0, 1, "Activities not present in the baseline in force", "baseline"),
    ("U12", "Long lags (> 20 d)", "Update discipline", "count_max", 0, 0, "Relationships with lag above 20 working days (informational)", "lags"),
]
CHECK_INDEX = {c[0]: c for c in CHECKS}
BANDS = [(85, "Good"), (70, "Fair"), (0, "Poor")]
ACTIVITY_CHECKS = ["D01", "D05", "D06", "D07", "D08", "D09", "D11", "U01", "U03", "U04", "U05", "U06", "U07",
                   "U09", "U11"]


def rating(score: float) -> str:
    return next(b for t, b in BANDS if score >= t)


def check_score(kind, value, threshold, weight, passed) -> float:
    if kind == "na" or weight == 0:
        return 0.0
    if passed:
        return float(weight)
    if kind == "pct_max":
        return weight * max(0.0, 1 - (value - threshold) / threshold)
    if kind == "count_max":
        return weight * max(0.0, 1 - value / 5)
    if kind == "pct_min":
        return weight * max(0.0, 1 - (threshold - value) / 10)
    if kind == "ratio_min":
        return weight * max(0.0, 1 - (threshold - value) / 0.10)
    return 0.0


def assess(sch, prev_sch, bl_sch, expected_data_date: dt.date | None, finish_code: str = DEFAULT_FINISH_CODE) -> dict:
    a = sch.act.set_index("task_code")
    dd = sch.data_date
    inc = a[(a.status_code != "TK_Complete") & (a.task_type != "TT_LOE")]
    preds, succs = defaultdict(list), defaultdict(list)
    for r in sch.rel.itertuples():
        preds[r.succ].append((r.pred, r.type, r.lag_h))
        succs[r.pred].append((r.succ, r.type, r.lag_h))
    status = a["status_code"].to_dict()
    rel_inc = sch.rel[[status[s] != "TK_Complete" for s in sch.rel.succ]]
    rk = lambda r: f"{r.pred}->{r.succ}:{r.type}"
    off: dict[str, list] = {}
    off["D01"] = sorted(i for i in inc.index if i not in (finish_code, PROJECT_START) and (not preds[i] or not succs[i]))
    off["D02"] = sorted(rk(r) for r in rel_inc.itertuples() if r.lag_h < 0)
    off["D03"] = sorted(rk(r) for r in rel_inc.itertuples() if r.lag_h > 0)
    off["D04"] = sorted(rk(r) for r in rel_inc.itertuples() if r.type != "FS")
    off["D05"] = sorted(inc.index[inc.cstr_type.isin(HARD_CONSTRAINTS)])
    tf = inc["total_float_hr_cnt"]
    off["D06"] = sorted(i for i, v in tf.items() if v is not None and v > 44 * H)
    off["D07"] = sorted(i for i, v in tf.items() if v is not None and v < 0)
    off["D08"] = sorted(i for i, r in inc.iterrows() if r.task_type == "TT_Task" and r.target_drtn_hr_cnt > 44 * H)
    bad = set()
    for i, r in a.iterrows():
        if (r.act_start_date is not None and r.act_start_date > dd) or (r.act_end_date is not None and r.act_end_date > dd):
            bad.add(i)
        if r.status_code != "TK_Complete":
            if r.status_code == "TK_NotStart" and r.early_start_date is not None and r.early_start_date < dd:
                bad.add(i)
            if r.early_end_date is not None and r.early_end_date < dd:
                bad.add(i)
    off["D09"] = sorted(bad)
    off["D10"] = []
    bl = bl_sch.act.set_index("task_code") if bl_sch is not None else None
    bl_fin = {}
    if bl is not None:
        for i, r in bl.iterrows():
            bl_fin[i] = r.act_end_date if r.status_code == "TK_Complete" else r.early_end_date
    due = [i for i in a.index if a.at[i, "task_type"] != "TT_LOE" and i in bl_fin and bl_fin[i] <= dd]
    off["D11"] = sorted(i for i in due if a.at[i, "status_code"] != "TK_Complete" or a.at[i, "act_end_date"] > bl_fin[i])
    completed = [i for i in a.index if a.at[i, "task_type"] != "TT_LOE" and a.at[i, "status_code"] == "TK_Complete"]
    # engine-based checks on the parsed XER
    net = network_from_frames(sch.fr, finish_code)
    eng = schedule(net)
    cp = critical_path_test(net, eng)
    off["D12"] = [] if cp["pass"] else [cp["activity"] or "n/a"]
    d1 = a.loc[finish_code]
    cal = net.calendars[int(d1.clndr_id)]
    from ..calendars import to_time
    cpl = (cal.pos(to_time(d1.early_end_date)) - cal.pos(to_time(dd))) / H
    cpli = (cpl + d1.total_float_hr_cnt / H) / cpl
    bei = len(completed) / len(due) if due else 1.0
    off["D13"] = [] if cpli >= 0.95 else [finish_code]
    off["D14"] = [] if bei >= 0.95 else sorted(off["D11"])
    oos = set()
    for s_, plist in preds.items():
        if a.at[s_, "act_start_date"] is None:
            continue
        for p, t, lag in plist:
            if t == "FS" and lag >= 0 and status[p] != "TK_Complete":
                oos.add(s_)
            if t == "SS" and a.at[p, "act_start_date"] is None:
                oos.add(s_)
    off["U01"] = sorted(oos)
    off["U02"] = sorted(i for i, r in a.iterrows() if (r.act_start_date is not None and r.act_start_date > dd)
                        or (r.act_end_date is not None and r.act_end_date > dd))
    off["U03"] = sorted(i for i, r in a.iterrows() if r.status_code == "TK_Complete" and (r.remain_drtn_hr_cnt or 0) > 0)
    off["U04"] = sorted(i for i, r in a.iterrows() if r.act_start_date is None and
                        ((r.phys_complete_pct or 0) > 0 or (r.remain_drtn_hr_cnt or 0) < (r.target_drtn_hr_cnt or 0)))
    off["U05"] = sorted(i for i, r in a.iterrows() if r.WS is None or r.AST is None or r.OWN is None)
    grp = a.groupby(["level1", "task_name"]).groups
    off["U06"] = sorted(i for k, idx in grp.items() if len(idx) > 1 for i in idx)
    off["U07"] = sorted(i for i, r in a.iterrows() if r.task_type == "TT_LOE" and r.status_code != "TK_Complete" and
                        (succs[i] or (r.total_float_hr_cnt is not None and r.total_float_hr_cnt <= 0)
                         or r.driving_path_flag == "Y"))
    dd_ok = expected_data_date is None or dd.date() == expected_data_date
    off["U08"] = [] if dd_ok else [f"data date {dd.date()} != cut-off {expected_data_date}"]
    stale = []
    if prev_sch is not None:
        p = prev_sch.act.set_index("task_code")
        for i, r in a.iterrows():
            if r.status_code == "TK_Active" and r.task_type != "TT_LOE" and i in p.index and \
                    p.at[i, "status_code"] == "TK_Active" and p.at[i, "remain_drtn_hr_cnt"] == r.remain_drtn_hr_cnt and \
                    p.at[i, "phys_complete_pct"] == r.phys_complete_pct:
                stale.append(i)
    off["U09"] = sorted(stale)
    off["U10"] = sorted(rk(r) for r in rel_inc.itertuples() if r.type == "SF")
    off["U11"] = sorted(i for i in a.index if bl is not None and i not in bl.index)
    off["U12"] = sorted(rk(r) for r in rel_inc.itertuples() if r.lag_h > 20 * H)

    n_inc, n_rel = len(inc), len(rel_inc)
    n_tasks_inc = int((inc.task_type == "TT_Task").sum())
    metric = {
        "D01": (100 * len(off["D01"]) / n_inc, n_inc), "D02": (len(off["D02"]), n_rel),
        "D03": (100 * len(off["D03"]) / n_rel, n_rel), "D04": (100 * (n_rel - len(off["D04"])) / n_rel, n_rel),
        "D05": (100 * len(off["D05"]) / n_inc, n_inc), "D06": (100 * len(off["D06"]) / n_inc, n_inc),
        "D07": (len(off["D07"]), n_inc), "D08": (100 * len(off["D08"]) / n_tasks_inc, n_tasks_inc),
        "D09": (len(off["D09"]), len(a)), "D10": (None, None),
        "D11": (100 * len(off["D11"]) / len(due) if due else 0.0, len(due)),
        "D12": (1.0 if cp["pass"] else 0.0, 1), "D13": (cpli, None), "D14": (bei, len(due)),
    }
    for u in [c[0] for c in CHECKS if c[0].startswith("U")]:
        metric[u] = (len(off[u]), len(a))
    metric["U08"] = (1.0 if dd_ok else 0.0, 1)
    results = []
    total_w = sum(c[5] for c in CHECKS)
    score_sum = 0.0
    for cid, name, group, kind, thr, w, desc, anchor in CHECKS:
        val, den = metric[cid]
        if kind == "na":
            passed = None
        elif kind == "pct_max":
            passed = val <= thr
        elif kind == "count_max":
            passed = val <= thr
        elif kind == "pct_min":
            passed = val >= thr
        elif kind == "ratio_min":
            passed = val >= thr
        else:
            passed = bool(val)
        sc = check_score(kind, val, thr, w, passed)
        score_sum += sc
        results.append(dict(check_id=cid, check_name=name, group=group, kind=kind, threshold=thr, weight=w,
                            value=None if val is None else round(float(val), 3), denominator=den,
                            count=len(off[cid]) if cid not in ("D12", "D13", "D14", "U08", "D10") else
                            (0 if passed else 1) if cid != "D14" else len(off["D11"]),
                            passed=passed, score=round(sc, 2), definition=desc, playbook=anchor,
                            offenders=off[cid]))
    dq = round(100 * score_sum / total_w, 1)
    # owner scorecard
    owner_rows = []
    owners = a["OWN"].fillna("UNASSIGNED")
    flagged_by_check = {c: set(i.split("->")[0] if "->" in i else i for i in off[c]) for c in ACTIVITY_CHECKS}
    for own in sorted(owners.unique()):
        ids = set(owners.index[owners == own])
        inc_ids = ids & set(inc.index)
        counts = {c: len(flagged_by_check[c] & ids) for c in ACTIVITY_CHECKS}
        flagged = set().union(*[flagged_by_check[c] & ids for c in ACTIVITY_CHECKS])
        base = max(1, len(ids))
        owner_rows.append(dict(owner_code=own, activities=len(ids), incomplete=len(inc_ids), flagged=len(flagged),
                               owner_dq=round(100 * (1 - len(flagged) / base), 1),
                               update_issues=sum(counts[c] for c in ("U01", "U03", "U04", "U05", "U09")),
                               logic_issues=sum(counts[c] for c in ("D01", "D05", "U07")),
                               **{f"n_{c}": v for c, v in counts.items()}))
    return {"checks": results, "dq_score": dq, "dq_rating": rating(dq), "owner_scorecard": owner_rows,
            "engine": eng, "net": net, "cp_test": cp, "cpli": cpli, "bei": bei, "offenders": off}
