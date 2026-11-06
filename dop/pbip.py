"""Power BI project (PBIP) generator: `python -m dop pbip`.

Writes `powerbi/DOP.pbip`, `powerbi/DOP.SemanticModel` (TMSL `model.bim`) and `powerbi/DOP.Report` (PBIR) from:

- the star-schema CSVs in `output/csv` (headers, plus every row to choose and verify each column type);
- `powerbi/measures.dax` (every MEASURE, with its expression kept verbatim);
- `powerbi/dop_theme.json` (registered as the report's custom theme);
- the relationships and page design of POWERBI.md, encoded below as data. `scripts/check_pbip.py` cross-checks
  the relationships and column types against POWERBI.md.

The output is deterministic: ids are uuid5 values of stable names, keys keep a fixed order, and files are UTF-8
without a BOM, with LF line endings and a 2-space indent. Running the command twice gives byte-identical files.
The command is not part of `run --all`, so a project saved from Power BI Desktop is never overwritten by a
pipeline run.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import shutil
import uuid
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = "DOP"
DEFAULT_CSV_FOLDER = r"V:\schedule-intelligence\output\csv"
PROGRAMME = "Destination Opening Programme"
THEME_FILE = "dop_theme.json"
BASE_THEME = "CY26SU10"                       # classic base theme shipped with the October 2026 Desktop
THEME_VERSION_AT_IMPORT = {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"}
MEASURE_TABLE = "_Measures"
THRESHOLD_TABLE = "Near-critical threshold"   # the name measures.dax uses (POWERBI.md section 4)
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
}

# Palette shared with the dashboard, the PowerPoint packs and dop_theme.json
NAVY, TEAL, SLATE = "#1F3A5F", "#2B7A78", "#64748B"
RED, AMBER, GREEN, WHITE, MUTED = "#C0392B", "#D68910", "#1E8449", "#FFFFFF", "#4A5568"

# Canvas and grid (pixels): header band (header strip and title row, 8 px apart), then the content area with
# 16 px margins and gutters
PAGE_W, PAGE_H, GUTTER = 1280, 720, 16
HEADER_Y, HEADER_H = 8, 56
TITLE_Y, TITLE_H = 72, 56
CONTENT_X, CONTENT_Y, CONTENT_W, CONTENT_H = 16, 144, 1248, 560
SLOT_W = 200                                  # header slicers and the data-date card
MIN_W, MIN_H = 180, 90                        # smallest content visual


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
_ONE_DECIMAL = {"Total float (min)", "Total float (average)", "DQ score", "DQ score movement",
                "Progress variance (pts)"}
_PERCENT = {"Planned % complete", "Weighted % complete (actual)", "Look-back hit rate", "Owner DQ"}
_RATIO = {"BEI", "CPLI"}
_DAY_DELTA = {"Day 1 total float", "Float erosion", "Float gain", "Recommended scenario Day 1 total float",
              "Scenario Day 1 impact", "Interface gap (max)", "Readiness gap"}
_TEXT_MEASURES = {"Baseline in force", "Source file", "Day 1 RAG colour", "DQ rating", "Recommended scenario",
                  "Reconciliation status", "Reconciliation colour", "Provenance line"}
_WHOLE = {"Selected snapshot id", "Previous snapshot id", "Look window (days)", "Near-critical threshold (d)",
          "Criticality band", "Look-ahead item (flag)", "Look-back item (flag)", "Risk score (max)"}
_COUNT_WORDS = re.compile(r"^(Activities|Milestones|Critical count|Near-critical count|Negative float count|"
                          r"Longest path count|Look-ahead|Look-back items|Look-back achieved|Look-back missed|"
                          r"DCMA|Update discipline|BEI tasks|Interfaces|Readiness stages|High risks|"
                          r"Open decisions|Overdue decisions|Controls|Finishes|Milestone finishes)")


def measure_format(name: str) -> str | None:
    """Format string for a measure (POWERBI.md section 5); None for text measures."""
    if name in _TEXT_MEASURES or name.startswith("Title - "):
        return None
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
    return {"solid": {"color": lit(text(hex_code))}}


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
_SECTION = re.compile(r"^\s*//\s*(\d+)\.\s+(.+?)\s*$")


def _is_rule(comment: str) -> bool:
    return len(comment) >= 3 and set(comment) <= set("-=")


def parse_measures(dax: str) -> list[dict]:
    """Every MEASURE in the DEFINE block: name, expression lines (dedented, otherwise verbatim), display folder
    (the numbered section heading) and description (the // comment directly above the MEASURE)."""
    lines = dax.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "DEFINE") + 1
    except StopIteration:
        raise ValueError("measures.dax: no DEFINE block") from None
    measures, folder, comment, state, i = [], None, [], "normal", start
    while i < len(lines):
        line, stripped = lines[i], lines[i].strip()
        if line.startswith("EVALUATE"):
            break
        match = _MEASURE_LINE.match(line)
        if match:
            indent = len(match.group("indent").expandtabs(4))
            body = [match.group("rest")] if match.group("rest").strip() else []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() and len(nxt.expandtabs(4)) - len(nxt.expandtabs(4).lstrip()) <= indent:
                    break
                body.append(nxt.expandtabs(4))
                j += 1
            while body and not body[-1].strip():
                body.pop()
            if not body:
                raise ValueError(f"measures.dax: measure [{match.group('name')}] has no expression")
            margin = min(len(b) - len(b.lstrip()) for b in body if b.strip())
            expression = [b[margin:].rstrip() if b.strip() else "" for b in body]
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
    names = [m["name"] for m in measures]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"measures.dax: measures defined more than once: {dupes}")
    return measures


# ----------------------------------------------------------------------------------------------------------------
# Semantic model (model.bim, TMSL)
# ----------------------------------------------------------------------------------------------------------------

