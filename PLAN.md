# PLAN — Destination Opening Programme (DOP) schedule intelligence

Goal: one decision-ready view of programme delivery. A P6-format integrated master schedule (IMS),
built and scheduled by a transparent CPM engine. A Python pipeline turns it into a reconciled star
schema, then into a web dashboard, Power BI guidance and executive PowerPoint packs.
All data is fictional.

---

## 1. Repo layout

```
dop/                      Python package (run with `python -m dop ...`)
  calendars.py            working-time calendars (8 h/day, holidays, work-position arithmetic)
  cpm.py                  CPM engine (forward/backward pass, constraints, data date, retained logic,
                          TF/FF, critical, near-critical, longest path, DCMA CP test, scenarios)
  programme.py            fictional programme definition (assets, workstreams, owners, activities, logic)
  storyline.py            six-month storyline as per-snapshot deltas + injected quality issues
  simulate.py             progress simulation (period-by-period execution, actuals, % complete)
  xer.py                  XER writer + generic XER parser (any table, typed)
  xer_model.py            parsed XER -> engine network (used for the DCMA CP test and re-schedule check)
  generate.py             Phase 1 orchestration: XER files, registers, truth files
  registers.py            risk / decision / change / interface / scenario registers (fictional)
  pipeline/
    model.py              star schema builder (dims + facts)
    quality.py            DCMA 14-point + update-discipline checks, DQ score, owner scorecard
    reconcile.py          reconciliation controls (XER -> model -> dashboard JSON), the gate
    dictionary.py         data dictionary (single source for definitions)
    export.py             CSV, dashboard.json, reconciliation markdown
    excel.py              openpyxl controls workbook per snapshot
  pptx_gen.py             monthly + fortnightly executive packs (python-pptx)
  cli.py / __main__.py    CLI
data/xer/                 DOP_BL0.xer, DOP_BL1.xer, DOP_UPD_<yyyy-mm-dd>.xer x6
data/registers/           risk, decision, change, interface, scenario CSVs (inputs, not in P6)
data/truth/               truth_<date>.json: injected issues per snapshot, used by tests
output/csv|xlsx|pptx|reports/
docs/                     GitHub Pages site (index.html, data/dashboard.json, downloads/, screenshots/)
governance/               framework, calendar, RACI, standards, playbook
powerbi/                  dop_theme.json, measures.dax
tests/                    pytest
```

CLI:
- `python -m dop generate`: Phase 1 (XER + registers + truth).
- `python -m dop pipeline`: Phase 2 (parse, model, quality, reconcile, CSV/JSON/XLSX). Exits non-zero if
  any reconciliation control fails.
- `python -m dop pptx --data-date 2026-10-29 --pack monthly|fortnightly`
- `python -m dop run --all`: generate, pipeline, both packs, copies downloads, prints elapsed time.
- `run_all.ps1` and `run_all.sh` wrap `run --all`.

Tests (`tests/`): `test_calendars.py`, `test_cpm_small.py` (hand-calculated networks),
`test_cpm_programme.py` (invariants on all snapshots), `test_xer_roundtrip.py`,
`test_quality_truth.py` (every injected issue detected, zero false positives),
`test_reconciliation.py` (gate passes; tampered JSON fails), `test_model_integrity.py` (no orphan keys),
`test_outputs.py` (pptx/xlsx open, no placeholders). The suite must run in under 2 minutes.

## 2. Fictional programme design

Programme **Destination Opening Programme (DOP)**. EPS `DOP` > project `DOP-IMS` (a single P6 project:
the integrated master schedule). WBS L1 = asset, L2 = workstream, L3 = package.

| Code | Asset (fictional) | Character |
|---|---|---|
| MTP | Mesa Theme Park | long ride-system installation and testing; near-critical |
| LWP | Lagoon Water Park | pools, slides, water treatment; moderate float |
| DAR | Dune Arena | 18k-seat arena; MEP-heavy; becomes the driving path |
| PBR | Palm Boulevard (Retail & Dining) | shell & core plus tenant fit-out waves |
| PEW | Programme Enabling Works | utilities (power, cooling, water), roads, transit link |
| PRG | Programme Integration & Day 1 | readiness gates, destination-wide trials, Day 1 Opening |

Workstreams: CON Construction · TNC Testing & Commissioning · HOV Handover (snagging, authority approvals,
completion/occupancy) · OPM Operator Mobilisation & Training · OTE Operational Trials & Test Events ·
D1R Day 1 Readiness.

