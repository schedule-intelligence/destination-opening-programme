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
    assert stats["measures"] == 120 and stats["relationships"] == 26 and stats["pages"] == 10


def test_generated_project_passes_all_checks_without_warnings(generated):
    out, _, summary = generated
    problems, warnings, stats = check_pbip.run_checks(out, ROOT)
    assert not problems, "\n".join(problems[:25])
    assert not warnings, "\n".join(warnings[:25])
    assert stats["validated"] == summary["files"] - 3           # all but model.bim, the theme copy and the background
    # + threshold, measures, Compare against, Trend KPI, Update axis, Risk grid
    assert summary["csv_tables"] == 22 and summary["tables"] == 28


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
    visual = next((out / PAGES / "p01_exec" / "visuals").glob("*_kpis/visual.json"))
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


def test_kpi_tiles_carry_trend_lines(generated):
    out = generated[0]
    model = _json(out / "DOP.SemanticModel" / "model.bim")["model"]
    tables = {t["name"]: t for t in model["tables"]}
    measures = {m["name"]: m for m in tables["_Measures"]["measures"]}
    def dax(m: dict) -> str:                 # TMSL keeps a multi-line expression as a list of lines
        return "\n".join(m["expression"]) if isinstance(m["expression"], list) else m["expression"]

    trends = {name: m for name, m in measures.items() if name.startswith("Trend - ")}
    assert len(trends) == 16
    renderer = measures["Trend line"]
    for name, m in trends.items():
        kpi = name[len("Trend - "):]
        assert m["dataCategory"] == "ImageUrl" and "formatString" not in m, name
        assert f"'Trend KPI'[KPI] = \"{kpi}\"" in dax(m), name
        assert f'"{kpi}", [{kpi}]' in dax(renderer), name
    assert "formatString" not in renderer and "dataCategory" not in renderer
    assert "data:image/svg+xml;utf8," in dax(renderer) and "REMOVEFILTERS ( dim_snapshot )" in dax(renderer)
    kpi_table = tables["Trend KPI"]
    assert kpi_table["isHidden"] is True and kpi_table["columns"][0]["isHidden"] is True
    rows = "\n".join(kpi_table["partitions"][0]["source"]["expression"])
    assert rows.startswith("DATATABLE (") and all(f'{{ "{name[len("Trend - "):]}" }}' in rows for name in trends)
    # every tile of the four KPI strips draws its own trend: the image settings and the measure, per tile
    for page, tiles in (("p01_exec", 4), ("p02_milestones", 4), ("p03_critical", 6), ("p06_quality", 4)):
        visual = _json(next((out / PAGES / page / "visuals").glob("*_kpis/visual.json")))["visual"]
        assert visual["visualType"] == "cardVisual"
        images = visual["objects"]["image"]
        settings = [e for e in images if "show" in e["properties"]]
        bound = [e for e in images if "imageData" in e["properties"]]
        assert len(settings) == len(bound) == tiles, page
        for e in settings:
            assert _literal(e["properties"], "imageType") == "'imageData'"
            assert _literal(e["properties"], "position") == "'Right'"
        for e in bound:
            assert e["properties"]["imageData"]["expr"]["Measure"]["Property"].startswith("Trend - ")
        assert {e["selector"]["metadata"] for e in settings} == {e["selector"]["metadata"] for e in bound}


