"""Every injected issue in the truth files is detected, and the offender sets computed from the parsed XER
equal the generator's expected sets exactly (zero false positives on clean activities)."""
import json
import pathlib

import pytest

from dop.pipeline.load import load_all
from dop.pipeline.quality import assess

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLS, UPS = load_all(ROOT)
TRUTH = {json.loads(p.read_text())["data_date"]: json.loads(p.read_text())
         for p in (ROOT / "data" / "truth").glob("*.json")}


def _assess(i):
    s = UPS[i]
    prev = UPS[i - 1] if i else BLS["BL0"]
    bl = BLS["BL1"] if s.project["sum_base_proj_id"] == 1101 else BLS["BL0"]
    return s, assess(s, prev, bl, s.data_date.date())


RESULTS = [_assess(i) for i in range(len(UPS))]


@pytest.mark.parametrize("i", range(6), ids=[u.name for u in UPS])
def test_injected_issues_detected(i):
    s, q = RESULTS[i]
    t = TRUTH[s.data_date.date().isoformat()]
    assert t["injected"], "truth file lists injected issues"
    for inj in t["injected"]:
        assert inj["item"] in q["offenders"][inj["check"]], inj


@pytest.mark.parametrize("i", range(6), ids=[u.name for u in UPS])
def test_offender_sets_equal_truth_exactly(i):
    s, q = RESULTS[i]
    t = TRUTH[s.data_date.date().isoformat()]
    for cid, expected in t["expected"].items():
        assert q["offenders"][cid] == expected, (cid, sorted(set(q["offenders"][cid]) ^ set(expected))[:10])


@pytest.mark.parametrize("i", range(6), ids=[u.name for u in UPS])
def test_metrics_match_truth(i):
    s, q = RESULTS[i]
    m = TRUTH[s.data_date.date().isoformat()]["metrics"]
    assert round(q["cpli"], 3) == m["cpli"]
    assert q["cp_test"]["pass"] == m["cp_test_pass"]
    assert q["cp_test"]["activity"] == m["cp_test_activity"]
    if m["bei"] is not None:
        assert round(q["bei"], 3) == m["bei"]
    assert 0 <= q["dq_score"] <= 100


def test_data_date_mismatch_is_caught():
    s = UPS[-1]
    import datetime as dt
    q = assess(s, UPS[-2], BLS["BL1"], dt.date(2026, 10, 22))
    u08 = next(c for c in q["checks"] if c["check_id"] == "U08")
    assert u08["passed"] is False
