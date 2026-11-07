# One command for the whole pipeline (Windows PowerShell).
# Usage:  .\run_all.ps1            (creates .venv on first run)
$ErrorActionPreference = "Stop"
$env:PIP_NO_INPUT = "1"; $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
}
.\.venv\Scripts\python.exe -m dop run --all
if ($LASTEXITCODE -ne 0) { Write-Error "pipeline failed (reconciliation gate or error)"; exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -m pytest -q
exit $LASTEXITCODE
