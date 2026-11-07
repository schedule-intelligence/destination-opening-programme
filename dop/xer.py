"""Primavera P6 XER writer and generic parser.

Format: ``ERMHDR`` header line; then per table ``%T <table>``, ``%F <fields...>``, ``%R <values...>``
(tab-delimited); file ends with ``%E``. The parser is generic and reads any table.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
from collections import OrderedDict

ENCODING = "cp1252"   # P6 exports Windows-1252 by default

# ----------------------------------------------------------------------------- field lists (P6 names)
FIELDS = {
    "PROJECT": ["proj_id", "fy_start_month_num", "rsrc_self_add_flag", "allow_complete_flag",
                "rsrc_multi_assign_flag", "checkout_flag", "project_flag", "step_complete_flag",
                "cost_qty_recalc_flag", "batch_sum_flag", "name_sep_char", "def_complete_pct_type",
                "proj_short_name", "acct_id", "orig_proj_id", "source_proj_id", "base_type_id", "clndr_id",
                "sum_base_proj_id", "task_code_base", "task_code_step", "priority_num", "wbs_max_sum_level",
                "strgy_priority_num", "last_checksum", "critical_drtn_hr_cnt", "def_cost_per_qty",
                "last_recalc_date", "plan_start_date", "plan_end_date", "scd_end_date", "add_date",
                "last_tasksum_date", "fcst_start_date", "def_duration_type", "task_code_prefix", "guid",
                "def_qty_type", "add_by_name", "web_local_root_path", "proj_url", "def_rate_type",
                "add_act_remain_flag", "act_this_per_link_flag", "def_task_type", "act_pct_link_flag",
                "critical_path_type", "task_code_prefix_flag", "def_rollup_dates_flag",
                "use_project_baseline_flag", "rem_target_link_flag", "reset_planned_flag", "allow_neg_act_flag",
                "sum_assign_level", "last_fin_dates_id", "fintmpl_id", "last_baseline_update_date",
                "cr_external_key", "apply_actuals_date", "location_id", "last_schedule_date",
                "loaded_scope_level", "export_flag", "new_fin_dates_id", "baselines_to_export",
                "baseline_names_to_export", "next_data_date", "close_period_flag", "sum_refresh_date",
                "trsrcsum_loaded", "sumtask_loaded"],
    "CALENDAR": ["clndr_id", "default_flag", "clndr_name", "proj_id", "base_clndr_id", "last_chng_date",
                 "clndr_type", "day_hr_cnt", "week_hr_cnt", "month_hr_cnt", "year_hr_cnt", "rsrc_private",
                 "clndr_data"],
    "PROJWBS": ["wbs_id", "proj_id", "obs_id", "seq_num", "est_wt", "proj_node_flag", "sum_data_flag",
                "status_code", "wbs_short_name", "wbs_name", "phase_id", "parent_wbs_id", "ev_user_pct",
                "ev_etc_user_value", "orig_cost", "indep_remain_total_cost", "ann_dscnt_rate_pct",
                "dscnt_period_type", "indep_remain_work_qty", "anticip_start_date", "anticip_end_date",
                "ev_compute_type", "ev_etc_compute_type", "guid", "tmpl_guid", "plan_open_state"],
    "TASK": ["task_id", "proj_id", "wbs_id", "clndr_id", "phys_complete_pct", "rev_fdbk_flag", "est_wt",
             "lock_plan_flag", "auto_compute_act_flag", "complete_pct_type", "task_type", "duration_type",
             "status_code", "task_code", "task_name", "rsrc_id", "total_float_hr_cnt", "free_float_hr_cnt",
             "remain_drtn_hr_cnt", "act_work_qty", "remain_work_qty", "target_work_qty", "target_drtn_hr_cnt",
             "target_equip_qty", "act_equip_qty", "remain_equip_qty", "cstr_date", "act_start_date",
             "act_end_date", "late_start_date", "late_end_date", "expect_end_date", "early_start_date",
             "early_end_date", "restart_date", "reend_date", "target_start_date", "target_end_date",
             "rem_late_start_date", "rem_late_end_date", "cstr_type", "priority_type", "suspend_date",
             "resume_date", "float_path", "float_path_order", "guid", "tmpl_guid", "cstr_date2", "cstr_type2",
             "driving_path_flag", "act_this_per_work_qty", "act_this_per_equip_qty",
             "external_early_start_date", "external_late_end_date", "create_date", "update_date",
             "create_user", "update_user", "location_id"],
    "TASKPRED": ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type",
                 "lag_hr_cnt", "comments", "float_path", "aref", "arls"],
    "ACTVTYPE": ["actv_code_type_id", "actv_short_len", "seq_num", "actv_code_type", "proj_id", "wbs_id",
                 "actv_code_type_scope", "super_flag"],
    "ACTVCODE": ["actv_code_id", "parent_actv_code_id", "actv_code_type_id", "actv_code_name", "short_name",
                 "seq_num", "color", "total_assignments"],
    "TASKACTV": ["task_id", "actv_code_type_id", "actv_code_id", "proj_id"],
}
TABLE_ORDER = ["PROJECT", "CALENDAR", "PROJWBS", "ACTVTYPE", "ACTVCODE", "TASK", "TASKPRED", "TASKACTV"]


def guid(seed: str) -> str:
    import base64
    return base64.b64encode(hashlib.md5(seed.encode()).digest()).decode()[:22]


def fmt_num(v) -> str:
    if v is None or v == "":
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:.2f}"


def write_xer(tables: dict[str, list[dict]], path: pathlib.Path, export_date: dt.date, user: str = "dop.planner"):
    lines = ["\t".join(["ERMHDR", "19.12", export_date.isoformat(), "Project", user, user,
                        "dbxDatabaseNoName", "Project Management", "USD"])]
    for t in TABLE_ORDER:
        if t not in tables:
            continue
        fields = FIELDS[t]
        lines.append("%T\t" + t)
        lines.append("%F\t" + "\t".join(fields))
        for row in tables[t]:
            vals = []
            for f in fields:
                v = row.get(f, "")
                v = "" if v is None else str(v)
                if "\t" in v or "\n" in v:
                    raise ValueError(f"illegal character in {t}.{f}")
                vals.append(v)
            lines.append("%R\t" + "\t".join(vals))
    lines.append("%E")
    data = ("\r\n".join(lines) + "\r\n").encode(ENCODING)
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------------- parser
def parse_xer(source) -> dict[str, list[dict[str, str]]]:
    """Generic XER parser: returns {table: [row dicts of strings]} for every table in the file."""
    if isinstance(source, (str, pathlib.Path)) and pathlib.Path(source).exists():
        text = pathlib.Path(source).read_bytes().decode(ENCODING)
    elif isinstance(source, bytes):
        text = source.decode(ENCODING)
    else:
        text = str(source)
    tables: dict[str, list[dict]] = OrderedDict()
    header = None
    cur, fields = None, None
    for raw in text.splitlines():
        if not raw:
            continue
        parts = raw.split("\t")
        tag = parts[0]
        if tag == "ERMHDR":
            header = parts
        elif tag == "%T":
            cur = parts[1]
            tables[cur] = []
        elif tag == "%F":
            fields = parts[1:]
        elif tag == "%R":
            vals = parts[1:] + [""] * (len(fields) - len(parts) + 1)
            tables[cur].append(dict(zip(fields, vals)))
        elif tag == "%E":
            break
    if header is None:
        raise ValueError("not an XER file: missing ERMHDR")
    tables["_header"] = [{"version": header[1], "export_date": header[2]}]
    return tables


def typed(value: str, field: str):
    """Typed conversion by P6 field-name convention."""
    if value == "":
        return None
    if field.endswith("_date") or field.endswith("_date2"):
        return dt.datetime.strptime(value[:16], "%Y-%m-%d %H:%M")
    if field.endswith("_hr_cnt") or field.endswith("_pct") or field.endswith("_qty") or field.endswith("_cnt"):
        return float(value)
    if field.endswith("_id") or field in ("seq_num", "fy_start_month_num", "priority_num"):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def to_frames(tables: dict[str, list[dict]]):
    """Convert parsed tables to typed pandas DataFrames."""
    import pandas as pd
    out = {}
    for t, rows in tables.items():
        if t.startswith("_"):
            continue
        cols = FIELDS.get(t, list(rows[0].keys()) if rows else [])
        out[t] = pd.DataFrame({c: pd.Series([typed(r.get(c, ""), c) for r in rows], dtype=object) for c in cols})
    return out


def hours_to_days(hours, clndr_id, calendars_df) -> float | None:
    """Convert hours to days using the activity calendar's day_hr_cnt (P6 display convention)."""
    if hours is None:
        return None
    day = float(calendars_df.set_index("clndr_id").loc[clndr_id, "day_hr_cnt"])
    return hours / day


def sha256_file(path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
