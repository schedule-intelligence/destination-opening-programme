# RACI: planning, controls and reporting

**Purpose:** make it clear who does, who answers for, who is consulted on and who is informed of each planning and reporting activity, so that no update, check or decision waits for an owner.

Owner: Programme Controls Manager (PMO) · Approver: Programme Director.
Related: [Scheduling framework](SCHEDULING_FRAMEWORK.md) · [Planning & reporting calendar](PLANNING_REPORTING_CALENDAR.md) · [Reporting standards](REPORTING_STANDARDS.md) · [Schedule owner playbook](SCHEDULE_OWNER_PLAYBOOK.md)

**R** Responsible (does the work) · **A** Accountable (one per row; signs off) · **C** Consulted (two-way, before) · **I** Informed (one-way, after)

## 1. Roles

| Column | Role (organisation, accountable lead) |
|---|---|
| PLN | Programme planner (PMO planning team) |
| PCM | Programme Controls Manager (PMO) |
| SO | Schedule / workstream owner: the accountable lead of the owner code on the activity |
| MWC | Main Works Contractor (MWC Project Director) |
| MEP | MEP & Systems Contractor (MEP Package Manager) |
| ICA | Independent Commissioning Authority (Lead Commissioning Manager) |
| OPR | Destination Operator (Operator Readiness Lead) |
| AAT | Authority Approvals Team (Approvals Manager) |
| PD | Programme Director |
| SC | Steering Committee (executive sponsors) |

Facilities Management (FMS, FM Mobilisation Manager) and Security & Safety (SSY, Head of Security & Safety) act as **SO** for their own activities, with the same duties as the column SO.

## 2. Matrix

| Activity | PLN | PCM | SO | MWC | MEP | ICA | OPR | AAT | PD | SC |
|---|---|---|---|---|---|---|---|---|---|---|
| Progress update of own activities (T-2) | C | I | **A** | R | R | R | R | R | | |
| Set data date, freeze and re-run (T0, T+2) | R | **A** | I | | | | | | | |
| Schedule QA: DCMA and update-discipline checks (T+1) | R | **A** | C | I | I | I | I | I | | |
| Close owner QA queries | C | I | **A** | R | R | R | R | R | | |
| Logic and constraint changes inside a workstream | R | **A** | C | C | C | C | C | C | | |
| Interface agreement (giver → receiver, need-by date) | R | **A** | C | C | C | C | C | C | I | |
| Change request: raise and assess impact (CR-xx) | R | **A** | R | C | C | C | C | C | I | I |
| Scope change approval within contingency (e.g. CR-002, CR-005) ² | C | R | C | C | C | C | C | | **A** | I |
| Baseline change / re-baseline (BL0 → BL1) | R | R | C | C | C | C | C | C | C | **A** |
| Reconciliation gate (R01 to R16) | R | **A** | | | | | | | I | |
| Dashboard refresh (T+3) | R | **A** | I | I | I | I | I | I | I | I |
| Variance sign-off per owner (T+3) | C | I | **A** | R | R | R | R | R | | |
| Pack sign-off and issue (T+4) | R | R | C | | | | | | **A** | I |
| Recovery options: model and recommend | R | **A** | C | C | C | C | C | C | I | I |
| Decisions delegated to the Programme Director (e.g. D-07) ¹ | I | R | C | C | C | C | C | C | **A** | I |
| Decisions reserved to the Steering Committee (e.g. D-08) ¹ | I | R | C | C | C | C | C | C | R | **A** |
| Readiness gates RG1 to RG3 declaration | R | R | C | C | C | C | C | C | **A** | I |
| RG4 Day 1 go/no-go | R | R | C | C | C | C | C | C | R | **A** |
| Schedule owner coaching and the scorecard | R | **A** | R | I | I | I | I | I | I | |

¹ The decision owner named in the [decision log](../data/registers/decision_log.csv) is the single accountable role for that decision. Examples: D-07 Programme Director (needed 12-Nov-2026), D-08 Steering Committee (26-Nov-2026), D-09 Programme Controls Manager (overdue since 15-Oct-2026). A decision the log delegates to another role, such as D-09, takes that role as **A**.

² A sequence change inside one workstream with no Day 1 loss is approved by the workstream lead instead (section 3, CR-004).

## 3. Delegated approvals (as used in the change register)

| Change type | Approver | Example |
|---|---|---|
| Baseline creation or re-baseline | Steering Committee | CR-001 (BL0), CR-003 (BL1, 23-Jul-2026), CR-006 (pending) |
| Scope within contingency, no re-baseline | Programme Director | CR-002 acoustic treatment; CR-005 smoke-extract works |
| Sequence within one workstream, no Day 1 loss | Workstream lead | CR-004 T&C compression (Lead Commissioning Manager) |
| Constraint or lag exception | Programme Controls Manager | Removal of the Mandatory Finish on `PBR-HOV-3110` (D-09) |

## 4. Rules

| Rule | Detail |
|---|---|
| One A per row | If two roles claim the same row, the Programme Controls Manager raises it at the next delivery review. |
| Owner codes are organisations | Each activity's `OWN` code names the accountable organisation. An activity without an owner shows as `UNASSIGNED` and fails U05. |
| Interfaces | The giver owns the date and the receiver owns the need-by date. Both sign off the giver → receiver milestone pair. |
| Escalation path | Schedule owner → Programme Controls Manager (same working day) → Programme Director (within 3 working days) → Steering Committee (next forum, or out of cycle when a need-by date falls before it). |
| Contractors | MWC and MEP update their own activities and give access to supporting evidence, such as delivery notes, test sheets and inspection records. |
| ICA | Witnesses and certifies T&C milestones (`*-TNC-M220`). Its certificate is the evidence for T&C complete. |
