"""Six-month storyline expressed as per-snapshot network deltas, progress events and injected issues.

k = 0 is the BL0 data date (30-Apr-2026); k = 1..6 are the monthly updates. An event applies to every
snapshot k with ``from <= k <= to``. Structural injected issues are events too, so the generator always
knows exactly which issues each snapshot contains (see truth.py).
"""
from __future__ import annotations

import copy
import datetime as dt

from .programme import build_template

D = dt.date
DATA_DATES = [D(2026, 4, 30), D(2026, 5, 28), D(2026, 6, 25), D(2026, 7, 30), D(2026, 8, 27),
              D(2026, 9, 24), D(2026, 10, 29)]
SNAPSHOT_LABELS = ["BL0", "S1", "S2", "S3", "S4", "S5", "S6"]
BL1_K = 3
INF = 99


def ev(op, frm=0, to=INF, **kw):
    return dict(op=op, frm=frm, to=to, **kw)


EVENTS = [
    # ---------------- injected structural issues (present from BL0, some cleaned up at BL1) ----------------
    ev("rel_remove", 0, 2, pred="PBR-CON-1230", succ="PBR-CON-M142", issue="open end (no successor)"),
    ev("rel_remove", 0, 4, pred="MTP-OPM-4030", succ="MTP-OTE-5030", issue="open end (no successor)"),
    ev("rel_remove", 0, 4, pred="MTP-OPM-4030", succ="MTP-OPM-4130", issue="open end (no successor)"),
    ev("rel_remove", 0, INF, pred="LWP-TNC-M220", succ="LWP-HOV-3210", issue="no predecessor; constraint used instead of logic"),
    ev("cstr", 0, INF, id="LWP-HOV-3210", type="CS_MSOA", date=D(2027, 5, 2)),
    ev("cstr", 0, 2, id="MTP-TNC-2140", type="CS_MANDSTART", date=D(2027, 1, 11), issue="hard constraint"),
    ev("cstr", 0, INF, id="PBR-HOV-3110", type="CS_MANDFIN", date=D(2027, 4, 22), issue="hard constraint"),
    ev("cstr", 4, 5, id="LWP-OPM-4020", type="CS_MANDSTART", date=D(2027, 2, 21), issue="hard constraint"),
    ev("rel_set", 0, INF, pred="PBR-CON-1310", succ="PBR-CON-1320", type="FS", lag=25, issue="long lag"),
    ev("rel_set", 0, INF, pred="DAR-CON-1040", succ="DAR-CON-1410", type="FS", lag=30, issue="long lag"),
    ev("rel_add", 0, INF, pred="PEW-TNC-2050", succ="PEW-HOV-3010", type="FS", lag=30, issue="long lag"),
    ev("rel_set", 0, INF, pred="MTP-HOV-3010", succ="MTP-HOV-3220", type="FS", lag=-3, issue="negative lag"),
    ev("rel_set", 0, INF, pred="PEW-CON-1150", succ="PEW-TNC-2070", type="FS", lag=-5, issue="negative lag"),
    ev("rel_set", 0, INF, pred="LWP-OTE-5020", succ="LWP-OTE-5110", type="SF", lag=0, issue="SF relationship"),
    ev("rel_set", 0, INF, pred="PEW-OTE-5010", succ="PEW-OTE-5020", type="SF", lag=5, issue="SF relationship"),
    ev("code_missing", 0, 3, id="PEW-CON-1170", code="OWN", issue="missing owner code"),
    ev("code_missing", 0, 5, id="PBR-OTE-5030", code="WS", issue="missing workstream code"),
    ev("code_missing", 0, 2, id="MTP-CON-1330", code="AST", issue="missing asset code"),
    ev("name", 0, 2, id="DAR-CON-1131", name="MEP second fix", issue="duplicate name"),
    ev("name", 0, 2, id="DAR-CON-1132", name="MEP second fix", issue="duplicate name"),
    ev("name", 0, INF, id="PEW-CON-1030", name="HV cabling", issue="duplicate name"),
    ev("name", 0, INF, id="PEW-CON-1040", name="HV cabling", issue="duplicate name"),
    ev("rel_add", 4, INF, pred="DAR-CON-9010", succ="DAR-TNC-2210", type="FS", lag=0, issue="LOE drives a successor"),
    ev("rel_add", 0, INF, pred="PRG-OPM-4005", succ="PEW-OPM-4010", type="FS", lag=0),
    ev("cstr", 0, INF, id="DAR-OPM-M120", type="CS_MSOA", date=D(2027, 4, 4)),
    ev("cstr", 0, INF, id="MTP-OPM-M120", type="CS_MSOA", date=D(2027, 3, 6)),

    # ---------------- S1 (28-May-2026): arena MEP plant late, first fix slow ----------------
    ev("dur", 1, INF, id="DAR-CON-1105", days=56, why="Chiller and switchgear delivery late (factory test failure)"),
    ev("dur", 1, INF, id="DAR-CON-1110", days=52, why="MEP first fix productivity below plan (labour shortage)"),
    ev("dur", 1, INF, id="DAR-CON-1030", days=44, why="Roof steel erection delayed by high winds"),
    ev("dur", 1, INF, id="MTP-CON-1310", days=114, why="Ride vendor installation crew late"),

    # ---------------- S2 (25-Jun-2026): arena slips again; OOS; new scope ----------------
    ev("dur", 2, INF, id="DAR-CON-1112", days=50, why="Upper-level first fix re-sequenced around late plant"),
    ev("dur", 2, INF, id="DAR-CON-1120", days=45, why="Plant installation re-sequenced around late deliveries"),
    ev("dur", 2, INF, id="DAR-CON-1320", days=44, why="Show-systems vendor design freeze late"),
    ev("add_act", 2, INF, id="DAR-CON-1240", spec=("Additional acoustic treatment - seating bowl", "CON", "FIT", 15, 1,
                                                   "TT_Task", "MWC", ""),
       preds=[("DAR-CON-1131", "FS", 0)], succs=[("DAR-CON-1220", "FS", 0)], why="Acoustic scope added by the operator"),

    # ---------------- S3 (30-Jul-2026): CR-003 approved -> BL1; clean-up at re-baseline ----------------
    ev("rel_set", 3, INF, pred="DAR-CON-1132", succ="DAR-CON-1220", type="SS", lag=30,
       why="CR-003 zone-based re-sequence of arena FOH fit-out"),
    ev("rel_add", 3, INF, pred="DAR-CON-1132", succ="DAR-CON-1220", type="FF", lag=10, why="CR-003"),
    ev("dur", 3, INF, id="DAR-CON-1330", days=44, why="CR-003 premium suites scope upgrade"),
    ev("dur", 3, INF, id="DAR-CON-1225", days=44, why="CR-003 premium FOH finishes"),
    ev("dur", 3, INF, id="DAR-CON-1230", days=30, why="CR-003 digital wayfinding scope"),

    # ---------------- S4 (27-Aug-2026): T&C compressed; power + operator access slip ----------------
    ev("dur", 4, INF, id="DAR-TNC-2110", days=20, why="T&C compression: added commissioning teams"),
    ev("dur", 4, INF, id="DAR-TNC-2130", days=21, why="T&C compression"),
    ev("dur", 4, INF, id="DAR-TNC-2150", days=16, why="T&C compression"),
    ev("rel_set", 4, INF, pred="DAR-TNC-2010", succ="DAR-TNC-2120", type="SS", lag=5, why="T&C compression: overlap"),
    ev("cstr", 4, INF, id="PEW-TNC-2030", type="CS_MSOA", date=D(2027, 1, 2),
       why="Utility energisation window for the North loop moved by the utility provider"),
    ev("cstr", 4, INF, id="DAR-OPM-M120", type="CS_MSOA", date=D(2027, 6, 19),
       why="Authority requires fire-strategy sign-off before operator access to the arena"),
    ev("dur", 4, INF, id="DAR-CON-1131", days=44, why="Zone A second fix rework after design clash"),

    # ---------------- S5 (24-Sep-2026): fire strategy change -> Day 1 negative float ----------------
    ev("add_act", 5, INF, id="DAR-CON-1250", spec=("Fire strategy changes - additional smoke extract works", "CON", "MEP",
                                                   10, 1, "TT_Task", "MEP", ""),
       preds=[("DAR-CON-1132", "FS", 0)], succs=[("DAR-CON-1220", "FS", 0), ("DAR-TNC-2130", "FS", 0)],
       why="Authority fire-strategy review requires additional smoke extract"),
    ev("dur", 5, INF, id="DAR-TNC-2130", days=26, why="Additional fire & life safety scope to commission"),


    # ---------------- S6 (29-Oct-2026): contractor recovery crews (partial recovery) ----------------
    ev("dur", 6, INF, id="DAR-CON-1250", days=8, why="Second MEP crew mobilised on smoke extract works"),
    ev("dur", 6, INF, id="DAR-CON-1132", days=37, why="Extended shifts on Zone B second fix"),
]

