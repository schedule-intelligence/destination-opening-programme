"""Schedule generation: simulate the programme, export P6 XER files (BL0, BL1, six updates),
write the governance registers and the per-snapshot truth files used by the tests."""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

from .calendars import HOURS_PER_DAY, fmt_time, to_time
from .cpm import ACTIVE, COMPLETE, LOE, NOT_STARTED
from .programme import (ASSETS, DAY1_ID, DAY1_TARGET, GATES, NTP_DATE, OWNERS, PACKAGES, PHASES, PROGRAMME,
                        WORKSTREAMS, interface_list)
from .registers import CHANGES, DECISIONS, RECOVERY_OPTIONS, REPORTING_STEPS, RISKS
from .simulate import CALS, Snapshot, simulate
from .storyline import BL1_K, DATA_DATES, EVENTS, SNAPSHOT_LABELS
from .truth import compute_truth
from .xer import guid, fmt_num, write_xer

ROOT = pathlib.Path(__file__).resolve().parents[1]
UPDATE_PROJ_ID, BL0_PROJ_ID, BL1_PROJ_ID = 1000, 1100, 1101
CODE_TYPES = [(1, "WS", "Workstream"), (2, "AST", "Asset"), (3, "OWN", "Owner"), (4, "PHS", "Phase"),
              (5, "IFC", "Interface"), (6, "RG", "Readiness Gate")]
CODE_VALUES = {
    "WS": [(k, v) for k, v in WORKSTREAMS.items()],
    "AST": [(k, v) for k, v in ASSETS.items()],
    "OWN": [(k, v) for k, v in OWNERS.items()],
    "PHS": [(k.split()[0], v) for k, v in PHASES.items()],
    "IFC": [("GIVER", "Giver"), ("RECEIVER", "Receiver"), ("NONE", "None")],
    "RG": [(k, v) for k, v in GATES.items()],
}


def xer_name(k: int) -> str:
    return "DOP_BL0.xer" if k == 0 else f"DOP_UPD_{DATA_DATES[k].isoformat()}.xer"


class Ids:
    """Stable P6 internal ids across all exports."""

    def __init__(self, snaps: list[Snapshot]):
        all_ids = sorted({a for s in snaps for a in s.spec})
        self.task = {a: 100001 + i for i, a in enumerate(all_ids)}
        nodes = [("ROOT",)]
        for a in ASSETS:
            nodes.append((a,))
            for ws in WORKSTREAMS:
                nodes.append((a, ws))
        pk = sorted({(s.spec[x]["asset"], s.spec[x]["ws"], s.spec[x]["pkg"]) for s in snaps for x in s.spec})
        nodes += pk
        self.wbs = {n: 5001 + i for i, n in enumerate(nodes)}
        self.code = {}
        n = 9001
        for tid, short, _ in CODE_TYPES:
            for v, _name in CODE_VALUES[short]:
                self.code[(short, v)] = n
                n += 1


def interface_roles() -> dict[str, str]:
    roles = {}
    for i in interface_list():
        roles[i["giver"]] = "GIVER"
    for i in interface_list():
        roles.setdefault(i["receiver"], "RECEIVER")
    return roles


def baseline_dates(s: Snapshot) -> dict[str, tuple[int, int]]:
    out = {}
    for aid, a in s.net.activities.items():
        r = s.sched.acts[aid]
        if a.status == COMPLETE:
            out[aid] = (a.act_start, a.act_finish)
        else:
            out[aid] = (r.es, r.ef)
    return out


