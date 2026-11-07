# Scheduling framework

**Purpose:** one set of rules for how the Destination Opening Programme (DOP) integrated master schedule (IMS) is structured, coded, constrained, baselined and statused, so that every update can be compared, checked and trusted.

Owner: Programme Controls Manager (PMO) · Approver: Programme Director · Applies to: every schedule owner who updates `DOP-IMS`.
Related: [Planning & reporting calendar](PLANNING_REPORTING_CALENDAR.md) · [RACI](RACI.md) · [Reporting standards](REPORTING_STANDARDS.md) · [Schedule owner playbook](SCHEDULE_OWNER_PLAYBOOK.md)

> **Transparency.** All names and data are fictional. Primavera P6 was not used: the schedules come from a custom CPM engine ([`dop/cpm.py`](../dop/cpm.py)) that follows P6 conventions, and they are exported in P6 XER format ([`data/xer/`](../data/xer/)). The rules below are written for a live P6 environment, and the engine follows them.

## 1. EPS, WBS and activity codes

| Level | Content | Example |
|---|---|---|
| EPS | `DOP` Destination Opening Programme | one node |
| Project | `DOP-IMS`, a single integrated master schedule | cross-asset interfaces are ordinary relationships |
| WBS L1 | Asset: `MTP` Mesa Theme Park, `LWP` Lagoon Water Park, `DAR` Dune Arena, `PBR` Palm Boulevard (Retail & Dining), `PEW` Programme Enabling Works, `PRG` Programme Integration & Day 1 | `DAR` |
| WBS L2 | Workstream: `CON` Construction, `TNC` Testing & Commissioning, `HOV` Handover, `OPM` Operator Mobilisation & Training, `OTE` Operational Trials & Test Events, `D1R` Day 1 Readiness | `DAR.TNC` |
| WBS L3 | Package, for example `STR`, `MEP`, `FIT`, `SYS`, `PRE`, `COM`, `IST`, `SNG`, `APR`, `HND`, `RCT`, `TRN`, `TRL`, `TEV`, `GAT`, or enabling `PWR`, `CLG`, `WAT`, `RDS`, `TRS`, `ICT` | `DAR.TNC.COM` |

Project-level activity codes are mandatory. A missing Workstream, Asset or Owner code fails check U05.

| Code type | Values | Rule |
|---|---|---|
| Workstream (`WS`) | CON, TNC, HOV, OPM, OTE, D1R | Must match WBS L2 |
| Asset (`AST`) | MTP, LWP, DAR, PBR, PEW, PRG | Must match WBS L1 |
| Owner (`OWN`) | MWC, MEP, ICA, OPR, PMO, AAT, FMS, SSY | One accountable organisation per activity |
| Phase (`PHS`) | P1 Build, P2 Commission, P3 Handover, P4 Prepare to operate, P5 Open | Derived from the workstream |
| Interface (`IFC`) | GIVER, RECEIVER, NONE | Set on the activities in the interface register |
| Readiness Gate (`RG`) | RG1 to RG4 | Only on gate-contributing milestones |

## 2. Activity-ID convention

`<ASSET>-<WS>-<NNNN>`, for example `DAR-CON-1132` (MEP second fix, Zone B).

| Range | Use |
|---|---|
| 1xxx / 2xxx / 3xxx / 4xxx / 5xxx / 6xxx | CON / TNC / HOV / OPM / OTE / D1R tasks |
| `9010` | Level-of-effort (LOE) supervision, for example `DAR-CON-9010` |
| `Mnnn` | Milestones, for example `DAR-TNC-M220` (T&C complete), `PRG-D1R-M999` (Day 1 Opening) |

IDs are never re-used or renumbered. Each name must be unique within an asset (check U06).

## 3. Calendars (8 h/day, 08:00 to 16:00)

| ID | Calendar | Working week | Exceptions | Used for |
|---|---|---|---|---|
| 1 | DOP 6-Day Site (Sat-Thu) | 6 days, 48 h | 31 public-holiday dates (2025 to 2027) | Construction, snagging, site walkdowns |
| 2 | DOP 5-Day Office (Sun-Thu) | 5 days, 40 h | the same 31 dates | Approvals, documentation, recruitment, classroom training, the reporting calendar |
| 3 | DOP 7-Day T&C / Trials | 7 days, 56 h | 3 national days (23-Sep) | Commissioning, familiarisation, trials, test events, gates |

Lags are calculated on the successor's calendar (P6 schedule option *Calendar for scheduling relationship lag* set to the successor activity calendar). Only the Programme Controls Manager may add a holiday exception, and only before the period's cut-off.

## 4. Milestone standards

