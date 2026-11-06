"""Critical Path Method engine (P6-style conventions).

Conventions (see PLAN.md section 5 and ASSUMPTIONS.md):
* Integer hours; each activity is scheduled in its own calendar's work positions.
* Lags are in working hours on the SUCCESSOR's calendar (a P6 "calendar for scheduling relationship lag" option;
  P6 ships with the predecessor calendar as default - see ASSUMPTIONS A03).
* Data date: no remaining work before it. Completed activities keep actuals, have no float.
* In-progress activities: remaining duration starts at max(data date, logic): retained logic.
* Open ends: late finish = project "must finish by" if given, else project early finish.
* TF = LF - EF in the activity's calendar (hours). FF = slack to the earliest successor.
* Critical: TF <= 0. Near-critical: 0 < TF <= threshold. Longest path: driving trace from the
  project finish activity (separate flag).
* LOE: spans SS-predecessor start to FF-predecessor finish; never drives its predecessors.
"""
from __future__ import annotations

import copy
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .calendars import HOURS_PER_DAY, Calendar

TASK, START_MS, FINISH_MS, LOE = "TT_Task", "TT_Mile", "TT_FinMile", "TT_LOE"
NOT_STARTED, ACTIVE, COMPLETE = "TK_NotStart", "TK_Active", "TK_Complete"

HARD_CONSTRAINTS = {"CS_MANDSTART", "CS_MANDFIN", "CS_MSOB", "CS_MEOB", "CS_MSO", "CS_MEO"}


@dataclass
class Activity:
    id: str
    name: str = ""
    cal: int = 1
    dur: int = 0                     # original / at-completion planned duration (hours)
    rem: int | None = None           # remaining duration (hours); None = dur
    type: str = TASK
    status: str = NOT_STARTED
    act_start: int | None = None
    act_finish: int | None = None
    cstr_type: str = ""
    cstr_date: int | None = None
    meta: dict = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        if self.status == COMPLETE:
            return 0
        return self.dur if self.rem is None else self.rem

    @property
    def is_milestone(self) -> bool:
        return self.type in (START_MS, FINISH_MS)


@dataclass
class Rel:
    pred: str
    succ: str
    type: str = "FS"
    lag: int = 0                     # hours

    @property
    def key(self) -> str:
        return f"{self.pred}->{self.succ}:{self.type}"


@dataclass
class Network:
    activities: dict[str, Activity]
    rels: list[Rel]
    calendars: dict[int, Calendar]
    data_date: int
    must_finish_by: int | None = None
    finish_activity: str | None = None    # for the longest-path trace (Day 1)

    def copy(self) -> "Network":
        return Network(copy.deepcopy(self.activities), copy.deepcopy(self.rels), self.calendars,
                       self.data_date, self.must_finish_by, self.finish_activity)


@dataclass
class ActResult:
    es: int | None = None
    ef: int | None = None
    ls: int | None = None
    lf: int | None = None
    rs: int | None = None            # remaining early start (in-progress) / early start
    tf: int | None = None            # hours
    ff: int | None = None            # hours
    critical: bool = False
    near_critical: bool = False
    longest_path: bool = False
    driving_preds: list[str] = field(default_factory=list)


@dataclass
class Schedule:
    net: Network
    acts: dict[str, ActResult]
    rel_driving: dict[str, bool]
    rel_slack: dict[str, int]
    project_finish: int
    order: list[str]
    near_critical_hours: int

    def day1(self) -> ActResult:
        return self.acts[self.net.finish_activity]


class CycleError(ValueError):
    pass


def topo_order(acts: dict[str, Activity], rels: list[Rel]) -> list[str]:
    indeg = {a: 0 for a in acts}
    out = defaultdict(list)
    for r in rels:
        out[r.pred].append(r.succ)
        indeg[r.succ] += 1
    q = deque(sorted(a for a, d in indeg.items() if d == 0))
    order = []
    while q:
        a = q.popleft()
        order.append(a)
        for s in out[a]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    if len(order) != len(acts):
        raise CycleError("network contains a logic loop: "
                         + ", ".join(sorted(a for a, d in indeg.items() if d > 0))[:300])
    return order


