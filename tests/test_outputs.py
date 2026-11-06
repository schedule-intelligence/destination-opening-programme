"""Output checks: the PowerPoint packs and the Excel controls workbook open cleanly and follow the house rules
(action titles, footer, Owner columns, native charts, no placeholders, nothing overlapping or overflowing)."""
import datetime as dt
import json
import re

import pytest
from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu

from conftest import ROOT
from dop import pptx_gen as g

DASH = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
LATEST = DASH["meta"]["latest"]
FOOTER = f"Source: DOP P6 XER · data date {dt.date.fromisoformat(LATEST):%d-%b-%Y} · reconciled ✓"
IN = 914400


@pytest.fixture(scope="module")
def packs(tmp_path_factory):
    out = tmp_path_factory.mktemp("pptx")
    paths = {p: g.build_pack(ROOT, LATEST, p, out_dir=out) for p in ("monthly", "fortnightly")}
    return {p: (path, Presentation(str(path))) for p, path in paths.items()}


def _norm(t):
    """Slides keep dates, IDs and number-unit pairs on one line with non-breaking hyphens and spaces; compare the
    visible text with the plain characters."""
    return t.replace("‑", "-").replace(" ", " ")


def _texts(slide):
    for sh in slide.shapes:
        if sh.has_text_frame:
            yield _norm(sh.text_frame.text)
        if sh.has_table:
            for row in sh.table.rows:
                for cell in row.cells:
                    yield _norm(cell.text)


def _title(slide):
    return _norm(next((sh.text_frame.text for sh in slide.shapes if sh.name == "Title" and sh.has_text_frame), ""))


def test_file_names(packs):
    assert packs["monthly"][0].name == f"DOP_monthly_pack_{LATEST}.pptx"
    assert packs["fortnightly"][0].name == f"DOP_fortnightly_flash_{LATEST}.pptx"


def test_slide_counts_and_size(packs):
    assert 13 <= len(packs["monthly"][1].slides) <= 15
    assert 5 <= len(packs["fortnightly"][1].slides) <= 7
    for _, prs in packs.values():
        assert (prs.slide_width, prs.slide_height) == (Emu(int(13.333 * IN)), Emu(int(7.5 * IN)))


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_titles_footer_and_no_placeholders(packs, pack):
    prs = packs[pack][1]
    titles = []
    for i, s in enumerate(prs.slides, 1):
        title = _title(s)
        assert title.strip(), f"slide {i} has no title"
        assert len(title.split()) >= 6, f"slide {i} title is not an action title: {title!r}"
        titles.append(title)
        assert len(s.placeholders) == 0, f"slide {i} has placeholders"
        texts = list(_texts(s))
        assert not any("click to add" in t.lower() for t in texts), f"slide {i} has placeholder text"
        assert any(t == FOOTER for t in texts), f"slide {i} lacks the footer"
        assert any(sh.name == "Slide Number" for sh in s.shapes), f"slide {i} has no slide number"
    assert len(set(titles)) == len(titles), "titles must be specific to each slide"


def test_headline_matches_dashboard(packs):
    # the dashboard headline, with floats in house units (wd); numbers unchanged
    raw = DASH["snapshots"][LATEST]["narrative"]["headline"]
    head = g.clean_narr(raw, g.Ctx(ROOT, LATEST))
    assert re.findall(r"[+-]?\d+", head) == re.findall(r"[+-]?\d+", raw)
    for pack in packs:
        # the slide title is a compact form of the headline: same numbers and dates, same answer
        title = _title(packs[pack][1].slides[0 if pack == "fortnightly" else 1])
        assert re.findall(r"[+-]?\d+", title) == re.findall(r"[+-]?\d+", head), (title, head)
        assert title.startswith("Day 1 forecast")
    cover = " ".join(_texts(packs["monthly"][1].slides[0]))
    snap = next(s for s in DASH["meta"]["snapshots"] if s["data_date"] == LATEST)
    assert snap["source_file"] in cover and snap["sha256"][:12] in cover
    assert "custom CPM engine" in cover and "no Primavera P6 licence" in cover