def _partition_m(table: CsvTable) -> list[str]:
    """Power Query for one CSV: read, promote headers, empty field -> null, then explicit types (en-GB).
    Date columns whose values carry a time of day are read as datetime and then reduced to date."""
    timed = [c.name for c in table.columns if c.has_time]
    derived = table.name in DERIVED_COLUMNS
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
    lines.append('    }, "en-GB")' + ("," if timed or derived else ""))
    last = "Typed"
    if timed:
        lines.append("    Dates = Table.TransformColumnTypes(Typed, {")
        for k, name in enumerate(timed):
            lines.append(f'        {{"{name}", type date}}' + ("," if k < len(timed) - 1 else ""))
        lines.append("    })" + ("," if derived else ""))
        last = "Dates"
    if derived:
        stages = ", ".join(f'"{s}"' for s in READINESS_STAGES)
        lines.append(f'    Staged = Table.AddColumn({last}, "stage_order", each 1 + List.PositionOf({{{stages}}}, '
                     "[stage]), Int64.Type)")
        last = "Staged"
    lines += ["in", f"    {last}"]
    return lines


def _column(table: str, c: CsvColumn, key_columns: set[tuple[str, str]]) -> dict:
    numeric = c.kind in ("int", "number")
    no_sum = (not numeric or c.name.endswith(("_id", "_key", "_code")) or c.name in _NO_SUM
              or (table, c.name) in key_columns)
    col = {"name": c.name, "dataType": TMSL_TYPE[c.kind]}
    if c.kind == "date":
        col["formatString"] = "dd-mmm-yyyy"
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


