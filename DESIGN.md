# DESIGN: Destination Opening Programme (DOP) schedule intelligence

Goal: one decision-ready view of programme delivery. A P6-format integrated master schedule (IMS), built and
scheduled by a transparent CPM engine. A Python pipeline turns it into a reconciled star schema, then into a web
dashboard, a Power BI model and executive PowerPoint packs. All data is fictional.

Related documents: [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) (the planning decisions behind this design),
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) (one definition per measure), [POWERBI.md](POWERBI.md) (Power BI build)
and the [governance pack](governance/).

---

## 1. Repo layout and commands

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
  generate.py             schedule generation: XER files, registers, truth files
  registers.py            risk / decision / change / interface / scenario registers (fictional)
  truth.py                injected-issue truth files used by the tests
  pipeline/
    load.py               XER intake (parse, hash, baseline in force)
    model.py              star schema builder (dims + facts)
    quality.py            DCMA 14-point + update-discipline checks, DQ score, owner scorecard
    narrative.py          data-driven headline and "so what" sentences
    reconcile.py          reconciliation controls (XER -> model -> dashboard JSON), the gate
    dictionary.py         data dictionary (single source for definitions)
    export.py             CSV, dashboard.json, reconciliation markdown
    excel.py              openpyxl controls workbook per snapshot
    run.py                pipeline orchestration (publishes only after the gate passes)
  pptx_gen.py             monthly + fortnightly executive packs (python-pptx)
  cli.py / __main__.py    CLI
