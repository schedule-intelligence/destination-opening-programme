"""Load every XER in data/xer into typed frames plus an activity-level frame per schedule."""
from __future__ import annotations

import datetime as dt
import pathlib
from dataclasses import dataclass

import pandas as pd

from ..xer import parse_xer, sha256_file, to_frames

CODE_TYPE_SHORT = {"Workstream": "WS", "Asset": "AST", "Owner": "OWN", "Phase": "PHS", "Interface": "IFC",
                   "Readiness Gate": "RG"}


@dataclass
class Schedule:
    name: str              # file name
    path: pathlib.Path
    sha256: str
    raw: dict              # parsed string tables (source of truth for reconciliation "source" values)
    fr: dict               # typed frames
    act: pd.DataFrame      # one row per activity (typed, with WBS path and codes)
    rel: pd.DataFrame      # one row per relationship (task codes)
    data_date: dt.datetime
    project: dict


def wbs_paths(projwbs: pd.DataFrame) -> pd.DataFrame:
    by_id = projwbs.set_index("wbs_id")
    rows = []
    for wid, r in by_id.iterrows():
        chain = []
        cur = wid
        while cur is not None and cur in by_id.index:
            chain.append(cur)
            p = by_id.loc[cur, "parent_wbs_id"]
            cur = None if p is None else int(p)
        chain = list(reversed(chain))[1:]  # drop project node
        codes = [by_id.loc[c, "wbs_short_name"] for c in chain]
        names = [by_id.loc[c, "wbs_name"] for c in chain]
        rows.append(dict(wbs_id=wid, wbs_code=".".join(codes) if codes else by_id.loc[wid, "wbs_short_name"],
                         wbs_name=r["wbs_name"], level=len(chain), parent_wbs_id=r["parent_wbs_id"],
                         path=" > ".join(names) if names else r["wbs_name"],
                         level1=codes[0] if len(codes) > 0 else None, level2=codes[1] if len(codes) > 1 else None,
                         level3=codes[2] if len(codes) > 2 else None, proj_node=r["proj_node_flag"] == "Y"))
    return pd.DataFrame(rows)


def load_schedule(path: pathlib.Path) -> Schedule:
    raw = parse_xer(path)
    fr = to_frames(raw)
    task = fr["TASK"].copy()
    wbs = wbs_paths(fr["PROJWBS"])
    task = task.merge(wbs[["wbs_id", "level1", "level2", "level3", "path"]], on="wbs_id", how="left")
    types = dict(zip(fr["ACTVTYPE"]["actv_code_type_id"], fr["ACTVTYPE"]["actv_code_type"]))
    codes = fr["ACTVCODE"].set_index("actv_code_id")
    ta = fr["TASKACTV"].copy()
    ta["ctype"] = [CODE_TYPE_SHORT[types[t]] for t in ta["actv_code_type_id"]]
    ta["cval"] = [codes.loc[c, "short_name"] for c in ta["actv_code_id"]]
    piv = ta.pivot_table(index="task_id", columns="ctype", values="cval", aggfunc="first")
    for c in CODE_TYPE_SHORT.values():
        if c not in piv.columns:
            piv[c] = None
    task = task.merge(piv, left_on="task_id", right_index=True, how="left")
    task = task.astype(object).where(pd.notna(task), None)
    code_of = dict(zip(task["task_id"], task["task_code"]))
    rel = fr["TASKPRED"].copy()
    rel["pred"] = [code_of[x] for x in rel["pred_task_id"]]
    rel["succ"] = [code_of[x] for x in rel["task_id"]]
    rel["type"] = [x.replace("PR_", "") for x in rel["pred_type"]]
    rel["lag_h"] = rel["lag_hr_cnt"].astype(float)
    proj = fr["PROJECT"].iloc[0].to_dict()
    return Schedule(path.name, path, sha256_file(path), raw, fr, task, rel[["pred", "succ", "type", "lag_h"]],
                    proj["last_recalc_date"], proj)


def load_all(root: pathlib.Path) -> tuple[dict[str, Schedule], list[Schedule]]:
    """Returns (baselines by name, updates ordered by data date)."""
    xer_dir = root / "data" / "xer"
    bls = {p.stem.split("_")[1]: load_schedule(p) for p in sorted(xer_dir.glob("DOP_BL*.xer"))}
    ups = sorted((load_schedule(p) for p in xer_dir.glob("DOP_UPD_*.xer")), key=lambda s: s.data_date)
    return bls, ups