def build_model(tables: list[CsvTable], measures: list[dict], csv_folder: str) -> dict:
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

    model_tables = []
    for t in tables:
        columns = [_column(t.name, c, key_columns) for c in t.columns]
        for derived in DERIVED_COLUMNS.get(t.name, []):
            columns.append({"name": derived, "dataType": "int64", "formatString": "0", "isHidden": True,
                            "lineageTag": guid("column", t.name, derived), "sourceColumn": derived,
                            "summarizeBy": "none",
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
    return {
        "compatibilityLevel": 1601,
        "model": {
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
        },
    }


# ----------------------------------------------------------------------------------------------------------------
# Report building blocks (property names follow Desktop-saved PBIR files)
# ----------------------------------------------------------------------------------------------------------------

AGG_FUNCTION = {"Sum": 0, "Min": 3, "Max": 4}


@dataclass(frozen=True)
class Field:
    kind: str                 # Column | Measure | Aggregation
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


def _column_expr(f: Field) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": f.table}}, "Property": f.name}}


def field_expr(f: Field) -> dict:
    if f.kind == "Column":
        return _column_expr(f)
    if f.kind == "Measure":
        return {"Measure": {"Expression": {"SourceRef": {"Entity": f.table}}, "Property": f.name}}
    return {"Aggregation": {"Expression": _column_expr(f), "Function": AGG_FUNCTION[f.func]}}


def query_ref(f: Field) -> str:
    base = f"{f.table}.{f.name}"
    return f"{f.func}({base})" if f.kind == "Aggregation" else base


class ReportBuilder:
    """Builds the PBIR report: pages, visuals and positions on a fixed grid."""

    def __init__(self, column_kinds: dict[tuple[str, str], str], latest_data_date: str, gate_ids: list[str]):
        self.kinds = column_kinds
        self.latest = latest_data_date
        self.gate_ids = gate_ids
        self.files: dict[str, bytes] = {}
        self.pages: list[str] = []

    # -- projections ------------------------------------------------------------------------------------------
    def native_ref(self, f: Field) -> str:
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
    def rules(f: Field, cases: list[tuple[dict, str]]) -> dict:
        """Rule-based colour: [(condition, hex)] -> Conditional expression on the measure f."""
        return {"solid": {"color": {"expr": {"Conditional": {"Cases": [
            {"Condition": cond, "Value": {"Literal": {"Value": text(hex_code)}}} for cond, hex_code in cases]}}}}}

    @staticmethod
    def compare(f: Field, kind: int, value: str) -> dict:
        return {"Comparison": {"ComparisonKind": kind, "Left": field_expr(f), "Right": {"Literal": {"Value": value}}}}

    # -- visuals ----------------------------------------------------------------------------------------------
    def textbox(self, paragraphs: list[list[tuple[str, dict]]]) -> dict:
        return {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [
                {"textRuns": [{"value": v, "textStyle": style} for v, style in runs], "horizontalTextAlignment": "left"}
                for runs in paragraphs]}}]},
            "visualContainerObjects": {"background": [{"properties": {"show": flag(False)}}]},
        }

    def card(self, fields: list[Field], title: str | None, value_size: int = 18, label: bool = False,
             colour_by: str | None = None, align_left: bool = False, accent: str | None = NAVY,
             alt: str | None = None) -> dict:
        value = {"textWrap": flag(True), "fontSize": num(value_size)}
        if align_left:
            value["horizontalAlignment"] = lit(text("left"))
        objects = {
            "outline": [{"properties": {"show": flag(False)}, "selector": {"id": "default"}}],
            "value": [{"properties": value, "selector": {"id": "default"}}],
            "label": [{"properties": ({"show": flag(True), "textWrap": flag(True), "fontSize": num(9)} if label
                                      else {"show": flag(False)}), "selector": {"id": "default"}}],
        }
        if colour_by:
            objects["value"].append({
                "properties": {"fontColor": {"solid": {"color": {"expr": field_expr(mea(colour_by))}}}},
                "selector": {"data": [{"dataViewWildcard": {"matchingOption": 0}}], "metadata": query_ref(fields[0])}})
        if accent:
            objects["accentBar"] = [{"properties": {"show": flag(True), "color": colour(accent), "width": num(3)},
                                     "selector": {"id": "default"}}]
        return {"visualType": "cardVisual", "query": {"queryState": {"Data": self.role(fields)}},
                "objects": objects, "visualContainerObjects": self.container_objects(title, alt)}

    def slicer(self, f: Field, header: str, mode: str, single: bool, strict: bool, sort_desc: bool = False,
               selected: str | None = None, sync: str | None = None) -> dict:
        query = {"queryState": {"Values": self.role([f], active=True)}}
        if sort_desc:
            query["sortDefinition"] = self.sort(f, "Descending")
        general = {"selfFilterEnabled": flag(True)}
        if selected is not None:
            alias = f.table[0].lower()
            general["filter"] = {"filter": {
                "Version": 2,
                "From": [{"Name": alias, "Entity": f.table, "Type": 0}],
                "Where": [{"Condition": {"In": {
                    "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": f.name}}],
                    "Values": [[{"Literal": {"Value": selected}}]]}}}]}}
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
              value_objects: list[dict] | None = None) -> dict:
        query = {"queryState": {"Values": self.role(fields)}}
        if sort:
            query["sortDefinition"] = self.sort(*sort)
        return {
            "visualType": "tableEx",
            "query": query,
            "objects": {
                "columnHeaders": [{"properties": {"columnAdjustment": lit(text("growToFit")),
                                                  "autoSizeColumnWidth": flag(True), "fontSize": num(9),
                                                  "wordWrap": flag(True)}}],
                "values": [{"properties": {"fontSize": num(9), "wordWrap": flag(False)}}] + (value_objects or []),
            },
            "visualContainerObjects": self.container_objects(title),
        }

    def matrix(self, rows: list[Field], columns: list[Field], values: list[Field], title: str,
               value_objects: list[dict] | None = None) -> dict:
        state = {"Rows": self.role(rows, active=True)}
        if columns:
            state["Columns"] = self.role(columns, active=True)
        state["Values"] = self.role(values)
        return {
            "visualType": "pivotTable",
            "query": {"queryState": state},
            "objects": {
                "columnHeaders": [{"properties": {"autoSizeColumnWidth": flag(True), "fontSize": num(9),
                                                  "wordWrap": flag(True)}}],
                "rowHeaders": [{"properties": {"fontSize": num(9), "wordWrap": flag(True)}}],
                "values": [{"properties": {"fontSize": num(9)}}] + (value_objects or []),
            },
            "visualContainerObjects": self.container_objects(title),
        }

    def chart(self, visual_type: str, category: Field, y: list[Field], title: str, series: Field | None = None,
              tooltips: list[Field] | None = None, sort: tuple[Field, str] | None = None,
              legend: bool | None = None, labels: bool = False) -> dict:
        state = {"Category": self.role([category], active=True)}
        if series:
            state["Series"] = self.role([series])
        state["Y"] = self.role(y)
        if tooltips:
            state["Tooltips"] = self.role(tooltips)
        query = {"queryState": state}
        if sort:
            query["sortDefinition"] = self.sort(*sort)
        show_legend = legend if legend is not None else (series is not None or len(y) > 1)
        objects = {
            "categoryAxis": [{"properties": {"show": flag(True), "fontSize": num(9)}}],
            "valueAxis": [{"properties": {"show": flag(True), "fontSize": num(9)}}],
            "legend": [{"properties": {"show": flag(show_legend)}}],
            "labels": [{"properties": {"show": flag(labels), "labelDisplayUnits": lit(text("1"))}}],
        }
        if visual_type != "lineChart" and len(y) == 1 and series is None:
            objects["dataPoint"] = [{"properties": {"defaultColor": colour(NAVY)}}]
        return {"visualType": visual_type, "query": query, "objects": objects,
                "visualContainerObjects": self.container_objects(title)}

    # -- pages ------------------------------------------------------------------------------------------------
    def add_page(self, number: int, key: str, display: str, title_measure: str | None, rows: list,
                 slicers: tuple[str, ...] = ("data_date",), no_filter_from_date: tuple[str, ...] = (),
                 drillthrough: Field | None = None, headline: Field | None = None) -> None:
        page = f"p{number:02d}_{key}"
        prefix = f"p{number:02d}"                 # visual names: p01_h1_programme, p01_v03_vs_bl0, ...
        placed: list[tuple[str, dict, tuple[int, int, int, int], dict | None]] = []

        # header strip: programme textbox | [threshold slicer] | selected data-date card | data-date slicer
        right = [s for s in ("threshold", "datecard", "data_date") if s == "datecard" or s in slicers]
        text_w = CONTENT_W - len(right) * (SLOT_W + GUTTER)
        placed.append((f"{prefix}_h1_programme", self.textbox([
            [(PROGRAMME, {"fontFamily": "Segoe UI Semibold", "fontSize": "15px", "color": NAVY, "fontWeight": "bold"})],
            [(f"Schedule intelligence | {display}", {"fontFamily": "Segoe UI", "fontSize": "11px", "color": MUTED})],
        ]), (CONTENT_X, HEADER_Y, text_w, HEADER_H), None))
        x = CONTENT_X + text_w + GUTTER
        for slot in right:
            box = (x, HEADER_Y, SLOT_W, HEADER_H)
            if slot == "datecard":
                label = "Selected data date" if "data_date" in slicers else "Latest data date"
                placed.append((f"{prefix}_h3_datadate", self.card([mea("Data date", label)], None, value_size=14,
                                                                label=True, accent=TEAL, alt=label), box, None))
            elif slot == "threshold":
                placed.append((f"{prefix}_h2_threshold", self.slicer(
                    col(THRESHOLD_TABLE, THRESHOLD_TABLE), "Near-critical threshold (d)", "Dropdown",
                    single=True, strict=False, sync="NearCriticalThreshold"), box, None))
            else:
                placed.append((f"{prefix}_h4_dd_slicer", self.slicer(
                    col("dim_snapshot", "data_date"), "Data date", "Dropdown", single=True, strict=True,
                    sort_desc=True, selected=f"datetime'{self.latest}T00:00:00'", sync="DataDate"), box, None))
            x += SLOT_W + GUTTER

        # title row: the page's action-title measure (or the drilled activity)
        head = mea(title_measure) if title_measure else headline
        placed.append((f"{prefix}_h0_title", self.card([head], None, value_size=12, align_left=True, accent=TEAL,
                                                     alt=f"Page headline: {display}"),
                       (CONTENT_X, TITLE_Y, CONTENT_W, TITLE_H), None))

        # content grid
        counter = [0]

        def lay(x0: int, y0: int, width: int, height: int, row_list: list) -> None:
            heights = [h for h, _ in row_list]
            if sum(heights) + GUTTER * (len(heights) - 1) != height:
                raise ValueError(f"{page}: row heights {heights} do not fill {height}px")
            y = y0
            for h, cells in row_list:
                widths = [w for w, _ in cells]
                if sum(widths) + GUTTER * (len(widths) - 1) != width:
                    raise ValueError(f"{page}: cell widths {widths} do not fill {width}px")
                cx = x0
                for w, item in cells:
                    if isinstance(item, list):
                        lay(cx, y, w, h, item)
                    else:
                        counter[0] += 1
                        vkey, visual, filters = item
                        if w < MIN_W or h < MIN_H:
                            raise ValueError(f"{page}/{vkey}: {w}x{h}px is below the {MIN_W}x{MIN_H}px minimum")
                        placed.append((f"{prefix}_v{counter[0]:02d}_{vkey}", visual, (cx, y, w, h), filters))
                    cx += w + GUTTER
                y += h + GUTTER

        lay(CONTENT_X, CONTENT_Y, CONTENT_W, CONTENT_H, rows)

        names = [p[0] for p in placed]
        for n in names:
            if len(n) > 50 or not re.fullmatch(r"[A-Za-z0-9_]+", n):
                raise ValueError(f"visual name {n!r} breaks the PBIR naming rules")
        for k, (name, visual, (x, y, w, h), filters) in enumerate(placed):
            z = (k + 1) * 1000
            container = {"$schema": SCHEMAS["visual"], "name": name,
                         "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
                         "visual": visual}
            if filters:
                container["filterConfig"] = {"filters": [
                    self.categorical_filter(hexid(20, page, name, "filter", str(i), f.table, f.name), f, vals)
                    for i, (f, vals) in enumerate(filters)]}
            self.files[f"definition/pages/{page}/visuals/{name}/visual.json"] = dumps(container)

        page_json = {"$schema": SCHEMAS["page"], "name": page, "displayName": display, "displayOption": "FitToPage",
                     "height": PAGE_H, "width": PAGE_W}
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