def test_table_sparklines_read_every_update(generated):
    out = generated[0]
    model = _json(out / "DOP.SemanticModel" / "model.bim")["model"]
    tables = {t["name"]: t for t in model["tables"]}
    axis = tables["Update axis"]                 # not related to the model: the data-date slicer leaves it whole
    assert axis["isHidden"] is True and {c["name"] for c in axis["columns"]} == {"snapshot_id", "data_date", "update"}
    assert not [r for r in model["relationships"] if "Update axis" in (r["fromTable"], r["toTable"])]
    measures = {m["name"]: m for m in tables["_Measures"]["measures"]}
    assert measures["Owner DQ by update"]["formatString"] == "0.0%"
    assert measures["Milestone variance vs BL1 by update"]["formatString"] == "+0;-0;0"
    for page, name, measure in (("p06_quality", "owner_scorecard", "Owner DQ by update"),
                                ("p02_milestones", "milestone_table", "Milestone variance vs BL1 by update"),
                                ("p05_risks", "risk_register", "Risk score (max) by update")):
        visual = _json(next((out / PAGES / page / "visuals").glob(f"*_{name}/visual.json")))["visual"]
        projections = visual["query"]["queryState"]["Values"]["projections"]
        spark = next(p for p in projections if "SparklineData" in p["field"])
        data = spark["field"]["SparklineData"]
        assert data["Measure"]["Measure"]["Property"] == measure
        assert data["Groupings"][0]["Column"]["Expression"]["SourceRef"]["Entity"] == "Update axis"
        assert spark["queryRef"] == f"SparklineData(_Measures.{measure}_[Update axis.data_date])"
        style = visual["objects"]["sparklines"][0]
        assert style["selector"]["metadata"] == spark["queryRef"]
        assert _literal(style["properties"], "markers") == "144D"           # the last point marked
        # only identifying columns group the rows: a per-update value as a column would cut the line to the
        # updates that share it
        if name != "milestone_table":
            grouped = [p["queryRef"] for p in projections if "Column" in p["field"]]
            assert all(not any(k in q for k in ("score", "trend", "incomplete", "flagged", "logic")) for q in grouped)


def test_report_pages_and_header_strip(generated):
    out = generated[0]
    order = _json(out / PAGES / "pages.json")["pageOrder"]
    assert len(order) == 10
    assert order.index("p09_gantt") == order.index("p03_critical") + 1     # the Gantt follows the critical path
    for page in order:
        meta = _json(out / PAGES / page / "page.json")
        names = {p.name for p in (out / PAGES / page / "visuals").iterdir()}
        prefix = page[:3]
        if meta.get("type") == "Tooltip":
            assert (meta["width"], meta["height"], meta["visibility"]) == (320, 240, "HiddenInViewMode")
            assert meta["pageBinding"]["type"] == "Tooltip"
            continue
        assert (meta["width"], meta["height"], meta["displayOption"]) == (1280, 720, "FitToPage")
        # every report page carries the rail (programme, page navigator, provenance) and the title row
        assert {f"{prefix}_h1_programme", f"{prefix}_h6_navigator", f"{prefix}_h7_provenance",
                f"{prefix}_h8_kicker", f"{prefix}_h0_title"} <= names
        nav = _json(out / PAGES / page / "visuals" / f"{prefix}_h6_navigator" / "visual.json")["visual"]
        assert nav["visualType"] == "pageNavigator"
        assert nav["objects"]["pages"][0]["properties"]["showHiddenPages"]["expr"]["Literal"]["Value"] == "false"
        image = meta["objects"]["background"][0]["properties"]["image"]["image"]
        assert image["url"]["expr"]["ResourcePackageItem"]["ItemName"] == "dop_background.svg"
        if meta.get("type") == "Drillthrough":
            assert meta["pageBinding"]["acceptsFilterContext"] == "None"
            continue
        slicer = _json(out / PAGES / page / "visuals" / f"{prefix}_h4_dd_slicer" / "visual.json")["visual"]
        assert slicer["syncGroup"]["groupName"] == "DataDate"
        assert slicer["objects"]["selection"][0]["properties"]["strictSingleSelect"]["expr"]["Literal"]["Value"] == "true"
        assert (f"{prefix}_h2_threshold" in names) == (page in ("p03_critical", "p06_quality", "p09_gantt"))


