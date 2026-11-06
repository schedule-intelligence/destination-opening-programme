"""Answer-first narrative generated from the model, shared by the dashboard JSON and the PowerPoint packs so
both always tell the same story with the same numbers."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from ..programme import ASSETS, DAY1_ID, DAY1_TARGET, OWNERS


def fd(d) -> str:
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return "n/a"
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    return d.strftime("%d-%b-%Y")


def sd(n, unit="d") -> str:
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "n/a"
    n = float(n)
    return f"{'+' if n > 0 else ''}{n:.0f} {unit}" if unit else f"{'+' if n > 0 else ''}{n:.0f}"


def plural(n, word):
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word[:-1]}ies" if word.endswith("y") and word[-2] not in "aeiou" else f"{n} {word}s"


def moved(n) -> str:
    if n is None or (isinstance(n, float) and pd.isna(n)) or n == 0:
        return "did not move"
    return f"moved {abs(n):.0f} days {'later' if n > 0 else 'earlier'}"


def snapshot_narrative(m: dict, sid: int) -> dict:
    S = m["fact_snapshot_summary"].set_index("snapshot_id")
    s = S.loc[sid]
    ids = list(S.index)
    k = ids.index(sid)
    prev = S.loc[ids[k - 1]] if k else None
    fa = m["fact_activity_snapshot"]
    f = fa[fa.snapshot_id == sid].merge(m["dim_activity"], on="activity_id")
    inc = f[f.status != "TK_Complete"]
    tf = s.day1_tf_d
    target = fd(DAY1_TARGET)
    scen = m["fact_scenario"]
    rec = scen[scen.recommended].iloc[0] if sid == ids[-1] else None
    dec = m["fact_decision"]
    open_dec = dec[dec.status == "Open"]
    # longest-path driver
    lp = inc[inc.is_longest_path & (inc.activity_type == "TT_Task")].sort_values("start")
    driver_asset = lp.asset_code.mode().iloc[0] if not lp.empty else None
    drivers = lp.head(3).activity_name.tolist()
    if tf < 0:
        head = (f"Day 1 Opening is forecast for {fd(s.day1_forecast)}, {abs(tf):.0f} days beyond the {target} target")
    else:
        head = f"Day 1 Opening is forecast for {fd(s.day1_forecast)} with {tf:.0f} days of float to the {target} target"
    if rec is not None and tf < 0:
        need = pd.to_datetime(open_dec[open_dec.decision_id.isin(rec.decision.split(", "))].needed_by).max()
        head += (f"; approving recovery {rec.options.replace(',', ' + ')} by {fd(need)} returns it to "
                 f"{fd(rec.day1_forecast)} ({sd(rec.day1_tf_d)} float)")
    elif prev is not None and s.day1_movement_d:
        head += f"; it {moved(s.day1_movement_d)} this period"
    head += "."
    msgs = []
    if driver_asset:
        msgs.append(f"The longest path runs through {ASSETS[driver_asset]}: " + ", ".join(drivers) + ".")
    if prev is not None:
        msgs.append(f"Day 1 {moved(s.day1_movement_d)} since {fd(prev.data_date)}; float {sd(prev.day1_tf_d)} -> "
                    f"{sd(tf)}; {plural(int(s.negative_float_count), 'activity')} carry negative float.")
    itf = m["fact_interface"]
    late = itf[(itf.snapshot_id == sid) & (itf.status == "Late")]
    if not late.empty:
        msgs.append(f"{plural(len(late), 'interface')} late against the receiver's need date, worst "
                    f"{late.gap_days.max():.0f} days ({late.sort_values('gap_days').iloc[-1].description}).")
    dq_prev = prev.dq_score if prev is not None else None
    msgs.append(f"Schedule quality {s.dq_score:.0f}/100 ({s.dq_rating})" +
                (f", {sd(s.dq_score - dq_prev, 'pts')} vs last period." if dq_prev is not None else "."))
    if sid == ids[-1] and not open_dec.empty:
        msgs.append(f"{plural(len(open_dec), 'decision')} open; " +
                    "; ".join(f"{r.decision_id} {r.owner} by {fd(r.needed_by)}" for r in open_dec.itertuples()) + ".")
    # chart so-whats
    ms = m["fact_milestone_trend"]
    msk = ms[ms.snapshot_id == sid]
    slipped = msk[(msk.movement_vs_prev_d.fillna(0) > 0)]
    lb = f[f.lookback_event.notna()]
    lb_done = int(lb.lookback_achieved.sum()) if not lb.empty else 0
    la = f[f.lookahead]
    la_crit = la[la.is_critical | la.is_longest_path]
    rd = m["fact_readiness"]
    rds = rd[(rd.snapshot_id == sid)]
    gap, tail = {}, {}
    for a, g in rds.groupby("asset_code"):
        c = g[g.stage == "Construction complete"].forecast.iloc[0]
        r = g[g.stage == "Day 1 ready"]
        tail[a] = (r.forecast.iloc[0] - c).days
        gap[a] = (r.gap_d.iloc[0], r.forecast.iloc[0], r.need_by.iloc[0])
    worst = max(gap, key=lambda a: gap[a][0]) if gap else None
    so = {
        "day1_trend": f"Day 1 forecast {fd(s.day1_forecast)} ({sd(s.day1_var_bl0_d)} vs BL0, {sd(s.day1_var_bl1_d)} vs BL1).",
        "milestones": f"{plural(len(slipped), 'milestone')} slipped this period; "
                      f"{int((msk.total_float_d < 0).sum())} carry negative float.",
        "critical_path": (f"{plural(int(s.longest_path_count), 'activity')} on the longest path; "
                          f"{int(s.near_critical_count)} near-critical (TF <= {m['near_critical_days']} d)."),
        "lookback": f"{lb_done} of {len(lb)} items planned for the last two weeks were achieved.",
        "lookahead": f"{len(la)} activities start or finish in the next 14 days; {len(la_crit)} are critical or on the longest path.",
        "readiness": (f"{ASSETS[worst]} is the readiness constraint: Day 1 ready {fd(gap[worst][1])} vs need-by "
                      f"{fd(gap[worst][2])} ({sd(gap[worst][0])}); construction-complete to ready-to-operate takes "
                      f"{tail[worst]} days." if worst else ""),
        "interfaces": f"{len(late)} of {int((itf.snapshot_id == sid).sum())} interfaces late against need date.",
        "dq": f"DQ {s.dq_score:.0f}/100 ({s.dq_rating}); CPLI {s.cpli:.2f}, BEI {s.bei:.2f}.",
    }
    return {"headline": head, "messages": msgs[:5], "so_what": so}


def owner_name(code: str) -> str:
    return OWNERS.get(code, "Owner code missing")