def schedule(net: Network, near_critical_days: int = 10) -> Schedule:
    acts, cals = net.activities, net.calendars
    for r in net.rels:
        if r.pred not in acts or r.succ not in acts:
            raise KeyError(f"relationship references unknown activity: {r.key}")
    order = topo_order(acts, net.rels)
    preds = defaultdict(list)
    succs = defaultdict(list)
    for r in net.rels:
        preds[r.succ].append(r)
        succs[r.pred].append(r)
    res: dict[str, ActResult] = {a: ActResult() for a in acts}
    rel_cand: dict[str, int] = {}
    dd = net.data_date

    # ------------------------------------------------------------------ forward pass
    start_p: dict[str, int] = {}
    finish_p: dict[str, int] = {}
    for aid in order:
        a = acts[aid]
        c = cals[a.cal]
        r = res[aid]
        if a.status == COMPLETE:
            r.es, r.ef = a.act_start, a.act_finish
            r.rs = a.act_start
            start_p[aid], finish_p[aid] = c.pos(a.act_start), c.pos(a.act_finish)
            continue
        dur = a.remaining
        dd_p = c.pos(dd)
        es_c, ef_c = [], []
        for rel in preds[aid]:
            p = res[rel.pred]
            if rel.type == "FS":
                v = c.pos(p.ef) + rel.lag
                es_c.append(v)
            elif rel.type == "SS":
                v = c.pos(p.es) + rel.lag
                es_c.append(v)
            elif rel.type == "FF":
                v = c.pos(p.ef) + rel.lag
                ef_c.append(v)
            else:  # SF
                v = c.pos(p.es) + rel.lag
                ef_c.append(v)
            rel_cand[rel.key] = v
        if a.type == LOE:
            s = max([dd_p] + es_c) if a.status == NOT_STARTED else dd_p
            f = max([s] + ef_c)
            if a.status == ACTIVE:
                r.es = a.act_start
                start_p[aid] = dd_p
            else:
                r.es = c.start_at(s)
                start_p[aid] = s
            r.rs = c.start_at(s)
            finish_p[aid] = f
            r.ef = c.finish_at(f)
            continue
        s = max([dd_p] + es_c + [v - dur for v in ef_c])
        ct, cd = a.cstr_type, a.cstr_date
        if a.status == NOT_STARTED and cd is not None:
            if ct in ("CS_MSOA", "CS_MSO"):
                s = max(s, c.pos(cd))
            elif ct == "CS_MANDSTART":
                s = max(dd_p, c.pos(cd))
        if cd is not None:
            if ct in ("CS_MEOA", "CS_MEO"):
                s = max(s, c.pos(cd) - dur)
            elif ct == "CS_MANDFIN":
                s = max(dd_p, c.pos(cd) - dur)
        start_p[aid] = s
        finish_p[aid] = s + dur
        if a.status == ACTIVE:
            r.es = a.act_start
            r.rs = c.start_at(s)
            r.ef = c.finish_at(s + dur) if dur > 0 else c.finish_at(s)
        elif a.type == START_MS:
            r.es = r.ef = r.rs = c.start_at(s)
        elif a.type == FINISH_MS:
            r.es = r.ef = r.rs = c.finish_at(s)
        else:
            r.es = r.rs = c.start_at(s)
            r.ef = c.finish_at(s + dur)

    # relationship driving flags and slack (successor calendar hours)
    rel_driving, rel_slack = {}, {}
    for rel in net.rels:
        sa = acts[rel.succ]
        if sa.status == COMPLETE or rel.key not in rel_cand:
            rel_driving[rel.key] = False
            continue
        bind = start_p[rel.succ] if rel.type in ("FS", "SS") else finish_p[rel.succ]
        slack = bind - rel_cand[rel.key]
        rel_slack[rel.key] = slack
        rel_driving[rel.key] = slack == 0 and acts[rel.pred].status != COMPLETE
    for aid in acts:
        res[aid].driving_preds = [rel.pred for rel in preds[aid] if rel_driving.get(rel.key)]

    proj_finish = max(res[a].ef for a in acts)
    open_end_finish = net.must_finish_by if net.must_finish_by is not None else proj_finish

    # ------------------------------------------------------------------ backward pass
    late_s: dict[str, int] = {}
    late_f: dict[str, int] = {}
    loe_post = []
    for aid in reversed(order):
        a = acts[aid]
        if a.status == COMPLETE:
            continue
        c = cals[a.cal]
        r = res[aid]
        dur = finish_p[aid] - start_p[aid]
        lf_c, ls_c = [], []
        for rel in succs[aid]:
            s = acts[rel.succ]
            if s.status == COMPLETE or s.type == LOE:
                continue
            cs = cals[s.cal]
            if rel.type == "FS":
                lf_c.append(c.pos(cs.start_at(late_s[rel.succ] - rel.lag)))
            elif rel.type == "FF":
                lf_c.append(c.pos(cs.start_at(late_f[rel.succ] - rel.lag)))
            elif rel.type == "SS":
                ls_c.append(c.pos(cs.start_at(late_s[rel.succ] - rel.lag)))
            else:
                ls_c.append(c.pos(cs.start_at(late_f[rel.succ] - rel.lag)))
        if a.type == LOE and not lf_c and not ls_c:
            loe_post.append(aid)
            continue
        cands = lf_c + [v + dur for v in ls_c]
        f = min(cands) if cands else c.pos(open_end_finish)
        ct, cd = a.cstr_type, a.cstr_date
        if cd is not None:
            if ct in ("CS_MEOB", "CS_MEO"):
                f = min(f, c.pos(cd))
            elif ct in ("CS_MSOB", "CS_MSO") and a.status == NOT_STARTED:
                f = min(f, c.pos(cd) + dur)
            elif ct == "CS_MANDFIN":
                f = c.pos(cd)
            elif ct == "CS_MANDSTART" and a.status == NOT_STARTED:
                f = c.pos(cd) + dur
        if aid == net.finish_activity and net.must_finish_by is not None:
            f = min(f, c.pos(net.must_finish_by))
        late_f[aid] = f
        late_s[aid] = f - dur
        _set_late(r, a, c, late_s[aid], late_f[aid], start_p[aid], finish_p[aid])

    for aid in loe_post:
        a, c, r = acts[aid], cals[acts[aid].cal], res[aid]
        dur = finish_p[aid] - start_p[aid]
        fc = []
        for rel in preds[aid]:
            if rel.type in ("FF", "FS") and rel.pred in late_f:
                fc.append(c.pos(cals[acts[rel.pred].cal].finish_at(late_f[rel.pred])) + rel.lag)
        f = min(fc) if fc else c.pos(open_end_finish)
        f = max(f, finish_p[aid]) if not fc else f
        late_f[aid], late_s[aid] = f, f - dur
        _set_late(r, a, c, late_s[aid], late_f[aid], start_p[aid], finish_p[aid])

    # ------------------------------------------------------------------ free float
    for aid in acts:
        a = acts[aid]
        if a.status == COMPLETE:
            continue
        c = cals[a.cal]
        sl = []
        for rel in succs[aid]:
            s = acts[rel.succ]
            if s.status == COMPLETE or s.type == LOE:
                continue
            cs = cals[s.cal]
            if rel.type in ("FS", "SS"):
                bound = c.pos(cs.start_at(start_p[rel.succ] - rel.lag))
            else:
                bound = c.pos(cs.start_at(finish_p[rel.succ] - rel.lag))
            base = finish_p[aid] if rel.type in ("FS", "FF") else start_p[aid]
            sl.append(bound - base)
        ffv = min(sl) if sl else c.pos(open_end_finish) - finish_p[aid]
        res[aid].ff = min(ffv, res[aid].tf) if res[aid].tf is not None else ffv

    # ------------------------------------------------------------------ flags
    nc_h = near_critical_days * HOURS_PER_DAY
    for aid, r in res.items():
        if r.tf is not None:
            r.critical = r.tf <= 0
            r.near_critical = 0 < r.tf <= nc_h
    fin = net.finish_activity or max(res, key=lambda k: (res[k].ef, k))
    net.finish_activity = fin
    stack, seen = [fin], set()
    while stack:
        aid = stack.pop()
        if aid in seen or acts[aid].status == COMPLETE:
            continue
        seen.add(aid)
        res[aid].longest_path = True
        stack.extend(res[aid].driving_preds)
    return Schedule(net, res, rel_driving, rel_slack, proj_finish, order, nc_h)