def test_native_charts(packs):
    charts = [sh for s in packs["monthly"][1].slides for sh in s.shapes if sh.has_chart]
    assert len(charts) >= 3
    types = {sh.chart.chart_type for sh in charts}
    assert types & {XL_CHART_TYPE.LINE, XL_CHART_TYPE.LINE_MARKERS}, "no native line chart"
    assert types & {XL_CHART_TYPE.COLUMN_CLUSTERED, XL_CHART_TYPE.BAR_CLUSTERED}, "no native bar chart"


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_coloured_bars_keep_their_sign(packs, pack):
    """A coloured data point without its own invertIfNegative is drawn as a positive bar by LibreOffice; every
    coloured point must state invertIfNegative = 0 so -14 wd is drawn below the axis in every renderer."""
    C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
    n = 0
    for s in packs[pack][1].slides:
        for sh in s.shapes:
            if sh.has_chart:
                for dpt in sh.chart._chartSpace.iter(C + "dPt"):
                    inv = dpt.find(C + "invertIfNegative")
                    assert inv is not None and inv.get("val") == "0", f"{sh.name}: coloured point without invertIfNegative=0"
                    n += 1
    assert n > 0


def test_cover_agenda_matches_slides(packs):
    prs = packs["monthly"][1]
    assert len(g.AGENDA) == len(prs.slides) - 1
    tags = [_norm(next(sh.text_frame.text for sh in s.shapes if sh.name == "Section tag")) for s in prs.slides]
    agenda = " ".join(_norm(sh.text_frame.text) for sh in prs.slides[0].shapes if sh.name == "Agenda")
    for k, item in enumerate(g.AGENDA, 2):
        assert f"{k}  {item}" in agenda, item
        assert tags[k - 1].split()[0] == item.upper().split()[0], (k, item, tags[k - 1])


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_tables_have_owner_column_and_readable_fonts(packs, pack):
    n = 0
    for i, s in enumerate(packs[pack][1].slides, 1):
        for sh in s.shapes:
            if not sh.has_table:
                continue
            n += 1
            tbl = sh.table
            headers = [c.text for c in tbl.rows[0].cells]
            assert "Owner" in headers, f"slide {i} table without Owner column: {headers}"
            assert len(tbl.rows) <= 13, f"slide {i} table has {len(tbl.rows)} rows"
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.text_frame.paragraphs:
                        for r in p.runs:
                            assert r.font.size is None or r.font.size.pt >= 10
        for sh in s.shapes:
            if sh.name == "Title":
                assert all(r.font.size.pt >= 20 for p in sh.text_frame.paragraphs for r in p.runs)
    assert n > 0


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_layout_inside_slide_no_overlap_text_fits(packs, pack):
    prs = packs[pack][1]
    W, H = prs.slide_width, prs.slide_height
    for i, s in enumerate(prs.slides, 1):
        boxes = []
        for sh in s.shapes:
            assert sh.left >= 0 and sh.top >= 0 and sh.left + sh.width <= W and sh.top + sh.height <= H, \
                f"slide {i}: {sh.name} outside the slide"
            boxes.append((sh.name, sh.left / IN, sh.top / IN, (sh.left + sh.width) / IN, (sh.top + sh.height) / IN))
            if sh.has_text_frame and sh.text_frame.text.strip():
                tf = sh.text_frame
                paras = [g.P(*[g.R(r.text, r.font.size.pt, bool(r.font.bold)) for r in p.runs])
                         for p in tf.paragraphs if p.runs]
                for p, src in zip(paras, [p for p in tf.paragraphs if p.runs]):
                    p["after"] = src.space_after.pt if src.space_after is not None else 0
                usable_w = (sh.width - tf.margin_left - tf.margin_right) / IN
                usable_h = (sh.height - tf.margin_top - tf.margin_bottom) / IN
                assert g.para_height(paras, usable_w) <= usable_h + 0.01, f"slide {i}: text overflows {sh.name}"
        tol = 0.005
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                A, B = boxes[a], boxes[b]
                overlap = A[1] < B[3] - tol and B[1] < A[3] - tol and A[2] < B[4] - tol and B[2] < A[4] - tol
                assert not overlap, f"slide {i}: {A[0]} overlaps {B[0]}"


