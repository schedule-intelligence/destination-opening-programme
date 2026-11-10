"""Check the published Power BI semantic model against the dashboard.

Runs one DAX query through the Power BI REST API (Execute Queries) against the semantic model in the service and
compares the headline measures for a data date with the same numbers in docs/data/dashboard.json, which the
reconciliation gate already proved against the source XER. It closes the last gap in the chain: XER = model =
dashboard = published report.

    python scripts/check_service.py                      # latest data date; a browser window asks you to sign in once
    python scripts/check_service.py --all                # every data date
    python scripts/check_service.py --data-date 2026-09-24
    python scripts/check_service.py --workspace dev      # the Development stage of the deployment pipeline
    python scripts/check_service.py --device-code        # sign in from another device (a code to enter)
    set PBI_TOKEN=<access token>  (or $env:PBI_TOKEN)    # skip the sign-in

Sign-in uses MSAL with Microsoft's public Azure CLI client id, scoped to the Power BI service: the first run opens
the browser, later runs reuse the token cache in output/tmp (git-ignored). `pip install msal` once. Exit code 1 if
any value differs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASHBOARD_JSON = ROOT / "docs" / "data" / "dashboard.json"
TOKEN_CACHE = ROOT / "output" / "tmp" / "pbi_token_cache.json"

# (workspace id, semantic model id) of each stage of the deployment pipeline
STAGES = {
    "prod": ("8cb3bd05-0fc7-4951-8bc2-30a6388484de", "bfce9993-96be-4e91-9bf8-ea8eb16695cc"),  # DOP Schedule Intelligence
    "dev": ("99692985-1efc-4b3c-b0e6-817f0cc57754", "96fe2c10-13c5-4370-9a79-fdf66a12f043"),   # ... [Development]
}
WORKSPACE_ID, DATASET_ID = STAGES["prod"]
API = "https://api.powerbi.com/v1.0/myorg"
SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
AUTHORITY = "https://login.microsoftonline.com/organizations"

# dashboard.json summary field -> measure in powerbi/measures.dax
MEASURES = {
    "day1_forecast": "Day 1 forecast",
    "day1_tf_d": "Day 1 total float",
    "day1_var_bl0_d": "Day 1 variance vs BL0",
    "day1_var_bl1_d": "Day 1 variance vs BL1",
    "day1_movement_d": "Day 1 movement vs previous period",
    "float_erosion_d": "Float erosion",
    "critical_count": "Critical count",
    "near_critical_count": "Near-critical count",
    "negative_float_count": "Negative float count",
    "longest_path_count": "Longest path count",
    "min_float_d": "Total float (min)",
    "activities": "Activities",
    "complete": "Activities complete",
    "in_progress": "Activities in progress",
    "not_started": "Activities not started",
    "dq_score": "DQ score",
    "cpli": "CPLI",
    "bei": "BEI",
    "controls_passed": "Controls passed",
    "controls_total": "Controls total",
}
TOLERANCE = {"dq_score": 0.05, "cpli": 0.005, "bei": 0.0005}


def dax_query(data_date: dt.date) -> str:
    cols = ",\n".join(f'        "{field}", [{measure}]' for field, measure in MEASURES.items())
    return (
        "EVALUATE\nCALCULATETABLE (\n    ROW (\n" + cols + "\n    ),\n"
        f"    dim_snapshot[data_date] = DATE ( {data_date.year}, {data_date.month}, {data_date.day} )\n)"
    )


def get_token(device_code: bool = False) -> str:
    """A token from PBI_TOKEN, the cache, a browser sign-in (default) or a device code."""
    token = os.environ.get("PBI_TOKEN")
    if token:
        return token
    try:
        import msal  # type: ignore
    except ImportError:
        sys.exit("set PBI_TOKEN, or `pip install msal` for the sign-in")
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        cache.deserialize(TOKEN_CACHE.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(AZURE_CLI_CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPE, account=accounts[0])
    if not result and not device_code:
        print("A browser window opens: sign in to Power BI with your work account.", flush=True)
        result = app.acquire_token_interactive(SCOPE, prompt="select_account")
    elif not result:
        flow = app.initiate_device_flow(scopes=SCOPE)
        if "user_code" not in flow:
            sys.exit(f"device flow failed: {flow}")
        print(flow["message"], "(the code is valid for 15 minutes)", flush=True)
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        sys.exit(f"sign-in failed: {result.get('error_description', result)}")
    if cache.has_state_changed:
        TOKEN_CACHE.write_text(cache.serialize(), encoding="utf-8")
    return result["access_token"]


def execute_query(token: str, dax: str, stage: str = "prod") -> dict:
    workspace, dataset = STAGES[stage]
    url = f"{API}/groups/{workspace}/datasets/{dataset}/executeQueries"
    body = json.dumps({"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Execute Queries failed: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:800]}")
    rows = payload["results"][0]["tables"][0]["rows"]
    if len(rows) != 1:
        sys.exit(f"expected one row, got {len(rows)}")
    return {k.strip("[]"): v for k, v in rows[0].items()}


def normalise(field: str, value):
    if field == "day1_forecast":
        return str(value)[:10] if value is not None else None
    return value


def compare(expected: dict, actual: dict) -> list[tuple[str, object, object, bool]]:
    out = []
    for field in MEASURES:
        want = normalise(field, expected.get(field))
        got = normalise(field, actual.get(field))
        if want is None or got is None:
            ok = False  # a value missing on either side is a finding, not agreement
        elif isinstance(want, (int, float)) and isinstance(got, (int, float)):
            ok = abs(float(want) - float(got)) <= TOLERANCE.get(field, 1e-9)
        else:
            ok = want == got
        out.append((field, want, got, ok))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-date", help="YYYY-MM-DD; default: the latest update in dashboard.json")
    ap.add_argument("--all", action="store_true", help="check every data date in dashboard.json")
    ap.add_argument("--workspace", choices=sorted(STAGES), default="prod", help="pipeline stage (default: prod)")
    ap.add_argument("--device-code", action="store_true", help="sign in with a device code instead of the browser")
    ap.add_argument("--print-dax", action="store_true", help="print the DAX query and exit")
    args = ap.parse_args()

    dashboard = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
    dates = sorted(dashboard["snapshots"]) if args.all else [args.data_date or dashboard["meta"]["latest"]]
    for data_date in dates:
        if data_date not in dashboard["snapshots"]:
            sys.exit(f"no snapshot {data_date} in dashboard.json; have {sorted(dashboard['snapshots'])}")
    if args.print_dax:
        print(dax_query(dt.date.fromisoformat(dates[0])))
        return 0

    token = get_token(args.device_code)
    width = max(len(f) for f in MEASURES)
    failed = 0
    for data_date in dates:
        actual = execute_query(token, dax_query(dt.date.fromisoformat(data_date)), args.workspace)
        results = compare(dashboard["snapshots"][data_date]["summary"], actual)
        bad = [r for r in results if not r[3]]
        print(f"Published model ({args.workspace}) vs dashboard.json at {data_date}: "
              f"{len(results) - len(bad)} of {len(results)} values agree")
        for field, want, got, ok in results:
            if not ok or not args.all:
                print(f"  {'ok ' if ok else 'XX '} {field:<{width}}  dashboard {want!s:>12}  service {got!s:>12}")
        failed += bool(bad)
    if args.all:
        print(f"{len(dates) - failed} of {len(dates)} data dates agree")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
