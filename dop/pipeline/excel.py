"""Excel controls workbook per data date (openpyxl): Reconciliation, DCMA, Milestone Variance, Look-ahead,
Owner Scorecard. Frozen headers, filters, conditional formatting; the workbook a planner hands to auditors."""
from __future__ import annotations

import datetime as dt
import pathlib

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

NAVY = "1F3A5F"
HDR = PatternFill("solid", fgColor=NAVY)
RED = PatternFill("solid", fgColor="F4C7C3")
GREEN = PatternFill("solid", fgColor="CDE8D5")
AMBER = PatternFill("solid", fgColor="FBE3B5")


def _sheet(wb, title, header, rows, widths=None, note=None):
    ws = wb.create_sheet(title)
    start = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = Font(italic=True, color="555555")
        start = 2
    for j, h in enumerate(header, 1):
        c = ws.cell(row=start, column=j, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HDR
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, r in enumerate(rows, start + 1):
        for j, v in enumerate(r, 1):
            if isinstance(v, dt.datetime):
                v = v.date()
            c = ws.cell(row=i, column=j, value=v)
            if isinstance(v, dt.date):
                c.number_format = "dd-mmm-yyyy"
    ws.freeze_panes = ws.cell(row=start + 1, column=1)
    last = get_column_letter(len(header))
    ws.auto_filter.ref = f"A{start}:{last}{max(start + 1, start + len(rows))}"
    for j, w in enumerate(widths or [16] * len(header), 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    return ws, start


def write_workbook(m: dict, sid: int, controls: list[dict], path: pathlib.Path):
    wb = Workbook()
    wb.remove(wb.active)
    ds = m["dim_snapshot"].set_index("snapshot_id").loc[sid]
    note = (f"DOP controls workbook | data date {ds.data_date:%d-%b-%Y} | source {ds.source_file} | baseline "
            f"{ds.baseline_in_force} | fictional data")
    # Reconciliation
    rows = [[c["control_id"], c["control"], str(c["source_value"]), str(c["model_value"]), str(c["dashboard_value"]),
             c["delta"] if c["delta"] is not None else "", "PASS" if c["passed"] else "FAIL"] for c in controls]
    ws, s = _sheet(wb, "Reconciliation", ["Control", "Description", "Source (XER)", "Model (CSV)", "Dashboard (JSON)",
                                          "Delta", "Result"], rows, [10, 44, 24, 24, 24, 10, 10], note)
    rng = f"G{s + 1}:G{s + len(rows)}"
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"PASS"'], fill=GREEN))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"FAIL"'], fill=RED))
    # DCMA
    dc = m["fact_dcma_check"]
    dc = dc[dc.snapshot_id == sid]
    rows = [[r.check_id, r.check_name, r.group, r.value, r.threshold, r.count, r.denominator,
             "N/A" if r.passed is None else "PASS" if r.passed else "FAIL", r.weight, r.score, r.definition]
            for r in dc.itertuples()]
    ws, s = _sheet(wb, "DCMA", ["Check", "Name", "Group", "Value", "Threshold", "Count", "Denominator", "Result",
                                "Weight", "Score", "Definition"], rows, [8, 30, 16, 10, 10, 8, 12, 9, 8, 8, 70], note)
    rng = f"H{s + 1}:H{s + len(rows)}"
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"PASS"'], fill=GREEN))
    ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"FAIL"'], fill=RED))
    off = m["fact_dcma_offender"]
    off = off[off.snapshot_id == sid]
    _sheet(wb, "DCMA Offenders", ["Check", "Item", "Activity", "Owner"],
           [[r.check_id, r.item, r.activity_id, r.owner_code] for r in off.itertuples()], [8, 48, 16, 12], note)
    # Milestone variance
    da = m["dim_activity"].set_index("activity_id")
    ms = m["fact_milestone_trend"]
    ms = ms[ms.snapshot_id == sid]
    rows = [[r.activity_id, da.at[r.activity_id, "activity_name"], r.owner_code, r.bl0_finish, r.bl1_finish,
             r.forecast_finish, r.var_bl0_d, r.var_bl1_d, r.movement_vs_prev_d, r.total_float_d, r.status]
            for r in ms.sort_values("forecast_finish").itertuples()]
    ws, s = _sheet(wb, "Milestone Variance", ["Milestone", "Name", "Owner", "BL0 finish", "BL1 finish", "Forecast",
                                              "Var vs BL0 (d)", "Var vs BL1 (d)", "Movement vs prev (d)", "TF (d)",
                                              "Status"], rows, [16, 46, 8, 13, 13, 13, 12, 12, 14, 8, 12], note)
    n = s + len(rows)
    ws.conditional_formatting.add(f"G{s + 1}:I{n}", CellIsRule(operator="greaterThan", formula=["0"], fill=AMBER))
    ws.conditional_formatting.add(f"J{s + 1}:J{n}", CellIsRule(operator="lessThan", formula=["0"], fill=RED))
    # Look-ahead
    fa = m["fact_activity_snapshot"]
    la = fa[(fa.snapshot_id == sid) & fa.lookahead].sort_values("start")
    rows = [[r.activity_id, da.at[r.activity_id, "activity_name"], da.at[r.activity_id, "owner_code"],
             "Start" if r.lookahead_start else "Finish", r.start, r.finish, r.total_float_d,
             "Yes" if r.is_critical or r.is_longest_path else "No"] for r in la.itertuples()]
    ws, s = _sheet(wb, "Look-ahead", ["Activity", "Name", "Owner", "Event", "Start", "Finish", "TF (d)",
                                      "Critical / longest path"], rows, [16, 50, 8, 8, 13, 13, 8, 12],
                   note + " | next 14 days")
    n = s + max(1, len(rows))
    ws.conditional_formatting.add(f"H{s + 1}:H{n}", CellIsRule(operator="equal", formula=['"Yes"'], fill=RED))
    # Owner scorecard
    os_ = m["fact_owner_scorecard"]
    os_ = os_[os_.snapshot_id == sid]
    rows = [[r.owner_code, r.activities, r.incomplete, r.flagged, r.owner_dq, r.update_issues, r.logic_issues]
            for r in os_.itertuples()]
    ws, s = _sheet(wb, "Owner Scorecard", ["Owner", "Activities", "Incomplete", "Flagged", "Owner DQ %",
                                           "Update-discipline issues", "Logic/constraint issues"], rows,
                   [12, 11, 11, 9, 11, 14, 14], note)
    ws.conditional_formatting.add(f"E{s + 1}:E{s + len(rows)}",
                                  ColorScaleRule(start_type="num", start_value=60, start_color="F4C7C3",
                                                 end_type="num", end_value=100, end_color="CDE8D5"))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.properties.creator = "dop.pipeline"
    wb.properties.created = dt.datetime(2026, 1, 1)
    wb.save(path)