def export_records(s: Snapshot, bl: dict | None) -> dict[str, dict]:
    """One record per activity with everything the XER TASK row needs (before injections)."""
    roles = interface_roles()
    recs = {}
    for aid, sp in s.spec.items():
        a = s.net.activities[aid]
        r = s.sched.acts[aid]
        codes = {"WS": sp["ws"], "AST": sp["asset"], "OWN": sp["owner"], "PHS": sp["phase"].split()[0],
                 "IFC": roles.get(aid, "NONE")}
        if sp.get("gate"):
            codes["RG"] = sp["gate"]
        for m in sp.get("missing_codes", []):
            codes.pop(m, None)
        rec = dict(id=aid, name=sp["name"], asset=sp["asset"], ws=sp["ws"], pkg=sp["pkg"], cal=a.cal, type=a.type,
                   status=a.status, dur=a.dur, rem=a.remaining, phys=s.phys_pct[aid],
                   act_start=a.act_start, act_finish=a.act_finish if a.status == COMPLETE else None,
                   cstr_type=a.cstr_type, cstr_date=a.cstr_date, codes=codes, longest=r.longest_path,
                   tf=r.tf, ff=r.ff, critical=r.critical)
        if a.status == COMPLETE:
            rec.update(es=a.act_start, ef=a.act_finish, rs=None, ls=None, lf=None)
        else:
            rec.update(es=r.rs if a.status == ACTIVE else r.es, ef=r.ef, rs=r.rs, ls=r.ls, lf=r.lf)
        if a.type == LOE:  # P6 shows an LOE's duration as its computed span
            c = CALS[a.cal]
            start = a.act_start if a.act_start is not None else r.es
            rec["dur"] = c.pos(r.ef) - c.pos(start)
            rec["rem"] = 0 if a.status == COMPLETE else c.pos(r.ef) - c.pos(max(start, s.net.data_date))
        if bl is not None and aid in bl:
            rec["target_start"], rec["target_end"] = bl[aid]
        else:
            rec["target_start"], rec["target_end"] = (rec["act_start"] or rec["es"]), rec["ef"]
        recs[aid] = rec
    return recs


def apply_injections(k: int, s: Snapshot, recs: dict[str, dict]) -> list[dict]:
    """Data-integrity injections applied to exported records (not to the engine run). Deterministic rules."""
    inj = []
    dd = to_time(DATA_DATES[k])
    if k == 2:
        cand = sorted(a for a in s.period_finished if a.startswith("DAR") and recs[a]["type"] == "TT_Task")
        aid = cand[0]
        recs[aid]["act_finish"] = recs[aid]["ef"] = to_time(DATA_DATES[k] + dt.timedelta(days=2), 16)
        inj.append({"check": "U02", "item": aid, "description": "Actual finish typed after the data date"})
    if k == 3:
        cand = sorted(a for a in s.period_finished if a.startswith("LWP") and recs[a]["type"] == "TT_Task")
        aid = cand[0]
        recs[aid]["rem"] = 16
        inj.append({"check": "U03", "item": aid, "description": "Completed activity still carries 16 h remaining"})
    if k == 4:
        cand = sorted((recs[a]["es"], a) for a in recs if a.startswith("PBR") and recs[a]["status"] == NOT_STARTED
                      and recs[a]["type"] == "TT_Task")
        a1, a2 = cand[0][1], cand[1][1]
        recs[a1]["es"] = recs[a1]["rs"] = to_time(DATA_DATES[k] - dt.timedelta(days=2))
        inj.append({"check": "D09", "item": a1, "description": "Forecast start before the data date (not rescheduled)"})
        recs[a2]["phys"] = 15.0
        inj.append({"check": "U04", "item": a2, "description": "Physical % complete entered without an actual start"})
    return inj


