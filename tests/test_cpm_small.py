"""Hand-calculated CPM networks. All expected values are worked out by hand in the comments.

Calendar 7 = 7-day, 08:00-16:00, no holidays. Calendar 5 = Sun-Thu. Data date Mon 01-Jun-2026 08:00.
"""
import datetime as dt

import pytest

from dop.calendars import ALL_WEEK, SUN_THU, Calendar, fmt_time, to_time
from dop.cpm import (ACTIVE, COMPLETE, FINISH_MS, START_MS, LOE, Activity, CycleError, Network, Rel,
                     compare_scenario, critical_path_test, schedule)

D = 8  # hours per day
CALS = {7: Calendar(7, "7d", ALL_WEEK), 5: Calendar(5, "5d", SUN_THU)}
DD = to_time(dt.date(2026, 6, 1))


def t(s):
    return fmt_time(s)


def net(acts, rels, dd=DD, mfb=None, fin=None):
    return Network({a.id: a for a in acts}, rels, CALS, dd, mfb, fin)


def test_fs_chain():
    # A 3d, B 2d, C 4d in sequence: A 01-03 Jun, B 04-05 Jun, C 06-09 Jun. All critical, TF 0.
    n = net([Activity("A", cal=7, dur=3 * D), Activity("B", cal=7, dur=2 * D), Activity("C", cal=7, dur=4 * D)],
            [Rel("A", "B"), Rel("B", "C")], fin="C")
    s = schedule(n)
    assert (t(s.acts["A"].es), t(s.acts["A"].ef)) == ("2026-06-01 08:00", "2026-06-03 16:00")
    assert (t(s.acts["B"].es), t(s.acts["B"].ef)) == ("2026-06-04 08:00", "2026-06-05 16:00")
    assert (t(s.acts["C"].es), t(s.acts["C"].ef)) == ("2026-06-06 08:00", "2026-06-09 16:00")
    assert all(s.acts[x].tf == 0 and s.acts[x].critical and s.acts[x].longest_path for x in "ABC")


def test_ss_ff_with_lags_and_float():
    # A 5d (01-05 Jun). B 3d SS+2d from A -> starts 03 Jun, ends 05 Jun.
    # C 2d FF+1d from A -> must finish >= 06 Jun 16:00 -> C 05-06 Jun.
    # F finish milestone after B and C (FS) -> 06 Jun 16:00. B has TF 1d (FF slack 1d).
    n = net([Activity("A", cal=7, dur=5 * D), Activity("B", cal=7, dur=3 * D), Activity("C", cal=7, dur=2 * D),
             Activity("F", cal=7, type=FINISH_MS)],
            [Rel("A", "B", "SS", 2 * D), Rel("A", "C", "FF", 1 * D), Rel("B", "F"), Rel("C", "F")], fin="F")
    s = schedule(n)
    assert (t(s.acts["B"].es), t(s.acts["B"].ef)) == ("2026-06-03 08:00", "2026-06-05 16:00")
    assert (t(s.acts["C"].es), t(s.acts["C"].ef)) == ("2026-06-05 08:00", "2026-06-06 16:00")
    assert t(s.acts["F"].ef) == "2026-06-06 16:00"
    assert s.acts["B"].tf == 1 * D and s.acts["B"].ff == 1 * D
    assert s.acts["C"].tf == 0 and s.acts["A"].tf == 0
    assert s.acts["A"].longest_path and s.acts["C"].longest_path and not s.acts["B"].longest_path
    assert s.rel_driving["A->C:FF"] and not s.rel_driving["B->F:FS"]


def test_sf_relationship():
    # B must finish >= A.start + 5d. A starts 01 Jun 08:00 -> B finishes 05 Jun 16:00, 3d -> starts 03 Jun.
    n = net([Activity("A", cal=7, dur=2 * D), Activity("B", cal=7, dur=3 * D)], [Rel("A", "B", "SF", 5 * D)], fin="B")
    s = schedule(n)
    assert (t(s.acts["B"].es), t(s.acts["B"].ef)) == ("2026-06-03 08:00", "2026-06-05 16:00")
    assert s.rel_driving["A->B:SF"]


