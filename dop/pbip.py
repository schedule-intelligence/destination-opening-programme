"""Power BI project (PBIP) generator: `python -m dop pbip`.

Writes `powerbi/DOP.pbip`, `powerbi/DOP.SemanticModel` (a TMDL `definition` folder, compatibility level 1702) and
`powerbi/DOP.Report` (PBIR) from:

- the star-schema CSVs in `output/csv` (headers, plus every row to choose and verify each column type);
- `powerbi/measures.dax` (every MEASURE and every FUNCTION, with its expression kept verbatim);
- `powerbi/dop_theme.json` (registered as the report's custom theme);
- a page background image, `dop_background.svg`, generated here from the grid constants (the navy header band);
- the report bookmarks of POWERBI.md section 7 and a phone layout (`mobile.json` per visual), built from the
  page design;
- the relationships and page design of POWERBI.md, encoded below as data. `scripts/check_pbip.py` cross-checks
  the relationships and column types against POWERBI.md.

The output is deterministic: ids are uuid5 values of stable names, keys keep a fixed order, and files are UTF-8
without a BOM, with LF line endings and a 2-space indent. Running the command twice gives byte-identical files.
The command is not part of `run --all`, so a project saved from Power BI Desktop is never overwritten by a
pipeline run.
"""
from __future__ import annotations

import copy
import csv
import json
import pathlib
import re
import shutil
import uuid
from dataclasses import dataclass