def test_no_layout_warnings():
    # covers truncated text and tables that drop rows without a "Showing n of m" note
    for pack in ("monthly", "fortnightly"):
        assert g.build_deck(ROOT, LATEST, pack).warnings == []


def _table(slide, name):
    return next(sh.table for sh in slide.shapes if sh.has_table and sh.name == name)


def _rows(tbl):
    return [[_norm(c.text) for c in r.cells] for r in list(tbl.rows)[1:]]


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_text_alignment_is_explicit(packs, pack):
    """python-pptx autoshapes centre their first paragraph by default; every text paragraph must be left or right."""
    for i, s in enumerate(packs[pack][1].slides, 1):
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                for p in sh.text_frame.paragraphs:
                    if p.runs:
                        assert p.alignment in (PP_ALIGN.LEFT, PP_ALIGN.RIGHT), f"slide {i}: {sh.name} {p.alignment}"


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_rag_by_asset_matches_dashboard_rule(packs, pack):
    """Same rule as the dashboard: minimum total float of incomplete activities; red < 0, amber <= near-critical."""
    S = DASH["snapshots"][LATEST]
    cols, nc = S["acts"]["cols"], DASH["meta"]["near_critical_days"]
    asset = {r[0]: dict(zip(DASH["activities"]["cols"], r))["asset_code"] for r in DASH["activities"]["rows"]}
    acts = [dict(zip(cols, r)) for r in S["acts"]["rows"]]
    rows = _rows(_table(packs[pack][1].slides[1 if pack == "monthly" else 0], "RAG table"))
    assert len(rows) == len(DASH["meta"]["assets"]), "every asset needs a RAG row"
    code_of = {g.SHORT_ASSET.get(c, c): c for c in DASH["meta"]["assets"]}
    tfs = []
    for row in rows:
        code = code_of[row[0]]
        tf = min(a["total_float_d"] for a in acts if asset[a["activity_id"]] == code
                 and a["status"] != "TK_Complete" and a["total_float_d"] is not None)
        assert row[1] == ("Red" if tf < 0 else "Amber" if tf <= nc else "Green"), (code, row)
        assert row[2].startswith(g.sg(tf, "wd")), (code, row)
        tfs.append(tf)
    assert tfs == sorted(tfs), "RAG rows are listed worst first"


def test_kpis_and_decisions_match_dashboard(packs):
    sm = DASH["snapshots"][LATEST]["summary"]
    tiles = " ".join(_norm(sh.text_frame.text) for sh in packs["monthly"][1].slides[1].shapes if sh.name == "KPI tile")
    for v in (g.fd(sm["day1_forecast"]), g.sg(sm["day1_tf_d"], "wd"), g.sg(sm["day1_var_bl1_d"], "d"),
              f"{g.dqs(sm['dq_score'])} / 100", f"{sm['controls_passed']} / {sm['controls_total']}"):
        assert v in tiles, v
    open_ = [d for d in DASH["decisions"] if d["raised_data_date"] <= LATEST and not
             (d["closed_on"] and d["closed_on"] <= LATEST)]
    for pack, k in (("monthly", 9), ("fortnightly", 4)):
        slide = packs[pack][1].slides[k]
        rows = {r[0]: r for r in _rows(next(sh.table for sh in slide.shapes if sh.has_table))}
        for d in open_:
            assert d["decision_id"] in rows and g.fd(d["needed_by"]) in rows[d["decision_id"]], d["decision_id"]
            want = "Overdue" if d["needed_by"] < LATEST else "Open"
            assert want in rows[d["decision_id"]], (d["decision_id"], rows[d["decision_id"]])


