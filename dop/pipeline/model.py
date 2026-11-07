"""Star schema for Power BI and the dashboard: dimensions and facts built from the parsed XER files plus the
governance registers. All date arithmetic for variances is in calendar days (positive = later than
reference); floats and durations are in working days of the activity calendar (hours / 8)."""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

import pandas as pd

from ..calendars import Calendar, to_time
from ..cpm import compare_scenario
from ..programme import (ASSETS, DAY1_ID, OWNER_LEADS, OWNERS, PACKAGES, PHASES, VENUES, WORKSTREAMS)
from .quality import assess

H = 8
D14 = dt.timedelta(days=14)
READINESS_STAGES = [("CON-M142", "Construction complete"), ("TNC-M220", "T&C complete"),
                    ("HOV-M230", "Handover to operator"), ("OPM-M150", "Operator trained"),
                    ("OTE-5110", "Trials & test events complete"), ("D1R-M020", "Day 1 ready")]
RECOVERY_MARGIN_D = 5  # recommend the smallest option set that restores at least this much Day 1 float
KEY_MILESTONES = [DAY1_ID, "PRG-D1R-M010", "PRG-D1R-M020", "PRG-D1R-M030", "PRG-D1R-M040"] + \
                 [f"{a}-D1R-M020" for a in VENUES] + [f"{a}-CON-M142" for a in VENUES]


def snap_id(d) -> int:
    return int(d.strftime("%Y%m%d"))