def test_constraint_drives_negative_float():
    # A 5d (01-05), B 5d (06-10), M finish milestone 10 Jun 16:00, FNLT 08 Jun 16:00 -> TF = -2d on all.
    n = net([Activity("A", cal=7, dur=5 * D), Activity("B", cal=7, dur=5 * D),
             Activity("M", cal=7, type=FINISH_MS, cstr_type="CS_MEOB", cstr_date=to_time(dt.date(2026, 6, 8), 16))],
            [Rel("A", "B"), Rel("B", "M")], fin="M")
    s = schedule(n)
    assert t(s.acts["M"].ef) == "2026-06-10 16:00"
    assert t(s.acts["M"].lf) == "2026-06-08 16:00"
    for x in "ABM":
        assert s.acts[x].tf == -2 * D and s.acts[x].critical
    assert t(s.acts["A"].ls) == "2026-05-30 08:00"


def test_must_finish_by_gives_positive_float():
    # Same chain, project must finish by 15 Jun 16:00 -> TF = +5d everywhere.
    n = net([Activity("A", cal=7, dur=5 * D), Activity("B", cal=7, dur=5 * D), Activity("M", cal=7, type=FINISH_MS)],
            [Rel("A", "B"), Rel("B", "M")], mfb=to_time(dt.date(2026, 6, 15), 16), fin="M")
    s = schedule(n)
    assert all(s.acts[x].tf == 5 * D for x in "ABM")
    assert not s.acts["A"].critical and s.acts["A"].near_critical
    assert s.acts["A"].longest_path  # longest path is independent of float value


def test_multi_calendar_and_lag_on_successor_calendar():
    # DD Thu 04 Jun. A on Sun-Thu, 2d -> Thu 04 + Sun 07 Jun 16:00.
    # B on 7-day FS -> Mon 08 Jun (1d). C on 7-day FS +1d lag (successor calendar) -> lag day Mon -> starts Tue 09.
    dd = to_time(dt.date(2026, 6, 4))
    n = net([Activity("A", cal=5, dur=2 * D), Activity("B", cal=7, dur=1 * D), Activity("C", cal=7, dur=1 * D),
             Activity("F", cal=7, type=FINISH_MS)],
            [Rel("A", "B"), Rel("A", "C", "FS", 1 * D), Rel("B", "F"), Rel("C", "F")], dd=dd, fin="F")
    s = schedule(n)
    assert t(s.acts["A"].ef) == "2026-06-07 16:00"
    assert t(s.acts["B"].es) == "2026-06-08 08:00"
    assert t(s.acts["C"].es) == "2026-06-09 08:00"
    assert s.acts["A"].tf == 0 and s.acts["B"].tf == 1 * D


def test_cross_calendar_backward_no_spurious_negative_float():
    # A 5-day cal finishes Thu 04 Jun 16:00; B 7-day starts Fri 05 Jun. Backward: A.LF = Thu 16:00 -> TF 0.
    dd = to_time(dt.date(2026, 6, 4))
    n = net([Activity("A", cal=5, dur=1 * D), Activity("B", cal=7, dur=1 * D)], [Rel("A", "B")], dd=dd, fin="B")
    s = schedule(n)
    assert t(s.acts["B"].es) == "2026-06-05 08:00"
    assert s.acts["A"].tf == 0 and t(s.acts["A"].lf) == "2026-06-04 16:00"