Owners (fictional organisations, roles only): MWC Main Works Contractor · MEP MEP & Systems Contractor ·
ICA Independent Commissioning Authority · OPR Destination Operator · PMO Programme Management Office ·
AAT Authority Approvals Team · FMS Facilities Management · SSY Security & Safety.

Calendars (8 h/day, 08:00–16:00, hours stored as in P6):
1. `DOP 6-Day Site (Sat–Thu)`: construction; public-holiday exceptions.
2. `DOP 5-Day Office (Sun–Thu)`: approvals, documentation, recruitment, classroom training; holidays.
3. `DOP 7-Day T&C / Trials`: commissioning, trials, test events; only the two national-day exceptions.

Milestones (38): per venue asset (x4): Ready for Commissioning (construction complete), Operator site
access (SNET), T&C complete, Occupancy certificate, Handover to operator, Operator trained, Asset Day 1
ready (28). PEW: permanent power South loop, permanent power North loop, district cooling available,
transit ready for trial running, enabling handover (5). PRG: RG1–RG4 readiness gates and **Day 1
Opening** (5). Day 1 Opening carries a Finish-On-or-Before (`CS_MEOB`) constraint at **14-Oct-2027**.

Interfaces (giver → receiver, owner, need-by = receiver's planned start in the baseline in force):
power loops → asset pre-commissioning; district cooling → HVAC commissioning; asset RFC → T&C;
T&C complete → handover; occupancy certificate → test events; handover → operational trials;
operator site access → familiarisation; transit ready → destination trial; asset Day 1 ready → RG4.

Activity-ID convention: `<ASSET>-<WS>-<NNNN>` (milestones in the `M` range, e.g. `DAR-TNC-M220`).

## 3. Six-month storyline (data dates are the last Thursday of each month)

| Snapshot | Data date | What happens | Expected Day 1 TF |
|---|---|---|---|
| BL0 | 30-Apr-2026 | Baseline approved. Day 1 forecast about 3 weeks ahead of the 14-Oct-2027 target. | ~+20 d |
| S1 | 28-May-2026 | Dune Arena MEP plant (chillers/switchgear) delivery late; 1st fix slow. Float erodes on the arena path. Theme-park ride testing has a Mandatory Start (hard constraint). | erodes |
| S2 | 25-Jun-2026 | Arena MEP slips again; arena becomes the longest path. FOH fit-out starts out of sequence. New scope (acoustic treatment) added outside the baseline. An actual finish is typed after the data date. | erodes |
| S3 | 30-Jul-2026 | **CR-003 approved:** arena zone-based re-sequence plus scope, so **BL1** is created. Open ends and the ride MSO cleaned up at the re-baseline. A completed activity still shows remaining duration. | reset vs BL1 |
| S4 | 27-Aug-2026 | Arena T&C compressed (overlaps, shorter durations); North power loop energisation slips (late interface); authority-driven operator access to the arena slips (SNET moved). Stale transit guideway. | near zero |
| S5 | 24-Sep-2026 | Arena fire & life-safety commissioning fails pre-IST; a re-test activity is added outside BL1. **Day 1 forecast passes the target: negative float.** | negative |
| S6 | 29-Oct-2026 | Contractor adds commissioning crews: partial recovery. Three recovery options modelled by the engine. **Two decisions needed:** approve zone-based parallel commissioning (D-07) and phased handover with early operator access (D-08). | still negative |

Recovery options (applied to S6 and rescheduled by the engine):
- **A. Commission the arena by zone in parallel**: HVAC, electrical and fire commissioning re-linked SS
  with lags, durations −15 %.
- **B. Phased handover with early operator access**: arena familiarisation linked from IST start (SS +10 d)
  instead of the occupancy certificate; operator access SNET brought forward.
- **C. Extra training shifts**: arena training moved to the 7-day calendar, durations −25 %.
- Combinations A+B and A+B+C. Report Day 1 impact, float gain, residual risk (negative-float and
  near-critical counts), recommendation.

## 4. Data model (star schema, CSV for Power BI; same content in dashboard.json)

| Table | Grain | Key(s) |
|---|---|---|
| dim_snapshot | one per data date | snapshot_id (yyyymmdd) |
| dim_activity | one per activity (union of all snapshots) | activity_id (task_code) |
| dim_wbs | one per WBS node | wbs_id; path, level1..3 |
| dim_code | one per activity code value | code_type, code_value |
| dim_owner | one per owner organisation | owner_code |
| dim_calendar | one per calendar | calendar_id |
| dim_date | one per calendar day 2025-01-01..2028-12-31 | date_key |
| fact_activity_snapshot | activity x snapshot | snapshot_id, activity_id |
| fact_relationship | relationship x snapshot | snapshot_id, pred_id, succ_id, type |
| fact_milestone_trend | milestone x snapshot | snapshot_id, activity_id |
| fact_interface | interface x snapshot | snapshot_id, interface_id |
| fact_dcma_check | check x snapshot | snapshot_id, check_id |
| fact_dcma_offender | offending item x check x snapshot | snapshot_id, check_id, item |
| fact_reconciliation | control x snapshot | snapshot_id, control_id |
| fact_risk | risk x snapshot | snapshot_id, risk_id |
| fact_decision | decision | decision_id |
| fact_change | change / baseline record | change_id |
| fact_scenario | scenario (on the latest snapshot) | scenario_id |
| fact_owner_scorecard | owner x snapshot | snapshot_id, owner_code |

## 5. CPM engine design and conventions

- Time = integer hours on a continuous clock. Each calendar maps time to its *work position*
  (cumulative working hours). Start-type dates take the first working moment of a position and
  finish-type dates take the last, as P6 does (a finish is shown at 16:00, the next start at 08:00).
- Forward pass in topological order; backward pass in reverse. All four relationship types are supported,
  with lags in working hours on the **successor's calendar** (a P6 scheduling option; P6's shipped default is the predecessor calendar, see ASSUMPTIONS A03). Negative lags are allowed.
