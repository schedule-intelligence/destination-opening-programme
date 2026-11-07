"""Power BI project (powerbi/DOP.pbip): offline checks on the committed project and on fresh generator output,
plus determinism. The checks themselves live in scripts/check_pbip.py."""
import importlib.util
import json
import pathlib
import shutil

import pytest

from dop.pbip import PROJECT, build_files, write_project

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_pbip", ROOT / "scripts" / "check_pbip.py")
check_pbip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_pbip)

PAGES = "DOP.Report/definition/pages"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("pbip")
    files, summary = build_files(ROOT)
    write_project(files, out)
    return out, files, summary


def _json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_project_passes_all_checks():
    problems, _, stats = check_pbip.run_checks(ROOT / "powerbi", ROOT)
    assert not problems, "\n".join(problems[:25])
    assert stats["measures"] == 96 and stats["relationships"] == 26 and stats["pages"] == 8


def test_generated_project_passes_all_checks_without_warnings(generated):
    out, _, summary = generated
    problems, warnings, stats = check_pbip.run_checks(out, ROOT)
    assert not problems, "\n".join(problems[:25])
    assert not warnings, "\n".join(warnings[:25])
    assert stats["validated"] == summary["files"] - 3           # all but model.bim, the theme copy and the background
    assert summary["csv_tables"] == 22 and summary["tables"] == 24


def test_generator_is_deterministic(generated, tmp_path):
    out, files, _ = generated
    again, _ = build_files(ROOT)
    assert list(again) == list(files)
    assert all(again[k] == files[k] for k in files)
    write_project(again, tmp_path)
    on_disk = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert on_disk == files


def test_files_are_utf8_lf_two_space_json(generated):
    _, files, _ = generated
    for rel, data in files.items():
        assert not data.startswith(b"\xef\xbb\xbf"), rel
        assert b"\r" not in data, rel
        data.decode("utf-8")
        if "StaticResources" not in rel:
            assert data.endswith(b"}\n") and data.startswith(b"{\n  \""), rel


def test_rewrite_removes_stale_pages_and_visuals(generated, tmp_path):
    out = tmp_path / "project"
    shutil.copytree(generated[0], out)
    stale_page = out / PAGES / "p99_old"
    stale_visual = out / PAGES / "p01_exec" / "visuals" / "p01_v99_old"
    for folder in (stale_page, stale_visual):
        folder.mkdir(parents=True)
        (folder / "placeholder.json").write_text("{}", encoding="utf-8")
    write_project(generated[1], out)
    assert not stale_page.exists() and not stale_visual.exists()


def test_refuses_to_mix_tmdl_and_model_bim(generated, tmp_path):
    out = tmp_path / "project"
    shutil.copytree(generated[0], out)
    (out / f"{PROJECT}.SemanticModel" / "definition").mkdir()
    with pytest.raises(SystemExit):
        write_project(generated[1], out)


def test_checker_reports_a_broken_field_reference(generated, tmp_path):
    out = tmp_path / "project"
    shutil.copytree(generated[0], out)
    visual = next((out / PAGES / "p01_exec" / "visuals").glob("*_day1_float/visual.json"))
    doc = _json(visual)
    role = next(iter(doc["visual"]["query"]["queryState"].values()))
    role["projections"][0]["field"]["Measure"]["Property"] = "No such measure"
    visual.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    problems, _, _ = check_pbip.run_checks(out, ROOT)
    assert any("No such measure" in p and "not in model.bim" in p for p in problems)


def test_semantic_model_contents(generated):
    model = _json(generated[0] / "DOP.SemanticModel" / "model.bim")["model"]
    tables = {t["name"]: t for t in model["tables"]}
    threshold = tables["Near-critical threshold"]
    assert threshold["partitions"][0]["source"] == {"type": "calculated", "expression": "GENERATESERIES ( 0, 30, 1 )"}
    measures = {m["name"]: m for m in tables["_Measures"]["measures"]}
    assert "SELECTEDVALUE ( 'Near-critical threshold'[Near-critical threshold], 10 )" in \
        measures["Near-critical threshold (d)"]["expression"]
    assert measures["Day 1 forecast"]["formatString"] == "dd-mmm-yyyy"
    assert measures["Float erosion"]["formatString"] == "+0;-0;0"
    assert measures["BEI"]["formatString"] == "0.000" and measures["Owner DQ"]["formatString"] == "0.0%"
    assert {r["fromColumn"] for r in model["relationships"] if r.get("isActive") is False} == {"bl0_finish", "bl1_finish"}
    assert tables["dim_date"]["dataCategory"] == "Time"
    assert '"V:\\schedule-intelligence\\output\\csv" meta [IsParameterQuery=true' in model["expressions"][0]["expression"]
    lookback = next(c for c in tables["fact_activity_snapshot"]["columns"] if c["name"] == "lookback_event")
    assert lookback["dataType"] == "string"
    partition = "\n".join(tables["fact_activity_snapshot"]["partitions"][0]["source"]["expression"])
    assert 'Table.ReplaceValue(Promoted, "", null' in partition         # empty text -> null keeps ISBLANK tests
    assert '{"finish", type datetime}' in partition and '{"finish", type date}' in partition


def test_report_pages_and_header_strip(generated):
    out = generated[0]
    order = _json(out / PAGES / "pages.json")["pageOrder"]
    assert len(order) == 8
    for page in order:
        meta = _json(out / PAGES / page / "page.json")
        assert (meta["width"], meta["height"], meta["displayOption"]) == (1280, 720, "FitToPage")
        names = {p.name for p in (out / PAGES / page / "visuals").iterdir()}
        prefix = page[:3]
        assert {f"{prefix}_h1_programme", f"{prefix}_h0_title"} <= names
        image = meta["objects"]["background"][0]["properties"]["image"]["image"]
        assert image["url"]["expr"]["ResourcePackageItem"]["ItemName"] == "dop_background.svg"
        if meta.get("type") == "Drillthrough":
            assert meta["pageBinding"]["acceptsFilterContext"] == "None"
            continue
        slicer = _json(out / PAGES / page / "visuals" / f"{prefix}_h4_dd_slicer" / "visual.json")["visual"]
        assert slicer["syncGroup"]["groupName"] == "DataDate"
        assert slicer["objects"]["selection"][0]["properties"]["strictSingleSelect"]["expr"]["Literal"]["Value"] == "true"
        assert (f"{prefix}_h2_threshold" in names) == (page in ("p03_critical", "p06_quality"))
