# DESIGN DECISIONS

The planning decisions behind this programme model, with the reasoning a planning manager would give a reviewer.
IDs are cited from code comments and the [governance pack](governance/); the design itself is in [DESIGN.md](DESIGN.md).

| # | Decision | Rationale |
|---|---|---|
| A01 | The IMS is one P6 project (`DOP-IMS`) under EPS `DOP`, with WBS L1 = asset. | One project keeps cross-asset interfaces as ordinary relationships, which is how most giga-project IMSs are scheduled. Asset at WBS L1 matches how the steering committee reads the programme. |
| A02 | 8-hour day, 08:00–16:00, no lunch break. | Keeps hour arithmetic exact. P6 stores hours, so 8 h = 1 day everywhere. |
| A03 | Lags are calculated on the successor's calendar (P6 schedule option *Calendar for scheduling relationship lag* = successor). | P6 offers predecessor (its shipped default), successor, 24-hour and project-default calendars. Successor is chosen because most lags here are waiting time owned by the receiving work, for example a lag into T&C runs on the 7-day calendar. Changing the option is a one-line change in `dop/cpm.py`. |
| A04 | Data date = the snapshot date at 08:00. Actuals must be earlier; remaining work starts no earlier. | Matches P6 behaviour when the data date is set to the start of the status day. |
| A05 | Day 1 target 14-Oct-2027 as Finish-On-or-Before (`CS_MEOB`) on the Day 1 milestone. | About 11.5 months after the latest data date, so the critical path is live. FNLT is the standard way to show negative float to a contractual or opening date. |
| A06 | The DCMA hard-constraint count includes the Day 1 FNLT. | It is the DCMA definition. The constraint policy allows it; the truth file labels it intentional. |
| A07 | DCMA "high duration" uses original duration of incomplete normal tasks; LOE is excluded. | Standard DCMA practice. |
| A08 | Duplicate-name check is within an asset (WBS L1). | Repeated standard activity names across assets are good practice. A duplicate within an asset is ambiguous. |
| A09 | "Long lag" = lag > 20 working days. | DCMA sets no threshold, so a planning-manager rule of thumb is used. Reported as informational (weight 0). |
| A10 | Need-by date of an interface = receiver's planned start in the baseline in force. | It is an agreed, fixed date, so the gap does not move with the receiver's own slippage. |
| A11 | Float-derived truth items (negative float, high float, LOE on the critical path, critical counts) are recorded in the truth files from the generator's engine run. The pipeline detects them independently from the XER fields. | Float is emergent from the network, not injected cell by cell. Structural and update-discipline issues are injected explicitly. |
| A12 | Data-integrity injections (forecast before data date, remaining duration on a completed activity, progress without actual start) are applied to exported XER records after scheduling. The truth file lists them, and the re-schedule control R16 excludes them. | P6 itself would correct these on the next F9; they arise when an update is exported without rescheduling. |
| A13 | No resources are loaded. DCMA check 10 is reported N/A with a note. | The IMS is a time-based, level-2/3 integration schedule. |
| A14 | Owners are organisation roles, not named people. Decision owners are roles (e.g. Programme Director). | Keeps all names fictional and neutral. |
| A15 | Percent complete: duration % complete is computed. Physical % is duration % with a seeded ±7 pt deviation for in-progress work, clamped to 1–99. | Gives realistic physical vs duration differences, reproducibly. |
| A16 | Recovery recommendation = the smallest option set that restores at least +5 working days of Day 1 float. | A recovery that lands exactly on the target date carries no contingency; a planning manager asks for margin. |
| A17 | Two-week look-back = activities the previous update forecast to start or finish in the 14 days before the data date. | Updates are monthly, so the previous forecast stands in for the previous fortnight's look-ahead. |
| A18 | Interface status: Late if the giver forecast is after the need-by date; At risk if it is within 7 days of it; otherwise On track. | Gives one week of early warning on every handover. |
| A19 | Planned % complete is linear in working time between the baseline start and finish. Actual % complete is duration-weighted. LOE and milestones are excluded from both. | Standard S-curve practice without resource loading. |
| A20 | Reconciliation control R16 (engine re-schedule = P6 dates) excludes activities flagged by the data-integrity checks (D09/U02/U03/U04) and lists them. | Those records deliberately contain dates P6 would correct on the next F9. |
| A21 | Recovery options are modelled as duration, logic, calendar and constraint deltas on the latest XER and rescheduled by the engine (`data/registers/recovery_options.json`). | Transparent and repeatable. The same deltas could be applied as a what-if P6 project. |
| A22 | The run timestamp in outputs is the real UTC time; everything else is deterministic. | The dashboard header shows when it was generated. Data, XER bytes and hashes are reproducible. |
| A23 | Dashboard links to the governance documents use GitHub blob URLs. | GitHub Pages serves `/docs` only. |
| A24 | Activity-level variances are in calendar days (positive = later); floats and durations are in working days of the activity calendar. | Executives read dates in calendar days; float is a working-time quantity, as in P6. |