# progress events applied in the period that ends at snapshot k
STALLS = {4: ["PEW-CON-1110"], 5: ["PEW-CON-1110", "MTP-CON-1310"]}
FORCE_START = {2: {"DAR-CON-1112": D(2026, 6, 13)}}   # out-of-sequence: starts before its FS predecessor finishes


def network_spec(k: int) -> tuple[dict[str, dict], list[tuple], list[dict]]:
    """Activities (dict specs) and relationships as known at snapshot k, plus the events applied."""
    acts, rels = build_template()
    acts = copy.deepcopy(acts)
    rels = list(rels)
    applied = []
    for e in EVENTS:
        if not (e["frm"] <= k <= e["to"]):
            continue
        applied.append(e)
        op = e["op"]
        if op == "rel_remove":
            rels = [r for r in rels if not (r[0] == e["pred"] and r[1] == e["succ"])]
        elif op == "rel_set":
            rels = [r for r in rels if not (r[0] == e["pred"] and r[1] == e["succ"])]
            rels.append((e["pred"], e["succ"], e["type"], e["lag"]))
        elif op == "rel_add":
            rels.append((e["pred"], e["succ"], e["type"], e["lag"]))
        elif op == "cstr":
            acts[e["id"]].update(cstr_type=e["type"], cstr_date=e["date"])
        elif op == "dur":
            acts[e["id"]]["dur"] = e["days"]
        elif op == "name":
            acts[e["id"]]["name"] = e["name"]
        elif op == "code_missing":
            acts[e["id"]].setdefault("missing_codes", []).append(e["code"])
        elif op == "add_act":
            from .programme import PHASE_BY_WS
            name, ws, pkg, dur, cal, typ, owner, gate = e["spec"]
            asset = e["id"].split("-")[0]
            acts[e["id"]] = dict(id=e["id"], name=name, asset=asset, ws=ws, pkg=pkg, dur=dur, cal=cal, type=typ,
                                 owner=owner, gate=gate, phase=PHASE_BY_WS[ws], cstr_type="", cstr_date=None,
                                 added_k=e["frm"])
            for p, t, lag in e.get("preds", []):
                rels.append((p, e["id"], t, lag))
            for s, t, lag in e.get("succs", []):
                rels.append((e["id"], s, t, lag))
        else:
            raise ValueError(op)
    return acts, rels, applied
