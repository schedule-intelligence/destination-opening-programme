"""Invariants of the CPM engine on the full programme, for every snapshot."""
from collections import defaultdict

import pytest

from dop.calendars import to_time
from dop.cpm import ACTIVE, COMPLETE, LOE, NOT_STARTED, critical_path_test
from dop.programme import DAY1_ID, DAY1_TARGET
from dop.simulate import simulate

SNAPS = simulate()
EXEMPT = {"CS_MANDSTART", "CS_MANDFIN"}


@pytest.mark.parametrize("snap", SNAPS, ids=[f"k{s.k}" for s in SNAPS])
def test_dates_ordered_and_no_work_before_data_date(snap):
    dd = snap.net.data_date
    for aid, a in snap.net.activities.items():
        r = snap.sched.acts[aid]
        assert r.es <= r.ef, aid
        if a.status == COMPLETE:
            assert a.act_finish < dd and r.tf is None
            continue
        assert r.ls <= r.lf, aid
        assert r.rs >= dd and r.ef >= dd, aid          # no remaining work before the data date
        assert r.tf is not None and r.ff is not None and r.ff <= r.tf, aid


@pytest.mark.parametrize("snap", SNAPS, ids=[f"k{s.k}" for s in SNAPS])
def test_every_relationship_honoured(snap):
    acts, res, cals = snap.net.activities, snap.sched.acts, snap.net.calendars
    for rel in snap.net.rels:
        s, p = acts[rel.succ], acts[rel.pred]
        if s.status == COMPLETE or s.type == LOE or s.cstr_type in EXEMPT:
            continue
        c = cals[s.cal]
        rs, ps = res[rel.succ], res[rel.pred]
        if rel.type == "FS":
            assert c.pos(rs.rs) >= c.pos(ps.ef) + rel.lag, rel.key
        elif rel.type == "SS" and s.status == NOT_STARTED:
            assert c.pos(rs.es) >= c.pos(ps.es) + rel.lag, rel.key
        elif rel.type == "FF":
            assert c.pos(rs.ef) >= c.pos(ps.ef) + rel.lag, rel.key
        elif rel.type == "SF":
            assert c.pos(rs.ef) >= c.pos(ps.es) + rel.lag, rel.key
        # backward pass: predecessor late finish allows the successor's late start
        if rel.type == "FS" and p.status != COMPLETE and p.type != LOE and p.cstr_type not in EXEMPT:
            cp = cals[p.cal]
            assert cp.pos(ps.lf) <= cp.pos(c.start_at(c.pos(rs.ls) - rel.lag)), rel.key


@pytest.mark.parametrize("snap", SNAPS, ids=[f"k{s.k}" for s in SNAPS])
def test_every_activity_reachable_or_flagged(snap):
    out = defaultdict(list)
    for r in snap.net.rels:
        out[r.pred].append(r.succ)
    seen, stack = set(), ["PRG-D1R-M000"]
    while stack:
        a = stack.pop()
        if a not in seen:
            seen.add(a)
            stack.extend(out[a])
    preds = {r.succ for r in snap.net.rels}
    unreachable = set(snap.net.activities) - seen
    # only activities deliberately left without a predecessor (injected DCMA D01 issue) may be unreachable
    roots = {a for a in snap.net.activities if a not in preds and a != "PRG-D1R-M000"}
    assert roots == {"LWP-HOV-3210"}
    for a in unreachable:
        assert any(a in desc for desc in [_descendants(out, r) for r in roots]), a


def _descendants(out, root):
    seen, stack = set(), [root]
    while stack:
        a = stack.pop()
        if a not in seen:
            seen.add(a)
            stack.extend(out[a])
    return seen


@pytest.mark.parametrize("snap", SNAPS, ids=[f"k{s.k}" for s in SNAPS])
def test_day1_float_equals_target_minus_forecast(snap):
    d1 = snap.sched.acts[DAY1_ID]
    c = snap.net.calendars[snap.net.activities[DAY1_ID].cal]
    assert d1.tf == c.pos(to_time(DAY1_TARGET, 16)) - c.pos(d1.ef)
    assert d1.longest_path
    # the longest path is a connected driving chain ending at Day 1
    lp = [a for a in snap.sched.order if snap.sched.acts[a].longest_path]
    assert lp[-1] == DAY1_ID


@pytest.mark.parametrize("snap", SNAPS[1:], ids=[f"k{s.k}" for s in SNAPS[1:]])
def test_dcma_critical_path_test_passes(snap):
    r = critical_path_test(snap.net, snap.sched)
    assert r["pass"], r


def test_storyline_shape():
    tf = [s.sched.day1().tf / 8 for s in SNAPS]
    assert tf[0] > 15 and tf[3] > 0 and tf[5] < 0 and tf[6] < 0
    assert tf[6] > tf[5]                     # month 6 recovery is partial
    assert all(270 <= len(s.spec) <= 330 for s in SNAPS)
    ms = [a for a, sp in SNAPS[-1].spec.items() if sp["type"] in ("TT_Mile", "TT_FinMile")]
    assert 30 <= len(ms) <= 40


def test_actuals_never_rewritten():
    for prev, cur in zip(SNAPS, SNAPS[1:]):
        for aid, a in prev.net.activities.items():
            b = cur.net.activities[aid]
            if a.act_start is not None:
                assert b.act_start == a.act_start, aid
            if a.status == COMPLETE:
                assert b.status == COMPLETE and b.act_finish == a.act_finish, aid