def p6_tables(k: int, recs: dict[str, dict], rels: list[tuple], ids: Ids, proj_id: int, short: str,
              baseline_proj: int | None, bl_date: dt.date | None, project_finish: int) -> dict[str, list[dict]]:
    dd = DATA_DATES[k]
    T = fmt_time
    tables = {}
    tables["PROJECT"] = [dict(
        proj_id=proj_id, fy_start_month_num=1, rsrc_self_add_flag="Y", allow_complete_flag="Y",
        rsrc_multi_assign_flag="Y", checkout_flag="N", project_flag="Y", step_complete_flag="N",
        cost_qty_recalc_flag="Y", batch_sum_flag="Y", name_sep_char=".", def_complete_pct_type="CP_Drtn",
        proj_short_name=short, orig_proj_id=UPDATE_PROJ_ID if proj_id != UPDATE_PROJ_ID else "", clndr_id=1,
        sum_base_proj_id=baseline_proj or "", task_code_base=1000, task_code_step=10, priority_num=10,
        wbs_max_sum_level=0, strgy_priority_num=100, critical_drtn_hr_cnt=0, def_cost_per_qty=0,
        last_recalc_date=T(to_time(dd)), plan_start_date=T(to_time(NTP_DATE)),
        plan_end_date=T(to_time(DAY1_TARGET, 16)), scd_end_date=T(project_finish), add_date="2026-04-01 08:00",
        def_duration_type="DT_FixedDrtn", guid=guid(short), def_qty_type="QT_Hour", add_by_name="dop.planner",
        def_rate_type="COST_PER_QTY", add_act_remain_flag="N", act_this_per_link_flag="Y", def_task_type="TT_Task",
        act_pct_link_flag="N", critical_path_type="CT_DrivPath", task_code_prefix_flag="Y", def_rollup_dates_flag="Y",
        use_project_baseline_flag="Y", rem_target_link_flag="Y", reset_planned_flag="N", allow_neg_act_flag="N",
        sum_assign_level="SL_Taskrsrc", last_baseline_update_date=T(to_time(bl_date)) if bl_date else "",
        last_schedule_date=T(to_time(dd)), loaded_scope_level=7, export_flag="Y")]
    tables["CALENDAR"] = [dict(clndr_id=c.clndr_id, default_flag="Y" if c.clndr_id == 1 else "N", clndr_name=c.name,
                               proj_id="", base_clndr_id="", last_chng_date="2026-01-05 08:00", clndr_type="CA_Base",
                               day_hr_cnt=HOURS_PER_DAY, week_hr_cnt=HOURS_PER_DAY * len(c.workweek),
                               month_hr_cnt=round(HOURS_PER_DAY * len(c.workweek) * 52 / 12),
                               year_hr_cnt=HOURS_PER_DAY * len(c.workweek) * 52, rsrc_private="N",
                               clndr_data=c.to_clndr_data()) for c in CALS.values()]
    wbs = []
    for node, wid in ids.wbs.items():
        if node == ("ROOT",):
            wbs.append(dict(wbs_id=wid, proj_id=proj_id, seq_num=0, proj_node_flag="Y", sum_data_flag="N",
                            status_code="WS_Open", wbs_short_name=short,
                            wbs_name=f"{PROGRAMME['name']} - Integrated Master Schedule", parent_wbs_id="",
                            guid=guid(f"wbs{wid}")))
            continue
        parent = ids.wbs[node[:-1]] if len(node) > 1 else ids.wbs[("ROOT",)]
        name = {1: ASSETS, 2: WORKSTREAMS, 3: PACKAGES}[len(node)][node[-1]]
        wbs.append(dict(wbs_id=wid, proj_id=proj_id, seq_num=wid - 5000, proj_node_flag="N", sum_data_flag="N",
                        status_code="WS_Open", wbs_short_name=node[-1], wbs_name=name, parent_wbs_id=parent,
                        guid=guid(f"wbs{wid}")))
    tables["PROJWBS"] = wbs
    tables["ACTVTYPE"] = [dict(actv_code_type_id=tid, actv_short_len=10, seq_num=tid, actv_code_type=name,
                               proj_id=proj_id, wbs_id="", actv_code_type_scope="AS_Project", super_flag="N")
                          for tid, _s, name in CODE_TYPES]
    codes = []
    assigned = {}
    for r in recs.values():
        for ct, v in r["codes"].items():
            assigned[(ct, v)] = assigned.get((ct, v), 0) + 1
    for tid, short_t, _ in CODE_TYPES:
        for i, (v, name) in enumerate(CODE_VALUES[short_t]):
            codes.append(dict(actv_code_id=ids.code[(short_t, v)], parent_actv_code_id="", actv_code_type_id=tid,
                              actv_code_name=name, short_name=v, seq_num=i + 1, color="",
                              total_assignments=assigned.get((short_t, v), 0)))
    tables["ACTVCODE"] = codes
    tasks, taskactv = [], []
    for aid in sorted(recs):
        r = recs[aid]
        complete = r["status"] == COMPLETE
        tid = ids.task[aid]
        tasks.append(dict(
            task_id=tid, proj_id=proj_id, wbs_id=ids.wbs[(r["asset"], r["ws"], r["pkg"])], clndr_id=r["cal"],
            phys_complete_pct=fmt_num(r["phys"]), rev_fdbk_flag="N", est_wt=1, lock_plan_flag="N",
            auto_compute_act_flag="N", complete_pct_type="CP_Drtn", task_type=r["type"],
            duration_type="DT_FixedDrtn", status_code=r["status"], task_code=aid, task_name=r["name"], rsrc_id="",
            total_float_hr_cnt="" if complete else fmt_num(r["tf"]),
            free_float_hr_cnt="" if complete else fmt_num(r["ff"]),
            remain_drtn_hr_cnt=fmt_num(r["rem"]), act_work_qty=0, remain_work_qty=0, target_work_qty=0,
            target_drtn_hr_cnt=fmt_num(r["dur"]), target_equip_qty=0, act_equip_qty=0, remain_equip_qty=0,
            cstr_date=T(r["cstr_date"]) if r["cstr_type"] else "", act_start_date=T(r["act_start"]),
            act_end_date=T(r["act_finish"]), late_start_date=T(r["ls"]), late_end_date=T(r["lf"]),
            expect_end_date="", early_start_date=T(r["es"]), early_end_date=T(r["ef"]),
            restart_date="" if complete else T(r["rs"]), reend_date="" if complete else T(r["ef"]),
            target_start_date=T(r["target_start"]), target_end_date=T(r["target_end"]),
            rem_late_start_date="" if complete else T(r["ls"]), rem_late_end_date="" if complete else T(r["lf"]),
            cstr_type=r["cstr_type"], priority_type="PT_Normal", guid=guid(aid),
            driving_path_flag="Y" if r["longest"] else "N", act_this_per_work_qty=0, act_this_per_equip_qty=0,
            create_date="2026-04-01 08:00", update_date=T(to_time(dd)), create_user="dop.planner",
            update_user="dop.planner"))
        for ct, v in r["codes"].items():
            tid_type = next(t for t, s_, _ in CODE_TYPES if s_ == ct)
            taskactv.append(dict(task_id=tid, actv_code_type_id=tid_type, actv_code_id=ids.code[(ct, v)],
                                 proj_id=proj_id))
    tables["TASK"] = tasks
    tables["TASKACTV"] = taskactv
    tables["TASKPRED"] = [dict(task_pred_id=700001 + i, task_id=ids.task[s_], pred_task_id=ids.task[p],
                               proj_id=proj_id, pred_proj_id=proj_id, pred_type="PR_" + t,
                               lag_hr_cnt=fmt_num(lag * HOURS_PER_DAY), comments="", float_path="", aref="", arls="")
                          for i, (p, s_, t, lag) in enumerate(sorted(rels))]
    return tables