def _set_late(r: ActResult, a: Activity, c: Calendar, ls_p: int, lf_p: int, es_p: int, ef_p: int):
    if a.type == START_MS:
        r.ls = r.lf = c.start_at(ls_p)
    elif a.type == FINISH_MS:
        r.ls = r.lf = c.finish_at(lf_p)
    else:
        r.ls = c.start_at(ls_p)
        r.lf = c.finish_at(lf_p) if lf_p != ls_p else c.start_at(lf_p)
    r.tf = lf_p - ef_p


# ---------------------------------------------------------------------- DCMA critical-path test
def critical_path_test(net: Network, sched: Schedule | None = None, delay_days: int = 600) -> dict:
    """DCMA check 12: add `delay_days` to an incomplete longest-path task and confirm the project
    finish moves by the same amount (measured on the test activity's calendar, +-5 days tolerance
    for cross-calendar holiday differences)."""
    sched = sched or schedule(net)
    cand = [a for a in sched.order
            if sched.acts[a].longest_path and net.activities[a].type == TASK
            and net.activities[a].status != COMPLETE]
    if not cand:
        return {"pass": False, "activity": None, "delta_days": 0, "note": "no longest-path task"}
    test_id = cand[0]
    n2 = net.copy()
    t = n2.activities[test_id]
    extra = delay_days * HOURS_PER_DAY
    if t.status == ACTIVE:
        t.rem = t.remaining + extra
    t.dur += extra
    s2 = schedule(n2)
    c = net.calendars[net.activities[test_id].cal]
    old, new = sched.day1().ef, s2.day1().ef
    delta = (c.pos(new) - c.pos(old)) / HOURS_PER_DAY
    return {"pass": abs(delta - delay_days) <= 5, "activity": test_id, "delta_days": delta,
            "old_finish": old, "new_finish": new}