def test_in_progress_with_data_date():
    # A started 25 May, 10d, 4d remaining at DD 01 Jun -> EF 04 Jun 16:00; B (FS, 2d) 05-06 Jun.
    n = net([Activity("A", cal=7, dur=10 * D, rem=4 * D, status=ACTIVE, act_start=to_time(dt.date(2026, 5, 25))),
             Activity("B", cal=7, dur=2 * D), Activity("Z", cal=7, dur=1 * D, status=COMPLETE,
                                                          act_start=to_time(dt.date(2026, 5, 20)),
                                                          act_finish=to_time(dt.date(2026, 5, 20), 16))],
            [Rel("Z", "A"), Rel("A", "B")], fin="B")
    s = schedule(n)
    assert t(s.acts["A"].es) == "2026-05-25 08:00" and t(s.acts["A"].ef) == "2026-06-04 16:00"
    assert (t(s.acts["B"].es), t(s.acts["B"].ef)) == ("2026-06-05 08:00", "2026-06-06 16:00")
    assert s.acts["Z"].tf is None  # completed: no float
    for r in s.acts.values():  # no remaining work before the data date
        if r.tf is not None:
            assert r.ef >= DD


def test_out_of_sequence_retained_logic():
    # A in progress, 3d remaining -> EF 03 Jun. B (FS from A) already started 28 May with 2d remaining.
    # Retained logic: B's remaining waits for A -> 04-05 Jun.
    n = net([Activity("A", cal=7, dur=6 * D, rem=3 * D, status=ACTIVE, act_start=to_time(dt.date(2026, 5, 27))),
             Activity("B", cal=7, dur=4 * D, rem=2 * D, status=ACTIVE, act_start=to_time(dt.date(2026, 5, 28)))],
            [Rel("A", "B")], fin="B")
    s = schedule(n)
    assert t(s.acts["B"].rs) == "2026-06-04 08:00"
    assert t(s.acts["B"].ef) == "2026-06-05 16:00"
    assert t(s.acts["B"].es) == "2026-05-28 08:00"


def test_longest_path_differs_from_negative_float_path():
    # Path 1: A 10d -> F (finish 10 Jun). Path 2: B 5d -> C 3d with FNLT 06 Jun on C (C finishes 08 Jun).
    # C and B: TF -2d (critical) but NOT on the longest path. A and F: TF 0, longest path.
    n = net([Activity("A", cal=7, dur=10 * D), Activity("B", cal=7, dur=5 * D),
             Activity("C", cal=7, dur=3 * D, cstr_type="CS_MEOB", cstr_date=to_time(dt.date(2026, 6, 6), 16)),
             Activity("F", cal=7, type=FINISH_MS)],
            [Rel("A", "F"), Rel("B", "C"), Rel("C", "F")], fin="F")
    s = schedule(n)
    assert s.acts["C"].tf == -2 * D and s.acts["B"].tf == -2 * D
    assert s.acts["C"].critical and not s.acts["C"].longest_path
    assert s.acts["A"].longest_path and s.acts["F"].longest_path and s.acts["A"].tf == 0


def test_mandatory_start_overrides_logic():
    # B has Mandatory Start 02 Jun even though A (5d) finishes 05 Jun -> B starts 02 Jun; A gets TF -4d.
    n = net([Activity("A", cal=7, dur=5 * D),
             Activity("B", cal=7, dur=2 * D, cstr_type="CS_MANDSTART", cstr_date=to_time(dt.date(2026, 6, 2)))],
            [Rel("A", "B")], fin="B")
    s = schedule(n)
    assert t(s.acts["B"].es) == "2026-06-02 08:00"
    assert s.acts["A"].tf == -4 * D


def test_snet_constraint_and_milestones():
    # SNET 08 Jun on B; start milestone S0 at DD; finish milestone after B.
    n = net([Activity("S0", cal=7, type=START_MS), Activity("B", cal=7, dur=2 * D, cstr_type="CS_MSOA",
                                                             cstr_date=to_time(dt.date(2026, 6, 8))),
             Activity("F", cal=7, type=FINISH_MS)], [Rel("S0", "B"), Rel("B", "F")], fin="F")
    s = schedule(n)
    assert t(s.acts["S0"].es) == "2026-06-01 08:00" and s.acts["S0"].ef == s.acts["S0"].es
    assert t(s.acts["B"].es) == "2026-06-08 08:00"
    assert t(s.acts["F"].ef) == "2026-06-09 16:00"
    assert s.acts["S0"].tf == 7 * D and not s.acts["S0"].longest_path  # data/constraint-driven break