| Type | Standard | Example |
|---|---|---|
| Asset key milestones (7 per venue) | Ready for commissioning, T&C complete (ICA certificate), Occupancy certificate, Handover to operator, Operator site access, Operator trained, Asset Day 1 ready | `MTP-CON-M142` |
| Interface milestones | Giver → receiver, with giver owner, receiver owner and need-by date. Need-by = the receiver's start in the baseline in force. 34 interfaces (`IF-01` to `IF-34`) | `PEW-TNC-M031` → `DAR-TNC-2010` |
| Readiness gates | RG1 Construction complete (`PRG-D1R-M010`), RG2 T&C complete (`M020`), RG3 Ready to operate (`M030`), RG4 Day 1 go/no-go (`M040`) | Asset milestones feed RG1 to RG3 by FS logic. *Asset Day 1 ready* feeds RG4 through the go/no-go review `PRG-D1R-6010` |
| Day 1 | `PRG-D1R-M999` Day 1 Opening, Finish-On-or-Before 14-Oct-2027 | The only accepted hard constraint |

## 5. Constraint policy

| Rule | Detail |
|---|---|
| Logic first | Every date comes from logic. A constraint is never a substitute for a missing link. |
| Soft constraints only where justified | Start-On-or-After (SNET) is allowed only for a dated external input, such as a notice to proceed, a vendor delivery, the utility energisation window (`PEW-TNC-2030`) or authority-controlled operator access (`DAR-OPM-M120`). Each one needs a reason and an evidence reference. |
| No hard constraints | Mandatory Start/Finish, Start On, Finish On, SNLT and FNLT are not allowed. The one exception is the Day 1 Finish-On-or-Before. |
| Removal | Restore the missing logic, replace the constraint with a target milestone, re-run the schedule (F9) and report the float the constraint was hiding. |
| Live example | `PBR-HOV-3110` carries a Mandatory Finish that masks slippage (risk R-08). Decision D-09 to remove it was needed by 15-Oct-2026 and is overdue. |

## 6. Relationship and lag policy

| Rule | Threshold |
|---|---|
| Finish-to-Start is the default | at least 90 % FS (D04; 92.1 % at 29-Oct-2026) |
| SS/FF only for genuine overlaps, in pairs where possible | for example the zone-based re-sequence under CR-003 |
| No leads (negative lags) | 0 (D02) |
| Lags only for a real waiting time, with the reason documented | at most 5 % of relationships (D03); none above 20 working days (U12, informational) |
| No Start-to-Finish | 0 (U10) |
| LOE never drives work | 0 (U07) |

## 7. Baseline and change procedure

| Step | Rule |
|---|---|
| Baselines | BL0 approved 28-Apr-2026 (CR-001, D-01), data date 30-Apr-2026. BL1 created 30-Jul-2026 after CR-003 was approved on 23-Jul-2026. The baseline in force is stored as `PROJECT.sum_base_proj_id` and checked by control R14. |
| When to re-baseline | Only for an approved scope or sequence change that makes variance against the current baseline meaningless. Otherwise, add the change to the forecast and report variance against the baseline in force (CR-002, CR-004, CR-005). |
| Change register fields | `change_id`, `title`, `reason`, `change_type`, `raised_data_date`, `approver`, `approval_date`, `status`, `baseline_effect`, `linked_activity`, `day1_impact_days` ([register](../data/registers/change_register.csv)) |
| Approval levels | Steering Committee: baseline and Day 1 changes (CR-001, CR-003, CR-006). Programme Director: scope within contingency (CR-002, CR-005). Workstream lead: sequence changes within the workstream (CR-004, approved by the Lead Commissioning Manager). |
| Added activities | New scope is added only with a change ID. Until a re-baseline, it shows in U11 "Missing from baseline" (for example `DAR-CON-1250`, CR-005). |

## 8. Data cut-off and status-date rules

| Rule | Detail |
|---|---|
| Data date | The last Thursday of the month at 08:00. It must equal the T0 cut-off in the [calendar](PLANNING_REPORTING_CALENDAR.md) (U08). If that Thursday is a public holiday, the calendar's holiday rule applies. |
| Actuals | Actual start and finish dates fall before the data date. None are later (D09/U02). |
| Remaining work | Starts on or after the data date. A completed activity has zero remaining duration (U03). |
| Scheduling options | Retained logic, lags on the successor's calendar, total float = late finish − early finish, longest path from driving relationships. Critical = TF ≤ 0. Near-critical = 0 < TF ≤ 10 working days. |
| Freeze | After T0 the period is frozen. Corrections are made in the next period, or by planner re-issue before T+2. |

## 9. Approvals of this framework

The Programme Director approves this framework and its thresholds on the recommendation of the Programme Controls Manager, and it is reviewed at each re-baseline or every six months. The Programme Controls Manager approves constraint and lag exceptions (reviewed at every T+1 QA) and calendar exceptions (reviewed annually and before each cut-off).