# ---------------------------------------------------------------------- scenarios
def apply_deltas(net: Network, deltas: list[dict]) -> Network:
    """Apply recovery-scenario deltas. Each delta is a dict with `op` in:
    dur_factor(id, factor) · dur_set(id, days) · calendar(id, cal) · rel_remove(pred, succ)
    rel_add(pred, succ, type, lag_days) · rel_set(pred, succ, type, lag_days) · constraint(id, type, date)
    """
    n = net.copy()
    for d in deltas:
        op = d["op"]
        if op in ("dur_factor", "dur_set", "calendar", "constraint"):
            a = n.activities[d["id"]]
        if op == "dur_factor":
            if a.status == ACTIVE:
                a.rem = int(round(a.remaining * d["factor"] / HOURS_PER_DAY)) * HOURS_PER_DAY
            elif a.status == NOT_STARTED:
                a.dur = int(round(a.dur * d["factor"] / HOURS_PER_DAY)) * HOURS_PER_DAY
                a.rem = None
        elif op == "dur_set":
            if a.status == NOT_STARTED:
                a.dur, a.rem = d["days"] * HOURS_PER_DAY, None
            elif a.status == ACTIVE:
                a.rem = d["days"] * HOURS_PER_DAY
        elif op == "calendar":
            a.cal = d["cal"]
        elif op == "constraint":
            a.cstr_type, a.cstr_date = d["type"], d["date"]
        elif op == "rel_remove":
            n.rels = [r for r in n.rels if not (r.pred == d["pred"] and r.succ == d["succ"])]
        elif op == "rel_add":
            n.rels.append(Rel(d["pred"], d["succ"], d.get("type", "FS"), d.get("lag_days", 0) * HOURS_PER_DAY))
        elif op == "rel_set":
            n.rels = [r for r in n.rels if not (r.pred == d["pred"] and r.succ == d["succ"])]
            n.rels.append(Rel(d["pred"], d["succ"], d.get("type", "FS"), d.get("lag_days", 0) * HOURS_PER_DAY))
        else:
            raise ValueError(f"unknown scenario op {op}")
    return n


def compare_scenario(base: Schedule, net: Network, deltas: list[dict], near_critical_days: int = 10) -> dict:
    n2 = apply_deltas(net, deltas)
    s2 = schedule(n2, near_critical_days)
    d1 = net.finish_activity
    c = net.calendars[net.activities[d1].cal]
    b, s = base.acts[d1], s2.acts[d1]

    def neg(sch):
        return sum(1 for r in sch.acts.values() if r.tf is not None and r.tf < 0)

    def nc(sch):
        return sum(1 for r in sch.acts.values() if r.near_critical)

    return {
        "day1_ef_base": b.ef, "day1_ef": s.ef,
        "day1_impact_days": -(c.pos(s.ef) - c.pos(b.ef)) / HOURS_PER_DAY,   # positive = earlier
        "day1_tf_days": s.tf / HOURS_PER_DAY, "float_gain_days": (s.tf - b.tf) / HOURS_PER_DAY,
        "neg_float_count": neg(s2), "near_critical_count": nc(s2),
        "neg_float_count_base": neg(base), "schedule": s2,
    }
