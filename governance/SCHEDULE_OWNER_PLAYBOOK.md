# Schedule owner playbook

**Purpose:** a coaching guide that lets each schedule owner give a clean update first time, understand every quality flag on the dashboard, and fix and prevent it without waiting for the planner.

Owner: Programme Controls Manager (PMO). Audience: the accountable leads of MWC, MEP, ICA, OPR, PMO, AAT, FMS and SSY, and their planners. Check definitions: `CHECKS` in [`dop/pipeline/quality.py`](../dop/pipeline/quality.py). The dashboard *Quality* tab links each check to its section below.
Related: [Scheduling framework](SCHEDULING_FRAMEWORK.md) · [Planning & reporting calendar](PLANNING_REPORTING_CALENDAR.md) · [RACI](RACI.md) · [Reporting standards](REPORTING_STANDARDS.md)

> **Transparency.** All data is fictional. Primavera P6 was not used: a custom CPM engine produced these schedules following P6 conventions and exported them in genuine XER format. The P6 steps are given as generic menu paths that an owner would follow in a licensed environment.

## 1. Update checklist (due at T-2)

| # | Check before you return your update | Protects |
|---|---|---|
| 1 | Every started activity has an **actual start** before the data date. | D09, U04 |
| 2 | Every finished activity has an **actual finish** before the data date and **zero remaining duration**. | D09, U02, U03 |
| 3 | **Remaining duration** of each in-progress activity is re-estimated, not just reduced by the elapsed time. | U09, D11 |
| 4 | Physical % is entered only after the activity has started. | U04 |
| 5 | No activity started while an FS predecessor is incomplete. If one did, tell the planner. | U01 |
| 6 | New or changed work carries a **change ID** (CR-xx), a predecessor, a successor and Workstream, Asset and Owner codes. | D01, U05, U11 |
| 7 | No constraint added and no lag or lead typed. Ask the planner instead. | D02, D03, D05 |
| 8 | Interface dates that you give are confirmed with the receiver. | Interface gap |
| 9 | Each variance over 5 calendar days against the baseline in force has a one-line reason. | Variance sign-off (T+3) |

## 2. How the DQ score and the owner scorecard work

**DQ score** = 100 × (sum of check scores) / (sum of weights). The weights total 100. A passing check earns its full weight. A failing check earns part of it:

| Kind | Partial score when failing |
|---|---|
| % maximum (D01, D03, D05, D06, D08, D11) | weight × max(0, 1 − (value − threshold) / threshold) |
| count maximum (D02, D07, D09 and all U-checks except U08; U02 and U12 carry weight 0) | weight × max(0, 1 − count / 5) |
| % minimum (D04) | weight × max(0, 1 − (threshold − value) / 10) |
| ratio minimum (D13, D14) | weight × max(0, 1 − (threshold − value) / 0.10) |
| pass/fail (D12, U08) | full weight or 0 |

Bands: **Good** ≥ 85, **Fair** 70 to 85, **Poor** < 70. The score was 75.4 (Fair) at 29-Oct-2026.

**Owner scorecard** (`fact_owner_scorecard`): for each owner code, *Owner DQ* = 100 × (1 − flagged / activities). *Flagged* counts that owner's distinct activities caught by any activity-level check (D01, D05, D06, D07, D08, D09, D11, U01, U03, U04, U05, U06, U07, U09, U11). The scorecard also shows `update_issues` (U01 + U03 + U04 + U05 + U09), `logic_issues` (D01 + D05 + U07) and one count per check. Read `update_issues` and `logic_issues` first, because they measure the owner's own discipline. D06 and D07 flags mostly reflect the network: discuss them, but do not "fix" them. At 29-Oct-2026: FMS 80.0 %, OPR 75.0 %, MEP 71.4 %, ICA 64.3 %, MWC 63.4 %, PMO 59.3 %, SSY 57.9 %, AAT 56.2 %.

## 3. Check-by-check guide

<a id="missing-logic"></a>
### D01 Missing logic (≤ 5 %, weight 10)
| | |
|---|---|
| What it means | An incomplete task or milestone has no predecessor or no successor (an "open end"). |
| Why it matters | Its dates do not drive anything, or nothing drives them. Float is overstated and slippage is hidden. |
| Fix in P6 | Activities window → activity details → *Predecessors* / *Successors* tab → *Assign*. The schedule log (Tools → Schedule → log to file) lists open ends. |
| Prevent | Add the successor when you add the activity. Seen at 29-Oct-2026: `PEW-HOV-3020` (no successor) and `LWP-HOV-3210` (an SNET used instead of the link from `LWP-TNC-M220`). |

