"""scripts/check_service.py compares the published model with dashboard.json; these tests cover its pure parts,
without the service: the DAX it sends and the comparison it makes."""
import datetime as dt
import importlib.util
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_service", ROOT / "scripts" / "check_service.py")
check_service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_service)


def test_every_checked_measure_exists_in_measures_dax():
    dax = (ROOT / "powerbi" / "measures.dax").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*MEASURE\s+\S+\[([^\]]+)\]", dax, re.M))
    missing = [m for m in check_service.MEASURES.values() if m not in defined]
    assert not missing, missing


def test_every_checked_field_is_in_the_dashboard_summary():
    dashboard = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    summary = dashboard["snapshots"][dashboard["meta"]["latest"]]["summary"]
    missing = [f for f in check_service.MEASURES if f not in summary]
    assert not missing, missing


def test_dax_filters_the_requested_data_date_and_names_every_field():
    dax = check_service.dax_query(dt.date(2026, 10, 29))
    assert "dim_snapshot[data_date] = DATE ( 2026, 10, 29 )" in dax
    for field, measure in check_service.MEASURES.items():
        assert f'"{field}", [{measure}]' in dax


def test_compare_accepts_equal_values_dates_and_tolerances_only():
    expected = {"day1_forecast": "2027-10-21", "day1_tf_d": -7, "dq_score": 75.3, "critical_count": 39}
    actual = {"day1_forecast": "2027-10-21T00:00:00", "day1_tf_d": -7.0, "dq_score": 75.32, "critical_count": 38}
    results = {f: ok for f, _, _, ok in check_service.compare(expected, actual)}
    assert results["day1_forecast"] and results["day1_tf_d"] and results["dq_score"]
    assert not results["critical_count"]
    assert not results["bei"]  # absent on both sides is not agreement
