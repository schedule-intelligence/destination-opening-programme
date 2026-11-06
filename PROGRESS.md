# PROGRESS

Resume protocol: read this file, ASSUMPTIONS.md and BLOCKERS.md first; continue at the first unchecked item.

| Phase | Status |
|---|---|
| Pre-flight (gh, venv, git init, attrs, ignore) | done |
| 0 Plan (PLAN.md) | done |
| 1 IMS + CPM engine + XER | done: 289–291 activities, 39 milestones, 8 XER files, truth files |
| 2 Pipeline | done: 22 star-schema tables, DCMA + update discipline, DQ score, 240 reconciliation controls (gate), scenarios, XLSX, JSON |
| 3 Dashboard | done: docs/index.html; Playwright 144 renders with zero errors; screenshots |
| 4 PowerPoint | done: monthly (15 slides) and fortnightly (6 slides); LibreOffice previews blocked (B02) |
| 5 Power BI docs | done: POWERBI.md, measures.dax (96 measures), theme; static check passes (B03) |
| 6 Governance pack | done: 5 documents in governance/ |
| 7 README + publish | done: repo public with metadata; Pages configured but deploy blocked on GitHub side (B05) |

Storyline outcome (Day 1 total float, working days): BL0 +22, S1 +14, S2 +14, S3/BL1 +8, S4 +3, S5 −14, S6 −7.
Recovery: A +2, B 0, C −4, A+B +8 (recommended), A+B+C +9.
Tests: 150 passed in about 22 s. `python -m dop run --all` takes about 6 s.

Current sub-step: complete.
Next action (only if resuming): check https://schedule-intelligence.github.io/destination-opening-programme/ ; if still 404, run gh workflow run pages.yml -R schedule-intelligence/destination-opening-programme