def test_negative_lag_lead():
    # A 5d (01-05). B FS -2d -> starts 04 Jun.
    n = net([Activity("A", cal=7, dur=5 * D), Activity("B", cal=7, dur=3 * D)], [Rel("A", "B", "FS", -2 * D)], fin="B")
    s = schedule(n)
    assert t(s.acts["B"].es) == "2026-06-04 08:00"


def test_loe_spans_and_does_not_drive():
    # A 3d, B 4d after A; LOE L with SS from A and FF from B -> spans 01-07 Jun; F after B.
    n = net([Activity("A", cal=7, dur=3 * D), Activity("B", cal=7, dur=4 * D), Activity("L", cal=7, type=LOE),
             Activity("F", cal=7, type=FINISH_MS)],
            [Rel("A", "B"), Rel("A", "L", "SS"), Rel("B", "L", "FF"), Rel("B", "F")], fin="F")
    s = schedule(n)
    assert (t(s.acts["L"].es), t(s.acts["L"].ef)) == ("2026-06-01 08:00", "2026-06-07 16:00")
    assert not s.acts["L"].longest_path
    assert s.acts["A"].tf == 0


def test_holiday_calendar():
    c = Calendar(9, "6d", (5, 6, 0, 1, 2, 3), frozenset({dt.date(2026, 6, 2)}))
    # Mon 01 Jun + 3 working days: 01, (02 holiday), 03, 04 -> finishes Thu 04 16:00; Fri 05 off.
    assert fmt_time(c.add(to_time(dt.date(2026, 6, 1)), 3 * D)) == "2026-06-04 16:00"
    assert fmt_time(c.add(to_time(dt.date(2026, 6, 4), 16), 0, finish=False)) == "2026-06-06 08:00"
    rt = Calendar.from_clndr_data(9, "6d", c.to_clndr_data())
    assert rt.workweek == c.workweek and rt.holidays == c.holidays


def test_scenario_reschedule():
    # A 10d -> B 10d -> F. Scenario halves B -> F moves 5 days earlier, float gain 5 days vs MFB.
    n = net([Activity("A", cal=7, dur=10 * D), Activity("B", cal=7, dur=10 * D), Activity("F", cal=7, type=FINISH_MS)],
            [Rel("A", "B"), Rel("B", "F")], mfb=to_time(dt.date(2026, 6, 18), 16), fin="F")
    base = schedule(n)
    assert base.acts["F"].tf == -2 * D
    out = compare_scenario(base, n, [{"op": "dur_factor", "id": "B", "factor": 0.5}])
    assert out["day1_impact_days"] == 5 and out["float_gain_days"] == 5 and out["day1_tf_days"] == 3
    assert out["neg_float_count"] == 0 and out["neg_float_count_base"] == 3


def test_dcma_critical_path_test():
    n = net([Activity("A", cal=7, dur=10 * D), Activity("B", cal=7, dur=10 * D), Activity("F", cal=7, type=FINISH_MS)],
            [Rel("A", "B"), Rel("B", "F")], fin="F")
    r = critical_path_test(n)
    assert r["pass"] and r["delta_days"] == 600
    # broken: finish milestone held by a mandatory finish -> delay does not propagate -> test fails
    n2 = net([Activity("A", cal=7, dur=10 * D),
              Activity("F", cal=7, type=FINISH_MS, cstr_type="CS_MANDFIN", cstr_date=to_time(dt.date(2026, 6, 20), 16))],
             [Rel("A", "F")], fin="F")
    assert not critical_path_test(n2)["pass"]


def test_cycle_detected():
    with pytest.raises(CycleError):
        schedule(net([Activity("A", cal=7, dur=D), Activity("B", cal=7, dur=D)], [Rel("A", "B"), Rel("B", "A")]))