from dop import tmdl

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = "DOP"
DEFAULT_CSV_FOLDER = r"V:\schedule-intelligence\output\csv"
PROGRAMME = "Destination Opening Programme"
THEME_FILE = "dop_theme.json"
BASE_THEME = "CY26SU10"                       # classic base theme shipped with the October 2026 Desktop
THEME_VERSION_AT_IMPORT = {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"}
MEASURE_TABLE = "_Measures"
THRESHOLD_TABLE = "Near-critical threshold"   # the name measures.dax uses (POWERBI.md section 4)
COMPARE_TABLE = "Compare against"             # field parameter (POWERBI.md section 4, item 4)
TREND_PREFIX = "Trend - "                     # measures.dax section 14: SVG trend images (data category Image URL)
TREND_FUNCTION = "DOP.TrendSvg"               # the DAX function (measures.dax section 0) every Trend - measure calls
COMPATIBILITY_LEVEL = 1702                    # DAX user-defined functions need 1702 or later
# measures.dax section 15: "<measure> by update" is drawn by table sparklines over the hidden, unrelated axis table
AXIS_TABLE, SPARK_SUFFIX = "Update axis", " by update"
GRID_TABLE = "Risk grid"      # the 25 cells of the risk map (page 5): probability x impact, 1 to 5 each
SPARK_MARKERS = "144D"        # sparkline markers, a bit mask as Desktop writes it: the last point (16) and isolated (128)
COMPARE_DEFAULT = "Finish variance vs BL1"    # the measure it shows when the page opens (button BL1)
# its options in slicer order (the first is selected when the page opens): label -> measure
COMPARE_OPTIONS = {"vs BL1": COMPARE_DEFAULT, "vs BL0": "Finish variance vs BL0",
                   "vs previous": "Slip vs previous period"}


def compare_key(label: str) -> str:
    """The value a selection of the Compare against slicer filters on: the hidden Fields column holds
    NAMEOF('_Measures'[measure]) for each option. Desktop keys the slicer's tiles on it, so a selection written on the
    label column filters the table but leaves every tile unselected."""
    return f"'_Measures'[{COMPARE_OPTIONS[label]}]"
NAMESPACE = uuid.UUID("5b0f8d2e-4c1a-5e7b-9a3d-6f2c8e1b4d70")

_FABRIC = "https://developer.microsoft.com/json-schemas/fabric/"
SCHEMAS = {
    "pbip": _FABRIC + "pbip/pbipProperties/1.0.0/schema.json",
    "platform": _FABRIC + "gitIntegration/platformProperties/2.0.0/schema.json",
    "pbir": _FABRIC + "item/report/definitionProperties/2.0.0/schema.json",
    "pbism": _FABRIC + "item/semanticModel/definitionProperties/1.0.0/schema.json",
    "version": _FABRIC + "item/report/definition/versionMetadata/1.0.0/schema.json",
    "report": _FABRIC + "item/report/definition/report/3.3.0/schema.json",
    "pages": _FABRIC + "item/report/definition/pagesMetadata/1.1.0/schema.json",
    "page": _FABRIC + "item/report/definition/page/2.1.0/schema.json",
    "visual": _FABRIC + "item/report/definition/visualContainer/2.12.0/schema.json",
    "mobile": _FABRIC + "item/report/definition/visualContainerMobileState/2.7.0/schema.json",
    "bookmark": _FABRIC + "item/report/definition/bookmark/2.1.0/schema.json",
    "bookmarks": _FABRIC + "item/report/definition/bookmarksMetadata/1.0.0/schema.json",
}

# Report bookmarks (POWERBI.md section 7): file name = bookmark name
BM_COMPARE_BL1, BM_COMPARE_BL0 = "bm_compare_bl1", "bm_compare_bl0"
BM_SPOTLIGHT, BM_RESET = "bm_decisions_spotlight", "bm_reset"
BM_LOOK_AHEAD, BM_LOOK_BACK = "bm_look_ahead", "bm_look_back"
BM_DECISIONS, BM_RISKS, BM_RISK_MAP = "bm_register_decisions", "bm_register_risks", "bm_register_map"
BM_FLOAT_TREND, BM_FLOAT_BRIDGE = "bm_float_trend", "bm_float_bridge"

# Palette shared with the dashboard, the PowerPoint packs and dop_theme.json. The report's structural colours
# (text, backgrounds, gridlines, outlines) live in dop_theme.json only; visuals name a palette colour by its theme
# position (theme_colour) and keep a fixed hex code only where a theme colour cannot go (see colour).
NAVY, TEAL, SLATE = "#1F3A5F", "#2B7A78", "#64748B"
RED, AMBER, GREEN, WHITE = "#C0392B", "#D68910", "#1E8449", "#FFFFFF"
FOREGROUND = "#1A202C"        # text in a text box (a text run takes a fixed colour)
RAIL_LINE = "#4A6A90"         # outline of the rail's buttons: the navy tinted toward white
PLOT_TINT = 0.95              # the hero chart's plot area: the navy tinted this far toward white

# Canvas and grid (pixels): the header strip sits on a navy band painted by the page background image, the title
# row under it, then the content area with 16 px margins and gutters
PAGE_W, PAGE_H, GUTTER, MARGIN = 1280, 720, 16, 24
# Navigation rail on the left (navy, painted by the page background): programme name, page navigator, source line
RAIL_W = 192
RAIL_X, RAIL_INNER_W = 16, 160
BRAND_Y, BRAND_H = 16, 64
NAV_Y, NAV_ROW_H = 96, 40
FOOTER_Y, FOOTER_H = 584, 112
# "Views" block between the page list and the source line: a label and two bookmark buttons
VIEWS_Y, VIEW_BTN_H = 436, 32
# Content column: page name (kicker), the headline sentence and the slicers on one row, then the content grid
CONTENT_X = RAIL_W + MARGIN                   # 216
CONTENT_W = PAGE_W - CONTENT_X - MARGIN       # 1040
KICKER_Y, KICKER_H = 14, 18
TITLE_Y, TITLE_H = 32, 56
CONTENT_Y = 96
CONTENT_H = PAGE_H - CONTENT_Y - MARGIN       # 600
SLOT_W, SLOT_Y, SLOT_H = 168, 20, 60          # title-row slicers
BACK_W = 120                                  # back button on the drill-through page
# Pages 2 to 8 were drawn on the earlier 1248 x 560 grid; their rows are scaled onto the content column
LEGACY_W, LEGACY_H = 1248, 560
MIN_W, MIN_H = 180, 90                        # smallest content visual
# Phone layout (mobile.json): Desktop's phone canvas is 324 units wide; visuals stack in one column
MOBILE_W, MOBILE_GAP = 324, 8
# BL1 | BL0 toggle in the title row of the finish-profile chart: (px left of the chart's right edge, px below its
# top, width, height)
TOGGLE_BL1, TOGGLE_BL0 = (96, 8, 42, 22), (50, 8, 42, 22)
# two-word toggles over a full-width table: Look-ahead | Look-back (page 3), Decisions | Risks (page 5)
TOGGLE_AHEAD, TOGGLE_BACK = (184, 8, 84, 22), (96, 8, 84, 22)
TOGGLE_FIRST_OF_3 = (272, 8, 84, 22)     # Decisions | Risks | Risk map (page 5): the first of three pills
TOGGLE_TREND, TOGGLE_BRIDGE = (136, 8, 62, 22), (70, 8, 62, 22)     # Trend | Bridge over the float chart (page 3)
PILL_BAND = 30                # on the phone, the band above a toggled visual that holds its buttons
CANVAS, BAND_SUBTEXT = "#F7F8FA", "#C9D4E3"
BACKGROUND_FILE = "dop_background.svg"


# ----------------------------------------------------------------------------------------------------------------
# Model data (POWERBI.md sections 2 to 4)
# ----------------------------------------------------------------------------------------------------------------

# Column types are inferred from the CSV values (see infer_type). These two differ from what the value pattern
# suggests, and follow POWERBI.md section 2.
TYPE_OVERRIDES = {
    ("fact_dcma_check", "denominator"): "int",
    ("fact_scenario", "day1_impact_days"): "number",
}

# POWERBI.md section 3: (many table, many column, one table, one column, active)
RELATIONSHIPS = [
    ("fact_activity_snapshot", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_activity_snapshot", "activity_id", "dim_activity", "activity_id", True),
    ("fact_activity_snapshot", "finish", "dim_date", "date", True),
    ("fact_activity_snapshot", "bl0_finish", "dim_date", "date", False),
    ("fact_activity_snapshot", "bl1_finish", "dim_date", "date", False),
    ("fact_snapshot_summary", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_milestone_trend", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_milestone_trend", "activity_id", "dim_activity", "activity_id", True),
    ("fact_relationship", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_relationship", "succ_id", "dim_activity", "activity_id", True),
    ("fact_interface", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_interface", "giver_id", "dim_activity", "activity_id", True),
    ("fact_readiness", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_readiness", "activity_id", "dim_activity", "activity_id", True),
    ("fact_dcma_check", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_dcma_offender", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_dcma_offender", "activity_id", "dim_activity", "activity_id", True),
    ("fact_owner_scorecard", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_owner_scorecard", "owner_code", "dim_owner", "owner_code", True),
    ("fact_reconciliation", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_risk", "snapshot_id", "dim_snapshot", "snapshot_id", True),
    ("fact_risk", "owner_code", "dim_owner", "owner_code", True),
    ("fact_s_curve", "date", "dim_date", "date", True),
    ("dim_activity", "wbs_id", "dim_wbs", "wbs_id", True),
    ("dim_activity", "owner_code", "dim_owner", "owner_code", True),
    ("dim_activity", "calendar_id", "dim_calendar", "calendar_id", True),
]

# POWERBI.md section 2, step 4 and the sort-by note: readiness stage order, and sort-by columns
READINESS_STAGES = ["Construction complete", "T&C complete", "Handover to operator", "Operator trained",
                    "Trials & test events complete", "Day 1 ready"]
SORT_BY = {("dim_date", "month_name"): "month", ("dim_snapshot", "label"): "data_date",
           ("fact_readiness", "stage"): "stage_order"}
DERIVED_COLUMNS = {"fact_readiness": ["stage_order"]}     # added in Power Query, not CSV headers

# True/False columns that tables show get a text twin, <column>_label, added in Power Query, so a table reads
# Yes/No or Pass/Fail instead of True/False. Measures and filters keep using the true/false column.
LABEL_COLUMNS = {
    ("fact_activity_snapshot", "lookback_achieved"): ("Yes", "No"),
    ("fact_dcma_check", "passed"): ("Pass", "Fail"),
    ("fact_decision", "overdue"): ("Yes", "No"),
    ("fact_reconciliation", "passed"): ("Pass", "Fail"),
    ("fact_relationship", "is_driving"): ("Yes", "No"),
    ("fact_scenario", "recommended"): ("Yes", "No"),
}


def label_column(column: str) -> str:
    return f"{column}_label"


# Column format strings. Day columns (*_d, *_days) show whole days; variances, slips, movements, gaps, float
# erosion and gain and Day 1 total float carry a sign, as their measures do (POWERBI.md section 5).
COLUMN_FORMATS = {
    ("fact_dcma_check", "value"): "0.##", ("fact_dcma_check", "threshold"): "0.##",
    ("fact_dcma_check", "score"): "0.0", ("fact_reconciliation", "delta"): "0.##",
    ("fact_snapshot_summary", "avg_float_d"): "0.0",
}
_SIGNED_DAYS = re.compile(r"(^|_)(var|slip)_|movement|gain|gap|erosion|day1_tf")

# POWERBI.md section 3, design notes: hierarchies
HIERARCHIES = {
    "dim_activity": [("Programme", ["asset_name", "workstream_name", "package_name", "activity_name"])],
    "dim_wbs": [("P6 WBS", ["level1", "level2", "level3", "wbs_name"])],
    "dim_date": [("Calendar", ["year", "quarter", "month_name", "date"])],
}

# Numeric columns that identify or label rather than add up
_NO_SUM = {"year", "month", "iso_week", "level", "probability", "impact", "trend", "working_days",
           "hours_per_day", "hours_per_week", "holiday_exceptions"}

# POWERBI.md section 5, format strings
_DATE_MEASURES = {"Data date", "Previous data date", "Day 1 forecast", "Day 1 target", "Forecast finish",
                  "Milestone forecast finish", "Next decision needed by"}
_ONE_DECIMAL = {"Total float (average)", "DQ score", "DQ score movement", "Progress variance (pts)"}
_PERCENT = {"Planned % complete", "Weighted % complete (actual)", "Look-back hit rate", "Owner DQ"}
_RATIO = {"BEI", "CPLI"}
_DAY_DELTA = {"Day 1 total float", "Float erosion", "Float bridge", "Float gain", "Recommended scenario Day 1 total float",
              "Scenario Day 1 impact", "Interface gap (max)", "Readiness gap"}
_TEXT_MEASURES = {"Baseline in force", "Source file", "Day 1 RAG colour", "DQ rating", "Recommended scenario",
                  "Reconciliation status", "Reconciliation colour", "Provenance line", "Risks in cell",
                  "Risk cell colour"}
_WHOLE = {"Selected snapshot id", "Previous snapshot id", "Look window (days)", "Near-critical threshold (d)",
          "Criticality band", "Look-ahead item (flag)", "Look-back item (flag)", "Risk score (max)",
          "Total float (min)"}
_COUNT_WORDS = re.compile(r"^(Activities|Milestones|Critical count|Near-critical count|Negative float count|"
                          r"Longest path count|Look-ahead|Look-back items|Look-back achieved|Look-back missed|"
                          r"DCMA|Update discipline|BEI tasks|Interfaces|Readiness stages|High risks|"
                          r"Open decisions|Overdue decisions|Controls|Finishes|Milestone finishes)")


def measure_format(name: str) -> str | None:
    """Format string for a measure (POWERBI.md section 5); None for text measures."""
    if name in _TEXT_MEASURES or name.startswith(("Title - ", TREND_PREFIX)):
        return None
    if name.endswith(SPARK_SUFFIX):           # a sparkline's values: the measure it reads by update
        return measure_format(name[:-len(SPARK_SUFFIX)])
    if name in _DATE_MEASURES:
        return "dd-mmm-yyyy"
    if name in _ONE_DECIMAL:
        return "0.0"
    if name in _PERCENT:
        return "0.0%"
    if name in _RATIO:
        return "0.000"
    if name in _DAY_DELTA or re.search(r"\bvariance\b|\bmovement\b|^Slip ", name):
        return "+0;-0;0"
    if name in _WHOLE or _COUNT_WORDS.match(name):
        return "0"
    raise ValueError(f"measures.dax: no format rule for measure [{name}]; add it to dop/pbip.py")


# ----------------------------------------------------------------------------------------------------------------
# Deterministic ids and JSON helpers
# ----------------------------------------------------------------------------------------------------------------

def guid(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


def hexid(n: int, *parts: str) -> str:
    return uuid.uuid5(NAMESPACE, "/".join(parts)).hex[:n]


def dumps(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def flag(value: bool) -> dict:
    return lit("true" if value else "false")


def num(value: float) -> dict:
    return lit(f"{value}D")


def colour(hex_code: str) -> dict:
    """A fixed colour. Kept for the cases a theme colour cannot express: text runs in a text box, the colour of
    a conditional-formatting case or gradient stop, a per-series fill with a metadata selector (Desktop resolves a
    theme colour there wrongly), and white text on the navy rail, which is white in any theme."""
    return {"solid": {"color": lit(text(hex_code))}}


# The theme's data colours by position (dop_theme.json dataColors, the shared palette order). A visual that
# colours itself by position follows the theme, so a theme-file change flows to every visual.
TC_NAVY, TC_TEAL, TC_GOLD, TC_PLUM, TC_SLATE, TC_RED, TC_AMBER, TC_GREEN = range(8)


def theme_colour(index: int, percent: float = 0) -> dict:
    """The theme's data colour at `index`, tinted toward white (percent > 0) or shaded toward black (< 0)."""
    return {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": index, "Percent": percent}}}}}


def fill_of(value: int | str) -> dict:
    """A theme colour for a palette position, a fixed colour for a hex code."""
    return theme_colour(value) if isinstance(value, int) else colour(value)


# ----------------------------------------------------------------------------------------------------------------
# CSV star schema: headers and types
# ----------------------------------------------------------------------------------------------------------------

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
_INT = re.compile(r"^-?\d+$")
_INT_DOT0 = re.compile(r"^-?\d+\.0+$")
_NUMBER = re.compile(r"^-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")

M_TYPE = {"text": "type text", "int": "Int64.Type", "number": "type number", "logical": "type logical",
          "date": "type date"}
TMSL_TYPE = {"text": "string", "int": "int64", "number": "double", "logical": "boolean", "date": "dateTime"}


@dataclass
class CsvColumn:
    name: str
    kind: str          # text | int | number | logical | date
    has_time: bool     # date column whose CSV values carry a time of day


@dataclass
class CsvTable:
    name: str
    columns: list[CsvColumn]
    rows: list[dict]


def infer_type(table: str, column: str, values: list[str]) -> CsvColumn:
    """Choose the column type from its values (ISO dates as date, *_d as number, True/False as logical, whole
    numbers and counts as Int64, other numbers as number, everything else as text) and verify every value."""
    vals = [v for v in values if v != ""]
    kind = TYPE_OVERRIDES.get((table, column))
    if kind is None:
        if vals and all(v in ("True", "False") for v in vals):
            kind = "logical"
        elif vals and all(_DATE.match(v) or _DATETIME.match(v) for v in vals):
            kind = "date"
        elif vals and all(_NUMBER.match(v) for v in vals):
            if column.endswith("_d"):
                kind = "number"
            elif all(_INT.match(v) for v in vals):
                kind = "int"
            elif all(_INT_DOT0.match(v) for v in vals) and column.endswith(("_id", "_days")):
                kind = "int"          # a whole-number key or count written as 5001.0 because of blanks
            else:
                kind = "number"
        else:
            kind = "text"
    if column.startswith("is_") and kind != "logical":
        raise ValueError(f"{table}.{column}: expected True/False values")
    bad = []
    for v in vals:
        ok = {"text": True, "logical": v in ("True", "False"),
              "date": bool(_DATE.match(v) or _DATETIME.match(v)),
              "int": bool(_INT.match(v) or _INT_DOT0.match(v)),
              "number": bool(_NUMBER.match(v))}[kind]
        if not ok:
            bad.append(v)
    if bad:
        raise ValueError(f"{table}.{column}: {len(bad)} values do not convert to {kind}, e.g. {bad[:3]}")
    return CsvColumn(column, kind, kind == "date" and any(_DATETIME.match(v) for v in vals))


def read_tables(csv_dir: pathlib.Path) -> list[CsvTable]:
    tables = []
    for path in sorted(csv_dir.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            data = list(reader)
        cols = [infer_type(path.stem, h, [r[i] if i < len(r) else "" for r in data]) for i, h in enumerate(header)]
        tables.append(CsvTable(path.stem, cols, [dict(zip(header, r)) for r in data]))
    if not tables:
        raise FileNotFoundError(f"no CSV files in {csv_dir}; run `python -m dop pipeline` first")
    return tables


# ----------------------------------------------------------------------------------------------------------------
# measures.dax
# ----------------------------------------------------------------------------------------------------------------

_MEASURE_LINE = re.compile(r"^(?P<indent>[ \t]*)MEASURE\s+'_Measures'\[(?P<name>[^\]]+)\]\s*=(?P<rest>.*)$")
_FUNCTION_LINE = re.compile(r"^(?P<indent>[ \t]*)FUNCTION\s+(?P<name>[A-Za-z_][\w.]*)\s*=(?P<rest>.*)$")
_SECTION = re.compile(r"^\s*//\s*(\d+)\.\s+(.+?)\s*$")


def _is_rule(comment: str) -> bool:
    return len(comment) >= 3 and set(comment) <= set("-=")


def parse_measures(dax: str) -> list[dict]:
    """Every MEASURE in the DEFINE block: name, expression lines (dedented, otherwise verbatim), display folder
    (the numbered section heading) and description (the // comment directly above the MEASURE)."""
    return _parse_define(dax)[0]


def parse_functions(dax: str) -> list[dict]:
    """Every FUNCTION in the DEFINE block (a DAX user-defined function): name, expression lines (the parameter
    list and the body, dedented) and description (the // comment directly above it)."""
    return _parse_define(dax)[1]


def _parse_define(dax: str) -> tuple[list[dict], list[dict]]:
    lines = dax.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "DEFINE") + 1
    except StopIteration:
        raise ValueError("measures.dax: no DEFINE block") from None
    measures, functions, folder, comment, state, i = [], [], None, [], "normal", start
    while i < len(lines):
        line, stripped = lines[i], lines[i].strip()
        if line.startswith("EVALUATE"):
            break
        match = _MEASURE_LINE.match(line) or _FUNCTION_LINE.match(line)
        if match:
            indent = len(match.group("indent").expandtabs(4))
            first = [match.group("rest").strip()] if match.group("rest").strip() else []   # text after the =
            body = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() and len(nxt.expandtabs(4)) - len(nxt.expandtabs(4).lstrip()) <= indent:
                    break
                body.append(nxt.expandtabs(4))
                j += 1
            while body and not body[-1].strip():
                body.pop()
            if not body and not first:
                raise ValueError(f"measures.dax: [{match.group('name')}] has no expression")
            margin = min((len(b) - len(b.lstrip()) for b in body if b.strip()), default=0)
            expression = first + [b[margin:].rstrip() if b.strip() else "" for b in body]
            if line.lstrip().startswith("FUNCTION"):
                functions.append({"name": match.group("name"), "expression": expression,
                                  "description": " ".join(comment)})
            else:
                measures.append({"name": match.group("name"), "expression": expression, "folder": folder,
                                 "description": " ".join(comment)})
            comment, state, i = [], "normal", j
            continue
        if stripped.startswith("//"):
            body_text = stripped[2:].strip()
            if _is_rule(body_text):
                state = "header_open" if state != "header" else "normal"
                comment = []
            elif state == "header_open" and _SECTION.match(line):
                number, title = _SECTION.match(line).groups()
                folder = f"{int(number):02d} {re.split(r'\s*[(:]|\.\s', title)[0].strip()}"
                state = "header"
            elif state != "header":
                comment.append(body_text)
                state = "normal"
        elif not stripped:
            comment = []
        i += 1
    names = [m["name"] for m in measures] + [f["name"] for f in functions]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"measures.dax: measures or functions defined more than once: {dupes}")
    return measures, functions


# ----------------------------------------------------------------------------------------------------------------
# Semantic model (built as a dictionary in TOM's shape, written as TMDL by dop.tmdl)
# ----------------------------------------------------------------------------------------------------------------

def _partition_m(table: CsvTable) -> list[str]:
    """Power Query for one CSV: read, promote headers, empty field -> null, then explicit types (en-GB).
    Date columns whose values carry a time of day are read as datetime and then reduced to date."""
    timed = [c.name for c in table.columns if c.has_time]
    derived = table.name in DERIVED_COLUMNS
    labels = sorted((column, words) for (t, column), words in LABEL_COLUMNS.items() if t == table.name)
    lines = [
        "let",
        f'    Source = Csv.Document(File.Contents(CsvFolder & "\\{table.name}.csv"), '
        '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
        '    Nulls = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted)),',
        "    Typed = Table.TransformColumnTypes(Nulls, {",
    ]
    for k, c in enumerate(table.columns):
        m_type = "type datetime" if c.has_time else M_TYPE[c.kind]
        lines.append(f'        {{"{c.name}", {m_type}}}' + ("," if k < len(table.columns) - 1 else ""))
    lines.append('    }, "en-GB")' + ("," if timed or derived or labels else ""))
    last = "Typed"
    if timed:
        lines.append("    Dates = Table.TransformColumnTypes(Typed, {")
        for k, name in enumerate(timed):
            lines.append(f'        {{"{name}", type date}}' + ("," if k < len(timed) - 1 else ""))
        lines.append("    })" + ("," if derived or labels else ""))
        last = "Dates"
    if derived:
        stages = ", ".join(f'"{s}"' for s in READINESS_STAGES)
        lines.append(f'    Staged = Table.AddColumn({last}, "stage_order", each 1 + List.PositionOf({{{stages}}}, '
                     "[stage]), Int64.Type)" + ("," if labels else ""))
        last = "Staged"
    for k, (column, (yes, no)) in enumerate(labels):
        step = f"Label_{column}"
        lines.append(f'    {step} = Table.AddColumn({last}, "{label_column(column)}", each if [{column}] = null '
                     f'then null else if [{column}] then "{yes}" else "{no}", type text)'
                     + ("," if k < len(labels) - 1 else ""))
        last = step
    lines += ["in", f"    {last}"]
    return lines


def _column(table: str, c: CsvColumn, key_columns: set[tuple[str, str]]) -> dict:
    numeric = c.kind in ("int", "number")
    no_sum = (not numeric or c.name.endswith(("_id", "_key", "_code")) or c.name in _NO_SUM
              or (table, c.name) in key_columns)
    col = {"name": c.name, "dataType": TMSL_TYPE[c.kind]}
    if c.kind == "date":
        col["formatString"] = "dd-mmm-yyyy"
    elif (table, c.name) in COLUMN_FORMATS:
        col["formatString"] = COLUMN_FORMATS[(table, c.name)]
    elif numeric and c.name.endswith(("_d", "_days")):
        col["formatString"] = "+0;-0;0" if _SIGNED_DAYS.search(c.name) else "0"
    elif c.kind == "int":
        col["formatString"] = "0"
    if table.startswith("fact_") and c.name == "snapshot_id":
        col["isHidden"] = True                 # always sliced through dim_snapshot (POWERBI.md section 10)
    if table == "dim_date" and c.name == "date":
        col["isKey"] = True
    col["lineageTag"] = guid("column", table, c.name)
    col["sourceColumn"] = c.name
    col["summarizeBy"] = "none" if no_sum else "sum"
    if (table, c.name) in SORT_BY:
        col["sortByColumn"] = SORT_BY[(table, c.name)]
    annotations = [{"name": "SummarizationSetBy", "value": "Automatic"}]
    if c.kind == "date":
        annotations.append({"name": "UnderlyingDateTimeDataType", "value": "Date"})
    col["annotations"] = annotations
    return col


def build_model(tables: list[CsvTable], measures: list[dict], csv_folder: str,
                functions: list[dict] | None = None) -> dict:
    by_name = {t.name: t for t in tables}
    key_columns = {(r[0], r[1]) for r in RELATIONSHIPS} | {(r[2], r[3]) for r in RELATIONSHIPS}
    for many, mcol, one, ocol, _ in RELATIONSHIPS:
        for t, c in ((many, mcol), (one, ocol)):
            if t not in by_name or c not in {x.name for x in by_name[t].columns}:
                raise ValueError(f"relationship column {t}[{c}] is not in output/csv")
        kinds = {next(x.kind for x in by_name[t].columns if x.name == c) for t, c in ((many, mcol), (one, ocol))}
        if len(kinds) != 1:
            raise ValueError(f"relationship {many}[{mcol}] -> {one}[{ocol}] joins different types {sorted(kinds)}")
    stages = {r["stage"] for r in by_name["fact_readiness"].rows} if "fact_readiness" in by_name else set()
    if stages - set(READINESS_STAGES):
        raise ValueError(f"fact_readiness has stages missing from the stage order: {sorted(stages - set(READINESS_STAGES))}")
    if {t for t, _ in LABEL_COLUMNS} - set(by_name):
        raise ValueError(f"LABEL_COLUMNS names tables not in output/csv: {sorted({t for t, _ in LABEL_COLUMNS} - set(by_name))}")

    model_tables = []
    for t in tables:
        columns = [_column(t.name, c, key_columns) for c in t.columns]
        for derived in DERIVED_COLUMNS.get(t.name, []):
            columns.append({"name": derived, "dataType": "int64", "formatString": "0", "isHidden": True,
                            "lineageTag": guid("column", t.name, derived), "sourceColumn": derived,
                            "summarizeBy": "none",
                            "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}]})
        kinds = {c.name: c.kind for c in t.columns}
        for column in sorted(c for (tn, c) in LABEL_COLUMNS if tn == t.name):
            if kinds.get(column) != "logical":
                raise ValueError(f"LABEL_COLUMNS: {t.name}[{column}] is not a True/False column in output/csv")
            name = label_column(column)
            columns.append({"name": name, "dataType": "string", "lineageTag": guid("column", t.name, name),
                            "sourceColumn": name, "summarizeBy": "none",
                            "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}]})
        table = {"name": t.name}
        if t.name == "dim_date":
            table["dataCategory"] = "Time"
        table["lineageTag"] = guid("table", t.name)
        table["columns"] = columns
        table["partitions"] = [{"name": f"{t.name}-{guid('partition', t.name)}", "mode": "import",
                                "source": {"type": "m", "expression": _partition_m(t)}}]
        if t.name in HIERARCHIES:
            table["hierarchies"] = [
                {"name": h, "lineageTag": guid("hierarchy", t.name, h),
                 "levels": [{"name": lvl, "ordinal": k, "column": lvl, "lineageTag": guid("level", t.name, h, lvl)}
                            for k, lvl in enumerate(levels)]}
                for h, levels in HIERARCHIES[t.name]]
        table["annotations"] = [{"name": "PBI_ResultType", "value": "Table"}]
        model_tables.append(table)

    model_tables.append({
        "name": THRESHOLD_TABLE,
        "lineageTag": guid("table", THRESHOLD_TABLE),
        "columns": [{"type": "calculatedTableColumn", "name": THRESHOLD_TABLE, "dataType": "int64",
                     "isNameInferred": False, "isDataTypeInferred": True, "formatString": "0",
                     "lineageTag": guid("column", THRESHOLD_TABLE, THRESHOLD_TABLE), "sourceColumn": "[Value]",
                     "summarizeBy": "none"}],
        "partitions": [{"name": THRESHOLD_TABLE, "mode": "import",
                        "source": {"type": "calculated", "expression": "GENERATESERIES ( 0, 30, 1 )"}}],
    })

    # POWERBI.md section 4, item 4: the "Compare against" field parameter (previous update, BL0, BL1). A button
    # slicer on page 2 picks one, and the milestone table's variance column shows that measure.
    # the baseline in force first: a forced single selection opens on the first item
    params = list(COMPARE_OPTIONS.items())
    missing = [m for _, m in params if m not in {x["name"] for x in measures}]
    if missing:
        raise ValueError(f"Compare against: measures {missing} are not in measures.dax")
    c, fields, order = COMPARE_TABLE, f"{COMPARE_TABLE} Fields", f"{COMPARE_TABLE} Order"
    model_tables.append({
        "name": c,
        "lineageTag": guid("table", c),
        "columns": [
            {"type": "calculatedTableColumn", "name": c, "dataType": "string", "isNameInferred": False,
             "isDataTypeInferred": True, "sourceColumn": "[Value1]", "sortByColumn": order,
             "relatedColumnDetails": {"groupByColumns": [{"groupingColumn": fields}]},
             "lineageTag": guid("column", c, c), "summarizeBy": "none"},
            {"type": "calculatedTableColumn", "name": fields, "dataType": "string", "isHidden": True,
             "isNameInferred": False, "isDataTypeInferred": True, "sourceColumn": "[Value2]",
             "lineageTag": guid("column", c, fields), "summarizeBy": "none",
             "extendedProperties": [{"type": "json", "name": "ParameterMetadata", "value": {"version": 3, "kind": 2}}]},
            {"type": "calculatedTableColumn", "name": order, "dataType": "int64", "isHidden": True,
             "isNameInferred": False, "isDataTypeInferred": True, "sourceColumn": "[Value3]", "formatString": "0",
             "lineageTag": guid("column", c, order), "summarizeBy": "none"},
        ],
        "partitions": [{"name": c, "mode": "import", "source": {"type": "calculated", "expression": (
            ["{"] + [f"    ( \"{label}\", NAMEOF ( '{MEASURE_TABLE}'[{m}] ), {k} )" + ("," if k < len(params) - 1 else "")
                     for k, (label, m) in enumerate(params)] + ["}"])}}],
    })

    # measures.dax section 14: every Trend - measure is the KPI drawn by the DOP.TrendSvg function (section 0)
    functions = list(functions or [])
    function_names = {f["name"] for f in functions}
    for m in measures:
        if m["name"].startswith(TREND_PREFIX):
            kpi = m["name"][len(TREND_PREFIX):]
            if "\n".join(m["expression"]).strip() != f"{TREND_FUNCTION} ( [{kpi}] )":
                raise ValueError(f"measures.dax: [{m['name']}] must be {TREND_FUNCTION} ( [{kpi}] )")
            if TREND_FUNCTION not in function_names:
                raise ValueError(f"measures.dax: the {TREND_PREFIX!r} measures need FUNCTION {TREND_FUNCTION}")
    for f in functions:
        if not f["name"].startswith("DOP."):
            raise ValueError(f"measures.dax: function {f['name']} must be in the DOP. namespace")

    # measures.dax section 15: the axis of the table sparklines, one row per update. It is not related to any table,
    # so the data-date slicer leaves every update on it; each "by update" measure reads its row's update itself
    if any(m["name"].endswith(SPARK_SUFFIX) for m in measures):
        def axis_column(name: str, data_type: str, **extra) -> dict:
            return {"type": "calculatedTableColumn", "name": name, "dataType": data_type, "isHidden": True,
                    "isNameInferred": False, "isDataTypeInferred": True, "sourceColumn": f"[{name}]", **extra,
                    "lineageTag": guid("column", AXIS_TABLE, name), "summarizeBy": "none"}
        model_tables.append({
            "name": AXIS_TABLE,
            "lineageTag": guid("table", AXIS_TABLE),
            "isHidden": True,
            # update: the month of the update ("Oct 2026"), the float bridge's category, in update order
            "columns": [axis_column("snapshot_id", "int64"),
                        axis_column("data_date", "dateTime", formatString="dd-mmm-yyyy"),
                        axis_column("update", "string", sortByColumn="snapshot_id")],
            "partitions": [{"name": AXIS_TABLE, "mode": "import", "source": {"type": "calculated", "expression": [
                "SELECTCOLUMNS (", "    dim_snapshot,", '    "snapshot_id", dim_snapshot[snapshot_id],',
                '    "data_date", dim_snapshot[data_date],',
                '    "update", FORMAT ( dim_snapshot[data_date], "mmm yyyy" )', ")"]}}],
        })

    # the cells of the risk map (page 5): every probability x impact pair, 1 to 5 each, so the matrix shows all 25
    # cells whether or not a risk sits in them ([Risks in cell] lists the risks of each)
    if any(m["name"] == "Risks in cell" for m in measures):
        model_tables.append({
            "name": GRID_TABLE,
            "lineageTag": guid("table", GRID_TABLE),
            "isHidden": True,
            "columns": [{"type": "calculatedTableColumn", "name": c, "dataType": "int64", "isHidden": True,
                         "isNameInferred": False, "isDataTypeInferred": True, "sourceColumn": f"[{c}]",
                         "lineageTag": guid("column", GRID_TABLE, c), "summarizeBy": "none"}
                        for c in ("probability", "impact")],
            "partitions": [{"name": GRID_TABLE, "mode": "import", "source": {"type": "calculated", "expression": [
                "CROSSJOIN (", '    SELECTCOLUMNS ( GENERATESERIES ( 1, 5, 1 ), "probability", [Value] ),',
                '    SELECTCOLUMNS ( GENERATESERIES ( 1, 5, 1 ), "impact", [Value] )', ")"]}}],
        })

    model_measures = []
    for m in measures:
        entry = {"name": m["name"],
                 "expression": m["expression"][0] if len(m["expression"]) == 1 else m["expression"]}
        fmt = measure_format(m["name"])
        if fmt:
            entry["formatString"] = fmt
        if m["folder"]:
            entry["displayFolder"] = m["folder"]
        if m["description"]:
            entry["description"] = m["description"]
        if m["name"].startswith(TREND_PREFIX):     # an SVG data URI: cards and tables draw it as a picture
            entry["dataCategory"] = "ImageUrl"
        entry["lineageTag"] = guid("measure", m["name"])
        model_measures.append(entry)
    model_tables.append({
        "name": MEASURE_TABLE,
        "lineageTag": guid("table", MEASURE_TABLE),
        "columns": [{"name": "Placeholder", "dataType": "string", "isHidden": True,
                     "lineageTag": guid("column", MEASURE_TABLE, "Placeholder"), "sourceColumn": "Placeholder",
                     "summarizeBy": "none",
                     "annotations": [{"name": "SummarizationSetBy", "value": "Automatic"}]}],
        "partitions": [{"name": f"{MEASURE_TABLE}-{guid('partition', MEASURE_TABLE)}", "mode": "import",
                        "source": {"type": "m", "expression": [
                            "let", "    Source = #table(type table [Placeholder = text], {})", "in", "    Source"]}}],
        "measures": model_measures,
        "annotations": [{"name": "PBI_ResultType", "value": "Table"}],
    })

    relationships = []
    for many, mcol, one, ocol, active in RELATIONSHIPS:
        rel = {"name": guid("relationship", many, mcol, one, ocol)}
        if not active:
            rel["isActive"] = False
        rel.update({"fromTable": many, "fromColumn": mcol, "toTable": one, "toColumn": ocol})
        relationships.append(rel)

    folder_m = csv_folder.replace('"', '""')
    query_order = ["CsvFolder"] + [t.name for t in tables] + [MEASURE_TABLE]
    model = {
        "culture": "en-US",
        "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
        "defaultPowerBIDataSourceVersion": "powerBI_V3",
        "sourceQueryCulture": "en-GB",
        "tables": model_tables,
        "relationships": relationships,
        "expressions": [{
            "name": "CsvFolder",
            "kind": "m",
            "expression": f'"{folder_m}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
            "lineageTag": guid("expression", "CsvFolder"),
            "annotations": [{"name": "PBI_ResultType", "value": "Text"}],
        }],
        "annotations": [
            {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
            {"name": "PBI_QueryOrder", "value": json.dumps(query_order, separators=(",", ":"))},
        ],
    }
    if functions:                 # DAX user-defined functions (measures.dax section 0), expressions verbatim
        model["functions"] = [{"name": f["name"],
                               "expression": f["expression"][0] if len(f["expression"]) == 1 else f["expression"],
                               **({"description": f["description"]} if f["description"] else {})}
                              for f in functions]
    return {"compatibilityLevel": COMPATIBILITY_LEVEL, "model": model}


# ----------------------------------------------------------------------------------------------------------------
# Report building blocks (property names follow Desktop-saved PBIR files)
# ----------------------------------------------------------------------------------------------------------------

AGG_FUNCTION = {"Sum": 0, "Min": 3, "Max": 4}
SLICER_TYPES = ("slicer", "advancedSlicerVisual")        # the classic dropdown and the button slicer


@dataclass(frozen=True)
class Field:
    kind: str                 # Column | Measure | Aggregation | Sparkline
    table: str
    name: str
    func: str | None = None   # Sum | Min | Max for an Aggregation
    label: str | None = None  # displayName override


def col(table: str, name: str, label: str | None = None) -> Field:
    return Field("Column", table, name, None, label)


def mea(name: str, label: str | None = None) -> Field:
    return Field("Measure", MEASURE_TABLE, name, None, label)


def agg(table: str, name: str, func: str, label: str | None = None) -> Field:
    return Field("Aggregation", table, name, func, label)


def spark(measure: str, label: str) -> Field:
    """A table column that draws [measure] (measures.dax section 15) as a line over 'Update axis'[data_date]."""
    if not measure.endswith(SPARK_SUFFIX):
        raise ValueError(f"sparkline [{measure}] must be one of the{SPARK_SUFFIX!r} measures")
    return Field("Sparkline", MEASURE_TABLE, measure, None, label)


def _column_expr(f: Field) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": f.table}}, "Property": f.name}}


def field_expr(f: Field) -> dict:
    if f.kind == "Column":
        return _column_expr(f)
    if f.kind == "Measure":
        return {"Measure": {"Expression": {"SourceRef": {"Entity": f.table}}, "Property": f.name}}
    if f.kind == "Sparkline":                 # as Desktop writes it (Add a sparkline, calculation group per point)
        return {"SparklineData": {
            "Measure": field_expr(mea(f.name)),
            "Groupings": [_column_expr(Field("Column", AXIS_TABLE, "data_date"))],
            "ApplyCalculationGroupTo": "Point"}}
    return {"Aggregation": {"Expression": _column_expr(f), "Function": AGG_FUNCTION[f.func]}}


def query_ref(f: Field) -> str:
    base = f"{f.table}.{f.name}"
    if f.kind == "Sparkline":
        return f"SparklineData({base}_[{AXIS_TABLE}.data_date])"
    return f"{f.func}({base})" if f.kind == "Aggregation" else base


DATE_FIELDS: set[str] = set()        # "table.column" of every date column; filled from the CSV types in build_files
# "table.column" -> longest value (characters) of the text columns whose values are codes (no spaces, at most
# CODE_MAX characters: ids, file names), and the text columns that hold phrases (spaces, longer than LONG_TEXT
# characters: names, asks, descriptions). Filled from the CSV values in build_files.
CODE_CHARS: dict[str, int] = {}
LONG_TEXT: set[str] = set()
CODE_MAX, LONG_MIN = 22, 30


def _field_key(query_ref_value: str) -> str:
    return query_ref_value.split("(")[-1].rstrip(")")


def scale_column_widths(visual: dict, factor: float | None, box_w: int) -> None:
    """Fit a table's fixed column widths to its box. factor=None (pages on the current grid): the widths are
    proportions, stretched to fill the box at 9 pt. A factor (pages drawn for the earlier, wider grid) shrinks
    them and the text drops to 8 pt. Either way every column keeps room for the longest word of its header, so no
    header breaks inside a word; dates and codes (activity ids, file names: their longest value in the data) stay
    whole; and the widest column gives up what the others need. Phrase columns wrap instead (see table)."""
    entries = visual.get("objects", {}).get("columnWidth", [])
    if not entries:
        return
    small = factor is not None
    labels = {p["queryRef"]: p.get("displayName") or p["nativeQueryRef"]
              for role in visual["query"]["queryState"].values() for p in role["projections"]}
    raw = [float(e["properties"]["value"]["expr"]["Literal"]["Value"][:-1]) for e in entries]
    factor = factor if small else (box_w - 34) / sum(raw)
    widths = [w * factor for w in raw]
    char, pad = (6.2, 14) if small else (7.0, 16)          # a header word in Segoe UI Semibold at 8 / 9 pt
    floors = [max(len(w) for w in re.split(r"[\s/-]+", labels[e["selector"]["metadata"]]) if w) * char + pad
              for e in entries]
    code_char = 6.4 if small else 7.0          # upper-case letters and digits at 8 / 9 pt (seen in Desktop)
    floors = [max(f, CODE_CHARS[_field_key(e["selector"]["metadata"])] * code_char + pad)
              if _field_key(e["selector"]["metadata"]) in CODE_CHARS else f for e, f in zip(entries, floors)]
    dates = {p["queryRef"] for role in visual["query"]["queryState"].values() for p in role["projections"]
             if (DATE_FIELDS & {_field_key(p["queryRef"])})}
    floors = [max(f, 76 if small else 82) if e["selector"]["metadata"] in dates else f
              for e, f in zip(entries, floors)]
    floors = [max(f, 72) if e["selector"]["metadata"].startswith("SparklineData(") else f     # room for the line
              for e, f in zip(entries, floors)]
    widths = [max(w, f) for w, f in zip(widths, floors)]
    excess = sum(widths) - (box_w - 34)                     # padding and the vertical scroll bar
    while excess > 0.5:                     # taken from the columns with the most room above their floor
        k = max(range(len(widths)), key=lambda i: widths[i] - floors[i])
        give = min(excess, widths[k] - floors[k])
        if give <= 0.5:
            break                           # every column is at its floor: the table scrolls sideways
        widths[k] -= give
        excess -= give
    for e, w in zip(entries, widths):
        e["properties"]["value"]["expr"]["Literal"]["Value"] = f"{int(w)}D"
    if not small:
        return
    for obj in ("columnHeaders", "values"):
        for entry in visual["objects"].get(obj, []):
            if "fontSize" in entry.get("properties", {}):
                entry["properties"]["fontSize"] = num(8)


def vco(**objects: dict) -> dict:
    """visualContainerObjects entries from {object: properties}."""
    return {name: [{"properties": props}] for name, props in objects.items()}


def shape_invisible() -> dict:
    """An empty shape with no fill and no outline, used only for its (wrapping, measure-bound) title. Show goes in
    an entry of its own, without a selector, or Desktop keeps the default navy fill."""
    sel = {"id": "default"}
    return {"shape": [{"properties": {"tileShape": lit(text("rectangle"))}, "selector": sel}],
            "fill": [{"properties": {"show": flag(False)}},
                     {"properties": {"transparency": num(100)}, "selector": sel}],
            "outline": [{"properties": {"show": flag(False)}},
                        {"properties": {"transparency": num(100)}, "selector": sel}]}


class ReportBuilder:
    """Builds the PBIR report: pages, visuals and positions on a fixed grid."""

    def __init__(self, column_kinds: dict[tuple[str, str], str], latest_data_date: str, gate_ids: list[str]):
        self.kinds = column_kinds
        self.latest = latest_data_date
        self.gate_ids = gate_ids
        self.files: dict[str, bytes] = {}
        self.pages: list[str] = []
        self.nav_pages = 8                # rows in the rail's page navigator: the visible pages
        # per report page, for the bookmarks: visual names in z order, slicer -> its default filter, the
        # visuals hidden until a bookmark shows them
        self.page_state: dict[str, dict] = {}

    # -- projections ------------------------------------------------------------------------------------------
    def native_ref(self, f: Field) -> str:
        if f.kind == "Sparkline":
            return f"{f.name} by data_date"
        if f.kind != "Aggregation":
            return f.name
        kind = self.kinds.get((f.table, f.name), "number")
        words = {("Sum", None): "Sum of", ("Min", "date"): "Earliest", ("Max", "date"): "Latest",
                 ("Min", "text"): "First", ("Max", "text"): "Last", ("Min", None): "Min of", ("Max", None): "Max of"}
        word = words.get((f.func, kind)) or words[(f.func, None)]
        return f"{word} {f.name}"

    def projection(self, f: Field, active: bool | None = None) -> dict:
        p = {"field": field_expr(f), "queryRef": query_ref(f), "nativeQueryRef": self.native_ref(f)}
        if active is not None:
            p["active"] = active
        if f.label:
            p["displayName"] = f.label
        return p

    def role(self, fields: list[Field], active: bool | None = None) -> dict:
        return {"projections": [self.projection(f, active) for f in fields]}

    @staticmethod
    def sort(f: Field, direction: str) -> dict:
        return {"sort": [{"field": field_expr(f), "direction": direction}]}

    # -- container objects --------------------------------------------------------------------------------------
    @staticmethod
    def container_objects(title: str | None, alt: str | None = None) -> dict:
        out = {}
        if title is None:
            out["title"] = [{"properties": {"show": flag(False)}}]
        else:
            out["title"] = [{"properties": {"show": flag(True), "text": lit(text(title)), "titleWrap": flag(True)}}]
        if alt or title:
            out["general"] = [{"properties": {"altText": lit(text(alt or title))}}]
        return out

    @staticmethod
    def categorical_filter(name: str, f: Field, values: list[str]) -> dict:
        alias = f.table[0].lower()
        return {
            "name": name,
            "field": _column_expr(f),
            "type": "Categorical",
            "filter": {
                "Version": 2,
                "From": [{"Name": alias, "Entity": f.table, "Type": 0}],
                "Where": [{"Condition": {"In": {
                    "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": f.name}}],
                    "Values": [[{"Literal": {"Value": v}}] for v in values]}}}],
            },
            "howCreated": "User",
        }

    @staticmethod
    def measure_filter(name: str, f: Field, condition: tuple[int, str]) -> dict:
        """Visual filter on a measure, kept per row of the visual: condition = (ComparisonKind, literal), for
        example (2, "1L") for [measure] >= 1."""
        kind, value = condition
        return {
            "name": name,
            "field": field_expr(f),
            "type": "Advanced",
            "filter": {
                "Version": 2,
                "From": [{"Name": "m", "Entity": f.table, "Type": 0}],
                "Where": [{"Condition": {"Comparison": {
                    "ComparisonKind": kind,
                    "Left": {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": f.name}},
                    "Right": {"Literal": {"Value": value}}}}}],
            },
            "howCreated": "User",
        }

    @staticmethod
    def rules(f: Field, cases: list[tuple[dict, str]]) -> dict:
        """Rule-based colour: [(condition, hex)] -> Conditional expression on the measure f."""
        return {"solid": {"color": {"expr": {"Conditional": {"Cases": [
            {"Condition": cond, "Value": {"Literal": {"Value": text(hex_code)}}} for cond, hex_code in cases]}}}}}

    @staticmethod
    def compare(f: Field, kind: int, value: str) -> dict:
        return {"Comparison": {"ComparisonKind": kind, "Left": field_expr(f), "Right": {"Literal": {"Value": value}}}}

    # -- visuals ----------------------------------------------------------------------------------------------
    def textbox(self, paragraphs: list[list[tuple[str, dict]]], tight: bool = False) -> dict:
        """tight=True removes the container padding, for a one-line label in a short box."""
        container = {"background": [{"properties": {"show": flag(False)}}]}
        if tight:
            container["padding"] = [{"properties": {"top": num(0), "bottom": num(0), "left": num(0),
                                                    "right": num(0)}}]
        return {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [
                {"textRuns": [{"value": v, "textStyle": style} for v, style in runs], "horizontalTextAlignment": "left"}
                for runs in paragraphs]}}]},
            "visualContainerObjects": container,
        }

    def card(self, fields: list[Field], title: str | None, value_size: int = 15, label: bool = False,
             colour_by: str | None = None, accent: int | None = TC_NAVY, alt: str | None = None,
             label_size: int = 9) -> dict:
        """The new card visual: several values with labels and accent bars, for boxes of 240 px and wider."""
        value = {"textWrap": flag(True), "fontSize": num(value_size)}
        objects = {
            "outline": [{"properties": {"show": flag(False)}, "selector": {"id": "default"}}],
            "value": [{"properties": value, "selector": {"id": "default"}}],
            "label": [{"properties": ({"show": flag(True), "textWrap": flag(True), "fontSize": num(label_size)}
                                      if label else {"show": flag(False)}), "selector": {"id": "default"}}],
        }
        if colour_by:
            objects["value"].append({
                "properties": {"fontColor": {"solid": {"color": {"expr": field_expr(mea(colour_by))}}}},
                "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}], "metadata": query_ref(fields[0])}})
        if accent is not None:
            objects["accentBar"] = [{"properties": {"show": flag(True), "color": theme_colour(accent), "width": num(3)},
                                     "selector": {"id": "default"}}]
        return {"visualType": "cardVisual", "query": {"queryState": {"Data": self.role(fields)}},
                "objects": objects, "visualContainerObjects": self.container_objects(title, alt)}

    def kpi(self, f: Field, title: str | None, value_size: int = 20, colour_by: str | None = None,
            alt: str | None = None, wrap: bool = False) -> dict:
        """One value in the classic card, centred in the whole box. The new card visual reserves padding inside each
        value cell, which clips a 12 pt line in a 48 px card and truncates a 20 pt date in a 180 px card (seen in
        Desktop). wrap=True lets a one-sentence headline take a second line."""
        labels = {"fontSize": num(value_size)}
        if colour_by:
            labels["color"] = {"solid": {"color": {"expr": field_expr(mea(colour_by))}}}
        return {"visualType": "card", "query": {"queryState": {"Values": self.role([f])}},
                "objects": {"labels": [{"properties": labels}],
                            "categoryLabels": [{"properties": {"show": flag(False)}}],
                            "wordWrap": [{"properties": {"show": flag(wrap)}}]},
                "visualContainerObjects": self.container_objects(title, alt)}

    def multirow(self, fields: list[Field], title: str, value_size: int = 15, label_size: int = 9) -> dict:
        """Several values side by side with their labels under them, in a narrow box (the multi-row card)."""
        return {"visualType": "multiRowCard", "query": {"queryState": {"Values": self.role(fields)}},
                "objects": {"dataLabels": [{"properties": {"fontSize": num(value_size)}}],
                            "categoryLabels": [{"properties": {"show": flag(True), "fontSize": num(label_size)}}],
                            "card": [{"properties": {"barShow": flag(True), "barColor": theme_colour(TC_NAVY),
                                                     "barWeight": num(3)}}]},
                "visualContainerObjects": self.container_objects(title)}

    @staticmethod
    def back_button() -> dict:
        """Back button for the drill-through page, navy on a white pill in the title row (reading view has no
        other way back). Its colours (pill, outline, text, icon) are the theme's button defaults."""
        sel = {"id": "default"}
        return {
            "visualType": "actionButton",
            "objects": {
                "icon": [{"properties": {"show": flag(True)}},
                         {"properties": {"shapeType": lit(text("back")), "placement": lit(text("left")),
                                         "iconSize": num(14), "leftMargin": lit("30L"), "rightMargin": lit("8L")},
                          "selector": sel}],
                "text": [{"properties": {"show": flag(True)}},
                         {"properties": {"text": lit(text("Back")), "fontSize": num(11), "bold": flag(True),
                                         "horizontalAlignment": lit(text("left"))}, "selector": sel}],
                "fill": [{"properties": {"show": flag(True)}}],
                "outline": [{"properties": {"show": flag(True)}}],
                "shape": [{"properties": {"tileShape": lit(text("rectangleRoundedByPixel")),
                                          "rectangleRoundedCurve": lit("18L")}, "selector": sel}],
            },
            "visualContainerObjects": {
                "visualLink": [{"properties": {"show": flag(True), "type": lit(text("Back")),
                                               "tooltip": lit(text("Back to the page you came from"))}}],
                "background": [{"properties": {"show": flag(False)}}],
                "border": [{"properties": {"show": flag(False)}}],
                "dropShadow": [{"properties": {"show": flag(False)}}],
                "general": [{"properties": {"altText": lit(text("Back to the previous page"))}}],
            },
        }

    def bookmark_button(self, label: str, bookmark: str, style: str, tooltip: str, icon: str | None = None) -> dict:
        """A button that applies a report bookmark. style "rail": outlined text on the navy rail; "on" / "off": the
        two looks of a segmented toggle (navy pill for the active choice, the theme's default button for the
        other). Buttons take fixed colours: Desktop does not resolve a theme colour in a button's fill, outline or
        text (seen in Desktop: the pill went white). None leaves the theme's button default (white fill, grey
        outline, navy text); the rail's colours are the rail's chrome."""
        looks = {
            "rail": {"fill": None, "fill_t": 100, "hover_t": 88, "text": WHITE, "line": RAIL_LINE, "size": 10,
                     "bold": False, "align": "left", "curve": "6L"},
            "on": {"fill": NAVY, "fill_t": 0, "hover_t": 0, "text": WHITE, "line": NAVY, "size": 9,
                   "bold": True, "align": "center", "curve": "10L"},
            "off": {"fill": None, "fill_t": 0, "hover_t": 0, "text": None, "line": None, "size": 9,
                    "bold": False, "align": "center", "curve": "10L"},
        }[style]

        def paint(value) -> dict:
            return {"color": colour(value)} if value is not None else {}

        text_props = {"text": lit(text(label)), "fontSize": num(looks["size"]), "bold": flag(looks["bold"]),
                      "fontFamily": lit(text("Segoe UI")), "horizontalAlignment": lit(text(looks["align"]))}
        if looks["text"] is not None:
            text_props["fontColor"] = colour(looks["text"])
        if style == "rail":
            text_props["leftMargin"] = lit("8L")
        fill = {k: v["color"] for k, v in (("fillColor", paint(looks["fill"])),) if v}
        line = {k: v["color"] for k, v in (("lineColor", paint(looks["line"])),) if v}
        objects = {
            "text": self._states(True, {"default": text_props, "hover": text_props}),
            "fill": self._states(True, {"default": {**fill, "transparency": num(looks["fill_t"])},
                                        "hover": {**fill, "transparency": num(looks["hover_t"])}}),
            "outline": self._states(True, {"default": {**line, "weight": num(1), "transparency": num(0)}}),
            "shape": [{"properties": {"tileShape": lit(text("rectangleRoundedByPixel")),
                                      "rectangleRoundedCurve": lit(looks["curve"])}, "selector": {"id": "default"}}],
        }
        if icon:
            icon_props = {"shapeType": lit(text(icon)), "placement": lit(text("left")), "iconSize": num(14),
                          "leftMargin": lit("10L"), "rightMargin": lit("8L")}
            if looks["text"] is not None:
                icon_props["lineColor"] = colour(looks["text"])
            objects["icon"] = self._states(True, {"default": icon_props, "hover": icon_props})
        else:
            objects["icon"] = self._states(False, {})
        return {
            "visualType": "actionButton",
            "objects": objects,
            "visualContainerObjects": vco(
                visualLink={"show": flag(True), "type": lit(text("Bookmark")), "bookmark": lit(text(bookmark)),
                            "tooltip": lit(text(tooltip))},
                background={"show": flag(False)}, border={"show": flag(False)}, dropShadow={"show": flag(False)},
                general={"altText": lit(text(f"Button: {label}. {tooltip}"))}),
        }

    # -- frame ----------------------------------------------------------------------------------------------
    @staticmethod
    def _states(show: bool | None, per_state: dict[str, dict]) -> list[dict]:
        """A stateful button object: one static entry for show, then one entry per state (default, hover,
        selected). Putting show and styling in one entry makes Desktop ignore the styling."""
        out = [] if show is None else [{"properties": {"show": flag(show)}}]
        return out + [{"properties": props, "selector": {"id": state}} for state, props in per_state.items()]

    def page_navigator(self) -> dict:
        """The rail's page navigator: one row per visible page, muted text on navy; the current page is a lighter
        tile with a teal accent bar and white bold text. Hidden (drill-through) and tooltip pages are left out."""
        base_text = {"fontFamily": lit(text("Segoe UI")), "fontSize": num(10), "fontColor": colour(BAND_SUBTEXT),
                     "horizontalAlignment": lit(text("left")), "leftMargin": lit("12L"), "bold": flag(False)}
        return {
            "visualType": "pageNavigator",
            "objects": {
                "layout": [{"properties": {"orientation": lit("1L")}}],
                "pages": [{"properties": {"showHiddenPages": flag(False), "showTooltipPages": flag(False)}}],
                "shape": [{"properties": {"tileShape": lit(text("rectangleRoundedByPixel")),
                                          "rectangleRoundedCurve": lit("6L")}}],
                "fill": self._states(True, {
                    "default": {"fillColor": colour(WHITE), "transparency": num(100)},
                    "hover": {"fillColor": colour(WHITE), "transparency": num(92)},
                    "selected": {"fillColor": colour(WHITE), "transparency": num(86)}}),
                "accentBar": self._states(True, {              # rail chrome: fixed colours (see bookmark_button)
                    "default": {"color": colour(NAVY), "position": lit(text("Left")), "width": num(4)},
                    "hover": {"color": colour(NAVY), "position": lit(text("Left")), "width": num(4)},
                    "selected": {"color": colour(TEAL), "position": lit(text("Left")), "width": num(4)}}),
                "text": self._states(True, {
                    "default": base_text,
                    "hover": {**base_text, "fontColor": colour(WHITE)},
                    "selected": {**base_text, "fontColor": colour(WHITE), "bold": flag(True)}}),
                "outline": self._states(False, {}),
            },
            "visualContainerObjects": vco(background={"show": flag(False)}, border={"show": flag(False)},
                                          dropShadow={"show": flag(False)}, title={"show": flag(False)},
                                          visualHeader={"show": flag(False)},
                                          general={"altText": lit(text("Report pages"))}),
        }

    def _bare_card(self, field: Field, value: dict, label: dict | None, alt: str) -> dict:
        """A one-value new card with no tile, outline or header: text sitting on the page."""
        sel = {"id": "default"}
        objects = {"value": [{"properties": value, "selector": sel}],
                   "label": [{"properties": label or {"show": flag(False)}, "selector": sel}],
                   "outline": [{"properties": {"show": flag(False)}, "selector": sel}],
                   "fillCustom": [{"properties": {"show": flag(False)}, "selector": sel}],
                   "layout": [{"properties": {"paddingUniform": lit("0L"), "backgroundShow": flag(False)},
                               "selector": sel}]}
        container = vco(background={"show": flag(False)}, border={"show": flag(False)},
                        dropShadow={"show": flag(False)}, title={"show": flag(False)},
                        visualHeader={"show": flag(False)}, general={"altText": lit(text(alt))},
                        padding={"top": num(0), "bottom": num(0), "left": num(0), "right": num(0)})
        return {"visualType": "cardVisual", "query": {"queryState": {"Data": self.role([field])}},
                "objects": objects, "visualContainerObjects": container}

    def headline(self, f: Field, alt: str) -> dict:
        """The page's thesis sentence: the title of an empty shape, bound to the title measure and word-wrapped,
        left-aligned. A visual title wraps onto a second line; the new card's value cut the sentence off with
        "..." in Desktop. Its colour is the theme's shape title (navy); a theme colour in a title went white."""
        sel = {"id": "default"}
        return {
            "visualType": "shape",
            "objects": shape_invisible(),
            "visualContainerObjects": vco(
                title={"show": flag(True), "text": {"expr": field_expr(f)}, "titleWrap": flag(True),
                       "fontSize": num(13), "fontFamily": lit(text("Segoe UI Semibold")), "bold": flag(True),
                       "alignment": lit(text("left")), "heading": lit(text("Heading2"))},
                background={"show": flag(False)}, border={"show": flag(False)}, dropShadow={"show": flag(False)},
                visualHeader={"show": flag(False)}, general={"altText": lit(text(alt))},
                padding={"top": num(0), "bottom": num(0), "left": num(0), "right": num(0)}),
        }

    def provenance(self) -> dict:
        """Rail footer on the navy: a "Source and controls" title over [Provenance line] (data date, baseline in
        force, controls passed, source file, DQ), as the title and subtitle of an empty shape."""
        sel = {"id": "default"}
        return {
            "visualType": "shape",
            "objects": shape_invisible(),
            "visualContainerObjects": vco(
                title={"show": flag(True), "text": lit(text("SOURCE AND CONTROLS")), "fontSize": num(9),
                       "fontFamily": lit(text("Segoe UI Semibold")), "bold": flag(True), "fontColor": colour(WHITE),
                       "alignment": lit(text("left"))},
                subTitle={"show": flag(True), "text": {"expr": field_expr(mea("Provenance line"))},
                          "titleWrap": flag(True), "fontSize": num(9), "fontColor": colour(BAND_SUBTEXT),
                          "alignment": lit(text("left"))},
                background={"show": flag(False)}, border={"show": flag(False)}, dropShadow={"show": flag(False)},
                visualHeader={"show": flag(False)},
                general={"altText": lit(text("Data provenance: data date, baseline, controls passed, source"))},
                padding={"top": num(0), "bottom": num(0), "left": num(0), "right": num(0)}),
        }

    def kpi_strip(self, fields: list[Field], refs: dict[int, list[tuple[str, str]]], title: str,
                  colour_by: dict[int, str] | None = None, value_size: int = 22, columns: int | None = None,
                  ref_style: str = "tabular", trends: dict[int, str] | None = None,
                  trend_area: int = 26) -> dict:
        """One new card holding several KPIs. Each KPI shows its label, its value and reference labels underneath
        (refs: {kpi index: [(measure, caption)]}), such as the change since the previous update or the baseline
        variance. colour_by colours a KPI value with a colour measure."""
        sel = {"id": "default"}
        # colours come from the theme (cardVisual: value, label, reference labels); the strip sets sizes and places
        objects = {
            "value": [{"properties": {"fontSize": num(value_size), "fontFamily": lit(text("Segoe UI Semibold")),
                                      "horizontalAlignment": lit(text("left"))}, "selector": sel}],
            "label": [{"properties": {"show": flag(True), "fontSize": num(10), "position": lit(text("aboveValue")),
                                      "horizontalAlignment": lit(text("left"))}, "selector": sel}],
            "outline": [{"properties": {"show": flag(False)}, "selector": sel}],
            "accentBar": [{"properties": {"show": flag(True), "color": theme_colour(TC_TEAL), "width": num(3)},
                           "selector": sel}],
            # tabular: caption left, value right-aligned; sentence: caption and value run together, for tiles
            # too narrow for both columns
            "referenceLabelLayout": [{"properties": {"arrangement": lit(text("rows")),
                                                     "style": lit(text(ref_style)),
                                                     "horizontalAlignment": lit(text("left"))}}],
            "referenceLabelTitle": [{"properties": {"titleFontSize": num(9)}, "selector": sel}],
            "referenceLabelValue": [{"properties": {"valueFontSize": num(9), "valueBold": flag(True)},
                                     "selector": sel}],
            "referenceLabel": [],
        }
        if columns:                       # a fixed grid (columns x rows) instead of one row of narrow tiles
            objects["layout"] = [{"properties": {"autoGrid": flag(False), "columnCount": lit(f"{columns}L")},
                                  "selector": sel}]
        if not refs:
            del objects["referenceLabel"], objects["referenceLabelTitle"], objects["referenceLabelValue"], \
                objects["referenceLabelLayout"]
        for k, field in enumerate(fields):
            for j, (measure, caption) in enumerate(refs.get(k, [])):
                ref_id = f"ref-{k}-{j}"
                target = {"data": [{"dataViewWildcard": {"matchingOption": 0}}], "metadata": query_ref(field),
                          "id": ref_id, "order": j}
                objects["referenceLabel"].append({"properties": {"value": {"expr": field_expr(mea(measure))}},
                                                  "selector": target})
                if measure in _DATE_MEASURES:
                    # a date label takes its tile's format, which the label reads as .NET (dd-mmm-yyyy shows
                    # 29-000-2026), so it gets its own, as Desktop writes it (MMM is the month). Desktop applies it
                    # only under a date tile: under a number the label shows the system short date, so a date
                    # reference goes under a date tile only
                    if field.kind != "Measure" or field.name not in _DATE_MEASURES:
                        raise ValueError(f"{title}: date reference [{measure}] under the non-date tile {field.name}")
                    objects["referenceLabelValue"].append({
                        "properties": {"customFormatString": lit(text("dd-MMM-yyyy"))},
                        "selector": {"metadata": query_ref(field), "id": ref_id}})
                objects["referenceLabelTitle"].append({"properties": {
                    "titleContentType": lit(text("custom")), "titleText": lit(text(caption))},
                    "selector": {"metadata": query_ref(field), "id": ref_id}})
        for k, measure in (colour_by or {}).items():
            objects["value"].append({"properties": {"fontColor": {"solid": {"color": {"expr": field_expr(mea(measure))}}}},
                                     "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}],
                                                  "metadata": query_ref(fields[k])}})
        # trend line in a tile: the tile's callout image is an SVG measure (measures.dax section 14), as Desktop
        # writes it (captured from Desktop: imageType 'imageData', the measure bound per tile). The card has no
        # native trend chart in Desktop 2.159, so the picture is drawn by DAX.
        for k, measure in (trends or {}).items():
            if not measure.startswith(TREND_PREFIX):
                raise ValueError(f"{title}: trend measure [{measure}] must be one of the {TREND_PREFIX!r} measures")
            tile = query_ref(fields[k])
            # the line sits to the right of the label and value (trend_area % of the tile), level with the value,
            # so the reference labels keep their rows. Below the value (cardImage) the card gave the labels a
            # clipped half row. The label shares the width with the line, so a tile with a trend needs a short label
            objects.setdefault("image", []).extend([
                {"properties": {"show": flag(True), "imageType": lit(text("imageData")),
                                "position": lit(text("Right")), "imageAreaSize": lit(f"{trend_area}L"),
                                "fit": lit(text("Fit")), "padding": lit("8L"),
                                "verticalAlignment": lit(text("bottom"))},
                 "selector": {"metadata": tile}},
                {"properties": {"imageData": {"expr": field_expr(mea(measure))}},
                 "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}], "metadata": tile}}])
        # no visual title: each tile has its own label, and the page name and headline above say what the strip is.
        # The title's height goes to the tiles, so both reference labels of a tile show. The title text stays as
        # the strip's alt text.
        container = self.container_objects(title, alt=f"KPI strip: {title}")
        container["title"] = [{"properties": {"show": flag(False), "text": lit(text(title))}}]
        container["visualHeader"] = [{"properties": {"show": flag(False)}}]
        return {"visualType": "cardVisual", "query": {"queryState": {"Data": self.role(fields)}},
                "objects": objects, "visualContainerObjects": container}

    def gantt(self, task: Field, columns: list[Field], title: str, subtitle: str,
              colour_measure: str = "Criticality band") -> dict:
        """The Gantt chart (Desktop preview visual): one bar per activity from its start to its finish, grouped by
        asset, with the activity's columns on the left. Bars are red when critical and amber when near-critical
        ([Criticality band] 2 and 1), navy otherwise."""
        band = field_expr(mea(colour_measure))

        def case(v, hex_code):
            return {"Condition": {"Comparison": {"ComparisonKind": 0, "Left": band,
                                                 "Right": {"Literal": {"Value": f"{v}L"}}}},
                    "Value": {"Literal": {"Value": text(hex_code)}}}
        colour_rule = {"solid": {"color": {"expr": {"Conditional": {
            "Cases": [case(2, RED), case(1, AMBER)], "DefaultValue": {"Literal": {"Value": text(NAVY)}}}}}}}
        fas = "fact_activity_snapshot"
        state = {
            "Category": self.role([col("dim_activity", "asset_name", "Asset")]),
            "Task": self.role([task]),
            "StartDate": self.role([agg(fas, "start", "Min", "Start")]),
            "EndDate": self.role([agg(fas, "finish", "Max", "Finish")]),
            "Columns": self.role(columns),
            "Tooltips": self.role([agg(fas, "status", "Min", "Status")]),
        }
        # the first column also holds the asset group rows ("Programme Integration & Day 1"), so it is wider
        # than an activity id needs
        widths = [("dim_activity.activity_id", 204)] + [(query_ref(c), w) for c, w in
                                                        zip(columns, (250, 56, 52, 52))]
        return {
            "visualType": "ganttChart",
            "query": {"queryState": state, "sortDefinition": self.sort(agg(fas, "start", "Min"), "Ascending")},
            "objects": {
                "row": [{"properties": {"color": colour_rule},
                         "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}],
                "bar": [{"properties": {"height": num(60), "cornerRadius": num(2)}}],
                "milestone": [{"properties": {"show": flag(True), "shape": lit(text("diamond"))}}],
                "axis": [{"properties": {"zoomShow": flag(True), "primaryUnit": lit(text("month")),
                                         "secondaryUnit": lit(text("year"))}}],
                "columnHeaders": [{"properties": {"customColumnWidth": flag(True)}}],
                "columnWidth": [{"properties": {"value": num(w)}, "selector": {"metadata": m}} for m, w in widths],
            },
            "visualContainerObjects": self.with_subtitle(self.container_objects(title), subtitle),
        }

    @staticmethod
    def selection_filter(f: Field, selected: str, filter_column: str | None = None) -> dict:
        """A slicer's selection when the page opens: the literal `selected` on filter_column (default: the slicer's
        own column), in the shape Desktop keeps under general.filter."""
        alias = f.table[0].lower()
        return {"filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": f.table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}},
                                            "Property": filter_column or f.name}}],
                "Values": [[{"Literal": {"Value": selected}}]]}}}]}}

    def button_slicer(self, f: Field, title: str, selected: str, filter_column: str, buttons: int) -> dict:
        """A row of buttons (the button slicer), one per value of f and one pressed at a time; `selected` is the
        button pressed when the page opens. A button at rest is the theme's default (white, grey outline, navy
        text); the pressed one is a navy pill with white text. Objects and state selectors as Desktop writes them:
        the button's text is `value` (the field's member; `label` is the optional highlight measure), its fill
        `fillCustom`, and the pressed state's selector id is "selection:selected"."""
        sel, pressed = {"id": "default"}, {"id": "selection:selected"}
        return {
            "visualType": "advancedSlicerVisual",
            "query": {"queryState": {"Values": self.role([f], active=True)}},
            "objects": {
                "general": [{"properties": {"filter": self.selection_filter(f, selected, filter_column)}}],
                "selection": [{"properties": {"singleSelect": flag(True), "strictSingleSelect": flag(True)}}],
                "layout": [{"properties": {"columnCount": lit(f"{buttons}L"), "rowCount": lit("1L")}}],
                "shapeCustomRectangle": [{"properties": {"tileShape": lit(text("rectangleRoundedByPixel")),
                                                         "rectangleRoundedCurve": lit("10L")}, "selector": sel}],
                "value": [{"properties": {"fontSize": num(9)}, "selector": sel},
                          {"properties": {"fontColor": colour(WHITE), "bold": flag(True)}, "selector": pressed}],
                "label": [{"properties": {"show": flag(False)}, "selector": sel}],
                "fillCustom": [{"properties": {"show": flag(True)}},
                               {"properties": {"fillColor": colour(NAVY), "transparency": num(0)}, "selector": pressed}],
                "outline": [{"properties": {"show": flag(True)}},
                            {"properties": {"weight": num(1)}, "selector": sel},
                            {"properties": {"lineColor": colour(NAVY)}, "selector": pressed}],
                "accentBar": [{"properties": {"show": flag(False)}, "selector": sel}],
            },
            # no title: a button row needs about 56 px of height for its text, which is the whole title-row slot
            "visualContainerObjects": {
                "title": [{"properties": {"show": flag(False), "text": lit(text(title))}}],
                "padding": [{"properties": {"top": num(2), "bottom": num(2), "left": num(8), "right": num(8)}}],
                "general": [{"properties": {"altText": lit(text(f"Slicer: {title}"))}}],
            },
        }

    def slicer(self, f: Field, header: str, mode: str, single: bool, strict: bool, sort_desc: bool = False,
               selected: str | None = None, sync: str | None = None, filter_column: str | None = None) -> dict:
        """The classic slicer (a dropdown): selected is the literal selected when the page opens, on filter_column
        (default: the slicer's column)."""
        query = {"queryState": {"Values": self.role([f], active=True)}}
        if sort_desc:
            query["sortDefinition"] = self.sort(f, "Descending")
        general = {"selfFilterEnabled": flag(True)}
        if selected is not None:
            general["filter"] = self.selection_filter(f, selected, filter_column)
        selection = {"singleSelect": flag(single)}
        if strict:
            selection["strictSingleSelect"] = flag(True)
        visual = {
            "visualType": "slicer",
            "query": query,
            "objects": {
                "header": [{"properties": {"show": flag(True), "text": lit(text(header))}}],
                "data": [{"properties": {"mode": lit(text(mode))}}],
                "general": [{"properties": general}],
                "selection": [{"properties": selection}],
            },
            "visualContainerObjects": {
                "padding": [{"properties": {"top": num(4), "bottom": num(4), "left": num(8), "right": num(8)}}],
                "general": [{"properties": {"altText": lit(text(f"Slicer: {header}"))}}],
            },
        }
        if sync:
            visual["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
        return visual

    def table(self, fields: list[Field], title: str, sort: tuple[Field, str] | None = None,
              value_objects: list[dict] | None = None, widths: list[int] | None = None, wrap: bool | None = None,
              subtitle: str | None = None, totals: bool = True) -> dict:
        """widths (px, one per field) fix the column widths, which grow in proportion to fill the box. Without them,
        columns size to their longest value and the last columns of a wide table sit off to the right. wrap=True
        wraps long text values (names, asks, descriptions) onto more lines instead of cutting them off; by default a
        table wraps when it shows a phrase column (LONG_TEXT), so no name or ask ends in "..."."""
        if wrap is None:
            wrap = any(_field_key(query_ref(f)) in LONG_TEXT for f in fields if f.kind not in ("Measure", "Sparkline"))
        # a field parameter column becomes the measure it shows by default plus a fieldParameters entry, so
        # Desktop swaps that projection when the parameter's slicer changes
        params = []
        shown = []
        for k, f in enumerate(fields):
            if f.table == COMPARE_TABLE:
                params.append({"parameterExpr": field_expr(f), "index": k, "length": 1})
                f = mea(COMPARE_DEFAULT, f.label)
            shown.append(f)
        fields = shown
        values = self.role(fields)
        if params:                        # a total of variances means nothing
            values["fieldParameters"] = params
            totals = False
        query = {"queryState": {"Values": values}}
        if sort:
            query["sortDefinition"] = self.sort(*sort)
        objects = {
            "columnHeaders": [{"properties": {"columnAdjustment": lit(text("growToFit")),
                                              "autoSizeColumnWidth": flag(widths is None), "fontSize": num(9),
                                              "wordWrap": flag(True)}}],
            "values": [{"properties": {"fontSize": num(9), "wordWrap": flag(wrap)}}] + (value_objects or []),
        }
        if not totals:
            objects["total"] = [{"properties": {"totals": flag(False)}}]
        if widths:
            if len(widths) != len(fields):
                raise ValueError(f"{title}: {len(widths)} widths for {len(fields)} columns")
            objects["columnWidth"] = [{"properties": {"value": num(w)}, "selector": {"metadata": query_ref(f)}}
                                      for f, w in zip(fields, widths)]
        # a sparkline column: a teal line over the updates up to the selected one, its last point marked in navy
        sparks = [f for f in fields if f.kind == "Sparkline"]
        if sparks:
            objects["sparklines"] = [
                {"properties": {"chartType": lit(text("line")), "dataColor": theme_colour(TC_TEAL),
                                "strokeWidth": num(1.5), "markers": lit(SPARK_MARKERS),
                                "markerColor": theme_colour(TC_NAVY), "markerSize": num(3)},
                 "selector": {"metadata": query_ref(f)}} for f in sparks]
        return {"visualType": "tableEx", "query": query, "objects": objects,
                "visualContainerObjects": self.with_subtitle(self.container_objects(title), subtitle)}

    @staticmethod
    def with_subtitle(container: dict, subtitle: str | None) -> dict:
        """The subtitle's size and colour are the theme's (visualStyles * subTitle)."""
        if subtitle:
            container["subTitle"] = [{"properties": {"show": flag(True), "text": lit(text(subtitle))}}]
        return container

    def matrix(self, rows: list[Field], columns: list[Field], values: list[Field], title: str,
               value_objects: list[dict] | None = None, subtitle: str | None = None,
               tooltip_page: str | None = None, column_totals: bool = True, row_totals: bool = True,
               sort: tuple[Field, str] | None = None, extra_objects: dict[str, list] | None = None) -> dict:
        state = {"Rows": self.role(rows, active=True)}
        if columns:
            state["Columns"] = self.role(columns, active=True)
        state["Values"] = self.role(values)
        query = {"queryState": state}
        if sort:
            query["sortDefinition"] = self.sort(*sort)
        totals = {**({} if column_totals else {"columnSubtotals": flag(False)}),
                  **({} if row_totals else {"rowSubtotals": flag(False)})}
        return {
            "visualType": "pivotTable",
            "query": query,
            "objects": {
                "columnHeaders": [{"properties": {"autoSizeColumnWidth": flag(True), "fontSize": num(9),
                                                  "wordWrap": flag(True)}}],
                "rowHeaders": [{"properties": {"fontSize": num(9), "wordWrap": flag(True)}}],
                "values": [{"properties": {"fontSize": num(9)}}] + (value_objects or []),
                **({"subTotals": [{"properties": totals}]} if totals else {}),
                **(extra_objects or {}),
            },
            "visualContainerObjects": self.with_tooltip(self.with_subtitle(self.container_objects(title), subtitle),
                                                        tooltip_page),
        }

    def waterfall(self, category: Field, y: Field, title: str, subtitle: str | None = None,
                  y_title: str = "") -> dict:
        """A waterfall: one bar per category value that rises or falls by y, and the total at the end. Rises are
        green, falls red and the total navy, with the value on every bar and a zero line."""
        state = {"Category": self.role([category], active=True), "Y": self.role([y])}
        query = {"queryState": state, "sortDefinition": self.sort(category, "Ascending")}
        value_axis = {"show": flag(True), "fontSize": num(9), "showAxisTitle": flag(bool(y_title))}
        if y_title:
            value_axis["titleText"] = lit(text(y_title))
        objects = {
            "categoryAxis": [{"properties": {"show": flag(True), "fontSize": num(9), "showAxisTitle": flag(False)}}],
            "valueAxis": [{"properties": value_axis}],
            "labels": [{"properties": {"show": flag(True), "fontSize": num(9), "labelDisplayUnits": lit(text("1"))}}],
            "legend": [{"properties": {"show": flag(False)}}],
            "sentimentColors": [{"properties": {"increaseFill": theme_colour(TC_GREEN),
                                                "decreaseFill": theme_colour(TC_RED),
                                                "totalFill": theme_colour(TC_NAVY)}}],
            "y1AxisReferenceLine": [{"properties": {
                "show": flag(True), "value": lit("0D"), "lineColor": theme_colour(TC_SLATE), "style": lit(text("solid")),
                "width": num(1), "position": lit(text("front")), "dataLabelShow": flag(False)},
                "selector": {"id": "0"}}],
        }
        return {"visualType": "waterfallChart", "query": query, "objects": objects,
                "visualContainerObjects": self.with_subtitle(self.container_objects(title), subtitle)}

    @staticmethod
    def with_tooltip(container: dict, page: str | None) -> dict:
        """Hovering a data point shows that report page (a tooltip page) for it."""
        if page:
            container["visualTooltip"] = [{"properties": {"show": flag(True), "type": lit(text("Canvas")),
                                                          "section": lit(text(page))}}]
        return container

    def add_tooltip_page(self, number: int, key: str, display: str, visual_key: str, visual: dict,
                         width: int = 320, height: int = 240) -> None:
        """A hidden tooltip page: one visual on a small canvas, shown when a reader hovers a data point of a
        visual that names this page. The hovered point's filters reach it."""
        page, prefix = f"p{number:02d}_{key}", f"p{number:02d}"
        name = f"{prefix}_v01_{visual_key}"
        if visual.get("visualType") == "tableEx":
            scale_column_widths(visual, None, width - 16)
        self.files[f"definition/pages/{page}/visuals/{name}/visual.json"] = dumps({
            "$schema": SCHEMAS["visual"], "name": name,
            "position": {"x": 8, "y": 8, "z": 1000, "height": height - 16, "width": width - 16, "tabOrder": 1000},
            "visual": visual})
        self.files[f"definition/pages/{page}/page.json"] = dumps({
            "$schema": SCHEMAS["page"], "name": page, "displayName": display, "displayOption": "FitToPage",
            "height": height, "width": width, "type": "Tooltip", "visibility": "HiddenInViewMode",
            "pageBinding": {"name": f"Pod{page}", "type": "Tooltip", "parameters": []},
            "objects": {"background": [{"properties": {"color": colour(WHITE), "transparency": num(0)}}]}})
        self.pages.append(page)

    def chart(self, visual_type: str, category: Field, y: list[Field], title: str, series: Field | None = None,
              tooltips: list[Field] | None = None, sort: tuple[Field, str] | None = None,
              legend: bool | None = None, labels: bool = False, y_title: str | None = None,
              series_colours: dict[str, str] | None = None, subtitle: str | None = None,
              y_lines: list[tuple] | None = None, x_line: tuple[str, str] | None = None,
              markers: bool = False, series_labels: bool = False, colours: dict[str, str] | None = None,
              category_room: int | None = None, drill: list[Field] | None = None,
              plot_tint: bool = False) -> dict:
        """series_colours fixes the colour of each series value ({value: hex}), so a status series never takes
        whichever theme colour its sort position gives it. y_title "" hides the value-axis title (the chart title
        says what is counted). y_lines: (value, label, palette position, shade[, (horizontal, vertical) label
        position]); the line and its label take that theme colour.
        category_room: the share of the chart (%) the category labels may take, so long owner names or rotated
        month labels show whole; with it the labels drop to 8 pt. drill: further category levels the reader can
        drill down to (the chart's header arrows), inactive until then."""
        state = {"Category": self.role([category], active=True)}
        if drill:
            state["Category"]["projections"] += self.role(drill, active=False)["projections"]
        if series:
            state["Series"] = self.role([series])
        state["Y"] = self.role(y)
        if tooltips:
            state["Tooltips"] = self.role(tooltips)
        query = {"queryState": state}
        if sort:
            query["sortDefinition"] = self.sort(*sort)
        show_legend = legend if legend is not None else (series is not None or len(y) > 1)
        value_axis = {"show": flag(True), "fontSize": num(9)}
        if y_title:                       # by default the axis title lists every series and gets cut off
            value_axis.update({"showAxisTitle": flag(True), "titleText": lit(text(y_title))})
        elif y_title == "":
            value_axis["showAxisTitle"] = flag(False)
        category_axis = {"show": flag(True), "fontSize": num(9)}
        if category_room:
            category_axis.update({"fontSize": num(8), "maxMarginFactor": lit(f"{category_room}L"),
                                  "showAxisTitle": flag(False)})
        objects = {
            "categoryAxis": [{"properties": category_axis}],
            "valueAxis": [{"properties": value_axis}],
            "legend": [{"properties": {"show": flag(show_legend)}}],
            "labels": [{"properties": {"show": flag(labels), "labelDisplayUnits": lit(text("1"))}}],
        }
        if visual_type != "lineChart" and len(y) == 1 and series is None:
            objects["dataPoint"] = [{"properties": {"defaultColor": theme_colour(TC_NAVY)}}]
        if series_colours:
            if series is None:
                raise ValueError(f"{title}: series_colours needs a series field")
            objects["dataPoint"] = [
                {"properties": {"fill": colour(hex_code)},
                 "selector": {"data": [{"scopeId": {"Comparison": {
                     "ComparisonKind": 0, "Left": field_expr(series), "Right": {"Literal": {"Value": text(value)}}}}}]}}
                for value, hex_code in series_colours.items()]
        if colours:                       # fixed colour per measure (queryRef -> hex), not by projection order
            objects["dataPoint"] = [{"properties": {"fill": colour(hex_code)}, "selector": {"metadata": ref}}
                                    for ref, hex_code in colours.items()]
        # horizontal lines (value, label, colour, shade "before"/"after"/"none") and a vertical line at a date
        # measure with the period after it shaded
        for i, (value, label, tone, shade, *where) in enumerate(y_lines or []):
            across, up = where[0] if where else ("left", "above")
            objects.setdefault("y1AxisReferenceLine", []).append({"properties": {
                "show": flag(True), "displayName": lit(text(label)), "value": lit(f"{value}D"),
                "lineColor": theme_colour(tone), "style": lit(text("dashed")), "width": num(1.5),
                "position": lit(text("front")), "dataLabelShow": flag(True), "dataLabelText": lit(text("Name")),
                "dataLabelColor": theme_colour(tone), "dataLabelHorizontalPosition": lit(text(across)),
                "dataLabelVerticalPosition": lit(text(up)),
                "shadeShow": flag(shade != "none"), "shadeRegion": lit(text(shade)), "shadeColor": theme_colour(tone),
                "shadeTransparency": num(92)}, "selector": {"id": str(i)}})
        if x_line:
            measure, label = x_line
            objects["xAxisReferenceLine"] = [{"properties": {
                "show": flag(True), "displayName": lit(text(label)), "value": {"expr": field_expr(mea(measure))},
                "lineColor": theme_colour(TC_TEAL), "style": lit(text("solid")), "width": num(2),
                "position": lit(text("front")), "dataLabelShow": flag(True), "dataLabelText": lit(text("Name")),
                "dataLabelColor": theme_colour(TC_TEAL), "dataLabelVerticalPosition": lit(text("above")),
                "shadeShow": flag(True), "shadeRegion": lit(text("after")), "shadeColor": theme_colour(TC_SLATE),
                "shadeTransparency": num(92)}, "selector": {"id": "0"}}]
        if markers:
            objects["lineStyles"] = [{"properties": {"showMarker": flag(True), "markerSize": num(5),
                                                     "strokeWidth": num(2.5)}}]
        if series_labels:                 # names at the end of each line instead of a legend
            objects["seriesLabels"] = [{"properties": {"show": flag(True), "textSize": num(9)}}]
            objects["legend"] = [{"properties": {"show": flag(False)}}]
        if plot_tint:                     # a faint tint behind the lines sets the hero chart apart from the cards
            objects["plotArea"] = [{"properties": {"color": theme_colour(TC_NAVY, PLOT_TINT),
                                                   "colorTransparency": num(0)}}]
        return {"visualType": visual_type, "query": query, "objects": objects,
                "visualContainerObjects": self.with_subtitle(self.container_objects(title), subtitle)}

    # -- pages ------------------------------------------------------------------------------------------------
    def add_page(self, number: int, key: str, display: str, title_measure: str | None, rows: list,
                 slicers: tuple[str, ...] = ("data_date",), no_filter_from_date: tuple[str, ...] = (),
                 drillthrough: Field | None = None, headline: Field | None = None, legacy: bool = True,
                 overlays: dict[str, list[tuple]] | None = None,
                 extra_slicer: tuple[str, dict] | None = None) -> None:
        """overlays: {content key: [(key, visual, box, hidden, filters)]} drawn over that content visual, for a
        bookmark toggle. box None: an alternative of the visual in the same box (hidden=True until a bookmark shows
        it); box (dx, dy, w, h): a control dx px left of the visual's right edge and dy px below its top."""
        page = f"p{number:02d}_{key}"
        prefix = f"p{number:02d}"                 # visual names: p01_h1_programme, p01_v03_vs_bl0, ...
        placed: list[tuple[str, dict, tuple[int, int, int, int], dict | None]] = []

        # navigation rail: programme name, page navigator, provenance line (data date, baseline, controls, source)
        placed.append((f"{prefix}_h1_programme", self.textbox([
            [(PROGRAMME, {"fontFamily": "Segoe UI Semibold", "fontSize": "14px", "color": WHITE, "fontWeight": "bold"})],
            [("Schedule intelligence", {"fontFamily": "Segoe UI", "fontSize": "11px", "color": BAND_SUBTEXT})],
        ]), (RAIL_X, BRAND_Y, RAIL_INNER_W, BRAND_H), None))
        placed.append((f"{prefix}_h6_navigator", self.page_navigator(),
                       (8, NAV_Y, RAIL_W - 16, NAV_ROW_H * self.nav_pages), None))
        placed.append((f"{prefix}_h7_provenance", self.provenance(),
                       (RAIL_X, FOOTER_Y, RAIL_INNER_W, FOOTER_H), None))
        # views: bookmark buttons for the steering-committee view and for getting back to the standard view
        placed.append((f"{prefix}_h9_views", self.textbox([[("VIEWS", {
            "fontFamily": "Segoe UI Semibold", "fontSize": "9px", "color": BAND_SUBTEXT, "fontWeight": "bold"})]],
            tight=True), (RAIL_X, VIEWS_Y, RAIL_INNER_W, 18), None))
        placed.append((f"{prefix}_h10_spotlight", self.bookmark_button(
            "Decisions spotlight", BM_SPOTLIGHT, "rail", "Executive summary with the decisions table in focus",
            icon="bookmarks"), (RAIL_X, VIEWS_Y + 22, RAIL_INNER_W, VIEW_BTN_H), None))
        placed.append((f"{prefix}_h11_reset", self.bookmark_button(
            "Reset view", BM_RESET, "rail", "Latest update, default threshold and BL1 on every page",
            icon="reset"), (RAIL_X, VIEWS_Y + 22 + VIEW_BTN_H + 8, RAIL_INNER_W, VIEW_BTN_H), None))

        # title row: page name above the headline sentence; slicers (or the Back button) at its right end
        # extra_slicer (key, visual): one more title-row slicer, named p06_h3_<key>, before the threshold
        right = [s for s in ("compare", "extra", "threshold", "data_date")
                 if s in slicers or (s == "extra" and extra_slicer)]
        slot_w = {"compare": 300, "extra": SLOT_W, "threshold": SLOT_W, "data_date": SLOT_W}   # three buttons
        right_w = sum(slot_w[s] + GUTTER for s in right) + (BACK_W + GUTTER if drillthrough else 0)
        placed.append((f"{prefix}_h8_kicker", self.textbox([[(display.upper(), {
            "fontFamily": "Segoe UI Semibold", "fontSize": "10px", "color": TEAL, "fontWeight": "bold"})]], tight=True),
            (CONTENT_X, KICKER_Y, CONTENT_W - right_w, KICKER_H), None))
        head = mea(title_measure) if title_measure else headline
        placed.append((f"{prefix}_h0_title", self.headline(head, alt=f"Page headline: {display}"),
                       (CONTENT_X, TITLE_Y, CONTENT_W - right_w, TITLE_H), None))
        x = CONTENT_X + CONTENT_W - right_w + GUTTER
        for slot in right:
            box = (x, SLOT_Y, slot_w[slot], SLOT_H)
            if slot == "compare":
                # a button slicer: one button per comparison, one pressed at a time, opening on BL1
                placed.append((f"{prefix}_h3_compare", self.button_slicer(
                    col(COMPARE_TABLE, COMPARE_TABLE), "Compare against", selected=text(compare_key("vs BL1")),
                    filter_column=f"{COMPARE_TABLE} Fields", buttons=len(COMPARE_OPTIONS)), box, None))
            elif slot == "extra":
                placed.append((f"{prefix}_h3_{extra_slicer[0]}", extra_slicer[1], box, None))
            elif slot == "threshold":
                placed.append((f"{prefix}_h2_threshold", self.slicer(
                    col(THRESHOLD_TABLE, THRESHOLD_TABLE), "Near-critical (wd)", "Dropdown",
                    single=True, strict=False, selected="10L", sync="NearCriticalThreshold"), box, None))
            else:
                placed.append((f"{prefix}_h4_dd_slicer", self.slicer(
                    col("dim_snapshot", "data_date"), "Data date", "Dropdown", single=True, strict=True,
                    sort_desc=True, selected=f"datetime'{self.latest}T00:00:00'", sync="DataDate"), box, None))
            x += slot_w[slot] + GUTTER
        if drillthrough:
            placed.append((f"{prefix}_h5_back", self.back_button(),
                           (CONTENT_X + CONTENT_W - BACK_W, SLOT_Y + 12, BACK_W, 36), None))

        # content grid. Rows drawn for the earlier 1248 x 560 grid (legacy=True) are scaled onto the content column;
        # fixed table column widths scale with their box
        counter = [0]

        def fit(sizes: list[int], total: int) -> list[int]:
            free, old_free = total - GUTTER * (len(sizes) - 1), sum(sizes)
            out = [s * free // old_free for s in sizes]
            out[out.index(max(out))] += free - sum(out)
            return out

        def lay(x0: int, y0: int, width: int, height: int, row_list: list) -> None:
            heights = [h for h, _ in row_list]
            if sum(heights) + GUTTER * (len(heights) - 1) != height:
                if not legacy:
                    raise ValueError(f"{page}: row heights {heights} do not fill {height}px")
                heights = fit(heights, height)
            y = y0
            for h, (_, cells) in zip(heights, row_list):
                widths = [w for w, _ in cells]
                if sum(widths) + GUTTER * (len(widths) - 1) != width:
                    if not legacy:
                        raise ValueError(f"{page}: cell widths {widths} do not fill {width}px")
                    widths = fit(widths, width)
                cx = x0
                for w, (w_old, item) in zip(widths, cells):
                    if isinstance(item, list):
                        lay(cx, y, w, h, item)
                    else:
                        counter[0] += 1
                        vkey, visual, filters = item
                        if w < MIN_W or h < MIN_H:
                            raise ValueError(f"{page}/{vkey}: {w}x{h}px is below the {MIN_W}x{MIN_H}px minimum")
                        if visual.get("visualType") == "tableEx":
                            scale_column_widths(visual, w / w_old if legacy and w != w_old else None, w)
                        placed.append((f"{prefix}_v{counter[0]:02d}_{vkey}", visual, (cx, y, w, h), filters))
                    cx += w + GUTTER
                y += h + GUTTER

        lay(CONTENT_X, CONTENT_Y, CONTENT_W, CONTENT_H, rows)

        # overlays: alternatives of a content visual in its box, and the toggle controls drawn over it
        hidden: set[str] = set()
        hosts: dict[str, str] = {}               # overlay -> the content visual it belongs to
        controls = 12                            # control names p02_h12_..., after the rail and title row (h0-h11)
        for host_key, items in (overlays or {}).items():
            host = next(p for p in placed if re.fullmatch(rf"{prefix}_v\d+_{host_key}", p[0]))
            hx, hy, hw, hh = host[2]
            for okey, visual, rel, is_hidden, filters in items:
                if rel is None:
                    counter[0] += 1
                    name, box = f"{prefix}_v{counter[0]:02d}_{okey}", host[2]
                    if visual.get("visualType") == "tableEx":
                        scale_column_widths(visual, None, hw)
                else:
                    dx, dy, w, h = rel
                    name, box = f"{prefix}_h{controls}_{okey}", (hx + hw - dx, hy + dy, w, h)
                    controls += 1
                placed.append((name, visual, box, filters))
                hosts[name] = host[0]
                if is_hidden:
                    hidden.add(name)

        names = [p[0] for p in placed]
        for n in names:
            if len(n) > 50 or not re.fullmatch(r"[A-Za-z0-9_]+", n):
                raise ValueError(f"visual name {n!r} breaks the PBIR naming rules")
        visual_filters: dict[str, list[dict]] = {}
        for k, (name, visual, (x, y, w, h), filters) in enumerate(placed):
            z = (k + 1) * 1000
            container = {"$schema": SCHEMAS["visual"], "name": name,
                         "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
                         "visual": visual}
            if name in hidden:
                container["isHidden"] = True
            if filters:
                container["filterConfig"] = {"filters": [
                    (self.measure_filter if f.kind == "Measure" else self.categorical_filter)(
                        hexid(20, page, name, "filter", str(i), f.table, f.name), f, vals)
                    for i, (f, vals) in enumerate(filters)]}
                visual_filters[name] = container["filterConfig"]["filters"]
            self.files[f"definition/pages/{page}/visuals/{name}/visual.json"] = dumps(container)

        page_json = {"$schema": SCHEMAS["page"], "name": page, "displayName": display, "displayOption": "FitToPage",
                     "height": PAGE_H, "width": PAGE_W, "objects": {"background": [{"properties": {
                         "image": {"image": {
                             "name": lit(text(BACKGROUND_FILE)),
                             "url": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources",
                                                                      "PackageType": 1, "ItemName": BACKGROUND_FILE}}},
                             "scaling": lit(text("Fit"))}},
                         "transparency": num(0)}}]}}
        if drillthrough:
            filter_name = "Filter" + hexid(24, page, "drillthrough", drillthrough.table, drillthrough.name)
            page_json["type"] = "Drillthrough"
            page_json["visibility"] = "HiddenInViewMode"
            page_json["filterConfig"] = {"filters": [{"name": filter_name, "field": _column_expr(drillthrough),
                                                      "type": "Categorical", "howCreated": "Drillthrough"}]}
            page_json["pageBinding"] = {"name": f"Pod{page}", "type": "Drillthrough",
                                        "parameters": [{"name": f"Param_{filter_name}", "boundFilter": filter_name,
                                                        "fieldExpr": _column_expr(drillthrough)}],
                                        "acceptsFilterContext": "None"}
        if no_filter_from_date:
            slicer_name = f"{prefix}_h4_dd_slicer"
            targets = [n for n in names if any(n.endswith("_" + t) for t in no_filter_from_date)]
            if len(targets) != len(no_filter_from_date):
                raise ValueError(f"{page}: interaction targets {no_filter_from_date} not all found")
            page_json["visualInteractions"] = [{"source": slicer_name, "target": t, "type": "NoFilter"}
                                               for t in targets]
        self.files[f"definition/pages/{page}/page.json"] = dumps(page_json)
        self.pages.append(page)
        self.page_state[page] = {
            "visuals": names, "hidden": hidden, "filters": visual_filters,
            "sorts": {n: v["query"]["sortDefinition"]["sort"] for n, v, _, _ in placed
                      if v.get("query", {}).get("sortDefinition")},
            "slicers": {n: v["objects"]["general"][0]["properties"]["filter"] for n, v, _, _ in placed
                        if v.get("visualType") in SLICER_TYPES and re.match(rf"{prefix}_h\d+_", n)
                        and "filter" in v["objects"]["general"][0]["properties"]},
            "slicer_types": {n: v["visualType"] for n, v, _, _ in placed if v.get("visualType") in SLICER_TYPES},
            # title-row slicers that open with nothing selected (Reset clears them)
            "cleared": [n for n, v, _, _ in placed if v.get("visualType") in SLICER_TYPES
                        and re.match(rf"{prefix}_h\d+_", n) and "filter" not in v["objects"]["general"][0]["properties"]]}
        if not any(v.get("visualType") == "ganttChart" for _, v, _, _ in placed):
            self.mobile_layout(page, placed, hosts)

    def mobile_layout(self, page: str, placed: list[tuple], hosts: dict[str, str]) -> None:
        """The phone layout (mobile.json beside each visual.json): one 324-unit column with the programme band, the
        page name, the headline, the slicers, the content in reading order (top to bottom, left to right) and the
        source line. The page list and the rail buttons are left out (the phone app lists the pages itself); the rail
        items that sit on the navy band take a navy background of their own. A page holding the Gantt has no phone
        layout: its bars need the width, so phones show the page as it is, in landscape."""
        W, G = MOBILE_W, MOBILE_GAP
        prefix = page[:3]
        by_name = {n: (v, box) for n, v, box, _ in placed}
        navy_box = {"background": {"show": flag(True), "color": theme_colour(TC_NAVY), "transparency": num(0)},
                    "padding": {"top": num(8), "bottom": num(8), "left": num(10), "right": num(10)}}
        out: dict[str, tuple[tuple[int, int, int, int], dict]] = {}
        y = 0

        def has(suffix: str) -> str | None:
            name = f"{prefix}_{suffix}"
            return name if name in by_name else None

        def put(name: str, box: tuple[int, int, int, int], extra: dict | None = None) -> None:
            out[name] = (box, extra or {})

        put(f"{prefix}_h1_programme", (0, 0, W, 56), {"visualContainerObjects": vco(**navy_box)})
        y = 56 + G
        back = has("h5_back")
        if back:
            put(back, (W - BACK_W, y, BACK_W, 36))
            put(f"{prefix}_h8_kicker", (0, y + 9, W - BACK_W - G, 18))
            y += 36 + G
        else:
            put(f"{prefix}_h8_kicker", (0, y, W, 18))
            y += 18 + 4
        # a visual title wraps onto three lines at most, so the sentence is set smaller on the phone
        put(f"{prefix}_h0_title", (0, y, W, 72),
            {"visualContainerObjects": vco(title={"fontSize": num(9)})})
        y += 72 + G
        wide = next((n for n in by_name if n.startswith(f"{prefix}_h3_")), None)   # compare, or the check
        if wide:
            put(wide, (0, y, W, 60))
            y += 60 + G
        pair = [n for n in (has("h2_threshold"), has("h4_dd_slicer")) if n]
        if pair:
            w = (W - G * (len(pair) - 1)) // len(pair)
            for i, n in enumerate(pair):
                put(n, (i * (w + G), y, w, 60))
            y += 60 + G

        def tiles_of(visual: dict) -> int:
            return len(next(iter(visual["query"]["queryState"].values()))["projections"])

        def columns_of(visual: dict) -> int:
            # caption | value references need the full width: in a half-width tile the captions are cut ("vs BL...")
            # and, run together as sentences, they wrap and the second one is clipped. Those strips get one tile
            # per row; the rest (no references, or short "threshold 10" sentences) two
            layout = visual["objects"].get("referenceLabelLayout")
            return 1 if layout and layout[0]["properties"]["style"] == lit(text("tabular")) else 2

        def height(visual: dict) -> int:
            vtype = visual["visualType"]
            if vtype == "cardVisual":
                if columns_of(visual) == 1:          # 108 for the label and value, 24 per reference row
                    rows = 1 + max(e["selector"]["order"] for e in visual["objects"]["referenceLabel"])
                    return 40 + tiles_of(visual) * (108 + 24 * rows)
                tile = 156 if "referenceLabel" in visual["objects"] else 88
                return 40 + -(-tiles_of(visual) // 2) * tile
            return {"tableEx": 288, "pivotTable": 264, "textbox": 200, "slicer": 168}.get(vtype, 232)

        content = sorted((n for n in by_name if re.match(rf"{prefix}_v\d+_", n) and n not in hosts),
                         key=lambda n: (by_name[n][1][1], by_name[n][1][0]))
        # a visual with toggle buttons gets a band above it on the phone, and the buttons go there: across a
        # 324-unit box they would cover its title
        pill_hosts = {host for n, host in hosts.items() if by_name[n][1] != by_name[host][1]}
        for n in content:
            visual = by_name[n][0]
            h = height(visual)
            extra = {}
            if n in pill_hosts:
                y += PILL_BAND
            if visual["visualType"] == "cardVisual":
                # a grid of one or two columns instead of one row of narrow tiles, and a smaller value so a date
                # fits its tile. As Desktop writes it: entries without a selector, arrangement 0 (grid)
                cols = columns_of(visual)
                extra["objects"] = {
                    "layout": [{"properties": {
                        "autoGrid": flag(True), "maxTiles": lit(f"{cols}L"), "orientation": lit("0D"),
                        "columnCount": lit(f"{cols}L"), "rowCount": lit(f"{-(-tiles_of(visual) // cols)}L")}}],
                    "value": [{"properties": {"fontSize": num(16 if cols == 1 else 14)}, "selector": {"id": "default"}}]}
                # a full-width tile keeps its trend line; beside a 14 pt value in a half-width tile it would cut the
                # label and a date, so there the line stays on the desktop canvas
                trend_tiles = [e["selector"] for e in visual["objects"].get("image", []) if "show" in e["properties"]]
                if trend_tiles and cols == 2:
                    extra["objects"]["image"] = [{"properties": {"show": flag(False)}, "selector": s}
                                                 for s in trend_tiles]
            put(n, (0, y, W, h), extra)
            y += h + G
        for n, host in hosts.items():          # overlays keep their place on the visual they belong to
            (hx, hy, hw, hh), (mx, my, mw, mh) = by_name[host][1], out[host][0]
            x, oy, w, h = by_name[n][1]
            same_box = (x, oy, w, h) == (hx, hy, hw, hh)
            extra = {}
            visual = by_name[n][0]
            if visual["visualType"] == "pivotTable" and "columnWidth" in visual["objects"]:
                # a grid of fixed cells (the risk map): five columns share the phone's width and the risks wrap
                # inside their cell, instead of five desktop-wide columns scrolling sideways
                cells = len(visual["objects"]["columnWidth"]) * 5
                extra["objects"] = {
                    "columnWidth": [{**e, "properties": {"value": num((W - 34 - 44) // cells)}}
                                    for e in visual["objects"]["columnWidth"]],
                    "values": [{"properties": {"wordWrap": flag(True), "fontSize": num(8)}}]}
            # a toggle button sits in the band above its visual, at its desktop distance from the right edge
            put(n, (mx, my, mw, mh) if same_box else (mx + mw - (hx + hw - x), my - PILL_BAND + 4, w, h), extra)
        put(f"{prefix}_h7_provenance", (0, y, W, 104), {"visualContainerObjects": vco(**navy_box)})

        z_of = {n: (k + 1) * 1000 for k, n in enumerate(by_name)}
        for name, ((x, y, w, h), extra) in out.items():
            doc = {"$schema": SCHEMAS["mobile"], **extra,
                   "position": {"x": x, "y": y, "z": z_of[name], "height": h, "width": w, "tabOrder": z_of[name]}}
            self.files[f"definition/pages/{page}/visuals/{name}/mobile.json"] = dumps(doc)


# ----------------------------------------------------------------------------------------------------------------
# Page design (POWERBI.md section 6, mirroring the web dashboard tabs)
# ----------------------------------------------------------------------------------------------------------------

def build_pages(rb: ReportBuilder) -> None:
    fas, act = "fact_activity_snapshot", "dim_activity"

    def float_rules(f: Field) -> list[dict]:
        # < 0 red, 0 to the default near-critical threshold (10) amber, above it green (POWERBI.md section 6), as
        # light tints with dark text so the status reads without the grid shouting
        tints = [((rb.compare(f, 3, "0D")), "#FBE4E1", "#9B2C22"),
                 ({"And": {"Left": rb.compare(f, 2, "0D"), "Right": rb.compare(f, 4, "10D")}}, "#FDF1DC", "#8A5A0B"),
                 (rb.compare(f, 1, "10D"), "#E3F2E8", "#1E6B3A")]
        selector = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": query_ref(f)}
        return [{"properties": {"backColor": rb.rules(f, [(c, bg) for c, bg, _ in tints]),
                                "fontColor": rb.rules(f, [(c, fg) for c, _, fg in tints])},
                 "selector": selector}]

    # 1 Executive summary --------------------------------------------------------------------------------------
    # Hero-right layout: the KPI strip (value, label and reference labels: change and baseline variance) beside the
    # chart that proves the headline (Day 1 float by update against zero); float by asset and progress below
    # left, the decisions and risks that act on it below right
    tf_min = mea("Total float (min)", "Minimum total float")
    kpi_fields = [mea("Day 1 forecast", "Day 1 forecast"), mea("Day 1 total float", "Day 1 total float (wd)"),
                  mea("Weighted % complete (actual)", "% complete (actual)"), mea("DQ score", "DQ score (of 100)")]
    kpi_strip = rb.kpi_strip(kpi_fields, {
        0: [("Day 1 variance vs BL1", "vs BL1 (cd)"), ("Day 1 movement vs previous period", "vs previous (cd)")],
        1: [("Float erosion", "vs previous (wd)"),
            ("Recommended scenario Day 1 total float", "with recovery")],
        2: [("Planned % complete", "planned"), ("Progress variance (pts)", "variance (pts)")],
        3: [("DQ rating", "rating"), ("DQ score movement", "vs previous")],
    }, "Programme position at the selected update", colour_by={0: "Day 1 RAG colour"}, value_size=20,
        trends={0: "Trend - Day 1 variance vs BL1", 1: "Trend - Day 1 total float",
                2: "Trend - Weighted % complete (actual)", 3: "Trend - DQ score"})
    float_trend = rb.chart(
        "lineChart", col("dim_snapshot", "data_date", "Data date"), [mea("Day 1 total float", "Day 1 total float")],
        "Day 1 total float by update (working days)", sort=(col("dim_snapshot", "data_date"), "Ascending"),
        labels=True, markers=True, legend=False, y_lines=[(0, "Zero float", TC_RED, "before")], plot_tint=True,
        colours={"_Measures.Day 1 total float": NAVY}, subtitle="Below the line, Day 1 is later than its target")
    s_curve = rb.chart(
        "lineChart", col("fact_s_curve", "date", "Month end"),
        [agg("fact_s_curve", "planned_bl0", "Sum", "Planned (BL0)"),
         agg("fact_s_curve", "planned_bl1", "Sum", "Planned (BL1)"),
         agg("fact_s_curve", "forecast", "Sum", "Forecast"), agg("fact_s_curve", "actual", "Sum", "Actual")],
        "Progress S-curve (% complete)",
        sort=(col("fact_s_curve", "date"), "Ascending"), y_title="% complete", series_labels=True,
        x_line=("Data date", "Data date"), subtitle="Shaded: after the data date",
        colours={"Sum(fact_s_curve.planned_bl0)": "#A0AEC0", "Sum(fact_s_curve.planned_bl1)": SLATE,
                 "Sum(fact_s_curve.forecast)": AMBER, "Sum(fact_s_curve.actual)": TEAL})
    rb.add_page(1, "exec", "Executive summary", "Title - Executive summary", [
        # the KPI tiles carry two reference labels under the value and the trend line beside it
        (200, [(1040, ("kpis", kpi_strip, None))]),
        (192, [(624, ("day1_float_trend", float_trend, None)), (400, ("s_curve", s_curve, None))]),
        (176, [
            # the matrix needs about 450 px (asset names and seven narrow columns); the rest goes to the asks
            (528, ("float_matrix", rb.matrix(
                [col(act, "asset_name", "Asset")], [col(act, "workstream_code", "Workstream")], [tf_min],
                "Minimum total float by asset and workstream (working days)", value_objects=float_rules(tf_min),
                subtitle="Red below 0, amber 0 to 10, green above 10 working days; hover a cell for its "
                         "activities", tooltip_page="p10_float_tip"), None)),
            # the ask second and wrapped, so a reader sees what is being decided without scrolling
            (496, ("open_decisions", rb.table(
                [col("fact_decision", "decision_id", "ID"), col("fact_decision", "ask", "Ask"),
                 col("fact_decision", "owner", "Owner"), col("fact_decision", "needed_by", "Needed by"),
                 col("fact_decision", "overdue_label", "Overdue")],
                "Decisions needed, with owner and date", sort=(col("fact_decision", "needed_by"), "Ascending"),
                widths=[42, 210, 100, 82, 60], subtitle="Open decisions, earliest first"),
                [(col("fact_decision", "status"), [text("Open")])])),
        ]),
    ], no_filter_from_date=("day1_float_trend",), legacy=False)

    # 2 Milestones & slippage ----------------------------------------------------------------------------------
    # KPI strip, then the gate trend beside slippage by owner, then the milestone register beside the finish profile
    def finish_profile(baseline: str, note: str) -> dict:
        planned = f"Milestone finishes ({baseline})"
        return rb.chart(
            "clusteredColumnChart", col("dim_date", "year_month", "Month"),
            [mea("Milestone finishes (forecast)", "Forecast"), mea(planned, baseline)],
            f"Finishes per month vs {baseline}", sort=(col("dim_date", "year_month"), "Ascending"),
            y_title="", category_room=38, subtitle=note,
            colours={"_Measures.Milestone finishes (forecast)": NAVY, f"_Measures.{planned}": "#A0AEC0"})

    gate_filter = [(col(act, "activity_id"), [text(i) for i in rb.gate_ids])] if rb.gate_ids else None
    milestone_kpis = rb.kpi_strip(
        [mea("Milestones later than baseline in force", "Late vs baseline"),       # short: the trend shares the row
         mea("Milestones slipped vs previous period", "Slipped vs previous"),
         mea("Day 1 forecast", "Day 1 forecast"),
         mea("Day 1 movement vs previous period", "Day 1 movement (cd)")],
        {0: [("Baseline in force", "baseline")],
         1: [("Activities slipped vs previous period", "all activities")],
         2: [("Day 1 variance vs BL1", "vs BL1 (cd)"), ("Day 1 variance vs BL0", "vs BL0 (cd)")],
         3: [("Float erosion", "float (wd)")]},
        "Milestones and Day 1 at the selected update", value_size=20,
        trends={0: "Trend - Milestones later than baseline in force",
                1: "Trend - Milestones slipped vs previous period", 2: "Trend - Day 1 variance vs BL1",
                3: "Trend - Day 1 movement vs previous period"})
    rb.add_page(2, "milestones", "Milestones & slippage", "Title - Milestones", [
        (184, [(1040, ("milestone_kpis", milestone_kpis, None))]),        # two reference labels need 184
        (208, [
            # BL0 is fixed per milestone, so variance vs BL0 moves exactly as the forecast date does while the
            # value axis stays numeric; the forecast date itself is in the tooltip
            (624, ("gate_forecasts", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"),
                [mea("Milestone variance vs BL0", "Forecast vs BL0 (calendar days)")],
                "Day 1 and readiness gates: calendar days later than BL0, by update",
                series=col(act, "activity_name", "Milestone"),
                tooltips=[mea("Milestone forecast finish", "Forecast finish")],
                sort=(col("dim_snapshot", "data_date"), "Ascending"), y_title="Days vs BL0",
                # no zoom slider: Desktop does not show one in a responsive visual this short (208 px)
                series_labels=True, markers=True, y_lines=[(0, "On BL0", TC_SLATE, "none")],
                plot_tint=True, subtitle="One line per gate; the forecast date is in the tooltip"),
                gate_filter)),
            # a count that is non-zero in every update. Drill levels below the owner (asset, then workstream) let
            # the reader split the late milestones as a decomposition tree would: a tree needs about 300 px for
            # one level of five bars, and this row is 208
            (400, ("late_by_owner", rb.chart(
                "clusteredBarChart", col("dim_owner", "owner_name", "Owner"),
                [mea("Milestones later than baseline in force", "Milestones later than baseline")],
                "Late milestones by owner",
                tooltips=[mea("Slip vs previous period", "Worst slip vs previous update (calendar days)")],
                sort=(mea("Milestones later than baseline in force"), "Descending"), labels=True, y_title="",
                category_room=45, drill=[col(act, "asset_name", "Asset"), col(act, "workstream_name", "Workstream")],
                subtitle="Drill down to asset and workstream; worst slip in the tooltip"),
             None)),
        ]),
        (176, [
            (688, ("milestone_table", rb.table(
                [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Milestone"),
                 col(act, "owner_code", "Owner"), col(fas, "bl0_finish", "BL0"), col(fas, "bl1_finish", "BL1"),
                 # the "Compare against" field parameter: the variance the button slicer picks
                 col(fas, "finish", "Forecast"), col(COMPARE_TABLE, COMPARE_TABLE, "Variance (cd)"),
                 spark("Milestone variance vs BL1 by update", "vs BL1 by update")],
                "Milestones: baseline and forecast finish", sort=(col(fas, "finish"), "Ascending"),
                widths=[96, 190, 46, 82, 82, 82, 60, 84],
                subtitle="Variance in calendar days against the comparison picked at the top; the line: vs BL1 at "
                         "every update"),
                [(col(act, "is_milestone"), ["true"])])),
            (336, ("finish_profile", finish_profile("BL1", "Against the baseline in force"), None)),
        ]),
    ], slicers=("compare", "data_date"), no_filter_from_date=("gate_forecasts",), legacy=False, overlays={
        # the BL0 copy of the chart in the same box, and a BL1 | BL0 toggle in its title row: the bookmarks
        # Compare - BL1 / Compare - BL0 show one copy, the matching "on" button, and set Compare against
        "finish_profile": [
            ("finish_profile_bl0", finish_profile("BL0", "Against the original baseline"), None, True, None),
            ("bl1_on", rb.bookmark_button("BL1", BM_COMPARE_BL1, "on", "Compare against BL1"),
             TOGGLE_BL1, False, None),
            ("bl1_off", rb.bookmark_button("BL1", BM_COMPARE_BL1, "off", "Compare against BL1"),
             TOGGLE_BL1, True, None),
            ("bl0_on", rb.bookmark_button("BL0", BM_COMPARE_BL0, "on", "Compare against BL0"),
             TOGGLE_BL0, True, None),
            ("bl0_off", rb.bookmark_button("BL0", BM_COMPARE_BL0, "off", "Compare against BL0"),
             TOGGLE_BL0, False, None),
        ]})

    # 3 Critical path & look-ahead -----------------------------------------------------------------------------
    critical_kpis = rb.kpi_strip(
        [mea("Critical count", "Critical"), mea("Near-critical count", "Near-critical"),
         # six tiles: a label beside its trend holds about 14 characters
         mea("Negative float count", "Negative float"), mea("Total float (min)", "Min float (wd)"),
         mea("Look-ahead items", "Look-ahead"), mea("Look-back hit rate", "Look-back")],
        {0: [("Longest path count", "on path")], 1: [("Near-critical threshold (d)", "threshold")],
         2: [("Activities", "activities")], 3: [("Total float (average)", "average")],
         4: [("Look-ahead critical items", "critical")], 5: [("Look-back missed", "missed")]},
        "Criticality at the selected update", value_size=20, ref_style="sentence", trend_area=24,
        trends={0: "Trend - Critical count", 1: "Trend - Near-critical count", 2: "Trend - Negative float count",
                3: "Trend - Total float (min)", 4: "Trend - Look-ahead items", 5: "Trend - Look-back hit rate"})
    tf = col(fas, "total_float_d", "Total float (wd)")

    def look_table(kind: str) -> dict:
        """The 14-day look-ahead or look-back across the full width, so activity and asset names show whole.
        Total float is tinted as on page 1 (below 0, 0 to 10, above 10)."""
        ident = [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col(act, "asset_name", "Asset"), col(act, "owner_code", "Owner")]
        if kind == "ahead":
            return rb.table(
                ident + [col(fas, "start", "Start"), col(fas, "finish", "Finish"), tf],
                "Look-ahead: activities starting or finishing in the next 14 days",
                sort=(col(fas, "start"), "Ascending"), widths=[96, 330, 190, 50, 82, 82, 70],
                value_objects=float_rules(tf), subtitle="Owners confirm these at the weekly controls meeting")
        # look-back rows are the ones with an event: a start or a finish that fell due in the last 14 days
        return rb.table(
            ident + [col(fas, "lookback_event", "Event"), col(fas, "prev_finish", "Previous forecast"),
                     col(fas, "lookback_achieved_label", "Achieved")],
            "Look-back: items due in the last 14 days", sort=(col(act, "activity_id"), "Ascending"),
            widths=[96, 330, 190, 50, 60, 92, 70],
            subtitle="Achieved: the event happened as the previous update forecast")
    rb.add_page(3, "critical", "Critical path & look-ahead", "Title - Critical path", [
        (176, [(1040, ("criticality_kpis", critical_kpis, None))]),
        (216, [
            (624, ("longest_path", rb.table(
                [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col(act, "owner_code", "Owner"), col(fas, "start", "Start"), col(fas, "finish", "Finish"), tf],
                "Longest path to Day 1: start, finish and total float", sort=(col(fas, "start"), "Ascending"),
                widths=[96, 250, 48, 82, 82, 66], value_objects=float_rules(tf),
                subtitle="The same activities as bars on the Critical path Gantt page; right-click to drill through"),
                [(col(fas, "is_longest_path"), ["true"])])),
            # the title is short: the Trend | Bridge toggle takes the right of its row
            (400, ("float_erosion", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"),
                [mea("Day 1 total float"), mea("Float erosion")],
                "Day 1 float by update (wd)",
                sort=(col("dim_snapshot", "data_date"), "Ascending"), y_title="Working days", markers=True,
                series_labels=True, y_lines=[(0, "Zero", TC_RED, "none")],
                colours={"_Measures.Day 1 total float": NAVY, "_Measures.Float erosion": TEAL},
                subtitle="Erosion below zero: float lost since the previous update"), None)),
        ]),
        (176, [(1040, ("look_ahead", look_table("ahead"), [(col(fas, "lookahead"), ["true"])]))]),
    ], slicers=("threshold", "data_date"), no_filter_from_date=("float_erosion",), legacy=False, overlays={
        # the float bridge in the same box as the float chart, behind a Trend | Bridge toggle (bookmarks Float -
        # trend / Float - bridge): the first update's float, the change at each later update up to the selected
        # one, and that update's float as the total
        "float_erosion": [
            ("float_bridge", rb.waterfall(
                col(AXIS_TABLE, "update", "Update"), mea("Float bridge by update", "Change (wd)"),
                "Day 1 float bridge (wd)",
                subtitle="Start: the first update's float; then the change at each update"),
             None, True, None),
            ("trend_on", rb.bookmark_button("Trend", BM_FLOAT_TREND, "on", "Show Day 1 float by update"),
             TOGGLE_TREND, False, None),
            ("trend_off", rb.bookmark_button("Trend", BM_FLOAT_TREND, "off", "Show Day 1 float by update"),
             TOGGLE_TREND, True, None),
            ("bridge_on", rb.bookmark_button("Bridge", BM_FLOAT_BRIDGE, "on", "Show how Day 1 float got here"),
             TOGGLE_BRIDGE, True, None),
            ("bridge_off", rb.bookmark_button("Bridge", BM_FLOAT_BRIDGE, "off", "Show how Day 1 float got here"),
             TOGGLE_BRIDGE, False, None),
        ],
        # the look-back in the same box, and a Look-ahead | Look-back toggle in the title row (bookmarks
        # Look - ahead / Look - back)
        "look_ahead": [
            ("look_back", look_table("back"), None, True,
             [(col(fas, "lookback_event"), [text("start"), text("finish")])]),
            ("ahead_on", rb.bookmark_button("Look-ahead", BM_LOOK_AHEAD, "on", "Show the next 14 days"),
             TOGGLE_AHEAD, False, None),
            ("ahead_off", rb.bookmark_button("Look-ahead", BM_LOOK_AHEAD, "off", "Show the next 14 days"),
             TOGGLE_AHEAD, True, None),
            ("back_on", rb.bookmark_button("Look-back", BM_LOOK_BACK, "on", "Show the last 14 days"),
             TOGGLE_BACK, True, None),
            ("back_off", rb.bookmark_button("Look-back", BM_LOOK_BACK, "off", "Show the last 14 days"),
             TOGGLE_BACK, False, None),
        ]})

    # 9 Critical path Gantt (shown after page 3) ----------------------------------------------------------------
    # The longest path and the 14-day look-ahead as bars from start to finish, coloured by criticality. Rows come
    # from dim_activity, so measure filters keep only the activities in question for the selected update; level-of-
    # effort activities are left out because their bars span the whole programme.
    gantt_columns = [agg(act, "activity_name", "Min", "Activity"), agg(act, "owner_code", "Min", "Owner"),
                     agg(fas, "total_float_d", "Min", "TF (d)")]
    no_loe = (col(act, "activity_type"), [text(t) for t in rb.activity_types if t != "TT_LOE"])
    rb.add_page(9, "gantt", "Critical path Gantt", "Title - Critical path", [
        (344, [(1040, ("longest_path_gantt", rb.gantt(
            col(act, "activity_id", "ID"), gantt_columns, "Longest path to Day 1: start and finish of each activity",
            "Red: critical (total float 0 or less); amber: near-critical; right-click an activity to drill through"),
            [no_loe, (mea("Longest path count"), (2, "1L"))]))]),
        (240, [(1040, ("look_ahead_gantt", rb.gantt(
            col(act, "activity_id", "ID"), gantt_columns, "Look-ahead: activities starting or finishing in the next "
            "14 days", "Owners confirm these at the weekly controls meeting"),
            [no_loe, (mea("Look-ahead item (flag)"), (0, "1L"))]))]),
    ], slicers=("threshold", "data_date"), legacy=False)

    # 4 Interfaces & readiness ---------------------------------------------------------------------------------
    gap = mea("Readiness gap", "Gap (days)")
    gap_rules = [{"properties": {"fontColor": rb.rules(gap, [(rb.compare(gap, 1, "0D"), RED),
                                                             (rb.compare(gap, 4, "0D"), GREEN)])},
                  "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": query_ref(gap)}}]
    late = mea("Interfaces late", "Late")
    late_scale = [{"properties": {"backColor": {"solid": {"color": {"expr": {"FillRule": {
        "Input": field_expr(late),
        "FillRule": {"linearGradient2": {
            "min": {"color": {"Literal": {"Value": text(WHITE)}}},
            "max": {"color": {"Literal": {"Value": text("#F1A9A0")}}},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": text("noColor")}}}}}}}}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": query_ref(late)}}]
    interface_kpis = rb.kpi_strip(
        [mea("Interfaces late", "Late interfaces"), mea("Interfaces at risk", "Interfaces at risk"),
         mea("Interface gap (max)", "Worst interface gap (cd)"), mea("Readiness gap", "Worst readiness gap (cd)"),
         mea("Readiness stages late", "Readiness stages late")],
        {}, "Interfaces and readiness at the selected update", value_size=20)
    rb.add_page(4, "interfaces", "Interfaces & readiness", "Title - Interfaces and readiness", [
        (136, [(1040, ("interface_kpis", interface_kpis, None))]),
        (232, [(1040, ("readiness_matrix", rb.matrix(
            [col("fact_readiness", "asset_code", "Asset")], [col("fact_readiness", "stage", "Stage")],
            [agg("fact_readiness", "forecast", "Max", "Forecast"), gap],
            "Readiness chain by asset: forecast and gap to the date that protects Day 1",
            value_objects=gap_rules, column_totals=False,
            subtitle="Gap in calendar days: red when later than the protecting date, green when earlier"), None))]),
        (200, [
            (336, ("late_interfaces", rb.matrix(
                [col("fact_interface", "giver_asset", "Giver")], [col("fact_interface", "receiver_asset", "Receiver")],
                [late], "Late interfaces by giver and receiver asset", value_objects=late_scale,
                subtitle="Darker red: more late interfaces"), None)),
            (688, ("interface_table", rb.table(
                [col("fact_interface", "interface_id", "Interface"), col("fact_interface", "description", "Description"),
                 col("fact_interface", "giver_owner", "Giver"), col("fact_interface", "receiver_owner", "Receiver"),
                 col("fact_interface", "need_by", "Need by"), col("fact_interface", "giver_forecast", "Giver forecast"),
                 col("fact_interface", "gap_days", "Gap (cd)"),
                 col(act, "activity_id", "Giver activity")],
                "Interfaces, largest gap first", sort=(col("fact_interface", "gap_days"), "Descending"),
                widths=[56, 240, 48, 64, 82, 82, 46, 96],
                subtitle="Gap: giver forecast against the need-by date (calendar days; positive = late)"), None)),
        ]),
    ], legacy=False)

    # 5 Risks, decisions & recovery ----------------------------------------------------------------------------
    recovery_kpis = rb.kpi_strip(
        [mea("High risks", "High risks"), mea("Open decisions", "Open decisions"),
         mea("Next decision needed by", "Next decision needed by"), mea("Recommended scenario", "Recommended scenario")],
        {0: [("Risk score (max)", "top score")], 1: [("Overdue decisions", "overdue")],
         2: [("Data date", "data date")],
         3: [("Float gain", "gain (wd)"), ("Recommended scenario Day 1 total float", "float after")]},
        "Risks, decisions and recovery at the selected update", value_size=20)
    rb.add_page(5, "risks", "Risks, decisions & recovery", "Title - Decisions", [
        (184, [(1040, ("recovery_kpis", recovery_kpis, None))]),         # two reference labels need 184
        (208, [
            # columns, not bars: all six scenarios fit without a scroll bar, and negative float points down. The
            # recommended scenario is teal and the rest slate (POWERBI.md section 6, page 5).
            (336, ("scenario_float", rb.chart(
                "columnChart", col("fact_scenario", "scenario_id", "Scenario"),
                [agg("fact_scenario", "day1_tf_d", "Sum", "Day 1 total float (working days)")],
                "Day 1 total float by recovery scenario (working days)",
                series=col("fact_scenario", "recommended_label", "Recommended"),
                sort=(agg("fact_scenario", "day1_tf_d", "Sum"), "Descending"), legend=False, labels=True,
                y_title="Working days", series_colours={"Yes": TEAL, "No": SLATE},
                # the label at the right end, above the line: the bars there are below zero
                y_lines=[(0, "Zero float", TC_RED, "none", ("right", "above"))],
                subtitle="Recommended scenario in teal"), None)),
            (688, ("scenario_table", rb.table(
                [col("fact_scenario", "scenario_id", "Scenario"), col("fact_scenario", "name", "Name"),
                 col("fact_scenario", "day1_forecast", "Day 1 forecast"), col("fact_scenario", "day1_tf_d", "Day 1 TF (wd)"),
                 col("fact_scenario", "float_gain_d", "Float gain (wd)"),
                 col("fact_scenario", "residual_risk", "Residual risk"), col("fact_scenario", "decision", "Decisions"),
                 col("fact_scenario", "recommended_label", "Recommended")],
                "Recovery scenarios: outcome, decisions needed and residual risk",
                # names are sentences of up to 130 characters: wrapped, one scenario fills the box, so they are
                # cut off instead (the full name is in the cell's tooltip)
                sort=(col("fact_scenario", "day1_tf_d"), "Descending"), widths=[62, 220, 84, 60, 60, 66, 76, 90],
                wrap=False,
                subtitle="Day 1 forecast and total float if the scenario's decisions are approved"), None)),
        ]),
        # the decision log across the full width (the headline is about decisions), with the risk register in the
        # same box behind a Decisions | Risks toggle (bookmarks Register - decisions / Register - risks)
        (176, [(1040, ("decision_log", rb.table(
            [col("fact_decision", "decision_id", "ID"), col("fact_decision", "ask", "Ask"),
             col("fact_decision", "owner", "Owner"), col("fact_decision", "needed_by", "Needed by"),
             col("fact_decision", "status", "Status"), col("fact_decision", "overdue_label", "Overdue"),
             col("fact_decision", "outcome", "Outcome")],
            "Decision log", sort=(col("fact_decision", "needed_by"), "Ascending"),
            widths=[44, 420, 180, 82, 58, 62, 200], subtitle="All decisions, earliest needed first"), None))]),
    ], legacy=False, overlays={"decision_log": [
        # probability and impact are already in the score and the rating repeats it, so the title gets the width
        # the risk's values are aggregated (one row per risk and update), so only the risk defines a row and its
        # sparkline reads the other updates; trend is the score's change since the previous update
        ("risk_register", rb.table(
            [col("fact_risk", "risk_id", "Risk"), col("fact_risk", "title", "Title"),
             col("fact_risk", "owner_code", "Owner"), agg("fact_risk", "score", "Max", "Score"),
             spark("Risk score (max) by update", "Score by update"),
             agg("fact_risk", "trend", "Max", "vs previous"),
             agg("fact_risk", "schedule_impact_days", "Max", "Impact (d)"),
             agg("fact_risk", "min_linked_float_d", "Min", "Min float (wd)")],
            "Risk register, highest score first", sort=(agg("fact_risk", "score", "Max"), "Descending"),
            widths=[50, 440, 60, 56, 96, 70, 76, 90], totals=False,
            subtitle="Score by update: every update up to the selected one. Min float: lowest float of the linked "
                     "activities"),
         None, True, None),
        # the third choice: the 5 x 5 risk map of POWERBI.md section 6, impact down (5 at the top) by probability
        # across, each cell tinted by its band and listing its risks. A scatter left about 20 px per impact level
        # in this 176 px box, so the risk labels ran into the next level's points
        ("risk_map", rb.matrix(
            [col(GRID_TABLE, "impact", "Impact")], [col(GRID_TABLE, "probability", "Probability")],
            [mea("Risks in cell", "Risks")],
            "Risk map at the selected update: impact (down) by probability (across)",
            value_objects=[{"properties": {"backColor": {"solid": {"color": {"expr": field_expr(mea("Risk cell colour"))}}}},
                            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                         "metadata": query_ref(mea("Risks in cell"))}}],
            column_totals=False, row_totals=False, sort=(col(GRID_TABLE, "impact"), "Descending"),
            subtitle="Cells by probability x impact: red 15 or more (high), amber 8 to 14, green below 8",
            # equal cells (the five probabilities share the width), the risks centred, white rules between the
            # tinted cells, and rows tight enough for all five impact levels in the box
            extra_objects={
                "columnWidth": [{"properties": {"value": num(186)}, "selector": {"metadata": query_ref(mea("Risks in cell"))}}],
                "columnFormatting": [{"properties": {"alignment": lit(text("Center")), "styleHeader": flag(True),
                                                     "styleValues": flag(True)},
                                      "selector": {"metadata": query_ref(mea("Risks in cell"))}}],
                "grid": [{"properties": {"gridVertical": flag(True), "gridVerticalColor": colour(WHITE),
                                         "gridVerticalWeight": num(2), "gridHorizontal": flag(True),
                                         "gridHorizontalColor": colour(WHITE), "gridHorizontalWeight": num(2),
                                         "rowPadding": num(0)}}],
                "columnHeaders": [{"properties": {"autoSizeColumnWidth": flag(False), "fontSize": num(9),
                                                  "wordWrap": flag(True), "alignment": lit(text("Center"))}}]}),
         None, True, None),
        ("decisions_on", rb.bookmark_button("Decisions", BM_DECISIONS, "on", "Show the decision log"),
         TOGGLE_FIRST_OF_3, False, None),
        ("decisions_off", rb.bookmark_button("Decisions", BM_DECISIONS, "off", "Show the decision log"),
         TOGGLE_FIRST_OF_3, True, None),
        ("risks_on", rb.bookmark_button("Risks", BM_RISKS, "on", "Show the risk register"),
         TOGGLE_AHEAD, True, None),
        ("risks_off", rb.bookmark_button("Risks", BM_RISKS, "off", "Show the risk register"),
         TOGGLE_AHEAD, False, None),
        ("map_on", rb.bookmark_button("Risk map", BM_RISK_MAP, "on", "Show the risks on probability and impact"),
         TOGGLE_BACK, True, None),
        ("map_off", rb.bookmark_button("Risk map", BM_RISK_MAP, "off", "Show the risks on probability and impact"),
         TOGGLE_BACK, False, None),
    ]})

    # 6 Schedule quality (DCMA) --------------------------------------------------------------------------------
    quality_kpis = rb.kpi_strip(
        [mea("DQ score", "DQ score (of 100)"), mea("DCMA pass count", "DCMA checks passed"), mea("CPLI", "CPLI"),
         mea("BEI", "BEI")],
        {0: [("DQ rating", "rating"), ("DQ score movement", "vs previous")],
         1: [("DCMA applicable checks", "applicable"), ("Update discipline pass count", "update checks")],
         2: [("Day 1 total float", "Day 1 float (wd)"), ("Longest path count", "on path")],
         3: [("BEI tasks completed", "completed"), ("BEI tasks due", "due")]},
        "Schedule quality at the selected update", value_size=20,
        trends={0: "Trend - DQ score", 1: "Trend - DCMA pass count", 2: "Trend - CPLI", 3: "Trend - BEI"})
    rb.add_page(6, "quality", "Schedule quality (DCMA)", "Title - Schedule quality", [
        (184, [(1040, ("quality_kpis", quality_kpis, None))]),          # two reference labels need 184
        (208, [
            (624, ("dcma_table", rb.table(
                [col("fact_dcma_check", "check_id", "Check"), col("fact_dcma_check", "check_name", "Check name"),
                 col("fact_dcma_check", "group", "Group"), col("fact_dcma_check", "value", "Value"),
                 col("fact_dcma_check", "threshold", "Threshold"), col("fact_dcma_check", "passed_label", "Pass"),
                 col("fact_dcma_check", "score", "Score"), col("fact_dcma_check", "weight", "Weight")],
                "DCMA and update-discipline checks", sort=(col("fact_dcma_check", "check_id"), "Ascending"),
                widths=[52, 190, 90, 60, 76, 50, 52, 60],
                subtitle="Value against threshold; the score is the check's share of the DQ score"), None)),
            (400, ("dq_trend", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"), [mea("DQ score")],
                "DQ score by update", sort=(col("dim_snapshot", "data_date"), "Ascending"), labels=True,
                markers=True, legend=False, colours={"_Measures.DQ score": NAVY},
                # labels at the right end, clear of the early updates' points
                y_lines=[(85, "Good (85)", TC_GREEN, "none", ("right", "above")),
                         (70, "Fair (70)", TC_AMBER, "none", ("right", "under"))],
                subtitle="Good at 85 or more, fair from 70 to 85"), None)),
        ]),
        (176, [
            # the counts are aggregated (one row per owner and update), so only the owner defines a row and the
            # sparkline reads the other updates
            (448, ("owner_scorecard", rb.table(
                [col("dim_owner", "owner_name", "Owner"), mea("Owner DQ", "Owner DQ"),
                 spark("Owner DQ by update", "DQ by update"),
                 agg("fact_owner_scorecard", "incomplete", "Sum", "Incomplete"),
                 agg("fact_owner_scorecard", "flagged", "Sum", "Flagged"),
                 agg("fact_owner_scorecard", "logic_issues", "Sum", "Logic issues")],
                "Owner scorecard, weakest first", sort=(mea("Owner DQ"), "Ascending"),
                widths=[150, 60, 84, 72, 58, 60]), None)),
            (576, ("offenders", rb.table(
                [col("fact_dcma_offender", "check_id", "Check"), col("fact_dcma_offender", "item", "Item"),
                 col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col("fact_dcma_offender", "owner_code", "Owner")],
                "Offenders for the selected check", sort=(col("fact_dcma_offender", "check_id"), "Ascending"),
                widths=[48, 190, 96, 240, 82], subtitle="Pick a check in the Offenders slicer at the top"), None)),
        ]),
    ], slicers=("threshold", "data_date"), no_filter_from_date=("dq_trend",), legacy=False,
        # no relationship links the checks to their offenders, so the check is picked in the title row, as a
        # dropdown that filters only the offenders table
        extra_slicer=("check", rb.slicer(col("fact_dcma_offender", "check_id"), "Offenders: check", "Dropdown",
                                         single=True, strict=False)))

    # 7 Reconciliation & lineage -------------------------------------------------------------------------------
    lineage_style = {"fontFamily": "Segoe UI", "fontSize": "11px", "color": FOREGROUND}
    lineage = rb.textbox([
        [("Data lineage", {"fontFamily": "Segoe UI Semibold", "fontSize": "13px", "color": NAVY, "fontWeight": "bold"})],
        [("1. P6 XER exports: DOP_BL0.xer, DOP_BL1.xer and DOP_UPD_<data date>.xer (data/xer)", lineage_style)],
        [("2. Pipeline: parse every XER table, re-check the CPM, run the DCMA and update-discipline checks",
          lineage_style)],
        [("3. Star schema: output/csv (22 tables) and the dashboard JSON", lineage_style)],
        [("4. Reconciliation gate: source XER = model = dashboard for every control; CSVs are published only "
          "when all pass", lineage_style)],
        [("5. This report: the CSV star schema, loaded through the CsvFolder parameter", lineage_style)],
    ])
    lineage["visualContainerObjects"] = vco(background={"show": flag(True), "color": colour(WHITE)},
                                            border={"show": flag(True), "color": colour("#E2E8F0"),
                                                    "radius": num(8)})
    recon_kpis = rb.kpi_strip(
        [mea("Reconciliation status", "Reconciliation"), mea("Controls passed", "Controls passed"),
         mea("Source file", "Source file (P6 XER)"), mea("Baseline in force", "Baseline in force")],
        {}, "Reconciliation at the selected update", colour_by={0: "Reconciliation colour"}, value_size=14)
    rb.add_page(7, "recon", "Reconciliation & lineage", "Title - Reconciliation", [
        (152, [(1040, ("recon_kpis", recon_kpis, None))]),
        (248, [(1040, ("controls_table", rb.table(
            [col("fact_reconciliation", "control_id", "Control"), col("fact_reconciliation", "control", "Description"),
             col("fact_reconciliation", "source_value", "Source (XER)"),
             col("fact_reconciliation", "model_value", "Model (CSV)"),
             col("fact_reconciliation", "dashboard_value", "Dashboard (JSON)"),
             col("fact_reconciliation", "delta", "Delta"), col("fact_reconciliation", "passed_label", "Pass")],
            "Reconciliation controls: source, model and dashboard values", sort=(col("fact_reconciliation", "control_id"), "Ascending"),
            widths=[120, 330, 170, 170, 170, 60, 60],
            subtitle="Every control must agree across the three before the update is published"), None))]),
        (168, [
            (512, ("lineage_text", lineage, None)),
            (512, ("source_files", rb.table(
                [col("dim_snapshot", "label", "Update"), col("dim_snapshot", "data_date", "Data date"),
                 col("dim_snapshot", "source_file", "Source file"), col("dim_snapshot", "sha256", "SHA-256"),
                 col("dim_snapshot", "baseline_in_force", "Baseline")],
                "Source files and hashes for every update", sort=(col("dim_snapshot", "data_date"), "Ascending"),
                widths=[50, 82, 160, 150, 60]), None)),
        ]),
    ], no_filter_from_date=("source_files",), legacy=False)

    # 8 Activity details (drill-through, hidden) ---------------------------------------------------------------
    # dim_activity columns only in the attribute strip: the drill-through filter on dim_activity does not reach
    # dim_owner or dim_calendar (filters run from the one side to the many side)
    attributes = rb.kpi_strip(
        [agg(act, "activity_id", "Min", "Activity ID"), agg(act, "asset_name", "Min", "Asset"),
         agg(act, "workstream_name", "Min", "Workstream"), agg(act, "owner_code", "Min", "Owner")],
        {}, "Activity attributes", value_size=12)
    # the float column on the latest update, so a level-of-effort activity shows its own float (the float
    # measures leave LOE out, as the summary does). Every tile carries a reference, so none shows an empty row
    latest = rb.kpi_strip(
        [mea("Forecast finish", "Forecast finish"), agg(fas, "total_float_d", "Min", "Total float (wd)"),
         mea("Slip vs previous period", "Movement (cd)")],
        {0: [("Finish variance vs BL1", "vs BL1")],             # vs BL0 is in the history table below
         1: [("Near-critical threshold (d)", "threshold")],
         2: [("Criticality band", "band")]}, "Latest update", value_size=12, ref_style="sentence")
    rb.add_page(8, "activity", "Activity details", None, [
        (184, [(624, ("attributes", attributes, None)),                # two reference labels need 184
               (400, ("latest", latest, [(col("dim_snapshot", "is_latest"), ["true"])]))]),
        (208, [(1040, ("history", rb.table(
            [col("dim_snapshot", "label", "Update"), col("dim_snapshot", "data_date", "Data date"),
             col(fas, "status", "Status"), col(fas, "start", "Start"), col(fas, "finish", "Finish"),
             col(fas, "total_float_d", "TF (wd)"), col(fas, "var_finish_bl0_d", "vs BL0 (cd)"),
             col(fas, "var_finish_bl1_d", "vs BL1 (cd)"), col(fas, "slip_vs_prev_d", "Movement (cd)"),
             col(fas, "constraint_type", "Constraint"), col(fas, "dq_flags", "DQ flags")],
            "History across all updates", sort=(col("dim_snapshot", "data_date"), "Ascending"),
            widths=[56, 88, 90, 88, 88, 60, 70, 70, 80, 110, 150]), None))]),
        (176, [
            # the column itself, so a level-of-effort activity shows its float too (see the latest-update card)
            (512, ("float_history", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"),
                [agg(fas, "total_float_d", "Min", "Total float (working days)")],
                "Total float by update: when did this activity lose its float?",
                sort=(col("dim_snapshot", "data_date"), "Ascending"), labels=True, markers=True,
                y_title="Working days", y_lines=[(0, "Zero float", TC_RED, "before", ("right", "above"))],
                legend=False), None)),
            (512, ("drivers", rb.table(
                [col("fact_relationship", "pred_id", "Predecessor"), col("fact_relationship", "rel_type", "Type"),
                 col("fact_relationship", "lag_d", "Lag (wd)"),
                 col("fact_relationship", "is_driving_label", "Driving"),
                 col("fact_relationship", "slack_d", "Slack (wd)")],
                "Predecessors in the latest update, driving first",
                sort=(col("fact_relationship", "is_driving_label"), "Descending"), widths=[150, 60, 70, 70, 70]),
                [(col("dim_snapshot", "is_latest"), ["true"])])),
        ]),
    ], slicers=(), drillthrough=col(act, "activity_id"), headline=agg(act, "activity_name", "Min", "Activity"),
        legacy=False)

    # 10 Tooltip for the float matrix (hidden): the activities behind a hovered asset x workstream cell -------------
    rb.add_tooltip_page(10, "float_tip", "Float tooltip", "activities", rb.table(
        [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
         agg(fas, "total_float_d", "Min", "TF (d)")],
        "Lowest-float activities in this cell", sort=(agg(fas, "total_float_d", "Min"), "Ascending"),
        widths=[92, 140, 54], totals=False))


# ----------------------------------------------------------------------------------------------------------------
# Project files
# ----------------------------------------------------------------------------------------------------------------

def build_bookmarks(rb: ReportBuilder) -> dict[str, bytes]:
    """The report bookmarks of POWERBI.md section 7, as definition/bookmarks files, and their index.

    Compare - BL1 / Compare - BL0 (page 2, Data on, Selected visuals only): set the Compare against slicer, show the
        matching copy of the finish-profile chart and the matching "on" button of the BL1 | BL0 toggle. Only those
        visuals are captured, so the data-date selection is left as it is.
    Look - ahead / Look - back (page 3) and Register - decisions / Register - risks (page 5), Data off, Selected
        visuals only: show one of the two full-width tables and the matching "on" button of the toggle over it.
    Decisions spotlight (Data off, Current page on): the executive summary with the decisions table in spotlight.
    Reset (Data on, Selected visuals only): every slicer back to its default (latest update, threshold 10, vs BL1),
        the spotlight cleared and both toggles on their first choice, on whichever page the reader is."""
    state = rb.page_state
    exec_page, ms_page, look_page, risk_page = "p01_exec", "p02_milestones", "p03_critical", "p05_risks"

    def named(page: str, key: str) -> str:
        return next(n for n in state[page]["visuals"] if re.fullmatch(rf"{page[:3]}_[hv]\d+_{key}", n))

    def slicer(filt: dict, label: str | None = None, visual_type: str = "slicer") -> dict:
        state = {"visualType": visual_type, "objects": {"merge": {"general": [{"properties": {"filter": filt}}]}}}
        if label:                          # the selected tile's name, as Desktop caches it for the filter pane
            where = filt["filter"]["Where"][0]["Condition"]["In"]
            column = where["Expressions"][0]["Column"]
            state["cachedFilterDisplayItems"] = [{"id": {"scopeId": {"Comparison": {
                "ComparisonKind": 0,
                "Left": {"Column": {"Expression": {"SourceRef": {"Entity": filt["filter"]["From"][0]["Entity"]}},
                                    "Property": column["Property"]}},
                "Right": where["Values"][0][0]}}}, "displayName": label}]
        return {"singleVisual": state}

    def shown(mode: str | None = None) -> dict:
        return {"singleVisual": {"display": {"mode": mode}} if mode else {}}

    compare = f"{ms_page[:3]}_h3_compare"

    def compare_state(label: str) -> dict:
        filt = copy.deepcopy(state[ms_page]["slicers"][compare])
        filt["filter"]["Where"][0]["Condition"]["In"]["Values"] = [[{"Literal": {"Value": text(compare_key(label))}}]]
        return slicer(filt, label, state[ms_page]["slicer_types"][compare])

    # bookmark toggles: page, then per choice (visual shown for it, its button prefix); the first is the default
    toggles = {"compare": (ms_page, {"BL1": ("finish_profile", "bl1"), "BL0": ("finish_profile_bl0", "bl0")}),
               "look": (look_page, {"ahead": ("look_ahead", "ahead"), "back": ("look_back", "back")}),
               "float": (look_page, {"trend": ("float_erosion", "trend"), "bridge": ("float_bridge", "bridge")}),
               "register": (risk_page, {"decisions": ("decision_log", "decisions"),
                                        "risks": ("risk_register", "risks"), "map": ("risk_map", "map")})}

    def toggle(kind: str, chosen: str | None = None) -> dict[str, dict]:
        """Display state of a toggle with `chosen` picked: its visual and "on" button shown, the other choices'
        visuals and "on" buttons hidden, and the "off" buttons the other way round."""
        page, choices = toggles[kind]
        chosen = chosen or next(iter(choices))
        out = {}
        for choice, (visuals, button) in choices.items():
            mine = choice == chosen
            for visual in (visuals if isinstance(visuals, tuple) else (visuals,)):
                out[named(page, visual)] = shown(None if mine else "hidden")
            out[named(page, f"{button}_on")] = shown(None if mine else "hidden")
            out[named(page, f"{button}_off")] = shown("hidden" if mine else None)
        return out

    def keep_filters(page: str, visuals: dict[str, dict]) -> dict[str, dict]:
        """A data bookmark restores the whole data state of each visual it names, so a visual's own filters
        (Open decisions, the 14-day look-ahead) and its sort go into it too; without them Desktop drops the
        filters and sorts the table by its first column (seen in Desktop)."""
        out = {}
        for n, st in visuals.items():
            st = copy.deepcopy(st)
            own = state[page]["filters"].get(n)
            if own:
                st = {"filters": {"byExpr": [{"name": f["name"], "type": f["type"], "filter": f["filter"],
                                              "expression": f["field"], "howCreated": 1} for f in own]}, **st}
            sort = state[page]["sorts"].get(n)
            if sort and "visualType" not in st["singleVisual"]:     # slicers keep their own order
                st["singleVisual"]["orderBy"] = [
                    {"Direction": 1 if s["direction"] == "Ascending" else 2, "Expression": s["field"]} for s in sort]
            out[n] = st
        return out

    def bookmark(name: str, display: str, options: dict, active: str, sections: dict) -> bytes:
        if options.get("suppressData") is False:
            sections = {page: keep_filters(page, visuals) for page, visuals in sections.items()}
        return dumps({"$schema": SCHEMAS["bookmark"], "displayName": display, "name": name, "options": options,
                      "explorationState": {"version": "1.3", "activeSection": active, "sections": {
                          page: {"visualContainers": visuals} for page, visuals in sections.items()}}})

    files = {}
    for name, baseline in ((BM_COMPARE_BL1, "BL1"), (BM_COMPARE_BL0, "BL0")):
        visuals = {compare: compare_state(f"vs {baseline}"), **toggle("compare", baseline)}
        files[name] = bookmark(name, f"Compare - {baseline}", {
            "targetVisualNames": list(visuals), "suppressData": False, "suppressDisplay": False,
            "suppressActiveSection": False, "applyOnlyToTargetVisuals": True}, ms_page, {ms_page: visuals})
    for name, kind, choice, display in ((BM_LOOK_AHEAD, "look", "ahead", "Look - ahead"),
                                        (BM_LOOK_BACK, "look", "back", "Look - back"),
                                        (BM_FLOAT_TREND, "float", "trend", "Float - trend"),
                                        (BM_FLOAT_BRIDGE, "float", "bridge", "Float - bridge"),
                                        (BM_DECISIONS, "register", "decisions", "Register - decisions"),
                                        (BM_RISKS, "register", "risks", "Register - risks"),
                                        (BM_RISK_MAP, "register", "map", "Register - risk map")):
        page = toggles[kind][0]
        visuals = toggle(kind, choice)            # display only: the slicers keep the reader's choices
        files[name] = bookmark(name, display, {
            "targetVisualNames": list(visuals), "suppressData": True, "suppressDisplay": False,
            "suppressActiveSection": False, "applyOnlyToTargetVisuals": True}, page, {page: visuals})
    decisions = named(exec_page, "open_decisions")
    files[BM_SPOTLIGHT] = bookmark(BM_SPOTLIGHT, "Decisions spotlight", {
        "suppressData": True, "suppressDisplay": False, "suppressActiveSection": False,
        "applyOnlyToTargetVisuals": False}, exec_page,
        {exec_page: {n: shown("spotlight" if n == decisions else None) for n in state[exec_page]["visuals"]
                     if n not in state[exec_page]["hidden"]}})
    reset: dict[str, dict] = {}
    for page, st in state.items():
        visuals = {n: compare_state("vs BL1") if n == compare else slicer(f) for n, f in st["slicers"].items()}
        for n in st["cleared"]:               # a slicer that opens with nothing selected: its selection removed
            visuals[n] = {"singleVisual": {"visualType": "slicer", "objects": {
                "remove": [{"object": "general", "property": "filter"}]}}}
        if page == exec_page:
            visuals[decisions] = shown()
        for kind, (toggle_page, _) in toggles.items():
            if page == toggle_page:
                visuals.update(toggle(kind))
        if visuals:
            reset[page] = visuals
    files[BM_RESET] = bookmark(BM_RESET, "Reset", {
        "targetVisualNames": [n for visuals in reset.values() for n in visuals], "suppressData": False,
        "suppressDisplay": False, "suppressActiveSection": True, "applyOnlyToTargetVisuals": True},
        exec_page, reset)

    out = {f"definition/bookmarks/{name}.bookmark.json": data for name, data in files.items()}
    out["definition/bookmarks/bookmarks.json"] = dumps({"$schema": SCHEMAS["bookmarks"], "items": [
        {"name": "bmg_compare", "displayName": "Compare", "children": [BM_COMPARE_BL1, BM_COMPARE_BL0]},
        {"name": "bmg_look", "displayName": "Look window", "children": [BM_LOOK_AHEAD, BM_LOOK_BACK]},
        {"name": "bmg_float", "displayName": "Float view", "children": [BM_FLOAT_TREND, BM_FLOAT_BRIDGE]},
        {"name": "bmg_register", "displayName": "Register", "children": [BM_DECISIONS, BM_RISKS, BM_RISK_MAP]},
        {"name": BM_SPOTLIGHT}, {"name": BM_RESET}]})
    return out


def background_svg() -> bytes:
    """Page background: the light canvas and the navy navigation rail on the left, with a teal rule across its top
    and hairlines between the programme name, the page list, the views buttons and the source line. Generated from
    the grid constants,
    so the rail lines up with the visuals placed on it."""
    rule = "#2E4C73"
    lines = "".join(f'  <rect x="{RAIL_X}" y="{y}" width="{RAIL_INNER_W}" height="1" fill="{rule}"/>\n'
                    for y in (NAV_Y - 12, VIEWS_Y - 12, FOOTER_Y - 12))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W}" height="{PAGE_H}" '
            f'viewBox="0 0 {PAGE_W} {PAGE_H}">\n'
            f'  <rect width="{PAGE_W}" height="{PAGE_H}" fill="{CANVAS}"/>\n'
            f'  <rect width="{RAIL_W}" height="{PAGE_H}" fill="{NAVY}"/>\n'
            f'  <rect width="{RAIL_W}" height="4" fill="{TEAL}"/>\n'
            f'{lines}'
            '</svg>\n').encode("utf-8")


def _platform(kind: str) -> dict:
    return {"$schema": SCHEMAS["platform"], "metadata": {"type": kind, "displayName": PROJECT},
            "config": {"version": "2.0", "logicalId": guid("platform", PROJECT, kind)}}


def build_files(root: pathlib.Path = ROOT, csv_folder: str = DEFAULT_CSV_FOLDER) -> tuple[dict[str, bytes], dict]:
    """All project files as {path relative to the powerbi folder: bytes}, plus a summary."""
    tables = read_tables(root / "output" / "csv")
    dax = (root / "powerbi" / "measures.dax").read_text(encoding="utf-8")
    measures, functions = parse_measures(dax), parse_functions(dax)
    theme = (root / "powerbi" / "dop_theme.json").read_bytes()
    json.loads(theme)                                            # must parse

    model = build_model(tables, measures, csv_folder, functions)
    by_name = {t.name: t for t in tables}
    kinds = {(t.name, c.name): c.kind for t in tables for c in t.columns}
    snapshots = by_name["dim_snapshot"].rows
    latest_rows = [r for r in snapshots if r["is_latest"] == "True"] or snapshots
    latest = max(r["data_date"][:10] for r in latest_rows)
    in_trend = {r["activity_id"] for r in by_name["fact_milestone_trend"].rows}
    gate_ids = sorted(r["activity_id"] for r in by_name["dim_activity"].rows
                      if r["asset_code"] == "PRG" and r["readiness_gate"] and r["activity_id"] in in_trend)

    rb = ReportBuilder(kinds, latest, gate_ids)
    rb.activity_types = sorted({r["activity_type"] for r in by_name["dim_activity"].rows})
    DATE_FIELDS.clear()
    DATE_FIELDS.update(f"{t}.{c}" for (t, c), kind in kinds.items() if kind == "date")
    CODE_CHARS.clear()
    LONG_TEXT.clear()
    for t in tables:
        for c in t.columns:
            values = [r[c.name] for r in t.rows if r.get(c.name)] if c.kind == "text" else []
            if not values:
                continue
            longest = max(len(v) for v in values)
            if not any(" " in v for v in values) and longest <= CODE_MAX:
                CODE_CHARS[f"{t.name}.{c.name}"] = longest
            elif any(" " in v for v in values) and longest > LONG_MIN:
                LONG_TEXT.add(f"{t.name}.{c.name}")
    build_pages(rb)
    rb.files.update(build_bookmarks(rb))

    sm, rp = f"{PROJECT}.SemanticModel", f"{PROJECT}.Report"
    files: dict[str, bytes] = {
        f"{PROJECT}.pbip": dumps({"$schema": SCHEMAS["pbip"], "version": "1.0",
                                  "artifacts": [{"report": {"path": rp}}],
                                  "settings": {"enableAutoRecovery": True}}),
        f"{sm}/.platform": dumps(_platform("SemanticModel")),
        f"{sm}/definition.pbism": dumps({"$schema": SCHEMAS["pbism"], "version": "4.2", "settings": {}}),
        **{f"{sm}/{path}": text.encode("utf-8") for path, text in tmdl.write_model(model, PROJECT).items()},
        f"{rp}/.platform": dumps(_platform("Report")),
        f"{rp}/definition.pbir": dumps({"$schema": SCHEMAS["pbir"], "version": "4.0",
                                        "datasetReference": {"byPath": {"path": f"../{sm}"}}}),
        f"{rp}/StaticResources/RegisteredResources/{THEME_FILE}": theme,
        f"{rp}/StaticResources/RegisteredResources/{BACKGROUND_FILE}": background_svg(),
        f"{rp}/definition/version.json": dumps({"$schema": SCHEMAS["version"], "version": "2.0.0"}),
        f"{rp}/definition/report.json": dumps({
            "$schema": SCHEMAS["report"],
            "themeCollection": {
                "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": THEME_VERSION_AT_IMPORT,
                              "type": "SharedResources"},
                "customTheme": {"name": THEME_FILE, "reportVersionAtImport": THEME_VERSION_AT_IMPORT,
                                "type": "RegisteredResources"},
            },
            # the filter pane starts collapsed: the page has the room, and readers can still open it
            "objects": {"section": [{"properties": {"verticalAlignment": lit(text("Top"))}}],
                        "outspacePane": [{"properties": {"expanded": flag(False)}}]},
            "resourcePackages": [
                {"name": "RegisteredResources", "type": "RegisteredResources",
                 "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"},
                           {"name": BACKGROUND_FILE, "path": BACKGROUND_FILE, "type": "Image"}]},
                {"name": "SharedResources", "type": "SharedResources",
                 "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            ],
            "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                         "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                         "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
        }),
        f"{rp}/definition/pages/pages.json": dumps({"$schema": SCHEMAS["pages"], "pageOrder": rb.pages,
                                                    "activePageName": rb.pages[0]}),
    }
    for path, data in rb.files.items():
        files[f"{rp}/{path}"] = data
    files = dict(sorted(files.items()))
    visuals = sum(1 for p in files if p.endswith("/visual.json"))
    summary = {"tables": len(model["model"]["tables"]), "csv_tables": len(tables), "measures": len(measures),
               "functions": len(functions), "relationships": len(RELATIONSHIPS), "pages": len(rb.pages),
               "visuals": visuals, "files": len(files)}
    return files, summary


def write_project(files: dict[str, bytes], out_dir: pathlib.Path) -> None:
    """Write the files and remove what the current design no longer has: page, visual, phone-layout or bookmark
    files in the report definition, table files in the model definition, and a `model.bim` left from the TMSL
    format (a project cannot hold both a TMDL definition folder and model.bim)."""
    for rel, data in files.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    model_bim = out_dir / f"{PROJECT}.SemanticModel" / "model.bim"
    if model_bim.exists():
        model_bim.unlink()
    # the definitions are generated as a whole: a file the current design does not have (an older design, or a
    # phone layout Desktop wrote for a visual) is removed
    for definition in (out_dir / f"{PROJECT}.Report" / "definition", out_dir / f"{PROJECT}.SemanticModel" / "definition"):
        for path in sorted(definition.rglob("*"), reverse=True):
            rel = path.relative_to(out_dir).as_posix()
            if path.is_file() and rel not in files:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                shutil.rmtree(path)


def generate_pbip(root: pathlib.Path = ROOT, out_dir: pathlib.Path | None = None,
                  csv_folder: str = DEFAULT_CSV_FOLDER) -> dict:
    files, summary = build_files(root, csv_folder)
    out = out_dir or (root / "powerbi")
    write_project(files, out)
    summary["out_dir"] = out
    return summary