<a id="leads"></a>
### D02 Leads (negative lags) (0, weight 6)
| | |
|---|---|
| What it means | A relationship with a negative lag, so the successor starts before its predecessor finishes. |
| Why it matters | It schedules work against an unknown future date and cannot be statused. |
| Fix in P6 | *Predecessors* tab → set *Lag* to 0. Use SS with a positive lag, or split the predecessor. |
| Prevent | Never type a minus in the lag field. Seen: `MTP-HOV-3010 → MTP-HOV-3220` (−3 d) and `PEW-CON-1150 → PEW-TNC-2070` (−5 d). |

<a id="lags"></a>
### D03 Lags (≤ 5 %, weight 4) and U12 Long lags > 20 d (informational)
| | |
|---|---|
| What it means | A relationship with a positive lag. U12 lists lags above 20 working days. |
| Why it matters | A lag is invisible time with no owner and no progress. |
| Fix in P6 | Replace long lags with a real activity, such as curing, procurement or mobilisation, and give it an owner. |
| Prevent | Record the reason for every lag. Seen: `DAR-CON-1040 → DAR-CON-1410` FS +30, `PEW-TNC-2050 → PEW-HOV-3010` FS +30, `PBR-CON-1310 → PBR-CON-1320` FS +25, `DAR-CON-1132 → DAR-CON-1220` SS +30 (CR-003). |

<a id="relationship-types"></a>
### D04 Relationship types (≥ 90 % FS, weight 4) and U10 SF relationships (0, weight 1)
| | |
|---|---|
| What it means | Too few Finish-to-Start links, or any Start-to-Finish links. |
| Why it matters | SS/FF overuse hides sequence. SF reverses cause and effect. |
| Fix in P6 | *Predecessors* tab → *Relationship type*. Model SF as FS from the real driver. |
| Prevent | FS by default. Use SS/FF only as a pair, for a genuine overlap. Seen: `LWP-OTE-5020 → LWP-OTE-5110` SF and `PEW-OTE-5010 → PEW-OTE-5020` SF +5. |

<a id="hard-constraints"></a>
### D05 Hard constraints (≤ 5 %, weight 8)
| | |
|---|---|
| What it means | Mandatory Start/Finish, Start On, Finish On, SNLT or FNLT on an incomplete activity. The Day 1 Finish-On-or-Before is counted but allowed. |
| Why it matters | It overrides logic, so the forecast looks on time while the logic says it is late. |
| Fix in P6 | Activity details → *Status* tab → *Primary/Secondary constraint* → set to None. Restore the logic, then re-run (F9). |
| Prevent | Ask the planner for a target milestone instead. Seen: `PBR-HOV-3110` Mandatory Finish (risk R-08, decision D-09 overdue). `MTP-TNC-2140` was removed at BL1. |

<a id="high-float"></a>
### D06 High float > 44 d (≤ 5 %, weight 5)
| | |
|---|---|
| What it means | Total float above 44 working days. |
| Why it matters | It usually means a missing successor. The work looks free to slip when it is not. |
| Fix in P6 | Group by total float, then trace successors (*Trace logic*). Add the missing link to the real receiver. |
| Prevent | Link every deliverable to its user. 22.3 % at 29-Oct-2026. |

<a id="negative-float"></a>
### D07 Negative float (0, weight 10)
| | |
|---|---|
| What it means | The forecast passes a constraint, here the Day 1 date of 14-Oct-2027. |
| Why it matters | It is the forecast telling you Day 1 is late: 36 incomplete activities at 29-Oct-2026 (38 when the two LOEs are counted, as on the dashboard summary), and Day 1 at −7 d. |
| Fix in P6 | Do not delete logic or the Day 1 constraint. Use the *longest path* filter to find the drivers and propose recovery (logic, duration or resources) to the Programme Controls Manager. |
| Prevent | Report a slip early through the risk register. Recovery A + B is modelled at +8 d. |

<a id="high-duration"></a>
### D08 High duration > 44 d (≤ 5 %, weight 5)
| | |
|---|---|
| What it means | A normal task with an original duration above 44 working days (about two months). |
| Why it matters | It cannot be statused reliably, and it hides the path inside it. |
| Fix in P6 | Split it by zone, level or system, then link the parts. |
| Prevent | Plan in steps of 44 days or less. Seen: `PEW-CON-1130` transit guideway (100 d). |

