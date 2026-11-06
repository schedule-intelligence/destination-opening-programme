# ASSUMPTIONS

Decisions taken during the unattended build, made the way a senior planning manager would make them.

| # | Decision | Rationale |
|---|---|---|
| A01 | The IMS is one P6 project (`DOP-IMS`) under EPS `DOP`, with WBS L1 = asset. | The brief fixes WBS L1 = asset. One project keeps cross-asset interfaces as ordinary relationships, which is how most giga-project IMSs are scheduled. |
| A02 | 8-hour day, 08:00–16:00, no lunch break. | Keeps hour arithmetic exact. P6 stores hours, so 8 h = 1 day everywhere. |
| A03 | Lags are calculated on the successor's calendar. | This is the P6 default scheduling option. |
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