- Constraints: SNET (`CS_MSOA`), SNLT (`CS_MSOB`), FNET (`CS_MEOA`), FNLT (`CS_MEOB`), Start On (`CS_MSO`),
  Finish On (`CS_MEO`), Mandatory Start (`CS_MANDSTART`), Mandatory Finish (`CS_MANDFIN`).
  ALAP is not used.
- Data date: no remaining work before it. Completed activities keep their actuals and have no float.
  In-progress work: remaining duration starts at max(data date, logic), so with **retained logic**
  out-of-sequence remaining work still waits for unfinished predecessors.
- Open ends (no successor): late finish = project early finish (max EF). Day 1's FNLT caps its late finish,
  which drives negative float back along the path when the forecast passes the target.
- TF = LF − EF in the activity calendar (hours, P6 style); FF = slack to the earliest successor constraint.
  Critical = TF ≤ 0. Near-critical = 0 < TF ≤ threshold (parameter, default 10 working days = 80 h).
  Longest path = trace of driving relationships back from Day 1; this is a separate flag from critical.
- LOE: spans from its SS predecessor's start to its FF predecessor's finish. It does not drive its
  predecessors. It is excluded from logic, duration and float counts unless it drives a successor
  (an injected issue).
- DCMA critical-path test: add 600 working days to a longest-path activity and confirm that Day 1 moves
  by the same amount.

## 6. Quality checks, thresholds and DQ score weights

DCMA 14-point (denominator = incomplete normal tasks and milestones, excluding LOE, unless stated):

| ID | Check | Threshold | Weight |
|---|---|---|---|
| D01 | Missing logic (no pred or no succ; Day 1 excluded) | ≤ 5 % | 10 |
| D02 | Leads (negative lags) | 0 | 6 |
| D03 | Lags (relationships with positive lag) | ≤ 5 % | 4 |
| D04 | FS relationships | ≥ 90 % | 4 |
| D05 | Hard constraints (MSO/MFO/SNLT/FNLT/Start On/Finish On) | ≤ 5 % | 8 |
| D06 | High float (> 44 d) | ≤ 5 % | 5 |
| D07 | Negative float | 0 | 10 |
| D08 | High duration (> 44 d, original) | ≤ 5 % | 5 |
| D09 | Invalid dates (actual > DD, forecast < DD) | 0 | 10 |
| D10 | Resources | N/A (no resources in IMS) | 0 |
| D11 | Missed tasks (baseline finish ≤ DD, not finished on time) | ≤ 5 % | 5 |
| D12 | Critical path test | pass | 6 |
| D13 | CPLI | ≥ 0.95 | 5 |
| D14 | BEI | ≥ 0.95 | 5 |

Update discipline (count-based, threshold 0 unless stated): U01 out-of-sequence progress (4),
U02 actuals after data date (shown in D09 too), U03 remaining duration on completed activities (2),
U04 progress without actual start (2), U05 missing activity codes (2), U06 duplicate names within an
asset (1), U07 LOE on the critical path (1), U08 data date matches the cut-off (1), U09 stale in-progress
activities (2), U10 SF relationships (1), U11 activities missing from the baseline in force (1),
U12 long lags > 20 d (0, informational). Weights sum to 100 (D06 carries 5; U02 carries 0, as D09 already covers it).
A pass scores the full weight. A failed % check scores weight × max(0, 1 − (value − threshold)/threshold).
A failed count check scores weight × max(0, 1 − count/5). Bands: ≥ 85 Good, 70–85 Fair, < 70 Poor.
Owner scorecard: per owner, the share of incomplete activities with no activity-level issue, plus
issue counts by check.

