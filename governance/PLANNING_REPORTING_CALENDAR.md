# Planning & reporting calendar

**Purpose:** fix when progress is collected, checked, published and decided, so that the steering committee gets a reconciled view within one working week of every data date.

Owner: Programme Controls Manager (PMO). Source of the dates: [`data/registers/reporting_calendar.csv`](../data/registers/reporting_calendar.csv), generated from `REPORTING_STEPS` in [`dop/registers.py`](../dop/registers.py).
Related: [Scheduling framework](SCHEDULING_FRAMEWORK.md) · [RACI](RACI.md) · [Reporting standards](REPORTING_STANDARDS.md) · [Schedule owner playbook](SCHEDULE_OWNER_PLAYBOOK.md)

## 1. Monthly cycle (T-days = working days on the 5-Day Office calendar, Sun-Thu)

| Step | What happens | Responsible | Output / gate |
|---|---|---|---|
| **T-2** | Progress updates due from schedule owners: actual dates, remaining duration, physical %, and new or changed logic with a change ID | Schedule owners (MWC, MEP, ICA, OPR, AAT, FMS, SSY, PMO) | Owner update returns |
| **T0** | Data date and cut-off. The P6 schedule is frozen for the period | Planner | Data date set, at 08:00 on the cut-off day |
| **T+1** | Planner QA: DCMA 14-point and update-discipline checks. Owner queries issued | Planner | Query log; draft DQ score |
| **T+2** | Schedule re-run (F9), XER export (`DOP_UPD_<date>.xer`), pipeline run and reconciliation gate (R01 to R16) | Planner; gate owned by the Programme Controls Manager | Gate PASS, or the run stops (non-zero exit) |
| **T+3** | Dashboard refresh and draft pack. Owners sign off their variances | Planner; schedule owners | `docs/data/dashboard.json`; draft pack |
| **T+4** | Monthly steering committee pack issued | Programme Controls Manager; Programme Director signs off | `DOP_monthly_pack_<date>.pptx`, `DOP_controls_<date>.xlsx` |
| **T+5** | Forum: steering committee | Steering Committee; the Programme Director presents | Decisions logged (D-xx), actions, change approvals (CR-xx) |

Hard rule: **nothing is issued if the reconciliation gate fails.** The planner fixes the cause and re-runs the gate at T+2, and the Programme Controls Manager decides whether the issue date at T+4 slips. The pack is never issued with a "to be confirmed" number.

## 2. Fortnightly cycle

| Step | What happens | Responsible |
|---|---|---|
| T-1 | Progress on critical, near-critical (TF ≤ 10 working days) and look-ahead activities | Schedule owners |
| T0 | Mid-period checkpoint (data date + 14 calendar days) | Planner |
| T+1 | QA on the changed activities, re-run, XER export and reconciliation gate | Planner |
| T+2 | Fortnightly flash issued (6 pages): headline, milestone movement, look-back/look-ahead, critical path status, decisions and escalations, data quality and reconciliation | Programme Controls Manager |
| T+3 | Delivery review with workstream leads | Programme Controls Manager (chair) |

The flash uses the same measures, thresholds and footer as the monthly pack ([Reporting standards](REPORTING_STANDARDS.md)). In this portfolio build both packs come from the monthly XER updates, so `DOP_fortnightly_flash_2026-10-29.pptx` is issued at the 29-Oct-2026 data date. The mid-period checkpoints below are the planned dates for live operation.

## 3. 2026 cut-off and reporting dates (from the reporting calendar)

| Period | Data date | T-2 updates due | T0 cut-off | T+1 QA | T+2 gate | T+3 refresh | T+4 issue | T+5 forum | Mid-period checkpoint |
|---|---|---|---|---|---|---|---|---|---|
| S1 | 28-May-2026 | 24-May | 31-May ¹ | 01-Jun | 02-Jun | 03-Jun | 04-Jun | 07-Jun | 11-Jun |
| S2 | 25-Jun-2026 | 23-Jun | 25-Jun | 28-Jun | 29-Jun | 30-Jun | 01-Jul | 02-Jul | 09-Jul |
| S3 (BL1) | 30-Jul-2026 | 28-Jul | 30-Jul | 02-Aug | 03-Aug | 04-Aug | 05-Aug | 06-Aug | 13-Aug |
| S4 | 27-Aug-2026 | 25-Aug | 27-Aug | 30-Aug | 31-Aug | 01-Sep | 02-Sep | 03-Sep | 10-Sep |
| S5 | 24-Sep-2026 | 21-Sep | 24-Sep | 27-Sep | 28-Sep | 29-Sep | 30-Sep | 01-Oct | 08-Oct |
| S6 | 29-Oct-2026 | 27-Oct | 29-Oct | 01-Nov | 02-Nov | 03-Nov | 04-Nov | 05-Nov | 12-Nov |
| S7 (planned) | 26-Nov-2026 | 24-Nov | 26-Nov | 29-Nov | 30-Nov | 01-Dec | 02-Dec | 03-Dec | 10-Dec |

¹ 28-May-2026 fell inside the 26 to 30 May public-holiday block, so the office-calendar T0 rolled to 31-May while the schedule kept a 28-May data date. Check U08 flagged the mismatch, which is why S1 fails U08. **Rule from S2 onwards:** when the last Thursday is a holiday, the cut-off moves to the last office working day before the holiday, and the calendar is re-issued at least one month ahead.

S7 is planned and not yet in the data. Its T0 is the need-by date of decision D-08 (26-Nov-2026), so the D-07 and D-08 outcomes will appear in the S7 update.

## 4. Decision timing against the calendar

| Decision | Owner | Needed by | Forum |
|---|---|---|---|
| D-07 Approve zone-based parallel commissioning of the arena (Recovery A) | Programme Director | 12-Nov-2026 | Out of forum, by the S6 mid-period checkpoint. The delivery review that follows (T+3) records it |
| D-08 Approve phased handover with early operator access (Recovery B) | Steering Committee | 26-Nov-2026 | Out-of-cycle session or written resolution by the S7 cut-off. The next scheduled forum (03-Dec-2026) is too late |
| D-09 Remove the Mandatory Finish on the boulevard authority inspection | Programme Controls Manager | 15-Oct-2026 (overdue) | Overdue, so escalated to the Programme Director. Close before the S7 cut-off |

## 5. Rules

- Updates that arrive after T-2 go into the next period, unless the planner accepts them before T0.
- Every period produces one XER per data date. The file's SHA-256 is shown in the dashboard header and on every pack footer (control R15).
- A missed step is escalated the same day to the Programme Controls Manager, and it is recorded in the delivery review.
