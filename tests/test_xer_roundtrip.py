"""XER files round-trip through the generic parser and equal the engine output."""
import json
import pathlib

import pytest

from dop.calendars import to_time
from dop.cpm import schedule
from dop.xer import parse_xer, to_frames, write_xer
from dop.xer_model import network_from_frames

ROOT = pathlib.Path(__file__).resolve().parents[1]
XERS = sorted((ROOT / "data" / "xer").glob("*.xer"))
TRUTH = {json.loads(p.read_text())["xer"]: json.loads(p.read_text()) for p in (ROOT / "data" / "truth").glob("*.json")}


def test_eight_xer_files():
    names = {p.name for p in XERS}
    assert {"DOP_BL0.xer", "DOP_BL1.xer"} <= names and len(names) == 8


@pytest.mark.parametrize("path", XERS, ids=[p.name for p in XERS])
def test_byte_identical_rewrite(path, tmp_path):
    tabs = parse_xer(path)
    hdr = tabs.pop("_header")[0]
    import datetime as dt
    out = tmp_path / "rt.xer"
    write_xer(tabs, out, dt.date.fromisoformat(hdr["export_date"]))
    assert out.read_bytes() == path.read_bytes()


@pytest.mark.parametrize("path", XERS, ids=[p.name for p in XERS])
def test_structure_and_enumerations(path):
    t = parse_xer(path)
    for table in ("PROJECT", "CALENDAR", "PROJWBS", "TASK", "TASKPRED", "ACTVTYPE", "ACTVCODE", "TASKACTV"):
        assert t[table], table
    assert {r["task_type"] for r in t["TASK"]} <= {"TT_Task", "TT_Mile", "TT_FinMile", "TT_LOE"}
    assert {r["status_code"] for r in t["TASK"]} <= {"TK_NotStart", "TK_Active", "TK_Complete"}
    assert {r["pred_type"] for r in t["TASKPRED"]} <= {"PR_FS", "PR_SS", "PR_FF", "PR_SF"}
    assert {r["cstr_type"] for r in t["TASK"]} <= {"", "CS_MSOA", "CS_MEOB", "CS_MANDSTART", "CS_MANDFIN"}
    assert sum(r["proj_node_flag"] == "Y" for r in t["PROJWBS"]) == 1
    ids = {r["task_id"] for r in t["TASK"]}
    assert all(r["task_id"] in ids and r["pred_task_id"] in ids for r in t["TASKPRED"])
    assert all(r["task_id"] in ids for r in t["TASKACTV"])


@pytest.mark.parametrize("path", XERS, ids=[p.name for p in XERS])
def test_reschedule_of_parsed_xer_equals_exported_dates(path):
    fr = to_frames(parse_xer(path))
    net = network_from_frames(fr)
    s = schedule(net)
    injected = {i["item"] for i in TRUTH.get(path.name, {}).get("injected", [])
                if i["check"] in ("D09", "U02", "U03", "U04")}
    mism = []
    for r in fr["TASK"].itertuples():
        if r.task_code in injected:
            continue
        e = s.acts[r.task_code]
        tf = None if r.total_float_hr_cnt is None else int(r.total_float_hr_cnt)
        got = (to_time(r.early_end_date), tf, r.driving_path_flag == "Y")
        exp = (e.ef, e.tf, e.longest_path)
        if r.status_code != "TK_Complete":
            got += (to_time(r.restart_date), to_time(r.late_end_date))
            exp += (e.rs, e.lf)
        if got != exp:
            mism.append((r.task_code, got, exp))
    assert not mism, mism[:5]
