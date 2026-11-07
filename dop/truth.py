"""Generator-side expected results ("truth") for every quality check.

This is deliberately an independent implementation from dop/pipeline/quality.py: truth is computed from
the generator's own records (before XER export), quality is computed from the parsed XER. The tests
assert both give exactly the same offender sets, and that every explicitly injected issue is present.
"""
from __future__ import annotations

from collections import defaultdict

from .calendars import HOURS_PER_DAY, to_time
from .cpm import COMPLETE, HARD_CONSTRAINTS, LOE, NOT_STARTED, critical_path_test
from .programme import DAY1_ID
from .storyline import DATA_DATES

HIGH_FLOAT_H = 44 * HOURS_PER_DAY
HIGH_DUR_H = 44 * HOURS_PER_DAY
LONG_LAG_H = 20 * HOURS_PER_DAY
PROJECT_START_ID = "PRG-D1R-M000"


def compute_truth(k, snap, recs: dict[str, dict], prev_recs: dict[str, dict], bl: dict, injections: list[dict]) -> dict:
    dd = to_time(DATA_DATES[k])
    rels = [(p, s, t, lag * HOURS_PER_DAY) for p, s, t, lag in snap.rels]
    inc = {a for a, r in recs.items() if r["status"] != COMPLETE and r["type"] != LOE}
    preds, succs = defaultdict(list), defaultdict(list)
    for p, s, t, lag in rels:
        preds[s].append((p, t, lag))
        succs[p].append((s, t, lag))
    rel_inc = [(p, s, t, lag) for p, s, t, lag in rels if recs[s]["status"] != COMPLETE]
    rkey = lambda p, s, t: f"{p}->{s}:{t}"
    E = {}
    E["D01"] = sorted(a for a in inc if a not in (DAY1_ID, PROJECT_START_ID) and (not preds[a] or not succs[a]))
    E["D02"] = sorted(rkey(p, s, t) for p, s, t, lag in rel_inc if lag < 0)
    E["D03"] = sorted(rkey(p, s, t) for p, s, t, lag in rel_inc if lag > 0)
    E["D04"] = sorted(rkey(p, s, t) for p, s, t, lag in rel_inc if t != "FS")
    E["D05"] = sorted(a for a in inc if recs[a]["cstr_type"] in HARD_CONSTRAINTS)
    E["D06"] = sorted(a for a in inc if recs[a]["tf"] is not None and recs[a]["tf"] > HIGH_FLOAT_H)
    E["D07"] = sorted(a for a in inc if recs[a]["tf"] is not None and recs[a]["tf"] < 0)
    E["D08"] = sorted(a for a in inc if recs[a]["type"] == "TT_Task" and recs[a]["dur"] > HIGH_DUR_H)
    inv = set()
    for a, r in recs.items():
        if (r["act_start"] is not None and r["act_start"] > dd) or (r["act_finish"] is not None and r["act_finish"] > dd):
            inv.add(a)
        if r["status"] != COMPLETE and ((r["es"] is not None and r["es"] < dd and r["status"] == NOT_STARTED)
                                        or (r["ef"] is not None and r["ef"] < dd)):
            inv.add(a)
    E["D09"] = sorted(inv)
    due = [a for a, r in recs.items() if r["type"] != LOE and a in bl and bl[a][1] <= dd]
    missed = [a for a in due if recs[a]["status"] != COMPLETE or recs[a]["act_finish"] > bl[a][1]]
    E["D11"] = sorted(missed)
    completed = [a for a, r in recs.items() if r["type"] != LOE and r["status"] == COMPLETE]
    # update discipline
    oos = set()
    for s, plist in preds.items():
        if recs[s]["act_start"] is None:
            continue
        for p, t, lag in plist:
            if t == "FS" and lag >= 0 and recs[p]["status"] != COMPLETE:
                oos.add(s)
            if t == "SS" and recs[p]["act_start"] is None:
                oos.add(s)
    E["U01"] = sorted(oos)
    E["U02"] = sorted(a for a, r in recs.items() if (r["act_start"] is not None and r["act_start"] > dd)
                      or (r["act_finish"] is not None and r["act_finish"] > dd))
    E["U03"] = sorted(a for a, r in recs.items() if r["status"] == COMPLETE and r["rem"] > 0)
    E["U04"] = sorted(a for a, r in recs.items() if r["act_start"] is None and (r["phys"] > 0 or r["rem"] < r["dur"]))
    E["U05"] = sorted(a for a, r in recs.items() if not {"WS", "AST", "OWN"} <= set(r["codes"]))
    names = defaultdict(list)
    for a, r in recs.items():
        names[(r["asset"], r["name"])].append(a)
    E["U06"] = sorted(a for v in names.values() if len(v) > 1 for a in v)
    E["U07"] = sorted(a for a, r in recs.items() if r["type"] == LOE and r["status"] != COMPLETE
                      and (succs[a] or (r["tf"] is not None and r["tf"] <= 0) or r["longest"]))
    E["U08"] = []
    stale = []
    for a, r in recs.items():
        p = prev_recs.get(a)
        if r["status"] == "TK_Active" and r["type"] != LOE and p and p["status"] == "TK_Active" \
                and p["rem"] == r["rem"] and p["phys"] == r["phys"]:
            stale.append(a)
    E["U09"] = sorted(stale)
    E["U10"] = sorted(rkey(p, s, t) for p, s, t, lag in rel_inc if t == "SF")
    E["U11"] = sorted(a for a in recs if a not in bl)
    E["U12"] = sorted(rkey(p, s, t) for p, s, t, lag in rel_inc if lag > LONG_LAG_H)
    # metrics
    cp = critical_path_test(snap.net, snap.sched)
    d1 = snap.sched.day1()
    c = snap.net.calendars[snap.net.activities[DAY1_ID].cal]
    cpl = (c.pos(d1.ef) - c.pos(dd)) / HOURS_PER_DAY
    metrics = {
        "incomplete": len(inc), "relationships_incomplete_succ": len(rel_inc),
        "due": len(due), "completed": len(completed),
        "bei": round(len(completed) / len(due), 3) if due else None,
        "cpli": round((cpl + d1.tf / HOURS_PER_DAY) / cpl, 3),
        "cp_test_pass": cp["pass"], "cp_test_activity": cp["activity"], "cp_test_delta_days": cp["delta_days"],
        "day1_tf_days": d1.tf / HOURS_PER_DAY,
    }
    for inj in injections:
        assert inj["item"] in E[inj["check"]], inj
    return {"snapshot": f"S{k}", "data_date": DATA_DATES[k].isoformat(), "injected": injections + structural(snap),
            "expected": E, "metrics": metrics}


def structural(snap) -> list[dict]:
    """Structural injected issues active in this snapshot (from the storyline events)."""
    out = []
    check_of = {"open end (no successor)": "D01", "no predecessor; constraint used instead of logic": "D01",
                "hard constraint": "D05", "long lag": "U12", "negative lag": "D02", "SF relationship": "U10",
                "missing owner code": "U05", "missing workstream code": "U05", "missing asset code": "U05",
                "duplicate name": "U06", "LOE drives a successor": "U07"}
    for e in snap.events:
        iss = e.get("issue")
        if not iss:
            continue
        chk = check_of[iss]
        if e["op"] in ("rel_remove",):
            item = e["pred"] if iss.startswith("open end") else e["succ"]
        elif e["op"] in ("rel_set", "rel_add") and chk in ("D02", "U10", "U12"):
            item = f"{e['pred']}->{e['succ']}:{e['type']}"
        elif e["op"] in ("rel_set", "rel_add"):
            item = e["pred"]
        else:
            item = e["id"]
        out.append({"check": chk, "item": item, "description": iss})
    return out
