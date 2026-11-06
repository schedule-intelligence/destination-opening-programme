# BLOCKERS

Blockers met during the unattended run, with the workaround that was implemented.

| # | Phase | Blocker | Attempts | Workaround / status |
|---|---|---|---|---|
| B01 | Pre-flight | Git-Bash in this environment has no coreutils (`cat`, `mkdir` missing), so bash cannot be used to verify `run_all.sh`. | 1 | All automation runs through PowerShell and Python. `run_all.sh` is provided but only syntax-reviewed, not executed. |
