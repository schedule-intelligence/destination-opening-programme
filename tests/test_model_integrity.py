"""Dimension integrity of the star schema (no orphan keys) and basic semantic checks on the outputs."""
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV = ROOT / "output" / "csv"


def t(name):
    return pd.read_csv(CSV / f"{name}.csv")


@pytest.fixture(scope="module")
def dims():
    return {n: t(n) for n in ("dim_snapshot", "dim_activity", "dim_wbs", "dim_owner", "dim_calendar", "dim_date")}


def test_all_tables_written():
    expected = {"dim_snapshot", "dim_activity", "dim_wbs", "dim_code", "dim_owner", "dim_calendar", "dim_date",
                "fact_activity_snapshot", "fact_relationship", "fact_milestone_trend", "fact_interface",
                "fact_dcma_check", "fact_dcma_offender", "fact_reconciliation", "fact_risk", "fact_decision",
                "fact_change", "fact_scenario", "fact_owner_scorecard", "fact_snapshot_summary", "fact_readiness",
                "fact_s_curve"}
    assert expected <= {p.stem for p in CSV.glob("*.csv")}


@pytest.mark.parametrize("fact,col,dim,key", [
    ("fact_activity_snapshot", "activity_id", "dim_activity", "activity_id"),
    ("fact_activity_snapshot", "snapshot_id", "dim_snapshot", "snapshot_id"),
    ("fact_relationship", "pred_id", "dim_activity", "activity_id"),
    ("fact_relationship", "succ_id", "dim_activity", "activity_id"),
    ("fact_milestone_trend", "activity_id", "dim_activity", "activity_id"),
    ("fact_interface", "giver_id", "dim_activity", "activity_id"),
    ("fact_interface", "receiver_id", "dim_activity", "activity_id"),
    ("fact_dcma_check", "snapshot_id", "dim_snapshot", "snapshot_id"),
    ("fact_reconciliation", "snapshot_id", "dim_snapshot", "snapshot_id"),
    ("fact_risk", "snapshot_id", "dim_snapshot", "snapshot_id"),
    ("fact_owner_scorecard", "owner_code", "dim_owner", "owner_code"),
    ("fact_decision", "linked_activity", "dim_activity", "activity_id"),
    ("fact_change", "linked_activity", "dim_activity", "activity_id"),
    ("fact_readiness", "activity_id", "dim_activity", "activity_id"),
])
def test_no_orphan_keys(dims, fact, col, dim, key):
    f = t(fact)
    missing = set(f[col].dropna()) - set(dims[dim][key])
    assert not missing, list(missing)[:5]


def test_dimension_keys(dims):
    a = dims["dim_activity"]
    assert a.activity_id.is_unique and dims["dim_snapshot"].snapshot_id.is_unique
    assert set(a.owner_code) <= set(dims["dim_owner"].owner_code)
    assert set(a.wbs_id) <= set(dims["dim_wbs"].wbs_id)
    assert set(a.calendar_id) <= set(dims["dim_calendar"].calendar_id)
    dd = pd.to_datetime(t("fact_activity_snapshot").finish).dt.strftime("%Y%m%d").astype(int)
    assert set(dd) <= set(dims["dim_date"].date_key)


def test_fact_grain_unique():
    f = t("fact_activity_snapshot")
    assert not f.duplicated(["snapshot_id", "activity_id"]).any()
    assert len(f.snapshot_id.unique()) == 6


def test_risk_links_resolve(dims):
    r = t("fact_risk")
    ids = set(dims["dim_activity"].activity_id)
    for links in r.linked_activities.unique():
        assert set(links.split(";")) <= ids, links


def test_scenarios_and_recommendation():
    s = t("fact_scenario")
    assert s.recommended.sum() == 1
    rec = s[s.recommended].iloc[0]
    base = s[s.scenario_id == "BASE"].iloc[0]
    assert rec.day1_tf_d >= 5 and base.day1_tf_d < 0
    assert set(s.scenario_id) == {"BASE", "A", "B", "C", "A+B", "A+B+C"}