def write_csv(path: pathlib.Path, header: list[str], rows: list[list]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_registers(snaps: list[Snapshot], root: pathlib.Path):
    reg = root / "data" / "registers"
    rows = []
    for rid, title, cause, effect, owner, linked, mit, mit_owner, imp, scores in RISKS:
        rows.append([rid, title, cause, effect, owner, linked, mit, mit_owner, imp])
    write_csv(reg / "risk_register.csv", ["risk_id", "title", "cause", "effect", "owner", "linked_activities",
                                          "mitigation", "mitigation_owner", "schedule_impact_days"], rows)
    srows = []
    for rid, *_, scores in RISKS:
        for k, (p, i) in enumerate(scores, start=1):
            srows.append([rid, DATA_DATES[k].isoformat(), p, i, p * i])
    write_csv(reg / "risk_scores.csv", ["risk_id", "data_date", "probability", "impact", "score"], srows)
    write_csv(reg / "decision_log.csv", ["decision_id", "ask", "owner", "raised_data_date", "needed_by", "status",
                                         "closed_on", "linked_activity", "outcome"],
              [[d[0], d[1], d[2], DATA_DATES[d[3]].isoformat(), d[4], d[5], d[6], d[7], d[8]] for d in DECISIONS])
    # change register impact computed from the engine where it is meaningful
    d1 = {s.k: s.sched.day1().ef for s in snaps}
    c3 = CALS[3]
    impact = {"CR-003": (c3.pos(d1[3]) - c3.pos(d1[2])) // HOURS_PER_DAY,
              "CR-005": (c3.pos(d1[5]) - c3.pos(d1[4])) // HOURS_PER_DAY}
    write_csv(reg / "change_register.csv", ["change_id", "title", "reason", "change_type", "raised_data_date",
                                            "approver", "approval_date", "status", "baseline_effect",
                                            "linked_activity", "day1_impact_days"],
              [[c[0], c[1], c[2], c[3], DATA_DATES[c[4]].isoformat(), c[5], c[6], c[7], c[8], c[9],
                impact.get(c[0], "")] for c in CHANGES])
    (reg / "recovery_options.json").write_text(json.dumps(RECOVERY_OPTIONS, indent=2), encoding="utf-8", newline="\n")
    write_csv(reg / "interfaces.csv", ["interface_id", "giver", "receiver", "description"],
              [[i["interface_id"], i["giver"], i["receiver"], i["description"]] for i in interface_list()])
    cal = []
    for k, d in enumerate(DATA_DATES[1:], start=1):
        for step, desc in REPORTING_STEPS:
            off = int(step[1:]) if step != "T0" else 0
            if off == 0:   # the cut-off is the data date itself, even when it falls in a holiday block
                day = to_time(d)
            else:
                day = CALS[2].start_at(CALS[2].pos(to_time(d)) + off * HOURS_PER_DAY)
            cal.append([SNAPSHOT_LABELS[k], d.isoformat(), step, fmt_time(day)[:10], desc, "monthly"])
    write_csv(reg / "reporting_calendar.csv", ["period", "data_date", "step", "date", "activity", "cycle"], cal)
    storyline = [[e["frm"], e["to"] if e["to"] < 99 else "", e["op"], e.get("id", e.get("pred", "")),
                  e.get("succ", ""), e.get("issue", ""), e.get("why", "")] for e in EVENTS]
    write_csv(reg / "storyline_events.csv", ["from_k", "to_k", "op", "activity_or_pred", "succ", "issue", "why"],
              storyline)


def generate(root: pathlib.Path = ROOT) -> dict:
    snaps = simulate()
    ids = Ids(snaps)
    xer_dir = root / "data" / "xer"
    truth_dir = root / "data" / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    bl0 = baseline_dates(snaps[0])
    bl1 = baseline_dates(snaps[BL1_K])
    manifest = {"files": {}}
    # baselines as separate P6 projects
    for k, pid, short in ((0, BL0_PROJ_ID, "DOP-IMS-BL0"), (BL1_K, BL1_PROJ_ID, "DOP-IMS-BL1")):
        s = snaps[k]
        recs = export_records(s, None)
        tabs = p6_tables(k, recs, s.rels, ids, pid, short, None, DATA_DATES[k], s.sched.project_finish)
        name = "DOP_BL0.xer" if k == 0 else "DOP_BL1.xer"
        manifest["files"][name] = write_xer(tabs, xer_dir / name, DATA_DATES[k])
    prev_recs = recs0 = export_records(snaps[0], None)
    for k in range(1, len(DATA_DATES)):
        s = snaps[k]
        bl, bl_ref, bl_date = (bl0, BL0_PROJ_ID, DATA_DATES[0]) if k < BL1_K else (bl1, BL1_PROJ_ID, DATA_DATES[BL1_K])
        recs = export_records(s, bl)
        injections = apply_injections(k, s, recs)
        tabs = p6_tables(k, recs, s.rels, ids, UPDATE_PROJ_ID, "DOP-IMS", bl_ref, bl_date, s.sched.project_finish)
        name = xer_name(k)
        manifest["files"][name] = write_xer(tabs, xer_dir / name, DATA_DATES[k])
        truth = compute_truth(k, s, recs, prev_recs, bl, injections)
        truth.update(xer=name, baseline="BL0" if k < BL1_K else "BL1")
        (truth_dir / f"truth_{DATA_DATES[k].isoformat()}.json").write_text(json.dumps(truth, indent=1),
                                                                          encoding="utf-8", newline="\n")
        prev_recs = recs
    write_registers(snaps, root)
    (root / "data" / "xer" / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return {"snapshots": len(snaps), "activities": [len(s.spec) for s in snaps],
            "day1_tf_days": [s.sched.day1().tf / HOURS_PER_DAY for s in snaps]}
