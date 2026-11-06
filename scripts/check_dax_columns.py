"""Validate the Power BI support files against the star-schema CSVs.

Checks
  1. Every Table[Column] referenced in powerbi/measures.dax and in the ```dax blocks of POWERBI.md exists
     in an output/csv header (or is one of the few model objects created in Power BI, listed below).
  2. Every bare [Name] reference is a measure defined in measures.dax (or [Value] from GENERATESERIES).
  3. Brackets and parentheses balance in each measure; no measure is defined twice.
  4. Every MEASURE block shown in POWERBI.md is identical to the one in measures.dax.
  5. The relationship keys documented in POWERBI.md section 3 are unique on the one side and every
     many-side value is found on the one side (blank keys and listed exceptions aside).
  6. powerbi/dop_theme.json parses and carries the shared palette in the agreed order.

Usage:  .venv\\Scripts\\python.exe scripts\\check_dax_columns.py      (exit 0 = pass)
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "output" / "csv"
DAX = ROOT / "powerbi" / "measures.dax"
DOC = ROOT / "POWERBI.md"
THEME = ROOT / "powerbi" / "dop_theme.json"

# Model objects created inside Power BI (POWERBI.md section 4), not loaded from output/csv.
MODEL_TABLES = {
    "_Measures": set(),
    "Near-critical threshold": {"Near-critical threshold"},
    "Hierarchy level": {"Hierarchy level", "Hierarchy level Fields", "Hierarchy level Order"},
    "Compare against": {"Compare against", "Compare against Fields", "Compare against Order"},
    "security_owner_map": {"user_upn", "owner_code"},
    "definitions": {"measure", "definition", "formula", "source_fields", "grain", "owner", "unit"},
}
BARE_OK = {"Value"}  # GENERATESERIES output column

# (many table, many column, one table, one column, values allowed to be missing on the one side)
RELATIONSHIPS = [
    ("fact_activity_snapshot", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_activity_snapshot", "activity_id", "dim_activity", "activity_id", set()),
    ("fact_activity_snapshot", "finish", "dim_date", "date", set()),
    ("fact_activity_snapshot", "bl0_finish", "dim_date", "date", set()),
    ("fact_activity_snapshot", "bl1_finish", "dim_date", "date", set()),
    ("fact_snapshot_summary", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_milestone_trend", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_milestone_trend", "activity_id", "dim_activity", "activity_id", set()),
    ("fact_relationship", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_relationship", "succ_id", "dim_activity", "activity_id", set()),
    ("fact_interface", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_interface", "giver_id", "dim_activity", "activity_id", set()),
    ("fact_readiness", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_readiness", "activity_id", "dim_activity", "activity_id", set()),
    ("fact_dcma_check", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_dcma_offender", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_dcma_offender", "activity_id", "dim_activity", "activity_id", {"*"}),  # U08 items are not activities
    ("fact_owner_scorecard", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_owner_scorecard", "owner_code", "dim_owner", "owner_code", set()),
    ("fact_reconciliation", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_risk", "snapshot_id", "dim_snapshot", "snapshot_id", set()),
    ("fact_risk", "owner_code", "dim_owner", "owner_code", set()),
    ("fact_s_curve", "date", "dim_date", "date", set()),
    ("dim_activity", "wbs_id", "dim_wbs", "wbs_id", set()),
    ("dim_activity", "owner_code", "dim_owner", "owner_code", set()),
    ("dim_activity", "calendar_id", "dim_calendar", "calendar_id", set()),
]
PALETTE = ["#1F3A5F", "#2B7A78", "#B7791F", "#8E6C8A", "#64748B", "#C0392B", "#D68910", "#1E8449"]


def strip_dax(text: str) -> str:
    """Remove comments and string literals (strings become "") so references can be scanned safely."""
    out, i, n = [], 0, len(text)
    while i < n:
        c, nxt = text[i], text[i + 1:i + 2]
        if c == "/" and nxt == "/" or c == "-" and nxt == "-":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c == '"':
            i += 1
            while i < n:
                if text[i] == '"' and text[i + 1:i + 2] == '"':
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            out.append('""')
        else:
            out.append(c)
            i += 1
    return "".join(out)


QUAL = re.compile(r"(?:'([^'\n]+)'|\b([A-Za-z_][A-Za-z0-9_]*))\s*\[([^\]\n]+)\]")
BARE = re.compile(r"\[([^\]\n]+)\]")
MEASURE_DEF = re.compile(r"MEASURE\s+'_Measures'\[([^\]]+)\]\s*=")


def headers() -> dict[str, set[str]]:
    out = {}
    for f in sorted(CSV_DIR.glob("*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            out[f.stem] = set(next(csv.reader(fh)))
    return out


def measure_blocks(text: str) -> dict[str, str]:
    """MEASURE name -> full definition text (until the next MEASURE, comment rule or EVALUATE)."""
    blocks = {}
    starts = [m for m in re.finditer(r"^[ \t]*MEASURE\s+'_Measures'\[([^\]]+)\]", text, re.M)]
    for k, m in enumerate(starts):
        end = starts[k + 1].start() if k + 1 < len(starts) else len(text)
        body = text[m.start():end]
        cut = re.search(r"^\s*(//|EVALUATE|```)", body[1:], re.M)
        if cut:
            body = body[:cut.start() + 1]
        blocks.setdefault(m.group(1), []).append(textwrap.dedent(body.rstrip()).strip())
    return blocks


def check_refs(label: str, code: str, tables: dict[str, set[str]], measures: set[str], errors: list[str]):
    clean = strip_dax(code)
    for m in QUAL.finditer(clean):
        table, col = m.group(1) or m.group(2), m.group(3)
        if table == "_Measures":
            if col not in measures:
                errors.append(f"{label}: unknown measure '_Measures'[{col}]")
        elif table not in tables:
            errors.append(f"{label}: unknown table {table!r} in {m.group(0)}")
        elif col not in tables[table]:
            errors.append(f"{label}: column {table}[{col}] not found")
    rest = QUAL.sub(" ", clean)
    for m in BARE.finditer(rest):
        if m.group(1) not in measures and m.group(1) not in BARE_OK:
            errors.append(f"{label}: bare reference [{m.group(1)}] is not a defined measure")


def balanced(code: str) -> bool:
    clean = re.sub(r"'[^'\n]*'|\[[^\]\n]*\]", "", strip_dax(code))
    return clean.count("(") == clean.count(")") and clean.count("{") == clean.count("}")


def read_csv_rows(name: str) -> list[dict]:
    with (CSV_DIR / f"{name}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def norm(v: str) -> str:
    v = v.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", v):
        return v[:10]          # datetimes are typed as dates in Power Query
    if re.match(r"^-?\d+\.0$", v):
        return v[:-2]
    return v


def main() -> int:
    errors: list[str] = []
    tables = headers()
    if len(tables) != 22:
        errors.append(f"expected 22 CSV tables in output/csv, found {len(tables)}")
    tables.update({k: v for k, v in MODEL_TABLES.items()})

    dax_text = DAX.read_text(encoding="utf-8")
    blocks = measure_blocks(dax_text)
    measures = set(blocks)
    for name, defs in blocks.items():
        if len(defs) > 1:
            errors.append(f"measures.dax: measure [{name}] defined {len(defs)} times")
        if not balanced(defs[0]):
            errors.append(f"measures.dax: unbalanced brackets in [{name}]")
    check_refs("measures.dax", dax_text, tables, measures, errors)

    doc = DOC.read_text(encoding="utf-8")
    doc_blocks = re.findall(r"```dax\n(.*?)```", doc, re.S)
    for k, code in enumerate(doc_blocks, 1):
        check_refs(f"POWERBI.md dax block {k}", code, tables, measures, errors)
        if not balanced(code):
            errors.append(f"POWERBI.md dax block {k}: unbalanced brackets")
    shown: dict[str, list[str]] = {}
    for code in doc_blocks:
        for name, defs in measure_blocks(code).items():
            shown.setdefault(name, []).extend(defs)
    for name, defs in shown.items():
        if name not in blocks:
            errors.append(f"POWERBI.md shows measure [{name}] that is not in measures.dax")
        elif defs[0] != blocks[name][0]:
            errors.append(f"POWERBI.md: measure [{name}] differs from measures.dax")

    for many, mcol, one, ocol, allowed in RELATIONSHIPS:
        one_vals = [norm(r[ocol]) for r in read_csv_rows(one)]
        if len(one_vals) != len(set(one_vals)):
            errors.append(f"relationship {one}[{ocol}] is not unique on the one side")
        keys = set(one_vals)
        missing = {norm(r[mcol]) for r in read_csv_rows(many) if r[mcol].strip()} - keys
        if missing and "*" not in allowed:
            errors.append(f"relationship {many}[{mcol}] -> {one}[{ocol}]: {len(missing)} keys missing, "
                          f"e.g. {sorted(missing)[:3]}")

    try:
        theme = json.loads(THEME.read_text(encoding="utf-8"))
        if theme.get("dataColors") != PALETTE:
            errors.append("dop_theme.json: dataColors do not match the shared palette order")
        for key in ("name", "background", "foreground", "tableAccent", "good", "neutral", "bad",
                    "textClasses", "visualStyles"):
            if key not in theme:
                errors.append(f"dop_theme.json: missing {key}")
    except json.JSONDecodeError as exc:
        errors.append(f"dop_theme.json does not parse: {exc}")

    if errors:
        print("Power BI checks FAILED:")
        print("\n".join(f"  - {e}" for e in errors))
        return 1
    print(f"Power BI checks passed: {len(measures)} measures, {len(doc_blocks)} DAX blocks in POWERBI.md "
          f"({len(shown)} measures shown), {len(RELATIONSHIPS)} relationships, theme OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