def test_compare_against_field_parameter(generated):
    model = _json(generated[0] / "DOP.SemanticModel" / "model.bim")["model"]
    table = next(t for t in model["tables"] if t["name"] == "Compare against")
    fields = next(c for c in table["columns"] if c["name"] == "Compare against Fields")
    assert fields["extendedProperties"][0]["value"] == {"version": 3, "kind": 2}
    expression = "\n".join(table["partitions"][0]["source"]["expression"])
    for measure in ("Slip vs previous period", "Finish variance vs BL0", "Finish variance vs BL1"):
        assert f"NAMEOF ( '_Measures'[{measure}] )" in expression
    slicer = _json(generated[0] / PAGES / "p02_milestones" / "visuals" / "p02_h3_compare" / "visual.json")["visual"]
    assert slicer["visualType"] == "slicer"
    table = _json(next((generated[0] / PAGES / "p02_milestones" / "visuals").glob("*_milestone_table/visual.json")))
    params = table["visual"]["query"]["queryState"]["Values"]["fieldParameters"]
    assert params[0]["parameterExpr"]["Column"]["Property"] == "Compare against"


def _literal(props: dict, key: str):
    return props[key]["expr"]["Literal"]["Value"]


def test_bookmarks_and_the_bl1_bl0_toggle(generated):
    out = generated[0]
    bm_dir = out / "DOP.Report" / "definition" / "bookmarks"
    index = _json(bm_dir / "bookmarks.json")["items"]
    assert index[0] == {"name": "bmg_compare", "displayName": "Compare",
                        "children": ["bm_compare_bl1", "bm_compare_bl0"]}
    assert [i["name"] for i in index[1:]] == ["bmg_look", "bmg_float", "bmg_register", "bm_decisions_spotlight",
                                         "bm_reset"]
    assert index[1]["children"] == ["bm_look_ahead", "bm_look_back"]
    assert index[2]["children"] == ["bm_float_trend", "bm_float_bridge"]
    assert index[3]["children"] == ["bm_register_decisions", "bm_register_risks", "bm_register_map"]
    bl0 = _json(bm_dir / "bm_compare_bl0.bookmark.json")
    # Data on, Selected visuals only: the data-date slicer is not captured, so it keeps the reader's choice
    assert bl0["options"]["applyOnlyToTargetVisuals"] is True and bl0["options"]["suppressData"] is False
    visuals = bl0["explorationState"]["sections"]["p02_milestones"]["visualContainers"]
    assert "p02_h4_dd_slicer" not in visuals
    where = (visuals["p02_h3_compare"]["singleVisual"]["objects"]["merge"]["general"][0]["properties"]["filter"]
             ["filter"]["Where"][0]["Condition"]["In"])
    assert where["Expressions"][0]["Column"]["Property"] == "Compare against Fields"
    assert where["Values"] == [[{"Literal": {"Value": "'''_Measures''[Finish variance vs BL0]'"}}]]
    assert visuals["p02_v05_finish_profile"]["singleVisual"]["display"]["mode"] == "hidden"
    assert "display" not in visuals["p02_v06_finish_profile_bl0"]["singleVisual"]          # shown, in month order
    assert visuals["p02_v06_finish_profile_bl0"]["singleVisual"]["orderBy"][0]["Direction"] == 1
    # the page opens on BL1: the BL0 copy of the chart and the inactive halves of the toggle start hidden
    page = out / PAGES / "p02_milestones" / "visuals"
    hidden = {d.name for d in page.iterdir() if _json(d / "visual.json").get("isHidden")}
    assert hidden == {"p02_v06_finish_profile_bl0", "p02_h13_bl1_off", "p02_h14_bl0_on"}
    # the owner bars drill down to asset and workstream
    bars = _json(page / "p02_v03_late_by_owner" / "visual.json")["visual"]["query"]["queryState"]["Category"]
    assert [(p["queryRef"], p["active"]) for p in bars["projections"]] == [
        ("dim_owner.owner_name", True), ("dim_activity.asset_name", False), ("dim_activity.workstream_name", False)]
    spotlight = _json(bm_dir / "bm_decisions_spotlight.bookmark.json")
    assert spotlight["options"]["suppressData"] is True and spotlight["options"]["suppressActiveSection"] is False
    sections = spotlight["explorationState"]["sections"]["p01_exec"]["visualContainers"]
    assert sections["p01_v05_open_decisions"]["singleVisual"]["display"]["mode"] == "spotlight"
    # pages 3 and 5: one full-width table with the other behind a toggle; display-only bookmarks
    for page, shown_by_default, hidden_by_default in (
            ("p03_critical", "look_ahead", {"p03_v06_look_back", "p03_h17_ahead_off", "p03_h18_back_on",
                                             "p03_v05_float_bridge", "p03_h13_trend_off", "p03_h14_bridge_on"}),
            ("p05_risks", "decision_log", {"p05_v05_risk_register", "p05_v06_risk_map", "p05_h13_decisions_off",
                                           "p05_h14_risks_on", "p05_h16_map_on"})):
        visuals_dir = out / PAGES / page / "visuals"
        assert {d.name for d in visuals_dir.iterdir() if _json(d / "visual.json").get("isHidden")} == hidden_by_default
        assert any(d.name.endswith(shown_by_default) for d in visuals_dir.iterdir())
    # the register's third choice: the risk map shown, the decision log and the register hidden
    risk_map = _json(bm_dir / "bm_register_map.bookmark.json")
    shown = risk_map["explorationState"]["sections"]["p05_risks"]["visualContainers"]
    assert "display" not in shown["p05_v06_risk_map"]["singleVisual"] and "display" not in shown["p05_h16_map_on"]["singleVisual"]
    assert {shown[n]["singleVisual"]["display"]["mode"] for n in ("p05_v04_decision_log", "p05_v05_risk_register")} == {"hidden"}
    # the 5 x 5 map: impact (5 at the top) by probability over the Risk grid cells, each tinted by its band
    grid = _json(out / PAGES / "p05_risks" / "visuals" / "p05_v06_risk_map" / "visual.json")["visual"]
    assert grid["visualType"] == "pivotTable"
    state = grid["query"]["queryState"]
    assert state["Rows"]["projections"][0]["queryRef"] == "Risk grid.impact"
    assert state["Columns"]["projections"][0]["queryRef"] == "Risk grid.probability"
    assert grid["query"]["sortDefinition"]["sort"][0]["direction"] == "Descending"
    tint = next(e for e in grid["objects"]["values"] if "backColor" in e["properties"])
    assert tint["properties"]["backColor"]["solid"]["color"]["expr"]["Measure"]["Property"] == "Risk cell colour"
    assert grid["objects"]["subTotals"][0]["properties"] == {"columnSubtotals": {"expr": {"Literal": {"Value": "false"}}},
                                                           "rowSubtotals": {"expr": {"Literal": {"Value": "false"}}}}
    # page 3: the float bridge behind a Trend | Bridge toggle, a waterfall over the update axis
    bridge = _json(bm_dir / "bm_float_bridge.bookmark.json")
    shown = bridge["explorationState"]["sections"]["p03_critical"]["visualContainers"]
    assert "display" not in shown["p03_v05_float_bridge"]["singleVisual"]
    assert shown["p03_v03_float_erosion"]["singleVisual"]["display"]["mode"] == "hidden"
    waterfall = _json(out / PAGES / "p03_critical" / "visuals" / "p03_v05_float_bridge" / "visual.json")["visual"]
    assert waterfall["visualType"] == "waterfallChart"
    assert waterfall["query"]["queryState"]["Category"]["projections"][0]["queryRef"] == "Update axis.update"
    look_back = _json(bm_dir / "bm_look_back.bookmark.json")
    assert look_back["options"]["suppressData"] is True and look_back["options"]["applyOnlyToTargetVisuals"] is True
    reset = _json(bm_dir / "bm_reset.bookmark.json")
    assert reset["options"]["suppressActiveSection"] is True
    # a data bookmark restores each named visual's own filters and sort, or Desktop drops them
    decisions = reset["explorationState"]["sections"]["p01_exec"]["visualContainers"]["p01_v05_open_decisions"]
    assert decisions["filters"]["byExpr"][0]["expression"]["Column"]["Property"] == "status"
    assert decisions["singleVisual"]["orderBy"][0]["Direction"] == 1
    # the offenders' check slicer opens empty, so Reset removes its selection
    check = reset["explorationState"]["sections"]["p06_quality"]["visualContainers"]["p06_h3_check"]
    assert check["singleVisual"]["objects"]["remove"] == [{"object": "general", "property": "filter"}]
    dd_slicers = {f"{p[:3]}_h4_dd_slicer" for p in _json(out / PAGES / "pages.json")["pageOrder"]
                  if (out / PAGES / p / "visuals" / f"{p[:3]}_h4_dd_slicer").exists()}
    assert dd_slicers <= set(reset["options"]["targetVisualNames"]) and len(dd_slicers) == 8
    # every report page's rail has both view buttons
    for page_dir in (out / PAGES).iterdir():
        if page_dir.is_dir() and _json(page_dir / "page.json").get("type") != "Tooltip":
            p = page_dir.name[:3]
            for key, target in (("h10_spotlight", "bm_decisions_spotlight"), ("h11_reset", "bm_reset")):
                link = _json(page_dir / "visuals" / f"{p}_{key}" / "visual.json")["visual"]
                props = link["visualContainerObjects"]["visualLink"][0]["properties"]
                assert _literal(props, "bookmark") == f"'{target}'"