# ----------------------------------------------------------------------------------------------------------------
# Page design (POWERBI.md section 6, mirroring the web dashboard tabs)
# ----------------------------------------------------------------------------------------------------------------

def build_pages(rb: ReportBuilder) -> None:
    fas, act = "fact_activity_snapshot", "dim_activity"

    def float_rules(f: Field) -> list[dict]:
        # < 0 red, 0 to the default near-critical threshold (10) amber, above it green (POWERBI.md section 6)
        cases = [(rb.compare(f, 3, "0D"), RED),
                 ({"And": {"Left": rb.compare(f, 2, "0D"), "Right": rb.compare(f, 4, "10D")}}, AMBER),
                 (rb.compare(f, 1, "10D"), GREEN)]
        selector = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": query_ref(f)}
        white = [(cond, WHITE) for cond, _ in cases]
        return [{"properties": {"backColor": rb.rules(f, cases), "fontColor": rb.rules(f, white)},
                 "selector": selector}]

    # 1 Executive summary --------------------------------------------------------------------------------------
    tf_min = mea("Total float (min)", "Minimum total float")
    kpis = [
        ("day1_forecast", rb.card([mea("Day 1 forecast")], "Day 1 forecast", colour_by="Day 1 RAG colour")),
        ("day1_float", rb.card([mea("Day 1 total float")], "Day 1 total float (working days)")),
        ("vs_bl0", rb.card([mea("Day 1 variance vs BL0")], "Day 1 vs BL0 (calendar days)")),
        ("vs_bl1", rb.card([mea("Day 1 variance vs BL1")], "Day 1 vs BL1 (calendar days)")),
        ("vs_previous", rb.card([mea("Day 1 movement vs previous period")], "Day 1 vs previous update (calendar days)")),
        ("dq_score", rb.card([mea("DQ score")], "Schedule quality (DQ score)")),
        ("recon_status", rb.card([mea("Reconciliation status")], "Reconciliation status",
                                 colour_by="Reconciliation colour")),
        ("progress", rb.card([mea("Weighted % complete (actual)", "Actual"), mea("Planned % complete", "Planned")],
                             "Progress: actual vs planned", value_size=16, label=True)),
    ]
    cards = [(k, v, None) for k, v in kpis]
    rb.add_page(1, "exec", "Executive summary", "Title - Executive summary", [
        (560, [
            (376, [(128, [(180, cards[0]), (180, cards[1])]), (128, [(180, cards[2]), (180, cards[3])]),
                   (128, [(180, cards[4]), (180, cards[5])]), (128, [(180, cards[6]), (180, cards[7])])]),
            (856, [
                (272, [
                    (480, ("float_matrix", rb.matrix(
                        [col(act, "asset_name", "Asset")], [col(act, "workstream_code", "Workstream")], [tf_min],
                        "Minimum total float by asset and workstream (working days)",
                        value_objects=float_rules(tf_min)), None)),
                    (360, ("s_curve", rb.chart(
                        "lineChart", col("fact_s_curve", "date", "Month end"),
                        [agg("fact_s_curve", "planned_bl0", "Sum", "Planned (BL0)"),
                         agg("fact_s_curve", "planned_bl1", "Sum", "Planned (BL1)"),
                         agg("fact_s_curve", "forecast", "Sum", "Forecast"),
                         agg("fact_s_curve", "actual", "Sum", "Actual")],
                        "Progress S-curve: planned, forecast and actual % complete",
                        sort=(col("fact_s_curve", "date"), "Ascending")), None)),
                ]),
                (272, [
                    (420, ("top_risks", rb.table(
                        [col("fact_risk", "risk_id", "Risk"), col("fact_risk", "title", "Title"),
                         col("fact_risk", "owner_code", "Owner"), col("fact_risk", "score", "Score"),
                         col("fact_risk", "trend", "Trend"), col("fact_risk", "schedule_impact_days", "Impact (days)")],
                        "Top risks for the selected update (highest score first)",
                        sort=(col("fact_risk", "score"), "Descending")), None)),
                    (420, ("open_decisions", rb.table(
                        [col("fact_decision", "decision_id", "Decision"), col("fact_decision", "ask", "Ask"),
                         col("fact_decision", "owner", "Owner"), col("fact_decision", "needed_by", "Needed by"),
                         col("fact_decision", "overdue", "Overdue")],
                        "Open decisions with owner and needed-by date",
                        sort=(col("fact_decision", "needed_by"), "Ascending")),
                        [(col("fact_decision", "status"), [text("Open")])])),
                ]),
            ]),
        ]),
    ])

    # 2 Milestones & slippage ----------------------------------------------------------------------------------
    gate_filter = [(col(act, "activity_id"), [text(i) for i in rb.gate_ids])] if rb.gate_ids else None
    rb.add_page(2, "milestones", "Milestones & slippage", "Title - Milestones", [
        (272, [
            # BL0 is fixed per milestone, so variance vs BL0 moves exactly as the forecast date does while the
            # value axis stays numeric; the forecast date itself is in the tooltip
            (616, ("gate_forecasts", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"),
                [mea("Milestone variance vs BL0", "Forecast vs BL0 (calendar days)")],
                "Day 1 and readiness gate forecasts by data date (calendar days later than BL0)",
                series=col(act, "activity_name", "Milestone"),
                tooltips=[mea("Milestone forecast finish", "Forecast finish")],
                sort=(col("dim_snapshot", "data_date"), "Ascending")), gate_filter)),
            (616, ("slip_by_owner", rb.chart(
                "clusteredBarChart", col("dim_owner", "owner_name", "Owner"),
                [mea("Slip vs previous period", "Worst slip (calendar days)")],
                "Worst slip since the previous update by owner (calendar days)",
                tooltips=[mea("Activities slipped vs previous period", "Activities slipped")],
                sort=(mea("Slip vs previous period"), "Descending"), labels=True), None)),
        ]),
        (272, [
            (816, ("milestone_table", rb.table(
                [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Milestone"),
                 col(act, "owner_code", "Owner"), col(fas, "bl0_finish", "BL0"), col(fas, "bl1_finish", "BL1"),
                 col(fas, "prev_finish", "Previous"), col(fas, "finish", "Current"),
                 col(fas, "var_finish_bl_d", "Variance vs baseline (days)"),
                 col(fas, "slip_vs_prev_d", "Movement vs previous (days)")],
                "Milestones: owner, BL0, BL1, previous and current forecast finish, variance (calendar days)",
                sort=(col(fas, "finish"), "Ascending")),
                [(col(act, "is_milestone"), ["true"])])),
            (416, ("finish_profile", rb.chart(
                "clusteredColumnChart", col("dim_date", "year_month", "Month"),
                [mea("Milestone finishes (forecast)", "Forecast"), mea("Milestone finishes (BL1)", "BL1")],
                "Milestone finishes per month: forecast vs BL1",
                sort=(col("dim_date", "year_month"), "Ascending")), None)),
        ]),
    ], no_filter_from_date=("gate_forecasts",))

    # 3 Critical path & look-ahead -----------------------------------------------------------------------------
    rb.add_page(3, "critical", "Critical path & look-ahead", "Title - Critical path", [
        (110, [(1248, ("criticality_kpis", rb.card(
            [mea("Critical count", "Critical"), mea("Near-critical count", "Near-critical (threshold slicer)"),
             mea("Negative float count", "Negative float"), mea("Longest path count", "Longest path"),
             mea("Total float (min)", "Minimum total float (d)"), mea("Look-back hit rate", "Look-back hit rate")],
            "Criticality for the selected update", value_size=16, label=True), None))]),
        (209, [
            (740, ("longest_path", rb.table(
                [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col(act, "owner_code", "Owner"), col(fas, "start", "Start"), col(fas, "finish", "Finish"),
                 col(fas, "total_float_d", "Total float (d)")],
                "Longest path to Day 1: start, finish and total float (working days)",
                sort=(col(fas, "start"), "Ascending")),
                [(col(fas, "is_longest_path"), ["true"])])),
            (492, ("float_erosion", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"),
                [mea("Day 1 total float"), mea("Float erosion")],
                "Day 1 total float and float erosion by data date (working days)",
                sort=(col("dim_snapshot", "data_date"), "Ascending")), None)),
        ]),
        (209, [
            (616, ("look_back", rb.table(
                [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col(act, "owner_code", "Owner"), col(fas, "lookback_event", "Event"),
                 col(fas, "prev_finish", "Previous forecast"), col(fas, "lookback_achieved", "Achieved")],
                "Look-back: items due in the last 14 days and whether they were achieved",
                sort=(col(act, "activity_id"), "Ascending")),
                [(col(fas, "lookback_achieved"), ["true", "false"])])),
            (616, ("look_ahead", rb.table(
                [col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col(act, "owner_code", "Owner"), col(fas, "start", "Start"), col(fas, "finish", "Finish"),
                 col(fas, "total_float_d", "Total float (d)"), mea("Criticality band", "Band (2 critical, 1 near)")],
                "Look-ahead: activities starting or finishing in the next 14 days",
                sort=(col(fas, "start"), "Ascending")),
                [(col(fas, "lookahead"), ["true"])])),
        ]),
    ], slicers=("threshold", "data_date"), no_filter_from_date=("float_erosion",))

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
            "max": {"color": {"Literal": {"Value": text(RED)}}},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": text("noColor")}}}}}}}}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": query_ref(late)}}]
    rb.add_page(4, "interfaces", "Interfaces & readiness", "Title - Interfaces and readiness", [
        (100, [(1248, ("interface_kpis", rb.card(
            [mea("Interfaces late", "Late interfaces"), mea("Interfaces at risk", "At risk"),
             mea("Interface gap (max)", "Worst interface gap (days)"),
             mea("Readiness gap", "Worst readiness gap (days)"), mea("Readiness stages late", "Readiness stages late")],
            "Interfaces and readiness for the selected update", value_size=16, label=True), None))]),
        (222, [(1248, ("readiness_matrix", rb.matrix(
            [col("fact_readiness", "asset_code", "Asset")], [col("fact_readiness", "stage", "Stage")],
            [agg("fact_readiness", "forecast", "Max", "Forecast"), gap],
            "Readiness chain by asset: forecast and gap to the date that protects Day 1 (calendar days; positive = late)",
            value_objects=gap_rules), None))]),
        (206, [
            (420, ("late_interfaces", rb.matrix(
                [col("fact_interface", "giver_asset", "Giver")], [col("fact_interface", "receiver_asset", "Receiver")],
                [late], "Late interfaces by giver and receiver asset", value_objects=late_scale), None)),
            (812, ("interface_table", rb.table(
                [col("fact_interface", "interface_id", "Interface"), col("fact_interface", "description", "Description"),
                 col("fact_interface", "giver_owner", "Giver"), col("fact_interface", "receiver_owner", "Receiver"),
                 col("fact_interface", "need_by", "Need by"), col("fact_interface", "giver_forecast", "Giver forecast"),
                 col("fact_interface", "gap_days", "Gap (days)"), col("fact_interface", "status", "Status"),
                 col(act, "activity_id", "Giver activity")],
                "Interfaces sorted by gap (calendar days; positive = late)",
                sort=(col("fact_interface", "gap_days"), "Descending")), None)),
        ]),
    ])

    # 5 Risks, decisions & recovery ----------------------------------------------------------------------------
    rb.add_page(5, "risks", "Risks, decisions & recovery", "Title - Decisions", [
        (100, [(1248, ("recovery_kpis", rb.card(
            [mea("High risks", "High risks"), mea("Open decisions", "Open decisions"),
             mea("Overdue decisions", "Overdue decisions"), mea("Next decision needed by", "Next decision needed by"),
             mea("Recommended scenario", "Recommended scenario"), mea("Float gain", "Float gain (working days)")],
            "Risks, decisions and recovery", value_size=16, label=True), None))]),
        (214, [
            (416, ("scenario_float", rb.chart(
                "clusteredBarChart", col("fact_scenario", "scenario_id", "Scenario"),
                [agg("fact_scenario", "day1_tf_d", "Sum", "Day 1 total float (working days)")],
                "Day 1 total float by recovery scenario (working days)",
                sort=(agg("fact_scenario", "day1_tf_d", "Sum"), "Descending"), labels=True), None)),
            (816, ("scenario_table", rb.table(
                [col("fact_scenario", "scenario_id", "Scenario"), col("fact_scenario", "name", "Name"),
                 col("fact_scenario", "day1_forecast", "Day 1 forecast"), col("fact_scenario", "day1_tf_d", "Day 1 TF (d)"),
                 col("fact_scenario", "float_gain_d", "Float gain (d)"),
                 col("fact_scenario", "neg_float_count", "Negative float"),
                 col("fact_scenario", "near_critical_count", "Near-critical"),
                 col("fact_scenario", "residual_risk", "Residual risk"), col("fact_scenario", "decision", "Decisions"),
                 col("fact_scenario", "recommended", "Recommended")],
                "Recovery scenarios: outcome, decisions needed and residual risk",
                sort=(col("fact_scenario", "day1_tf_d"), "Descending")), None)),
        ]),
        (214, [
            (616, ("risk_register", rb.table(
                [col("fact_risk", "risk_id", "Risk"), col("fact_risk", "title", "Title"),
                 col("fact_risk", "owner_code", "Owner"), col("fact_risk", "probability", "P"),
                 col("fact_risk", "impact", "I"), col("fact_risk", "score", "Score"), col("fact_risk", "rating", "Rating"),
                 col("fact_risk", "trend", "Trend"), col("fact_risk", "mitigation_owner", "Mitigation owner"),
                 col("fact_risk", "schedule_impact_days", "Impact (days)"),
                 col("fact_risk", "min_linked_float_d", "Min linked float (d)")],
                "Risk register for the selected update", sort=(col("fact_risk", "score"), "Descending")), None)),
            (616, ("decision_log", rb.table(
                [col("fact_decision", "decision_id", "Decision"), col("fact_decision", "ask", "Ask"),
                 col("fact_decision", "owner", "Owner"), col("fact_decision", "raised_data_date", "Raised"),
                 col("fact_decision", "needed_by", "Needed by"), col("fact_decision", "status", "Status"),
                 col("fact_decision", "overdue", "Overdue"), col("fact_decision", "closed_on", "Closed"),
                 col("fact_decision", "outcome", "Outcome")],
                "Decision log (all decisions)", sort=(col("fact_decision", "needed_by"), "Ascending")), None)),
        ]),
    ])

    # 6 Schedule quality (DCMA) --------------------------------------------------------------------------------
    rb.add_page(6, "quality", "Schedule quality (DCMA)", "Title - Schedule quality", [
        (100, [
            (300, ("dq_card", rb.card([mea("DQ score", "DQ score"), mea("DQ rating", "Rating")],
                                      "DQ score and rating", value_size=16, label=True), None)),
            (300, ("dcma_card", rb.card([mea("DCMA pass count", "Passed"), mea("DCMA applicable checks", "Applicable")],
                                        "DCMA checks passed", value_size=16, label=True), None)),
            (300, ("cpli_card", rb.card([mea("CPLI")], "CPLI (critical path length index)", value_size=16), None)),
            (300, ("bei_card", rb.card([mea("BEI", "BEI"), mea("BEI tasks completed", "Completed"),
                                        mea("BEI tasks due", "Due")],
                                       "BEI (baseline execution index)", value_size=16, label=True), None)),
        ]),
        (214, [
            (816, ("dcma_table", rb.table(
                [col("fact_dcma_check", "check_id", "Check"), col("fact_dcma_check", "check_name", "Check name"),
                 col("fact_dcma_check", "group", "Group"), col("fact_dcma_check", "value", "Value"),
                 col("fact_dcma_check", "threshold", "Threshold"), col("fact_dcma_check", "passed", "Pass"),
                 col("fact_dcma_check", "score", "Score"), col("fact_dcma_check", "weight", "Weight")],
                "DCMA and update-discipline checks: value, threshold and pass",
                sort=(col("fact_dcma_check", "check_id"), "Ascending")), None)),
            (416, ("dq_trend", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"), [mea("DQ score")],
                "DQ score by data date (Good 85 or more, Fair 70 to 85)",
                sort=(col("dim_snapshot", "data_date"), "Ascending"), labels=True), None)),
        ]),
        (214, [
            (520, ("owner_scorecard", rb.table(
                [col("dim_owner", "owner_name", "Owner"), mea("Owner DQ", "Owner DQ"),
                 col("fact_owner_scorecard", "incomplete", "Incomplete"), col("fact_owner_scorecard", "flagged", "Flagged"),
                 col("fact_owner_scorecard", "update_issues", "Update issues"),
                 col("fact_owner_scorecard", "logic_issues", "Logic issues")],
                "Owner scorecard: Owner DQ and flags", sort=(mea("Owner DQ"), "Ascending")), None)),
            (200, ("check_slicer", rb.slicer(col("fact_dcma_offender", "check_id"), "DCMA check (offenders)", "Basic",
                                             single=True, strict=False), None)),
            (496, ("offenders", rb.table(
                [col("fact_dcma_offender", "check_id", "Check"), col("fact_dcma_offender", "item", "Item"),
                 col(act, "activity_id", "Activity ID"), col(act, "activity_name", "Activity"),
                 col("fact_dcma_offender", "owner_code", "Owner")],
                "Offenders for the selected check", sort=(col("fact_dcma_offender", "check_id"), "Ascending")), None)),
        ]),
    ], slicers=("threshold", "data_date"), no_filter_from_date=("dq_trend",))

    # 7 Reconciliation & lineage -------------------------------------------------------------------------------
    lineage_style = {"fontFamily": "Segoe UI", "fontSize": "12px", "color": "#1A202C"}
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
    rb.add_page(7, "recon", "Reconciliation & lineage", "Title - Reconciliation", [
        (100, [
            (300, ("recon_status", rb.card([mea("Reconciliation status")], "Reconciliation status", value_size=16,
                                           colour_by="Reconciliation colour"), None)),
            (300, ("controls_card", rb.card([mea("Controls passed", "Passed"), mea("Controls total", "Total")],
                                            "Controls passed", value_size=16, label=True), None)),
            (300, ("source_file", rb.card([mea("Source file")], "Source file (P6 XER)", value_size=12), None)),
            (300, ("baseline", rb.card([mea("Baseline in force")], "Baseline in force", value_size=16), None)),
        ]),
        (266, [(1248, ("controls_table", rb.table(
            [col("fact_reconciliation", "control_id", "Control"), col("fact_reconciliation", "control", "Description"),
             col("fact_reconciliation", "source_value", "Source (XER)"),
             col("fact_reconciliation", "model_value", "Model (CSV)"),
             col("fact_reconciliation", "dashboard_value", "Dashboard (JSON)"),
             col("fact_reconciliation", "delta", "Delta"), col("fact_reconciliation", "passed", "Pass")],
            "Reconciliation controls: source, model and dashboard values, delta and pass",
            sort=(col("fact_reconciliation", "control_id"), "Ascending")), None))]),
        (162, [
            (616, ("lineage_text", lineage, None)),
            (616, ("source_files", rb.table(
                [col("dim_snapshot", "label", "Update"), col("dim_snapshot", "data_date", "Data date"),
                 col("dim_snapshot", "source_file", "Source file"), col("dim_snapshot", "sha256", "SHA-256"),
                 col("dim_snapshot", "baseline_in_force", "Baseline"),
                 col("dim_snapshot", "baseline_file", "Baseline file")],
                "Source files and hashes for every update", sort=(col("dim_snapshot", "data_date"), "Ascending")),
                None)),
        ]),
    ], no_filter_from_date=("source_files",))

    # 8 Activity details (drill-through, hidden) ---------------------------------------------------------------
    rb.add_page(8, "activity", "Activity details", None, [
        (126, [
            # dim_activity columns only: the drill-through filter on dim_activity does not reach dim_owner or
            # dim_calendar (filters run from the one side to the many side)
            (832, ("attributes", rb.card(
                [agg(act, "activity_id", "Min", "Activity ID"), agg(act, "asset_name", "Min", "Asset"),
                 agg(act, "workstream_name", "Min", "Workstream"), agg(act, "package_name", "Min", "Package"),
                 agg(act, "owner_code", "Min", "Owner"), agg(act, "activity_type", "Min", "Type"),
                 agg(act, "phase", "Min", "Phase")],
                "Activity attributes", value_size=12, label=True), None)),
            (400, ("latest", rb.card(
                [mea("Forecast finish", "Forecast finish"), mea("Finish variance vs BL1", "vs BL1 (days)"),
                 mea("Total float (min)", "Total float (d)"), mea("Criticality band", "Criticality band")],
                "Latest update", value_size=14, label=True), None)),
        ]),
        (204, [(1248, ("history", rb.table(
            [col("dim_snapshot", "label", "Update"), col("dim_snapshot", "data_date", "Data date"),
             col(fas, "status", "Status"), col(fas, "start", "Start"), col(fas, "finish", "Finish"),
             col(fas, "total_float_d", "TF (d)"), col(fas, "var_finish_bl0_d", "vs BL0 (d)"),
             col(fas, "var_finish_bl1_d", "vs BL1 (d)"), col(fas, "slip_vs_prev_d", "Movement (d)"),
             col(fas, "constraint_type", "Constraint"), col(fas, "dq_flags", "DQ flags")],
            "History across all updates", sort=(col("dim_snapshot", "data_date"), "Ascending")), None))]),
        (198, [
            (616, ("float_history", rb.chart(
                "lineChart", col("dim_snapshot", "data_date", "Data date"),
                [mea("Total float (min)", "Total float (working days)")],
                "Total float by data date: when did this activity lose its float?",
                sort=(col("dim_snapshot", "data_date"), "Ascending"), labels=True), None)),
            (616, ("drivers", rb.table(
                [col("fact_relationship", "pred_id", "Predecessor"), col("fact_relationship", "rel_type", "Type"),
                 col("fact_relationship", "lag_d", "Lag (d)"), col("fact_relationship", "is_driving", "Driving"),
                 col("fact_relationship", "slack_d", "Slack (d)")],
                "Predecessors in the latest update (driving first)",
                sort=(col("fact_relationship", "is_driving"), "Descending")),
                [(col("dim_snapshot", "is_latest"), ["true"])])),
        ]),
    ], slicers=(), drillthrough=col(act, "activity_id"), headline=agg(act, "activity_name", "Min", "Activity"))