## 7. Reconciliation controls (each: source, model, dashboard, delta, pass)

R01 activity count · R02 count by status (x3) · R03 count by asset · R04 count by workstream ·
R05 relationship count · R06 milestone count · R07 Day 1 early finish · R08 Day 1 late finish ·
R09 key milestone EF (each milestone) · R10 sum of remaining duration (h) · R11 weighted % complete
(duration-weighted) · R12 critical count · R13 data date · R14 baseline reference · R15 source file
SHA-256 · R16 engine re-schedule of the parsed XER matches the XER dates (except recorded injections).
Source = raw XER table counts; model = fact tables; dashboard = values recomputed from the written
dashboard.json. Any failure exits non-zero.

## 8. Dashboard tabs (single-file `docs/index.html`)

```
┌ DOP · Data date 29-Oct-2026 · Baseline BL1 · Reconciled ✓ DOP_UPD_2026-10-29.xer (a1b2c3) · DQ 78 ┐
│ [Data date ▾] [Compare: previous | BL0 | BL1 ▾]  Programme › Dune Arena › T&C › …  [◐ theme]     │
├ Exec | Milestones | Critical path | Interfaces | Risks & Recovery | Quality | Reconciliation | About ┤
│ HEADLINE: Day 1 forecast 22-Oct-2027 is 8 days beyond the 14-Oct target; two decisions recover it.  │
│ [Day 1 vs BL0/BL1/prev tiles] [RAG asset x workstream] [Top 3 risks] [Decisions required]          │
│ [S-curve planned vs actual]  "so-what" line under every chart                                       │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
Tabs: 1 Executive Summary · 2 Milestones & Slippage Trend · 3 Critical Path & Look-back/Look-ahead ·
4 Interfaces & Readiness Gap · 5 Risks, Decisions & Recovery · 6 Schedule Quality (DCMA) ·
7 Reconciliation & Lineage · About/Method panel. The activity table, breadcrumb drill-down and detail
drawer are available on every tab.

## 9. PowerPoint pages (monthly, 14 slides; draft action titles)

1. Cover: DOP Steering Committee, data date, BL1, DQ, reconciled ✓
2. Executive summary: "Day 1 is forecast 8 days late; approving two recovery actions by 26-Nov returns positive float"
3. Milestone outlook: "Arena milestones drive the slip; the other assets hold within their baseline window"
4. Critical path: "The longest path now runs through arena fire & life-safety re-test, IST and handover"
5. Two-week look-back: "x of y planned items delivered; misses are concentrated in arena commissioning"
6. Two-week look-ahead: "z critical activities start in the next 14 days; three need owner confirmation"
7. Trend analysis: "Day 1 has slipped in four of six periods; float erosion has slowed since recovery crews mobilised"
8. Interfaces & readiness gap: "Construction-complete to ready-to-operate takes n days at the arena, more than the plan allows"
9. Top risks: "Five risks threaten Day 1; two have no funded mitigation"
10. Decision log: "Two decisions are needed this month; one overdue item is escalated"
11. Recovery plan: "Options A+B together recover the target; C alone is not enough"
12. Change & baseline governance: "BL1 remains the approved baseline; one change is pending approval"
13. Schedule quality actions: "DQ improved from x to y; three owners must close update-discipline gaps"
14. Appendix: data lineage and definitions

Fortnightly flash (6): headline · milestone movement · look-back/look-ahead · critical path status ·
decisions & escalations · data quality & reconciliation.
Each title is filled from the data at run time; the wording above is the draft pattern.

## 10. Test plan
See §1. Hand-calculated networks: FS chain; SS/FF with lags; SF; constraint producing negative float;
multi-calendar; in-progress with data date; out-of-sequence with retained logic; longest path ≠ TF ≤ 0
because of a constraint; scenario reschedule; DCMA CP test. Programme invariants for every snapshot.

## 11. Commit plan
`chore: scaffold` · `feat(engine): CPM engine, calendars, tests` (WIP) · `feat(data): synthetic IMS,
storyline, XER export` (Phase 1) · `feat(pipeline): ...` (Phase 2) · `feat(dashboard): ...` (Phase 3) ·
`feat(pptx): ...` (Phase 4) · `docs(powerbi): ...` (Phase 5) · `docs(governance): ...` (Phase 6) ·
`docs: README, final report` (Phase 7). Forbidden-name check before every commit.