data/xer/                 DOP_BL0.xer, DOP_BL1.xer, DOP_UPD_<yyyy-mm-dd>.xer x6
data/registers/           risk, decision, change, interface, recovery-option and reporting-calendar inputs (not in P6)
data/truth/               truth_<date>.json: injected issues per snapshot, used by tests
output/csv|xlsx|pptx|reports/
docs/                     GitHub Pages site (index.html, data/dashboard.json, downloads/, screenshots/)
governance/               framework, calendar, RACI, standards, playbook
powerbi/                  report theme, DAX measures and the Power BI project
tests/                    pytest
```

Commands:
- `python -m dop generate`: build the fictional IMS (XER exports, registers, truth files).
- `python -m dop pipeline [--near-critical 10]`: parse, model, quality, reconcile, then CSV/JSON/XLSX. Exits
  non-zero, and publishes nothing, if any reconciliation control fails.
- `python -m dop pptx --data-date 2026-10-29 --pack monthly|fortnightly`
- `python -m dop run --all`: generate, pipeline, both packs, copies the downloads, prints the elapsed time.
- `run_all.ps1` and `run_all.sh` wrap `run --all` and the test suite.

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

Size at the latest update: 291 activities, 499 relationships, 39 milestones, 34 interfaces.

Milestones (39): per venue asset (x4): Ready for commissioning (construction complete), Operator site access
(SNET), T&C complete (ICA certificate), Occupancy certificate, Handover to operator, Operator trained & certified,
Asset Day 1 ready (28). PEW: permanent power South loop, permanent power North loop, district cooling available,
transit ready for trial running, enabling works handover (5). PRG: programme notice to proceed, RG1–RG4 readiness
gates and **Day 1 Opening** (6). Day 1 Opening carries a Finish-On-or-Before (`CS_MEOB`) constraint at
**14-Oct-2027**.

Interfaces (giver → receiver, owner, need-by = receiver's planned start in the baseline in force):
power loops → asset pre-commissioning; district cooling → HVAC commissioning; asset RFC → T&C;
T&C complete → handover; occupancy certificate → test events; handover → operational trials;
operator site access → familiarisation; transit ready → destination trial; asset Day 1 ready → RG4.

Activity-ID convention: `<ASSET>-<WS>-<NNNN>` (milestones in the `M` range, e.g. `DAR-TNC-M220`).

## 3. Six-month storyline (data dates are the last Thursday of each month)

| Snapshot | Data date | What happens | Day 1 TF (wd) |
|---|---|---|---|
| BL0 | 30-Apr-2026 | Baseline approved with 22 working days of float on Day 1 against the 14-Oct-2027 target. | +22 |
| S1 | 28-May-2026 | Dune Arena MEP plant (chillers/switchgear) delivery late; 1st fix slow. Float erodes on the arena path. Theme-park ride testing has a Mandatory Start (hard constraint). | +14 |
| S2 | 25-Jun-2026 | Arena MEP slips again; arena becomes the longest path. FOH fit-out starts out of sequence. New scope (acoustic treatment) added outside the baseline. An actual finish is typed after the data date. | +14 |
| S3 | 30-Jul-2026 | **CR-003 approved:** arena zone-based re-sequence plus scope, so **BL1** is created. Open ends and the ride MSO cleaned up at the re-baseline. A completed activity still shows remaining duration. | +8 (vs BL1) |
| S4 | 27-Aug-2026 | Arena T&C compressed (overlaps, shorter durations); North power loop energisation slips (late interface); authority-driven operator access to the arena slips (SNET moved). Stale transit guideway. | +3 |
| S5 | 24-Sep-2026 | Arena fire & life-safety commissioning fails pre-IST; a re-test activity is added outside BL1. **Day 1 forecast passes the target: negative float.** | −14 |
| S6 | 29-Oct-2026 | Contractor adds commissioning crews: partial recovery. Three recovery options modelled by the engine. **Two decisions needed:** approve zone-based parallel commissioning (D-07) and phased handover with early operator access (D-08). | −7 |

At 29-Oct-2026 Day 1 is forecast for 21-Oct-2027. Recovery options (applied to S6 and rescheduled by the engine):
- **A. Commission the arena by zone in parallel**: HVAC, electrical and fire commissioning re-linked SS
  with lags, durations −15 %. Day 1 TF +2.
- **B. Phased handover with early operator access**: arena familiarisation linked from IST start (SS +10 d)
  instead of the occupancy certificate; operator access SNET brought forward. Day 1 TF 0.
- **C. Extra training shifts**: arena training moved to the 7-day calendar, durations −25 %. Day 1 TF −4.
- Combinations: **A+B +8 (recommended)** and A+B+C +9. Each option reports Day 1 impact, float gain, residual
  risk (negative-float and near-critical counts) and the recommendation rule in DESIGN_DECISIONS A16.

## 4. Data model (star schema, CSV for Power BI; same content in dashboard.json)

Seven dimensions and fifteen facts (22 CSV tables in `output/csv/`). Full column definitions are in
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) and [POWERBI.md](POWERBI.md).

| Table | Grain | Key(s) |
|---|---|---|
| dim_snapshot | one per data date (source file, SHA-256, baseline in force, cut-off) | snapshot_id (yyyymmdd) |
| dim_activity | one per activity (union of all snapshots) | activity_id (task_code) |
| dim_wbs | one per WBS node | wbs_id; path, level1..3 |
| dim_code | one per activity code value | code_type, code_value |
| dim_owner | one per owner organisation | owner_code |
| dim_calendar | one per calendar | calendar_id |
| dim_date | one per calendar day 2025-01-01..2028-12-31 | date_key |
| fact_activity_snapshot | activity x snapshot | snapshot_id, activity_id |
| fact_relationship | relationship x snapshot | snapshot_id, pred_id, succ_id, rel_type |
| fact_milestone_trend | milestone x snapshot | snapshot_id, activity_id |
| fact_interface | interface x snapshot | snapshot_id, interface_id |
| fact_readiness | asset x readiness stage x snapshot | snapshot_id, asset_code, stage |
| fact_dcma_check | check x snapshot | snapshot_id, check_id |
| fact_dcma_offender | offending item x check x snapshot | snapshot_id, check_id, item |
| fact_owner_scorecard | owner x snapshot | snapshot_id, owner_code |
| fact_reconciliation | control x snapshot | snapshot_id, control_id |
| fact_snapshot_summary | one per data date (Day 1, floats, DQ, counts) | snapshot_id |
| fact_s_curve | one per month (planned BL0/BL1, forecast, actual) | date |
| fact_risk | risk x snapshot | snapshot_id, risk_id |
| fact_decision | decision | decision_id |
| fact_change | change / baseline record | change_id |
| fact_scenario | recovery scenario (on the latest snapshot) | scenario_id |

## 5. CPM engine design and conventions

- Time = integer hours on a continuous clock. Each calendar maps time to its *work position*
  (cumulative working hours). Start-type dates take the first working moment of a position and
  finish-type dates take the last, as P6 does (a finish is shown at 16:00, the next start at 08:00).
- Forward pass in topological order; backward pass in reverse. All four relationship types are supported,
  with lags in working hours on the **successor's calendar** (a P6 scheduling option; P6's shipped default is
  the predecessor calendar, see DESIGN_DECISIONS A03). Negative lags are allowed.
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
  (an injected issue, detected by check U07).
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

Scoring: a pass scores the full weight. A failed % check scores weight × max(0, 1 − (value − threshold)/threshold).
A failed count check scores weight × max(0, 1 − count/5). Bands: ≥ 85 Good, 70–85 Fair, < 70 Poor.
Owner scorecard: per owner, the share of incomplete activities with no activity-level issue, plus issue counts
by check. N/A checks (D10) score nothing, count nothing and are shown as "–".

## 7. Reconciliation controls (each: source, model, dashboard, delta, pass)

40 controls per data date, 240 across the six updates:

R01 activity count · R02 count by status (x3) · R03 count by asset (x6) · R04 count by workstream (x6) ·
R05 relationship count · R06 milestone count · R07 Day 1 early finish · R08 Day 1 late finish ·
R09 key milestone finish (x13: construction complete and Day 1 ready per venue asset, the four readiness gates
and Day 1) · R10 sum of remaining duration (h) · R11 weighted % complete (duration-weighted) · R12 critical count ·
R13 data date · R14 baseline reference · R15 source file SHA-256 · R16 engine re-schedule of the parsed XER
matches the XER dates (except recorded injections).

Source = raw XER table counts; model = fact tables; dashboard = values recomputed from the written
dashboard.json. Any failure exits non-zero and nothing is published.

## 8. Dashboard tabs (single-file `docs/index.html`)

```
┌ DOP · Data date 29-Oct-2026 · Baseline BL1 · Reconciled ✓ DOP_UPD_2026-10-29.xer (bf4584) · DQ 75 ┐
│ [Data date ▾] [Compare: previous | BL0 | BL1 ▾]  Programme › Dune Arena › T&C › …  [◐ theme]     │
├ Exec | Milestones | Critical path | Interfaces | Risks & Recovery | Quality | Reconciliation | About ┤
│ HEADLINE: Day 1 forecast 21-Oct-2027, 7 wd beyond the 14-Oct target; approving A + B by 26-Nov ... │
│ [Day 1 vs BL0/BL1/prev tiles] [RAG asset x workstream] [Top 3 risks] [Decisions required]          │
│ [S-curve planned vs actual]  "so-what" line under every chart                                       │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
Tabs: 1 Executive Summary · 2 Milestones & Slippage Trend · 3 Critical Path & Look-back/Look-ahead ·
4 Interfaces & Readiness Gap · 5 Risks, Decisions & Recovery · 6 Schedule Quality (DCMA) ·
7 Reconciliation & Lineage · About/Method panel. The activity table, breadcrumb drill-down and detail
drawer are available on every tab. Every title is an action title filled from the data at run time.