<a id="invalid-dates"></a>
### D09 Invalid dates (0, weight 10) and U02 Actuals after data date
| | |
|---|---|
| What it means | An actual date after the data date, or a forecast date before it. |
| Why it matters | It reports something that has not happened, or work in the past. |
| Fix in P6 | *Status* tab → correct the actual date. Re-run (F9) so forecasts move to the data date. |
| Prevent | Never type early dates, and always re-run before you export. Seen: `DAR-CON-1030` actual finish typed after the 25-Jun-2026 data date; `PBR-CON-1132` forecast before the 27-Aug-2026 data date. |

<a id="resources"></a>
### D10 Resources (not applicable)
| | |
|---|---|
| What it means | Activities without resources. |
| Why it matters | The IMS is a time-based integration schedule. Resource loading belongs in the contractors' detailed schedules. |
| Fix in P6 | None in the IMS. |
| Prevent | Contractors keep resource-loaded schedules that align with IMS activity IDs. |

<a id="missed-tasks"></a>
### D11 Missed tasks (≤ 5 %, weight 5)
| | |
|---|---|
| What it means | Tasks due by the data date in the baseline in force that are late or not finished. |
| Why it matters | It is a measure of delivery against the plan. 10.2 % at 29-Oct-2026. |
| Fix in P6 | Not a data fix. Status the work honestly and give each miss a reason. |
| Prevent | Use the two-week look-ahead and raise a risk early. |

<a id="critical-path-test"></a>
### D12 Critical path test (pass, weight 6)
| | |
|---|---|
| What it means | Adding 600 working days to a longest-path task must move Day 1 by the same amount. |
| Why it matters | It proves the path is continuous from the data date to Day 1. |
| Fix in P6 | In a what-if copy, add the duration and re-run. If Day 1 does not move, remove the constraint, open end or LOE link that breaks the path. |
| Prevent | Follow the constraint and LOE rules. It passed at 29-Oct-2026. |

<a id="cpli"></a>
### D13 CPLI (≥ 0.95, weight 5)
| | |
|---|---|
| What it means | (critical path length + Day 1 TF) / critical path length. |
| Why it matters | Below 1 means the remaining critical path is longer than the time left to the Day 1 target, so float is negative. It was 0.98 at 29-Oct-2026. |
| Fix in P6 | Recovery, not data. |
| Prevent | Escalate negative float early. |

<a id="bei"></a>
### D14 BEI (≥ 0.95, weight 5)
| | |
|---|---|
| What it means | Tasks completed / tasks due by the data date in the baseline in force. |
| Why it matters | It shows whether the baseline is being executed. It was 0.949 at 29-Oct-2026, a fail. |
| Fix in P6 | Status completions honestly, and recover the missed tasks (D11). |
| Prevent | Use look-ahead planning. |

<a id="out-of-sequence"></a>
### U01 Out-of-sequence progress (0, weight 4)
| | |
|---|---|
| What it means | An activity started while an FS predecessor was incomplete, or an SS predecessor had not started. |
| Why it matters | The logic is wrong, or the actuals are. Under retained logic the remaining work waits. |
| Fix in P6 | Correct the actual date, or with the planner change the link (for example to SS with a lag). The schedule log lists out-of-sequence activities. |
| Prevent | Agree a sequence change before starting work. Seen: `DAR-CON-1112` started 13-Jun-2026 (S2). |

<a id="remaining-on-complete"></a>
### U03 Remaining duration on completed (0, weight 2)
| | |
|---|---|
| What it means | A finished activity still carries remaining duration. |
| Why it matters | Remaining-work totals and control R10 are overstated. |
| Fix in P6 | *Status* tab → tick *Finished*. Remaining duration goes to 0. |
| Prevent | Do not edit remaining duration on finished work. Seen: `LWP-CON-1030` with 16 h (S3). |

<a id="progress-without-start"></a>
### U04 Progress without actual start (0, weight 2)
| | |
|---|---|
| What it means | Physical % or consumed duration with no actual start. |
| Why it matters | The progress cannot be trusted or dated. |
| Fix in P6 | Tick *Started* and enter the actual start, or clear the %. |
| Prevent | Enter the start first, then the %. Seen: `PBR-CON-1140` (S4). |

