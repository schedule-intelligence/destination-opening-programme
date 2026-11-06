# FINAL REPORT: Destination Opening Programme schedule intelligence

## Links

- **Live dashboard:** https://schedule-intelligence.github.io/destination-opening-programme/
- **Repository:** https://github.com/schedule-intelligence/destination-opening-programme
- Pages status at hand-over: PAGES_STATUS

## What was built

| Phase | Deliverable | Result |
|---|---|---|
| 1 | Fictional integrated master schedule: 5 assets plus a programme node, 6 workstreams, 8 owner organisations, 3 calendars, 289–291 activities, 39 milestones, 34 interfaces, FS/SS/FF/SF logic, constraints, LOE | `dop/programme.py`, `dop/storyline.py` |
| 1 | CPM engine: forward/backward pass in working time, per-activity calendars, lags, 8 constraint types, data date, retained logic, TF/FF, critical vs longest path, LOE, DCMA critical-path test, scenarios | `dop/cpm.py`, 18 hand-calculated tests |
| 1 | Six monthly updates (28-May to 29-Oct-2026) plus BL0 and BL1 as real-structure P6 XER files, with truth files for the injected quality issues | `data/xer/`, `data/truth/` |
| 2 | Generic XER parser → star schema (7 dims, 15 facts) → DCMA 14 + 12 update-discipline checks → DQ score and owner scorecard → recovery scenarios → reconciliation gate (40 controls × 6 data dates, XER = model = JSON, exits non-zero on failure) | `dop/pipeline/`, `output/csv/`, `output/reports/`, `output/xlsx/` |
| 3 | Single-file web dashboard: data-date and compare-to selectors, drill-down breadcrumb, activity drawer, 7 tabs plus About, light/dark, 360 px, print | `docs/index.html` |
| 4 | Monthly steering-committee pack (15 slides) and fortnightly flash (6 slides): action titles, owners, asks, native charts, lineage footers | `dop/pptx_gen.py`, `docs/downloads/` |
| 5 | Power BI build guide, 96 DAX measures, report theme | `POWERBI.md`, `powerbi/` |
| 6 | Governance and capability transfer: scheduling framework, reporting calendar, RACI, reporting standards, schedule owner playbook | `governance/` |
| 7 | README with screenshots, 2-minute tour, architecture, JD mapping, transparency; MIT licence | `README.md` |

**Storyline (Day 1 total float, working days):** BL0 +22 → S1 +14 → S2 +14 → S3 (BL1, CR-003) +8 → S4 +3 →
S5 −14 → S6 −7. At 29-Oct-2026, Day 1 is forecast for 21-Oct-2027. The recovery options were rescheduled by the
engine: A +2, B 0, C −4, **A+B +8 (recommended)**, A+B+C +9. Decisions D-07 (12-Nov-2026) and D-08 (26-Nov-2026)
are open, and D-09 is overdue.

## Verification (definition of done)

| Item | Evidence |
|---|---|
| `pytest` green | **150 passed in about 22 s** |
| `python -m dop run --all` end to end, prints elapsed time | `[run] all steps complete in 5.7 s` |
| Reconciliation gate passes for all six snapshots | 240/240 controls. Negative tests: a tampered Day 1 date, a dropped activity or relationship, or a tampered hash or baseline each fail the gate, and the pipeline then exits 1 and publishes nothing |
| Every injected issue detected, zero false positives | The offender sets from the parsed XER equal the generator's truth exactly, for all 26 checks × 6 snapshots |
| Engine = P6 output | Re-scheduling every parsed XER reproduces the exported dates, floats and longest-path flags (R16 plus round-trip tests). XER files rewrite byte-identically |
| Dashboard: zero console errors, desktop and 360 px, every data date | Playwright: 144 renders (6 dates × 3 compare modes × 8 tabs), zero console or page errors, no horizontal scroll at 360 px, screenshots in `docs/screenshots/` |
| PPT packs and Excel open, no placeholders | `tests/test_outputs.py` re-opens both packs and the workbook: titles, footers, Owner columns, native charts, no "Click to add" |
| No forbidden names | `scripts/check_forbidden.py` (tracked files, PPTX/XLSX XML, commit log) passes; repo description checked |
| One commit per phase, pushed | 10+ conventional commits on `main` |

## Deviations and blockers (see BLOCKERS.md and ASSUMPTIONS.md)

- **LibreOffice previews (optional):** the silent install did not complete unattended, so there are no slide PNG
  previews. The packs are verified programmatically instead (B02).
- **Power BI:** delivered as a documented build (CSV, DAX, theme). The DAX was checked statically against the CSV
  headers and emulated in pandas, but not executed in Power BI Desktop (B03).
- **Lag calendar:** the engine computes lags on the successor's calendar. This is a P6 scheduling option; P6's
  shipped default is the predecessor calendar. It is documented in ASSUMPTIONS A03 and is a one-line change.
- **Monthly pack is 15 slides,** not 14, because the appendix is split into A (lineage) and B (definitions).
- **Fortnightly flash** uses the latest monthly data date (the data is monthly).
- `run_all.sh` is provided but not executed here, because this machine's Git-Bash has no coreutils (B01).
  `run_all.ps1` and `python -m dop run --all` were executed.

## Tools installed

- Python packages in `.venv` (pinned in `requirements.txt`): numpy 2.1.3, pandas 2.2.3, openpyxl 3.1.5,
  python-pptx 1.0.2, pytest 8.3.4, playwright 1.49.1, plus their dependencies.
- Playwright Chromium headless shell 131.0.6778.33 (`python -m playwright install chromium`).
- Attempted, not installed: LibreOffice via winget. The installer is cached in the user temp folder; nothing was installed.

## Email note to the panel (draft)

> Subject: Destination opening schedule intelligence – follow-up from our conversation
>
> Thank you for the conversation. As promised, here is a working example of the single, decision-ready view we discussed: https://schedule-intelligence.github.io/destination-opening-programme/
> It takes a P6-format integrated master schedule from construction to Day 1 and turns it into a dashboard, a Power BI model and steering-committee packs. Every number reconciles to the source schedule, and DCMA and update-discipline checks show schedule quality by owner.
> The first screen gives the status, the risk and the two decisions needed. A two-minute tour, the governance pack and the code are here: https://github.com/schedule-intelligence/destination-opening-programme
> All data is fictional, and I have been transparent about method and limitations. I would welcome the chance to walk you through it.