def read_csv(path: pathlib.Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def days(a, b):
    """Calendar days a - b (None-safe)."""
    if a is None or b is None:
        return None
    return (a.date() - b.date()).days


def finish_of(r):
    return r["act_end_date"] if r["status_code"] == "TK_Complete" else r["early_end_date"]


def start_of(r):
    return r["act_start_date"] if r["act_start_date"] is not None else r["early_start_date"]


def bl_dates(bl) -> dict:
    out = {}
    for r in bl.act.to_dict("records"):
        out[r["task_code"]] = (start_of(r), finish_of(r))
    return out


def planned_pct(bls, blf, when, cal: Calendar, is_ms: bool) -> float:
    if bls is None or blf is None:
        return 0.0
    if is_ms or blf <= bls:
        return 100.0 if blf <= when else 0.0
    p0, p1, pw = cal.pos(to_time(bls)), cal.pos(to_time(blf)), cal.pos(to_time(when))
    return 100.0 * min(1.0, max(0.0, (pw - p0) / (p1 - p0))) if p1 > p0 else 0.0


def build_model(root: pathlib.Path, bls: dict, ups: list, run_ts: str, near_critical_days: int = 10) -> dict:
    reg = root / "data" / "registers"
    cal_rows = read_csv(reg / "reporting_calendar.csv")
    cutoff = {r["data_date"]: r["date"] for r in cal_rows if r["step"] == "T0"}
    bl0, bl1 = bl_dates(bls["BL0"]), bl_dates(bls["BL1"])
    bl_proj = {1100: "BL0", 1101: "BL1"}
    cals = {int(r.clndr_id): Calendar.from_clndr_data(int(r.clndr_id), r.clndr_name, r.clndr_data)
            for r in ups[-1].fr["CALENDAR"].itertuples()}

    # ---------------------------------------------------------------- dimensions
    dim_snapshot = []
    for i, s in enumerate(ups):
        bref = bl_proj[int(s.project["sum_base_proj_id"])]
        dim_snapshot.append(dict(snapshot_id=snap_id(s.data_date), label=f"S{i + 1}", data_date=s.data_date.date(),
                                 source_file=s.name, sha256=s.sha256, baseline_in_force=bref,
                                 baseline_file=f"DOP_{bref}.xer", baseline_sha256=bls[bref].sha256,
                                 cutoff_expected=cutoff.get(s.data_date.date().isoformat()), run_timestamp=run_ts,
                                 is_latest=i == len(ups) - 1))
    latest = ups[-1]
    acts_all = {}
    for s in ups:
        for r in s.act.to_dict("records"):
            acts_all[r["task_code"]] = r  # latest wins
    first_seen = {}
    for s in ups:
        for c in s.act.task_code:
            first_seen.setdefault(c, snap_id(s.data_date))
    dim_activity = []
    for code, r in sorted(acts_all.items()):
        asset = r["level1"]
        dim_activity.append(dict(activity_id=code, activity_name=r["task_name"], activity_type=r["task_type"],
                                 is_milestone=r["task_type"] in ("TT_Mile", "TT_FinMile"), calendar_id=r["clndr_id"],
                                 wbs_id=r["wbs_id"], wbs_path=r["path"], asset_code=asset,
                                 asset_name=ASSETS.get(asset), workstream_code=r["level2"],
                                 workstream_name=WORKSTREAMS.get(r["level2"]), package_code=r["level3"],
                                 package_name=PACKAGES.get(r["level3"]), owner_code=r["OWN"] or "UNASSIGNED",
                                 phase=r["PHS"], interface_role=r["IFC"] or "NONE", readiness_gate=r["RG"],
                                 first_snapshot_id=first_seen[code], in_bl0=code in bl0, in_bl1=code in bl1))
    from .load import wbs_paths
    dim_wbs = wbs_paths(latest.fr["PROJWBS"]).to_dict("records")
    dim_code = []
    t = latest.fr["ACTVTYPE"].set_index("actv_code_type_id")["actv_code_type"].to_dict()
    for r in latest.fr["ACTVCODE"].itertuples():
        dim_code.append(dict(code_type=t[r.actv_code_type_id], code_value=r.short_name, code_name=r.actv_code_name))
    dim_owner = [dict(owner_code=k, owner_name=v, accountable_role=OWNER_LEADS[k]) for k, v in OWNERS.items()]
    dim_owner.append(dict(owner_code="UNASSIGNED", owner_name="Owner code missing", accountable_role="Programme Controls Manager"))
    dim_calendar = [dict(calendar_id=r.clndr_id, calendar_name=r.clndr_name, hours_per_day=r.day_hr_cnt,
                         hours_per_week=r.week_hr_cnt, working_days=len(cals[int(r.clndr_id)].workweek),
                         holiday_exceptions=len(cals[int(r.clndr_id)].holidays))
                    for r in latest.fr["CALENDAR"].itertuples()]
    dim_date = []
    d = dt.date(2025, 1, 1)
    while d <= dt.date(2028, 12, 31):
        dim_date.append(dict(date_key=int(d.strftime("%Y%m%d")), date=d, year=d.year, quarter=f"Q{(d.month - 1) // 3 + 1}",
                             month=d.month, month_name=d.strftime("%b"), year_month=d.strftime("%Y-%m"),
                             iso_week=d.isocalendar()[1], weekday=d.strftime("%a"), is_weekend=d.weekday() in (4, 5)))
        d += dt.timedelta(days=1)

    # ---------------------------------------------------------------- facts per snapshot
    fas, frel, fms, fif, fdc, fdo, fown, summary = [], [], [], [], [], [], [], []
    quality = {}
    interfaces = read_csv(reg / "interfaces.csv")
    prev_rows = {c: r for c, r in ((r["task_code"], r) for r in bls["BL0"].act.to_dict("records"))}
    for i, s in enumerate(ups):
        sid = snap_id(s.data_date)
        dd = s.data_date
        bref = bl_proj[int(s.project["sum_base_proj_id"])]
        bl_in = bl0 if bref == "BL0" else bl1
        prev = ups[i - 1] if i else bls["BL0"]
        q = assess(s, prev, bls[bref], dt.date.fromisoformat(cutoff[dd.date().isoformat()]))
        quality[sid] = q
        eng = q["engine"]
        flags = {}
        for c in q["checks"]:
            for item in c["offenders"]:
                for aid in ([item.split("->")[0], item.split("->")[1].split(":")[0]] if "->" in item else [item]):
                    flags.setdefault(aid, set()).add(c["check_id"])
        rows = s.act.to_dict("records")
        for r in rows:
            code = r["task_code"]
            st, fi = start_of(r), finish_of(r)
            b0 = bl0.get(code, (None, None))
            b1 = bl1.get(code, (None, None))
            bi = bl_in.get(code, (None, None))
            pr = prev_rows.get(code)
            pfin = finish_of(pr) if pr else None
            pst = start_of(pr) if pr else None
            tf = r["total_float_hr_cnt"]
            ms = r["task_type"] in ("TT_Mile", "TT_FinMile")
            # look-back: previous forecast said this would start/finish in the last 14 days
            lb_event, lb_done = None, None
            if pfin is not None and dd - D14 <= pfin < dd and (pr["status_code"] != "TK_Complete"):
                lb_event, lb_done = "finish", r["status_code"] == "TK_Complete"
            elif pst is not None and dd - D14 <= pst < dd and pr["act_start_date"] is None:
                lb_event, lb_done = "start", r["act_start_date"] is not None
            la_start = r["status_code"] == "TK_NotStart" and st is not None and dd <= st < dd + D14
            la_finish = r["status_code"] != "TK_Complete" and fi is not None and dd <= fi < dd + D14
            pct_d = 100.0 if r["status_code"] == "TK_Complete" else (
                0.0 if r["status_code"] == "TK_NotStart" or not r["target_drtn_hr_cnt"] else
                round(100 * (r["target_drtn_hr_cnt"] - r["remain_drtn_hr_cnt"]) / r["target_drtn_hr_cnt"], 1))
            cal = cals[int(r["clndr_id"])]
            fas.append(dict(
                snapshot_id=sid, activity_id=code, status=r["status_code"], pct_duration=pct_d,
                pct_physical=r["phys_complete_pct"], orig_dur_d=r["target_drtn_hr_cnt"] / H,
                rem_dur_d=(r["remain_drtn_hr_cnt"] or 0) / H, actual_start=r["act_start_date"],
                actual_finish=r["act_end_date"], start=st, finish=fi, late_start=r["late_start_date"],
                late_finish=r["late_end_date"], total_float_d=None if tf is None else tf / H,
                free_float_d=None if r["free_float_hr_cnt"] is None else r["free_float_hr_cnt"] / H,
                is_critical=tf is not None and tf <= 0,
                is_near_critical=tf is not None and 0 < tf <= near_critical_days * H,
                is_longest_path=r["driving_path_flag"] == "Y", bl0_start=b0[0], bl0_finish=b0[1], bl1_start=b1[0],
                bl1_finish=b1[1], bl_start=bi[0], bl_finish=bi[1], var_finish_bl0_d=days(fi, b0[1]),
                var_finish_bl1_d=days(fi, b1[1]), var_finish_bl_d=days(fi, bi[1]), prev_finish=pfin,
                slip_vs_prev_d=days(fi, pfin), lookback_event=lb_event, lookback_achieved=lb_done,
                lookahead_start=la_start, lookahead_finish=la_finish, lookahead=la_start or la_finish,
                planned_pct_bl=round(planned_pct(bi[0], bi[1], dd, cal, ms), 1),
                constraint_type=r["cstr_type"] or None, constraint_date=r["cstr_date"],
                dq_flags=",".join(sorted(flags.get(code, []))) or None))
            if ms:
                fms.append(dict(snapshot_id=sid, activity_id=code, forecast_finish=fi, bl0_finish=b0[1],
                                bl1_finish=b1[1], var_bl0_d=days(fi, b0[1]), var_bl1_d=days(fi, b1[1]),
                                movement_vs_prev_d=days(fi, pfin), total_float_d=None if tf is None else tf / H,
                                status=r["status_code"], owner_code=r["OWN"] or "UNASSIGNED"))
        for r in s.rel.itertuples():
            key = f"{r.pred}->{r.succ}:{r.type}"
            frel.append(dict(snapshot_id=sid, pred_id=r.pred, succ_id=r.succ, rel_type=r.type, lag_d=r.lag_h / H,
                             is_driving=bool(eng.rel_driving.get(key)),
                             slack_d=None if key not in eng.rel_slack else eng.rel_slack[key] / H))
        byc = {r["task_code"]: r for r in rows}
        for itf in interfaces:
            g, rv = byc.get(itf["giver"]), byc.get(itf["receiver"])
            gf = finish_of(g)
            need = bl_in.get(itf["receiver"], (None, None))[0]
            gap = days(gf, need)
            status = "Complete" if g["status_code"] == "TK_Complete" else (
                "Late" if gap is not None and gap > 0 else "At risk" if gap is not None and gap > -7 else "On track")
            fif.append(dict(snapshot_id=sid, interface_id=itf["interface_id"], giver_id=itf["giver"],
                            receiver_id=itf["receiver"], description=itf["description"],
                            giver_owner=g["OWN"] or "UNASSIGNED", receiver_owner=rv["OWN"] or "UNASSIGNED",
                            giver_asset=g["level1"], receiver_asset=rv["level1"], giver_ws=g["level2"],
                            receiver_ws=rv["level2"], need_by=need, giver_forecast=gf, gap_days=gap, status=status,
                            giver_tf_d=None if g["total_float_hr_cnt"] is None else g["total_float_hr_cnt"] / H))
        for c in q["checks"]:
            fdc.append(dict(snapshot_id=sid, **{k: v for k, v in c.items() if k != "offenders"}))
            for item in c["offenders"]:
                aid = item.split("->")[1].split(":")[0] if "->" in item else item
                fdo.append(dict(snapshot_id=sid, check_id=c["check_id"], item=item, activity_id=aid,
                                owner_code=(byc.get(aid) or {}).get("OWN") or "UNASSIGNED"))
        for o in q["owner_scorecard"]:
            fown.append(dict(snapshot_id=sid, **o))
        d1 = byc[DAY1_ID]
        summary.append(dict(snapshot_id=sid, label=f"S{i + 1}", data_date=dd.date(), baseline=bref,
                            day1_forecast=d1["early_end_date"], day1_tf_d=d1["total_float_hr_cnt"] / H,
                            day1_var_bl0_d=days(d1["early_end_date"], bl0[DAY1_ID][1]),
                            day1_var_bl1_d=days(d1["early_end_date"], bl1[DAY1_ID][1]),
                            dq_score=q["dq_score"], dq_rating=q["dq_rating"], cpli=round(q["cpli"], 3),
                            bei=round(q["bei"], 3)))
        prev_rows = byc
    fact_activity = pd.DataFrame(fas)
    loe_ids = {c for c, r in acts_all.items() if r["task_type"] == "TT_LOE"}
    # counts and float erosion per snapshot
    for srow in summary:
        f = fact_activity[fact_activity.snapshot_id == srow["snapshot_id"]]
        inc = f[(f.status != "TK_Complete") & ~f.activity_id.isin(loe_ids)]   # LOE excluded, as in R12 / D07
        srow.update(critical_count=int(inc.is_critical.sum()), near_critical_count=int(inc.is_near_critical.sum()),
                    longest_path_count=int(f.is_longest_path.sum()), negative_float_count=int((inc.total_float_d < 0).sum()),
                    min_float_d=float(inc.total_float_d.min()), avg_float_d=round(float(inc.total_float_d.mean()), 1),
                    activities=len(f), complete=int((f.status == "TK_Complete").sum()),
                    in_progress=int((f.status == "TK_Active").sum()), not_started=int((f.status == "TK_NotStart").sum()))
    for a, b in zip(summary, summary[1:]):
        b["float_erosion_d"] = round(b["day1_tf_d"] - a["day1_tf_d"], 1)
        b["day1_movement_d"] = days(b["day1_forecast"], a["day1_forecast"])
    summary[0]["float_erosion_d"] = round(summary[0]["day1_tf_d"] - bls_tf(bls["BL0"]), 1)
    summary[0]["day1_movement_d"] = days(summary[0]["day1_forecast"], bl0[DAY1_ID][1])

    # ---------------------------------------------------------------- registers
    risks = {r["risk_id"]: r for r in read_csv(reg / "risk_register.csv")}
    scores = read_csv(reg / "risk_scores.csv")
    frisk = []
    prev_score = {}
    for sc in scores:
        sid = snap_id(dt.datetime.fromisoformat(sc["data_date"]))
        rk = risks[sc["risk_id"]]
        linked = rk["linked_activities"].split(";")
        f = fact_activity[(fact_activity.snapshot_id == sid) & fact_activity.activity_id.isin(linked)]
        score = int(sc["score"])
        trend = score - prev_score.get(sc["risk_id"], score)
        prev_score[sc["risk_id"]] = score
        frisk.append(dict(snapshot_id=sid, risk_id=sc["risk_id"], title=rk["title"], owner_code=rk["owner"],
                          probability=int(sc["probability"]), impact=int(sc["impact"]), score=score,
                          rating="High" if score >= 15 else "Medium" if score >= 8 else "Low", trend=trend,
                          linked_activities=rk["linked_activities"], mitigation=rk["mitigation"],
                          mitigation_owner=rk["mitigation_owner"], schedule_impact_days=int(rk["schedule_impact_days"]),
                          min_linked_float_d=None if f.total_float_d.dropna().empty else float(f.total_float_d.min())))
    latest_dd = ups[-1].data_date
    lf = fact_activity[fact_activity.snapshot_id == snap_id(latest_dd)].set_index("activity_id")
    fdec = []
    for d_ in read_csv(reg / "decision_log.csv"):
        need = dt.datetime.fromisoformat(d_["needed_by"])
        la = d_["linked_activity"]
        fdec.append(dict(decision_id=d_["decision_id"], ask=d_["ask"], owner=d_["owner"],
                         raised_data_date=d_["raised_data_date"], needed_by=need.date(), status=d_["status"],
                         closed_on=d_["closed_on"] or None, linked_activity=la,
                         linked_forecast=lf.at[la, "finish"] if la in lf.index else None,
                         linked_tf_d=lf.at[la, "total_float_d"] if la in lf.index else None,
                         days_to_need=(need.date() - latest_dd.date()).days,
                         overdue=d_["status"] == "Open" and need.date() < latest_dd.date(), outcome=d_["outcome"]))
    fchg = [dict(c, day1_impact_days=int(c["day1_impact_days"]) if c["day1_impact_days"] else None)
            for c in read_csv(reg / "change_register.csv")]

    # ---------------------------------------------------------------- scenarios on the latest snapshot
    options = json.loads((reg / "recovery_options.json").read_text(encoding="utf-8"))
    q_last = quality[snap_id(latest_dd)]
    base = q_last["engine"]
    net = q_last["net"]
    from ..registers import SCENARIO_COMBOS
    fscn = [dict(scenario_id="BASE", name="Current forecast (no recovery)", options="", owner="",
                 day1_forecast=base.day1().ef, day1_impact_days=0.0, day1_tf_d=base.day1().tf / H,
                 float_gain_d=0.0, neg_float_count=sum(1 for r in base.acts.values() if r.tf is not None and r.tf < 0),
                 near_critical_count=sum(1 for r in base.acts.values() if r.near_critical), recommended=False,
                 decision="", cost="", description="")]
    by_id = {o["id"]: o for o in options}
    for sid_, ids_ in SCENARIO_COMBOS:
        deltas = []
        for oid in ids_:
            for dlt in by_id[oid]["deltas"]:
                dlt = dict(dlt)
                if dlt.get("op") == "constraint":
                    dlt["date"] = to_time(dt.date.fromisoformat(dlt["date"]))
                deltas.append(dlt)
        res = compare_scenario(base, net, deltas, near_critical_days)
        fscn.append(dict(scenario_id=sid_, name=" + ".join(by_id[o]["name"] for o in ids_), options=",".join(ids_),
                         owner="; ".join(by_id[o]["owner"] for o in ids_), day1_forecast=res["day1_ef"],
                         day1_impact_days=res["day1_impact_days"], day1_tf_d=res["day1_tf_days"],
                         float_gain_d=res["float_gain_days"], neg_float_count=res["neg_float_count"],
                         near_critical_count=res["near_critical_count"], recommended=False,
                         decision=", ".join(by_id[o]["decision"] for o in ids_ if by_id[o]["decision"]),
                         cost="; ".join(by_id[o]["cost"] for o in ids_),
                         description=" ".join(by_id[o]["description"] for o in ids_)))
    ok = [s_ for s_ in fscn[1:] if s_["day1_tf_d"] >= RECOVERY_MARGIN_D]
    rec = min(ok, key=lambda s_: (len(s_["options"].split(",")), -s_["day1_tf_d"])) if ok else \
        max(fscn[1:], key=lambda s_: s_["day1_tf_d"])
    rec["recommended"] = True
    for s_ in fscn:
        s_["day1_forecast"] = dt.datetime(*[int(x) for x in _fmt(s_["day1_forecast"])])
        s_["residual_risk"] = ("High" if s_["day1_tf_d"] < 0 else "Medium" if s_["day1_tf_d"] < 5 or
                               s_["near_critical_count"] > 25 else "Low")

    # ---------------------------------------------------------------- readiness chain and S-curve
    readiness = []
    for s in ups:
        sid = snap_id(s.data_date)
        f = fact_activity[fact_activity.snapshot_id == sid].set_index("activity_id")
        for a in VENUES:
            prev_date = None
            for sfx, label in READINESS_STAGES:
                code = f"{a}-{sfx}"
                r = f.loc[code]
                need = r.late_finish if r.status != "TK_Complete" else r.finish
                readiness.append(dict(snapshot_id=sid, asset_code=a, stage=label, activity_id=code,
                                      forecast=r.finish, baseline=r.bl_finish, need_by=need,
                                      gap_d=days(r.finish, need), var_bl_d=r.var_finish_bl_d,
                                      span_from_prev_d=days(r.finish, prev_date), status=r.status,
                                      total_float_d=r.total_float_d))
                prev_date = r.finish
    s_curve = build_s_curve(ups, bls, fact_activity, cals)
    return dict(dim_snapshot=pd.DataFrame(dim_snapshot), dim_activity=pd.DataFrame(dim_activity),
                dim_wbs=pd.DataFrame(dim_wbs), dim_code=pd.DataFrame(dim_code), dim_owner=pd.DataFrame(dim_owner),
                dim_calendar=pd.DataFrame(dim_calendar), dim_date=pd.DataFrame(dim_date),
                fact_activity_snapshot=fact_activity, fact_relationship=pd.DataFrame(frel),
                fact_milestone_trend=pd.DataFrame(fms), fact_interface=pd.DataFrame(fif),
                fact_dcma_check=_nullable_int(pd.DataFrame(fdc), "count"), fact_dcma_offender=pd.DataFrame(fdo),
                fact_owner_scorecard=pd.DataFrame(fown), fact_snapshot_summary=pd.DataFrame(summary),
                fact_risk=pd.DataFrame(frisk), fact_decision=pd.DataFrame(fdec), fact_change=pd.DataFrame(fchg),
                fact_scenario=pd.DataFrame(fscn), fact_readiness=pd.DataFrame(readiness),
                fact_s_curve=pd.DataFrame(s_curve), _quality=quality)


def _fmt(t):
    from ..calendars import from_time
    x = from_time(t)
    return x.year, x.month, x.day, x.hour


def _nullable_int(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Whole numbers with gaps (an N/A check has no count): keep Python ints and None so the CSV writes 36 and an
    empty cell, and the JSON writes null, instead of pandas turning the column into 36.0 / NaN."""
    df[col] = pd.Series([None if pd.isna(v) else int(v) for v in df[col]], dtype=object, index=df.index)
    return df


def weighted_pct_complete(rows) -> float:
    """Duration-weighted % complete over normal tasks (LOE and milestones excluded)."""
    num = den = 0.0
    for r in rows:
        if r["task_type"] != "TT_Task" or not r["target_drtn_hr_cnt"]:
            continue
        w = float(r["target_drtn_hr_cnt"])
        if r["status_code"] == "TK_Complete":
            p = 100.0
        elif r["status_code"] == "TK_NotStart":
            p = 0.0
        else:
            p = 100.0 * (w - float(r["remain_drtn_hr_cnt"])) / w
        num += w * p
        den += w
    return round(num / den, 2) if den else 0.0


def bls_tf(bl) -> float:
    r = bl.act.set_index("task_code").loc[DAY1_ID]
    return r["total_float_hr_cnt"] / H


def build_s_curve(ups, bls, fact_activity, cals) -> list[dict]:
    """Monthly duration-weighted % complete: planned (BL0, BL1), forecast (latest schedule), actual (data dates)."""
    def weighted(sch_rows, when, mode):
        num = den = 0.0
        for r in sch_rows:
            if r["task_type"] in ("TT_LOE", "TT_Mile", "TT_FinMile") or not r["target_drtn_hr_cnt"]:
                continue
            w = r["target_drtn_hr_cnt"]
            cal = cals[int(r["clndr_id"])]
            if mode == "plan":
                p = planned_pct(start_of(r), finish_of(r), when, cal, False)
            else:
                p = planned_pct(r["early_start_date"] if r["act_start_date"] is None else r["act_start_date"],
                                finish_of(r), when, cal, False)
            num += w * p
            den += w
        return round(num / den, 2) if den else 0.0

    months = []
    d = dt.datetime(2025, 3, 31)
    while d <= dt.datetime(2027, 10, 31):
        months.append(d)
        nm = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        d = (nm + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    b0 = bls["BL0"].act.to_dict("records")
    b1 = bls["BL1"].act.to_dict("records")
    lt = ups[-1].act.to_dict("records")
    out = [dict(date=m.date(), planned_bl0=weighted(b0, m, "plan"), planned_bl1=weighted(b1, m, "plan"),
                forecast=weighted(lt, m, "plan") if m >= ups[-1].data_date else None, actual=None) for m in months]
    for s in ups:
        act = weighted_pct_complete(s.act.to_dict("records"))
        out.append(dict(date=s.data_date.date(), planned_bl0=weighted(b0, s.data_date, "plan"),
                        planned_bl1=weighted(b1, s.data_date, "plan"), forecast=None, actual=act))
    return sorted(out, key=lambda r: (r["date"], r["actual"] is None))
