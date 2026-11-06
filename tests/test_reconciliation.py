"""The reconciliation gate passes on the real outputs and fails when the dashboard JSON is tampered with."""
import copy
import datetime as dt
import pathlib

import pytest

from dop.pipeline.export import build_dashboard_json
from dop.pipeline.load import load_all
from dop.pipeline.model import build_model, snap_id
from dop.pipeline.reconcile import reconcile
from dop.pipeline.run import INTEGRITY_CHECKS

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLS, UPS = load_all(ROOT)
M = build_model(ROOT, BLS, UPS, "2026-01-01T00:00:00Z")
JS = build_dashboard_json(M, "2026-01-01T00:00:00Z", 10)
BL_IDS = {str(s.project["proj_id"]): n for n, s in BLS.items()}


def _run(js, s):
    q = M["_quality"][snap_id(s.data_date)]
    flagged = {i for c in INTEGRITY_CHECKS for i in q["offenders"][c]}
    return reconcile(s, M, js, BL_IDS, flagged)


@pytest.mark.parametrize("i", range(6), ids=[u.name for u in UPS])
def test_gate_passes_for_every_snapshot(i):
    res = _run(JS, UPS[i])
    assert len(res) >= 35
    failed = [c for c in res if not c["passed"]]
    assert not failed, failed[:3]
    assert {c["control_id"].split(".")[0] for c in res} == {f"R{n:02d}" for n in range(1, 17)}


def test_tampered_day1_date_fails_gate():
    js = copy.deepcopy(JS)
    d = UPS[-1].data_date.date().isoformat()
    snap = js["snapshots"][d]
    cols = snap["acts"]["cols"]
    for row in snap["acts"]["rows"]:
        if row[cols.index("activity_id")] == "PRG-D1R-M999":
            row[cols.index("finish")] = "2027-10-14"   # someone "fixes" the dashboard by hand
    res = _run(js, UPS[-1])
    bad = {c["control_id"] for c in res if not c["passed"]}
    assert "R07" in bad and "R09.PRG-D1R-M999" in bad


def test_dropped_activity_and_relationship_fail_gate():
    js = copy.deepcopy(JS)
    d = UPS[2].data_date.date().isoformat()
    js["snapshots"][d]["acts"]["rows"].pop(5)
    js["snapshots"][d]["rels"]["rows"].pop(0)
    bad = {c["control_id"] for c in _run(js, UPS[2]) if not c["passed"]}
    assert {"R01", "R05"} <= bad


def test_tampered_hash_and_baseline_fail_gate():
    js = copy.deepcopy(JS)
    meta = js["meta"]["snapshots"][0]
    meta["sha256"] = "0" * 64
    meta["baseline_in_force"] = "BL1"
    bad = {c["control_id"] for c in _run(js, UPS[0]) if not c["passed"]}
    assert {"R14", "R15"} <= bad


def test_pipeline_exit_code_is_nonzero_when_gate_fails(tmp_path, monkeypatch):
    import dop.pipeline.run as run
    real = run.reconcile

    def tamper(s, m, js, bl, fl):
        out = real(s, m, js, bl, fl)
        out[0]["passed"] = False
        return out
    monkeypatch.setattr(run, "reconcile", tamper)
    rc = run.run_pipeline(ROOT, json_path=tmp_path / "dash.json", quiet=True)
    assert rc == 1
