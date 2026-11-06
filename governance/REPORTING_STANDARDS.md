# Reporting standards

**Purpose:** make every page of the dashboard, the Power BI report and the PowerPoint packs answer three questions in the same way: what is the status, what is at risk, and what decision is needed.

Owner: Programme Controls Manager (PMO) · Approver: Programme Director. Measure names and formulas: [`DATA_DICTIONARY.md`](../DATA_DICTIONARY.md).
Related: [Scheduling framework](SCHEDULING_FRAMEWORK.md) · [Planning & reporting calendar](PLANNING_REPORTING_CALENDAR.md) · [RACI](RACI.md) · [Schedule owner playbook](SCHEDULE_OWNER_PLAYBOOK.md)

## 1. Page standard

| Element | Rule | Example (29-Oct-2026) |
|---|---|---|
| Action title | One full sentence that gives the answer first. It contains a number, a date and a comparison. No topic labels such as "Milestones". | "Day 1 Opening is forecast for 21-Oct-2027, 7 working days beyond the 14-Oct-2027 target; approving recovery A (by 12-Nov-2026) and B (by 26-Nov-2026) brings it to 06-Oct-2027 with +8 wd float." |
| Storyline | Status → cause → risk → decision. The first screen or slide holds the answer, and the detail follows. | Executive summary → milestones → critical path → interfaces → risks & recovery → quality → reconciliation |
| Evidence | One chart or table per message, with its source data date and baseline. | Day 1 trend against BL0 and BL1 |
| So-what line | One sentence under every chart that says what the reader should conclude. | "Dune Arena is the readiness constraint …" |
| Owner | Every issue, risk and ask names an owner role and organisation code. | "MEP Package Manager (MEP)" |
| Ask | Every page that shows a problem ends with the decision or action needed, the owner and the date. | "D-07: Programme Director to approve Recovery A by 12-Nov-2026" |

## 2. Headline rules

| Rule | Do | Do not |
|---|---|---|
| Answer first | "Day 1 is forecast 7 days late" | "This month saw continued pressure on the arena" |
| Numbers | Give the figure and the unit: "-7 wd float", "38 activities with negative float" | "significant slippage" |
| Date | Write the forecast and the target as dates | "slightly after target" |
| Comparison | Compare against the target, the baseline in force and the previous period | A number with nothing to compare it to |
| Neutral tone | Plain verbs: forecast, slipped, recovered, needs | "critical crisis", "great progress" |

## 3. RAG definitions (thresholds as implemented)

Colours: red `#C0392B`, amber `#D68910`, green `#1E8449`. RAG is always shown with a text label as well as the colour.

| Measure | Red | Amber | Green | Source |
|---|---|---|---|---|
| Total float / Day 1 total float | < 0 working days | 0 to 10 working days (near-critical) | > 10 working days | `near_critical_days` = 10 |
| Interface status | Late: giver forecast after the need-by date | At risk: giver forecast less than 7 calendar days before the need-by date | On track (Complete is shown grey) | [Design decision A18](../DESIGN_DECISIONS.md) |
| Risk score (probability × impact) | High ≥ 15 | Medium 8 to 14 | Low < 8 | `dop/pipeline/model.py` |
| DQ score | Poor < 70 | Fair 70 to < 85 | Good ≥ 85 | `BANDS` in `quality.py` |
| Owner DQ | < 70 % | 70 to < 85 % | ≥ 85 % | same bands |
| CPLI / BEI | < 0.95 | n/a | ≥ 0.95 | DCMA D13 / D14 |
| Scenario residual risk | High: Day 1 TF < 0 | Medium: TF < 5 wd, or more than 25 near-critical activities | Low | recovery model |
| Decision | Overdue (open after its need-by date) | Open | Closed | decision log |
| Reconciliation status | Any control fails (nothing is published) | n/a | All controls pass (40/40 at each data date) | `reconcile.py` |

The recommended recovery is the smallest set of options that leaves Day 1 total float of at least +5 working days ([design decision A16](../DESIGN_DECISIONS.md)). At 29-Oct-2026 A alone leaves +2 d and B alone 0 d, so A + B is recommended: it leaves +8 wd (*Float gain* +15 wd).

## 4. Number and date formats

| Item | Format | Example |
|---|---|---|
| Dates | dd-Mmm-yyyy | 21-Oct-2027 |
| Floats and durations | Working days (wd) in the activity calendar, signed, 0 dp | -7 wd float; 37 wd duration |
| Variances (vs BL0, vs BL1, vs previous period, interface gap, readiness gap) | Calendar days (cd), positive = later | Day 1 +15 cd vs BL1 |
| DQ score | 1 dp and the band | 75.4 (Fair) |
| CPLI, BEI | 3 dp (so a 0.949 fail never reads as 0.95) | CPLI 0.980, BEI 0.949 |
| Percentages | 0 dp, or 1 dp for weighted % complete | 92 % FS |
| Counts | Whole numbers with the noun | 38 activities |
| Codes | Activity ID in monospace, followed by the name | `DAR-TNC-M220` T&C complete |

Use the exact measure names from the data dictionary: *Day 1 forecast*, *Day 1 total float*, *Finish variance vs BL1*, *Slip vs previous period*, *Float erosion*, *Interface gap*, *Readiness gap*, *DQ score*, *Owner DQ*, *Reconciliation status*, *Scenario Day 1 impact*, *Float gain*.

## 5. Footer and lineage statement

Every slide carries the footer `Source: DOP P6 XER · data date 29-Oct-2026 · reconciled ✓` and a slide number. The dashboard header and the pack cover add the file name, SHA-256 prefix, baseline in force and DQ score, for example `DOP_UPD_2026-10-29.xer (bf458482) · BL1 · DQ 75.4 (Fair)`.

The appendix of each pack and the dashboard *Reconciliation* tab and *About* panel carry the lineage statement:

> P6 XER export → generic XER parser → CPM re-schedule and quality checks → star schema (`output/csv`) → reconciliation gate (source XER = model = dashboard JSON; the run stops on any failure) → dashboard, Excel controls workbook and PowerPoint packs. All data is fictional. Schedules come from a custom CPM engine that follows Primavera P6 conventions and are exported in P6 XER format; no Primavera P6 licence was used.

## 6. Pack structure

| Pack | Pages | Audience | Issue |
|---|---|---|---|
| Monthly (`DOP_monthly_pack_<date>.pptx`) | 15: cover, executive summary, milestones, critical path, look-back, look-ahead, trend, interfaces & readiness, risks, decisions, recovery, change & baseline, quality, appendix A (lineage) and B (definitions) | Steering Committee | T+4 |
| Fortnightly flash (`DOP_fortnightly_flash_<date>.pptx`) | 6: headline, milestone movement, look-back/look-ahead, critical path status, decisions & escalations, data quality & reconciliation | Delivery review | T+2 of the fortnightly cycle |
| Controls workbook (`DOP_controls_<date>.xlsx`) | Reconciliation, DCMA checks, DCMA offenders, milestone variance, look-ahead, owner scorecard | Planners and schedule owners | T+4, with the monthly pack |

Visual identity (series order): navy `#1F3A5F`, teal `#2B7A78`, ochre `#B7791F`, plum `#8E6C8A` and slate `#64748B` on `#F7F8FA`, in the Segoe UI font. The dashboard, Power BI theme and slides use the same tokens.