<a id="missing-codes"></a>
### U05 Missing activity codes (0, weight 2)
| | |
|---|---|
| What it means | Workstream, Asset or Owner code is blank. |
| Why it matters | The activity drops out of the owner, asset and RAG views, and shows as UNASSIGNED. |
| Fix in P6 | Activity details → *Codes* tab → *Assign*. Use Global Change to fill codes in bulk. |
| Prevent | Copy a coded activity rather than create a blank one. Seen: `PBR-OTE-5030` (Workstream, until S5) and `PEW-CON-1170` (Owner, until S3). |

<a id="duplicate-names"></a>
### U06 Duplicate names (0, weight 1)
| | |
|---|---|
| What it means | Two activities share a name within the same asset. |
| Why it matters | Updates and reports become ambiguous. |
| Fix in P6 | *General* tab → add a qualifier, such as a zone, level or loop. |
| Prevent | Name every activity as verb + object + location. Seen: `PEW-CON-1030` / `PEW-CON-1040` "HV cabling". The fix is "HV cabling - South loop" and "HV cabling - North loop". |

<a id="loe"></a>
### U07 LOE driving work / critical (0, weight 1)
| | |
|---|---|
| What it means | A level-of-effort activity has successors, is on the longest path, or has TF ≤ 0. |
| Why it matters | Supervision then "drives" delivery, which distorts the critical path. |
| Fix in P6 | Remove the LOE's successors. Link it SS from its first activity and FF from its last. |
| Prevent | An LOE never drives a successor. Seen: `DAR-CON-9010 → DAR-TNC-2210`, which Recovery A corrects. `PRG-D1R-9010` has no successor. It is flagged because it spans to Day 1 and carries −5 d float, so confirm that it drives nothing and record the flag as accepted. |

<a id="data-date"></a>
### U08 Data date matches cut-off (pass, weight 1)
| | |
|---|---|
| What it means | The project data date equals the T0 cut-off in the reporting calendar. |
| Why it matters | It keeps periods comparable and makes the look-back valid. |
| Fix in P6 | Tools → Schedule (F9) → set *Current data date* to the T0 date. |
| Prevent | Check the [calendar](PLANNING_REPORTING_CALENDAR.md). S1 failed this check: the 28-May-2026 data date fell in the holiday block, and the cut-off rolled to 31-May. |

<a id="stale"></a>
### U09 Stale in-progress (0, weight 2)
| | |
|---|---|
| What it means | An activity in progress in both periods with no change in remaining duration or %. |
| Why it matters | Either the update was skipped or the work has stalled. Either way, the forecast is unreliable. |
| Fix in P6 | Re-estimate remaining duration. If the work is stopped, record suspend and resume dates on the *Status* tab, with a reason. |
| Prevent | Touch every in-progress activity each period. Seen: `PEW-CON-1110` in S4 and S5. |

<a id="baseline"></a>
### U11 Missing from baseline (0, weight 1)
| | |
|---|---|
| What it means | The activity is not in the baseline in force. |
| Why it matters | It is unapproved or newly approved scope, and it has no baseline to measure variance against. |
| Fix in P6 | Add it only with a CR ID. It is included at the next approved re-baseline (Project → Maintain/Assign Baselines). |
| Prevent | Follow the [change procedure](SCHEDULING_FRAMEWORK.md#7-baseline-and-change-procedure). Seen: `DAR-CON-1240` (CR-002, S2) and `DAR-CON-1250` (CR-005, S5 onwards). |

## 4. Common mistakes

| Mistake | Effect | Instead |
|---|---|---|
| Moving a date by adding a constraint | Hides slippage (D05) | Fix the logic and report the float |
| Deleting a link to "remove" negative float | Breaks the path (D01, D12) | Propose recovery |
| Reducing remaining duration by the elapsed days only | Stale forecast (U09, D11) | Re-estimate the work left |
| Exporting without re-running (F9) | Invalid dates (D09) | Re-run, then export |
| Adding scope without a CR ID | U11 flag, and an unexplained variance | Raise a change request |

## 5. Capability-transfer path

| Session | Content | Exit test |
|---|---|---|
| 1 (60 min) | This checklist and statusing on the *Status* tab | A clean T-2 update with no U-flags |
| 2 (60 min) | Logic, constraints and lags (D01 to D05) | Owner logic_issues = 0 |
| 3 (45 min) | Reading the dashboard: float, the longest path, interface gaps | The owner explains their RAG at the delivery review |
| 4 (ongoing) | Monthly scorecard review with the planner | Owner DQ ≥ 85 % for two periods |