def test_full_tables_where_no_note(packs):
    S = DASH["snapshots"][LATEST]
    m = packs["monthly"][1]
    assert len(_rows(_table(m.slides[7], "Readiness table"))) == \
        len({r["asset_code"] for r in S["readiness"] if r["stage"] == "Construction complete"})
    fails = sum(1 for c in S["dcma"] if c["passed"] is False and c["weight"])   # informational checks listed apart
    assert len(_rows(_table(m.slides[12], "Failing checks"))) == fails
    assert len(_rows(_table(packs["fortnightly"][1].slides[5], "Failing checks"))) == fails


@pytest.mark.parametrize("pack", ["monthly", "fortnightly"])
def test_house_units_and_wording(packs, pack):
    overdue = [d for d in DASH["decisions"] if d["raised_data_date"] <= LATEST and d["needed_by"] < LATEST
               and not (d["closed_on"] and d["closed_on"] <= LATEST)]
    for i, s in enumerate(packs[pack][1].slides, 1):
        for t in _texts(s):
            assert "<=" not in t and ">=" not in t and "->" not in t, f"slide {i}: ASCII operator in {t!r}"
            assert not re.search(r"float [+-]?\d+ d\b|[+-]?\d+ d float|TF ≤ \d+ d\b", t), \
                f"slide {i}: float not in working days: {t!r}"
            for d in overdue:
                assert not re.search(rf"{d['decision_id']}[^;.\n]*? by {g.fd(d['needed_by'])}", t), \
                    f"slide {i}: overdue {d['decision_id']} shown as 'by' a past date"


def test_ratio_and_points_formatting():
    assert g.ratio(0.949, 0.95) == "0.949"          # a miss is never rounded up to the threshold
    assert g.ratio(0.98, 0.95) == "0.98" and g.ratio(0.95, 0.95) == "0.95"
    assert g.pts(0.04) == "0.04" and g.pts(2.4) == "2.4" and g.pts(10) == "10"
    assert g.short_if("Dune Arena T&C complete to operator site access (T&C > operator)",
                      DASH["meta"]["assets"]) == "DAR T&C complete to operator site access"


def test_deterministic(tmp_path):
    a = g.build_pack(ROOT, LATEST, "fortnightly", out_dir=tmp_path / "a").read_bytes()
    b = g.build_pack(ROOT, LATEST, "fortnightly", out_dir=tmp_path / "b").read_bytes()
    assert a == b


def test_earlier_data_date_builds(tmp_path):
    first = DASH["meta"]["snapshots"][0]["data_date"]
    prs = Presentation(str(g.build_pack(ROOT, first, "monthly", out_dir=tmp_path)))
    assert 13 <= len(prs.slides) <= 15
    for s in DASH["meta"]["snapshots"]:
        for pack in ("monthly", "fortnightly"):
            assert g.build_deck(ROOT, s["data_date"], pack).warnings == [], (s["data_date"], pack)


def test_controls_workbook():
    path = ROOT / "output" / "xlsx" / f"DOP_controls_{LATEST}.xlsx"
    if not path.exists():
        pytest.skip("controls workbook not built yet (run the pipeline)")
    wb = load_workbook(path)
    for name in ("Reconciliation", "DCMA", "Milestone Variance", "Look-ahead", "Owner Scorecard"):
        assert name in wb.sheetnames, name
        ws = wb[name]
        assert ws.freeze_panes, f"{name}: no frozen panes"
        assert ws.auto_filter.ref, f"{name}: no auto-filter"
        assert ws.max_row > 2, f"{name}: empty"
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                assert not (isinstance(v, str) and "placeholder" in v.lower()), f"{ws.title}: placeholder text"