# ----------------------------------------------------------------------------------------------------------------
# Project files
# ----------------------------------------------------------------------------------------------------------------

def _platform(kind: str) -> dict:
    return {"$schema": SCHEMAS["platform"], "metadata": {"type": kind, "displayName": PROJECT},
            "config": {"version": "2.0", "logicalId": guid("platform", PROJECT, kind)}}


def build_files(root: pathlib.Path = ROOT, csv_folder: str = DEFAULT_CSV_FOLDER) -> tuple[dict[str, bytes], dict]:
    """All project files as {path relative to the powerbi folder: bytes}, plus a summary."""
    tables = read_tables(root / "output" / "csv")
    measures = parse_measures((root / "powerbi" / "measures.dax").read_text(encoding="utf-8"))
    theme = (root / "powerbi" / "dop_theme.json").read_bytes()
    json.loads(theme)                                            # must parse

    model = build_model(tables, measures, csv_folder)
    by_name = {t.name: t for t in tables}
    kinds = {(t.name, c.name): c.kind for t in tables for c in t.columns}
    snapshots = by_name["dim_snapshot"].rows
    latest_rows = [r for r in snapshots if r["is_latest"] == "True"] or snapshots
    latest = max(r["data_date"][:10] for r in latest_rows)
    in_trend = {r["activity_id"] for r in by_name["fact_milestone_trend"].rows}
    gate_ids = sorted(r["activity_id"] for r in by_name["dim_activity"].rows
                      if r["asset_code"] == "PRG" and r["readiness_gate"] and r["activity_id"] in in_trend)

    rb = ReportBuilder(kinds, latest, gate_ids)
    build_pages(rb)

    sm, rp = f"{PROJECT}.SemanticModel", f"{PROJECT}.Report"
    files: dict[str, bytes] = {
        f"{PROJECT}.pbip": dumps({"$schema": SCHEMAS["pbip"], "version": "1.0",
                                  "artifacts": [{"report": {"path": rp}}],
                                  "settings": {"enableAutoRecovery": True}}),
        f"{sm}/.platform": dumps(_platform("SemanticModel")),
        f"{sm}/definition.pbism": dumps({"$schema": SCHEMAS["pbism"], "version": "4.2", "settings": {}}),
        f"{sm}/model.bim": dumps(model),
        f"{rp}/.platform": dumps(_platform("Report")),
        f"{rp}/definition.pbir": dumps({"$schema": SCHEMAS["pbir"], "version": "4.0",
                                        "datasetReference": {"byPath": {"path": f"../{sm}"}}}),
        f"{rp}/StaticResources/RegisteredResources/{THEME_FILE}": theme,
        f"{rp}/definition/version.json": dumps({"$schema": SCHEMAS["version"], "version": "2.0.0"}),
        f"{rp}/definition/report.json": dumps({
            "$schema": SCHEMAS["report"],
            "themeCollection": {
                "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": THEME_VERSION_AT_IMPORT,
                              "type": "SharedResources"},
                "customTheme": {"name": THEME_FILE, "reportVersionAtImport": THEME_VERSION_AT_IMPORT,
                                "type": "RegisteredResources"},
            },
            "objects": {"section": [{"properties": {"verticalAlignment": lit(text("Top"))}}]},
            "resourcePackages": [
                {"name": "RegisteredResources", "type": "RegisteredResources",
                 "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}]},
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
               "relationships": len(RELATIONSHIPS), "pages": len(rb.pages), "visuals": visuals,
               "files": len(files)}
    return files, summary


def write_project(files: dict[str, bytes], out_dir: pathlib.Path) -> None:
    """Write the files and remove page or visual folders that the current design no longer has."""
    sm_definition = out_dir / f"{PROJECT}.SemanticModel" / "definition"
    if sm_definition.exists():
        raise SystemExit(f"{sm_definition} holds a TMDL model; a project cannot have both TMDL and model.bim. "
                         "Remove that folder or write to another --out folder.")
    for rel, data in files.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    pages_dir = out_dir / f"{PROJECT}.Report" / "definition" / "pages"
    parts = [pathlib.PurePosixPath(p).parts for p in files]
    # DOP.Report/definition/pages/<page>/page.json and .../<page>/visuals/<visual>/visual.json
    wanted = {pp[3] for pp in parts if pp[:3] == (f"{PROJECT}.Report", "definition", "pages") and len(pp) > 4}
    wanted_visuals = {pp[5] for pp in parts if len(pp) > 6 and pp[4] == "visuals"}
    for page in pages_dir.iterdir():
        if page.is_dir() and page.name not in wanted:
            shutil.rmtree(page)
        elif page.is_dir() and (page / "visuals").is_dir():
            for visual in (page / "visuals").iterdir():
                if visual.is_dir() and visual.name not in wanted_visuals:
                    shutil.rmtree(visual)


def generate_pbip(root: pathlib.Path = ROOT, out_dir: pathlib.Path | None = None,
                  csv_folder: str = DEFAULT_CSV_FOLDER) -> dict:
    files, summary = build_files(root, csv_folder)
    out = out_dir or (root / "powerbi")
    write_project(files, out)
    summary["out_dir"] = out
    return summary
