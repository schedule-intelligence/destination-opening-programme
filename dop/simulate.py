"""Progress simulation: executes the programme period by period and produces the seven schedules
(BL0 data date plus six monthly updates) with consistent actuals.

For each period (previous data date -> current data date):
1. Take the network as known at the current snapshot (durations revised by the storyline).
2. Schedule it from the previous data date, applying progress events (stalls, out-of-sequence starts).
3. Everything scheduled to start or finish before the current data date becomes actual.
4. Reschedule at the current data date with the full logic (retained logic): this is the snapshot.
Actuals are never rewritten, so every snapshot is consistent with every earlier one.
"""
from __future__ import annotations

import datetime as dt
import zlib
from dataclasses import dataclass, field

import numpy as np

from .calendars import HOURS_PER_DAY, programme_calendars, to_time
from .cpm import ACTIVE, COMPLETE, LOE, NOT_STARTED, START_MS, FINISH_MS, Activity, Network, Rel, Schedule, schedule
from .programme import DAY1_ID, DAY1_TARGET, NTP_DATE
from .storyline import DATA_DATES, FORCE_START, STALLS, network_spec

SEED = 20260430
CALS = programme_calendars()
D = HOURS_PER_DAY


@dataclass
class ActState:
    status: str = NOT_STARTED
    act_start: int | None = None
    act_finish: int | None = None
    rem: int | None = None


@dataclass
class Snapshot:
    k: int
    data_date: dt.date
    spec: dict[str, dict]
    rels: list[tuple]
    events: list[dict]
    net: Network
    sched: Schedule
    phys_pct: dict[str, float] = field(default_factory=dict)
    period_started: list[str] = field(default_factory=list)
    period_finished: list[str] = field(default_factory=list)


def _cstr_time(a: dict) -> int | None:
    d = a.get("cstr_date")
    if d is None:
        return None
    finish_type = a["cstr_type"] in ("CS_MEOB", "CS_MEOA", "CS_MEO", "CS_MANDFIN")
    return to_time(d, 16 if finish_type else 8)


def build_network(spec: dict[str, dict], rels: list[tuple], state: dict[str, ActState], data_date: int) -> Network:
    acts = {}
    for aid, a in spec.items():
        st = state.get(aid, ActState())
        acts[aid] = Activity(aid, a["name"], a["cal"], a["dur"] * D, st.rem if st.status == ACTIVE else None,
                             a["type"], st.status, st.act_start, st.act_finish, a["cstr_type"], _cstr_time(a))
    rl = [Rel(p, s, t, lag * D) for p, s, t, lag in rels]
    return Network(acts, rl, CALS, data_date, to_time(DAY1_TARGET, 16), DAY1_ID)


def simulate() -> list[Snapshot]:
    state: dict[str, ActState] = {}
    prev_spec = None
    snaps: list[Snapshot] = []
    prev_dd = NTP_DATE
    for k, dd in enumerate(DATA_DATES):
        spec, rels, events = network_spec(k)
        # 1. revise remaining durations of in-progress work for the storyline duration changes
        run_state = {aid: ActState(s.status, s.act_start, s.act_finish, s.rem) for aid, s in state.items()}
        for aid, st in run_state.items():
            if st.status == ACTIVE and prev_spec is not None and aid in prev_spec:
                st.rem = max(D, st.rem + (spec[aid]["dur"] - prev_spec[aid]["dur"]) * D)
        # 2. period run from the previous data date with progress events
        prev_t, cur_t = to_time(prev_dd), to_time(dd)
        period_spec = {a: dict(v) for a, v in spec.items()}
        period_rels = list(rels)
        for aid in STALLS.get(k, []):
            st = run_state.get(aid)
            if st and st.status == ACTIVE:
                st.rem += CALS[spec[aid]["cal"]].work_hours(prev_t, cur_t)
        for aid, start in FORCE_START.get(k, {}).items():
            if run_state.get(aid, ActState()).status == NOT_STARTED:
                period_spec[aid].update(cstr_type="CS_MSOA", cstr_date=start)
                period_rels = [r for r in period_rels if not (r[1] == aid and r[2] == "FS")]
        pnet = build_network(period_spec, period_rels, run_state, prev_t)
        ps = schedule(pnet)
        # 3. actualise everything that happened before the current data date
        started, finished = [], []
        new_state: dict[str, ActState] = {}
        for aid, a in pnet.activities.items():
            st = run_state.get(aid, ActState())
            r = ps.acts[aid]
            c = CALS[a.cal]
            if st.status == COMPLETE:
                new_state[aid] = st
                continue
            s_new = ActState(st.status, st.act_start, None, st.rem)
            if st.status == NOT_STARTED and r.es < cur_t:
                s_new.status, s_new.act_start = ACTIVE, r.es
                started.append(aid)
            if s_new.status == ACTIVE:
                if r.ef < cur_t:
                    s_new.status, s_new.act_finish, s_new.rem = COMPLETE, r.ef, 0
                    finished.append(aid)
                else:
                    s_new.rem = c.pos(r.ef) - c.pos(cur_t)
            if a.type in (START_MS, FINISH_MS) and s_new.status == ACTIVE:
                s_new.status, s_new.act_finish, s_new.rem = COMPLETE, s_new.act_start, 0
                finished.append(aid)
            new_state[aid] = s_new
        state = new_state
        # 4. snapshot schedule at the current data date
        net = build_network(spec, rels, state, cur_t)
        sch = schedule(net)
        snap = Snapshot(k, dd, spec, rels, events, net, sch, period_started=started, period_finished=finished)
        snap.phys_pct = physical_pct(net, k)
        if snaps:  # a stalled activity reports exactly the same progress as last period
            for aid in STALLS.get(k, []):
                if net.activities[aid].status == ACTIVE and snaps[-1].net.activities[aid].status == ACTIVE:
                    snap.phys_pct[aid] = snaps[-1].phys_pct[aid]
        snaps.append(snap)
        prev_spec, prev_dd = spec, dd
    return snaps


def duration_pct(a: Activity) -> float:
    if a.status == COMPLETE:
        return 100.0
    if a.status == NOT_STARTED or a.dur == 0:
        return 0.0
    return round(max(0.0, min(99.0, 100.0 * (a.dur - a.remaining) / a.dur)), 1)


def physical_pct(net: Network, k: int) -> dict[str, float]:
    out = {}
    for aid, a in net.activities.items():
        dp = duration_pct(a)
        if a.status == ACTIVE and a.type != LOE:
            rng = np.random.default_rng(SEED + zlib.crc32(f"{aid}|{k}".encode()))
            dp = float(np.clip(round(dp + rng.uniform(-7, 7)), 1, 99))
        out[aid] = dp
    return out
