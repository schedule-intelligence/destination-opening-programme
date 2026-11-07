"""Build a CPM engine network from a parsed XER. This is what lets the pipeline re-schedule a P6 export
(reconciliation control R16), run the DCMA critical-path test and model recovery scenarios on it."""
from __future__ import annotations

from .calendars import Calendar, to_time
from .cpm import Activity, Network, Rel

DEFAULT_FINISH_CODE = "PRG-D1R-M999"


def _t(v):
    return None if v is None else to_time(v)


def network_from_frames(fr: dict, finish_code: str = DEFAULT_FINISH_CODE, cap_actuals: bool = True) -> Network:
    proj = fr["PROJECT"].iloc[0]
    dd = _t(proj["last_recalc_date"])
    cals = {int(r.clndr_id): Calendar.from_clndr_data(int(r.clndr_id), r.clndr_name, r.clndr_data)
            for r in fr["CALENDAR"].itertuples()}
    task = fr["TASK"]
    code_of = dict(zip(task["task_id"], task["task_code"]))
    acts = {}
    for r in task.itertuples():
        ast, aen = _t(r.act_start_date), _t(r.act_end_date)
        if cap_actuals:  # actuals after the data date are invalid (D09); P6 would not accept them on reschedule
            c = cals[int(r.clndr_id)]
            if ast is not None and ast > dd:
                ast = c.start_at(c.pos(dd) - 8)
            if aen is not None and aen > dd:
                aen = c.finish_at(c.pos(dd))
        rem = r.remain_drtn_hr_cnt
        acts[r.task_code] = Activity(
            r.task_code, r.task_name, int(r.clndr_id), int(r.target_drtn_hr_cnt or 0),
            int(rem) if rem is not None and r.status_code == "TK_Active" else None,
            r.task_type, r.status_code, ast, aen if r.status_code == "TK_Complete" else None,
            r.cstr_type or "", _t(r.cstr_date))
    rels = [Rel(code_of[r.pred_task_id], code_of[r.task_id], r.pred_type.replace("PR_", ""), int(r.lag_hr_cnt or 0))
            for r in fr["TASKPRED"].itertuples()]
    mfb = _t(proj["plan_end_date"])
    return Network(acts, rels, cals, dd, mfb, finish_code if finish_code in acts else None)
