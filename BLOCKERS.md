# BLOCKERS

Blockers met during the unattended run, with the workaround that was implemented.

| # | Phase | Blocker | Attempts | Workaround / status |
|---|---|---|---|---|
| B02 | 4 | LibreOffice (optional PPTX → PDF/PNG previews) did not install unattended. `winget install TheDocumentFoundation.LibreOffice --silent` downloaded the installer but never completed; it most likely needs an elevation step that a headless run cannot answer. | 1 (time-boxed at 10 min, exceeded) | No slide PNG previews in the README. The packs are verified programmatically instead: re-opened with python-pptx (slide counts, titles, footer, no placeholders, native charts, Owner columns), plus a geometry check for overlap and overflow (`tests/test_outputs.py`). |
| B03 | 5 | Power BI Desktop is not available, so the DAX and Power Query M have not been executed. | n/a | `scripts/check_dax_columns.py` checks every table and column reference against the CSV headers and the theme JSON. A pandas emulation of the core measures matched `fact_snapshot_summary` for all six updates. |
| B04 | 3 | The forbidden-name checker matched a short token by chance inside compressed PNG bytes. | 1 | The checker now skips binary image and PDF payloads (pixels cannot carry text). It still scans text, JSON, XER, and the XML inside PPTX/XLSX. |
| B01 | Pre-flight | Git-Bash in this environment has no coreutils (`cat`, `mkdir` missing), so bash cannot be used to verify `run_all.sh`. | 1 | All automation runs through PowerShell and Python. `run_all.sh` is provided but only syntax-reviewed, not executed. |