## 9. PowerPoint packs

Monthly steering-committee pack (15 slides): 1 cover · 2 executive summary · 3 milestone outlook ·
4 critical path to Day 1 · 5 two-week look-back · 6 two-week look-ahead · 7 trend analysis ·
8 interfaces and readiness gap · 9 top risks · 10 decision log · 11 recovery plan ·
12 change and baseline governance · 13 schedule-quality actions for schedule owners ·
14 appendix A: data lineage, reconciliation and method · 15 appendix B: definitions.

Fortnightly flash (6 slides): headline · milestone movement · look-back and look-ahead · critical path status ·
decisions and escalations · data quality and reconciliation.

Every slide carries an action title written from the data, an owner or ask where one applies, native charts and
tables, and a lineage footer (source file, hash, data date, reconciliation status).

## 10. Power BI

The CSV star schema is the Power BI source. [POWERBI.md](POWERBI.md) gives the model, relationships, DAX measures
(`powerbi/measures.dax`), the page design and the report theme (`powerbi/dop_theme.json`).

## 11. Test plan

Hand-calculated networks: FS chain; SS/FF with lags; SF; constraint producing negative float; multi-calendar;
in-progress with data date; out-of-sequence with retained logic; longest path ≠ TF ≤ 0 because of a constraint;
scenario reschedule; DCMA CP test. Programme invariants for every snapshot. XER round trip (byte-identical rewrite).
Every injected issue detected with zero false positives. The reconciliation gate passes and fails on tampered
inputs. No orphan keys in the star schema. Packs and workbook open with no placeholders. The suite runs in under
2 minutes.