def test_phone_layout(generated):
    out = generated[0]
    visuals = out / PAGES / "p01_exec" / "visuals"
    mobile = {d.name: _json(d / "mobile.json") for d in visuals.iterdir() if (d / "mobile.json").exists()}
    # the page list and the rail buttons stay off the phone (the app lists the pages itself)
    assert not {"p01_h6_navigator", "p01_h9_views", "p01_h10_spotlight", "p01_h11_reset"} & set(mobile)
    assert {"p01_h1_programme", "p01_h0_title", "p01_h4_dd_slicer", "p01_v01_kpis", "p01_h7_provenance"} <= set(mobile)
    boxes = sorted((m["position"]["y"], m["position"]["height"], n) for n, m in mobile.items())
    for m in mobile.values():
        assert m["position"]["x"] >= 0 and m["position"]["x"] + m["position"]["width"] <= 324
    for (y1, h1, a), (y2, _, b) in zip(boxes, boxes[1:]):
        assert y1 + h1 <= y2, f"{a} and {b} overlap on the phone"
    # caption | value references need the width: one tile per row, the trend line kept
    kpis = mobile["p01_v01_kpis"]["objects"]
    layout = kpis["layout"][0]["properties"]
    assert _literal(layout, "columnCount") == "1L" and _literal(layout, "orientation") == "0D"
    assert "image" not in kpis
    # the six short-reference tiles of page 3 go two per row, without the trend line
    p03 = _json(next((out / PAGES / "p03_critical" / "visuals").glob("*_kpis/mobile.json")))["objects"]
    assert _literal(p03["layout"][0]["properties"], "columnCount") == "2L"
    assert len(p03["image"]) == 6 and all(_literal(e["properties"], "show") == "false" for e in p03["image"])
    # the Gantt page keeps its landscape layout on phones
    assert not list((out / PAGES / "p09_gantt").rglob("mobile.json"))


def test_tooltip_page_is_wired_to_the_float_matrix(generated):
    out = generated[0]
    matrix = next((out / PAGES / "p01_exec" / "visuals").glob("*_float_matrix/visual.json"))
    tip = _json(matrix)["visual"]["visualContainerObjects"]["visualTooltip"][0]["properties"]
    assert tip["type"]["expr"]["Literal"]["Value"] == "'Canvas'"
    assert tip["section"]["expr"]["Literal"]["Value"] == "'p10_float_tip'"
    assert (out / PAGES / "p10_float_tip" / "page.json").exists()
