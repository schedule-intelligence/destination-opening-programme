# dashboard.json: schema (v1.0)

`dashboard.json` is a single self-describing file written by `python -m dop pipeline`. The pipeline
reads it back from disk and reconciles it against the source XER and the model; if any control fails, the
run exits non-zero. All data is fictional.

Conventions: dates are `YYYY-MM-DD`. Floats and durations are **working days** in the activity calendar.
Variances are **calendar days**, positive = later than the reference. Large tables are columnar
(`{"cols": [...], "rows": [[...]]}`).

```
schema_version            "1.0"
meta
  programme               {code, name, project, eps, eps_name}
  generated_utc, synthetic, disclaimer, engine
  day1_id                 "PRG-D1R-M999"      day1_target "2027-10-14"
  near_critical_days      10                  latest      "2026-10-29"
  snapshots[]             {snapshot_id, label (S1..S6), data_date, source_file, sha256, baseline_in_force (BL0|BL1),
                           baseline_file, baseline_sha256, cutoff_expected, is_latest}
  assets{code:name} workstreams{code:name} packages{code:name} owners{code:{name, role}}
  calendars[]             {calendar_id, calendar_name, hours_per_day, ...}
  checks[]                {check_id, check_name, group (DCMA|Update discipline), kind, threshold, weight, definition, playbook}
definitions[]             {measure, definition, formula, source_fields, grain, owner, unit}   (= DATA_DICTIONARY.md)
activities                columnar dim_activity: activity_id, activity_name, activity_type (TT_Task|TT_Mile|TT_FinMile|TT_LOE),
                          is_milestone, calendar_id, wbs_id, wbs_path, asset_code, workstream_code, package_code, owner_code,
                          phase, interface_role (GIVER|RECEIVER|NONE), readiness_gate, first_snapshot_id, in_bl0, in_bl1
wbs[]                     {wbs_id, wbs_code (e.g. DAR.TNC.COM), wbs_name, level (0..3), parent_wbs_id, path}
snapshots{<data_date>}
  summary                 day1_forecast, day1_tf_d, day1_var_bl0_d, day1_var_bl1_d, day1_movement_d, float_erosion_d, dq_score,
                          dq_rating, cpli, bei, critical_count, near_critical_count, longest_path_count, negative_float_count,
                          min_float_d, avg_float_d, activities, complete, in_progress, not_started, baseline, label,
                          reconciled (bool), controls_passed, controls_total
  acts                    columnar fact_activity_snapshot: activity_id, status (TK_NotStart|TK_Active|TK_Complete), pct_duration,
                          pct_physical, orig_dur_d, rem_dur_d, actual_start, actual_finish, start, finish, late_start, late_finish,
                          total_float_d, free_float_d, is_critical, is_near_critical, is_longest_path, bl0_start, bl0_finish,
                          bl1_start, bl1_finish, bl_finish (baseline in force), var_finish_bl0_d, var_finish_bl1_d, var_finish_bl_d,
                          prev_finish, slip_vs_prev_d, lookback_event (start|finish|null), lookback_achieved, lookahead_start,
                          lookahead_finish, lookahead, planned_pct_bl, constraint_type, constraint_date, dq_flags ("D06,U05")
  rels                    columnar: pred, succ, type (FS|SS|FF|SF), lag_d, driving
  milestones[]            activity_id, forecast_finish, bl0_finish, bl1_finish, var_bl0_d, var_bl1_d, movement_vs_prev_d,
                          total_float_d, status, owner_code
  interfaces[]            interface_id, giver_id, receiver_id, description, giver_owner, receiver_owner, giver_asset, receiver_asset,
                          giver_ws, receiver_ws, need_by, giver_forecast, gap_days, status (Complete|Late|At risk|On track), giver_tf_d
  readiness[]             asset_code, stage (Construction complete > T&C complete > Handover to operator > Operator trained >
                          Trials & test events complete > Day 1 ready), activity_id, forecast, baseline, need_by (late finish),
                          gap_d, var_bl_d, span_from_prev_d, status, total_float_d
  dcma[]                  check_id, check_name, group, kind, threshold, weight, value, denominator, count, passed (true|false|null),
                          score, definition, playbook, offenders[] (activity ids or "PRED->SUCC:TYPE")
  dq                      {score, rating}
  owner_scorecard[]       owner_code, activities, incomplete, flagged, owner_dq, update_issues, logic_issues, n_<check>
  risks[]                 risk_id, title, owner_code, probability, impact, score, rating, trend, linked_activities ("A;B"),
                          mitigation, mitigation_owner, schedule_impact_days, min_linked_float_d
  narrative               {headline, messages[], so_what{day1_trend, milestones, critical_path, lookback, lookahead, readiness,
                          interfaces, dq}}
  reconciliation[]        control_id, control, source_value, model_value, dashboard_value, delta, passed
trends
  summary[]               one fact_snapshot_summary row per data date (same fields as snapshots[].summary)
  s_curve[]               {date, planned_bl0, planned_bl1, forecast, actual}   (duration-weighted %, monthly + data dates)
  milestones[]            every milestone x data date (snapshot_id + milestone fields)
decisions[]               decision_id, ask, owner, raised_data_date, needed_by, status (Open|Closed), closed_on, linked_activity,
                          linked_forecast, linked_tf_d, days_to_need, overdue, outcome
changes[]                 change_id, title, reason, change_type, raised_data_date, approver, approval_date, status, baseline_effect,
                          linked_activity, day1_impact_days
scenarios[]               scenario_id (BASE|A|B|C|A+B|A+B+C), name, options, owner, day1_forecast, day1_impact_days, day1_tf_d,
                          float_gain_d, neg_float_count, near_critical_count, recommended, decision, cost, description, residual_risk
lineage[]                 {step, detail}
governance_docs[]         {title, path}  (paths relative to the repo root)
```
