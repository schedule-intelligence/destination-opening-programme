#!/usr/bin/env bash
# One command for the whole pipeline (bash / macOS / Linux / Git-Bash).
# Usage:  ./run_all.sh            (creates .venv on first run)
set -euo pipefail
cd "$(dirname "$0")"
export PIP_NO_INPUT=1 PIP_DISABLE_PIP_VERSION_CHECK=1
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe   # Git-Bash on Windows
"$PY" -m dop run --all
"$PY" -m pytest -q
