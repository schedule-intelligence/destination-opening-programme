"""Executive PowerPoint packs: monthly steering-committee pack and fortnightly flash.

Every number is read from ``docs/data/dashboard.json`` (the reconciled single source written by the pipeline),
so the packs always tell the same story as the dashboard. Layout is drawn on the blank layout with explicit text
boxes, native tables and native charts: no placeholders, no "click to add" text.

Text fitting: python-pptx cannot measure text, so a conservative character-width model (``text_lines``) sizes
every text box and table row before it is drawn; text that would not fit is shrunk (never below 10 pt) and, as a
last resort, truncated with an ellipsis. Any such truncation in a text box is recorded in ``Deck.warnings``.

Output is deterministic: fixed core properties and fixed zip timestamps (embedded chart workbooks included).
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import pathlib
import re
import zipfile
from collections import Counter

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.chart import XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

# ----------------------------------------------------------------------------------------------- identity
NAVY, TEAL, PLUM, OCHRE, SLATE = "1F3A5F", "2B7A78", "8E6C8A", "B7791F", "64748B"
RED, AMBER, GREEN = "C0392B", "D68910", "1E8449"
BG, SURFACE, BORDER, TEXT, MUTED = "F7F8FA", "FFFFFF", "E2E8F0", "1A202C", "4A5568"
TINT = {"red": "F6D5D1", "amber": "FBE7C6", "green": "D4EDDA", "teal": "E3F0EF", "navy": "E4EAF2"}
FONT = "Segoe UI"

SW, SH = 13.333, 7.5          # 16:9 in inches
ML = 0.5                      # left/right margin
CW = SW - 2 * ML              # content width
TAG_Y, TAG_H, TITLE_Y, TITLE_H, RULE_Y = 0.12, 0.27, 0.40, 1.0, 1.44
BODY_Y, BODY_B = 1.6, 6.15    # content band
ASK_Y, ASK_H = 6.22, 0.64     # "so what" / ask box
FOOT_LINE_Y, FOOT_Y, FOOT_H = 6.95, 7.0, 0.3
GAP = 0.15
WID, WDT, WOW, WNUM = 1.32, 1.07, 0.64, 0.82   # table column widths: activity id, date, owner code, number

LINE = 1.33                   # line height factor (Segoe UI ascent + descent)
PAD_X, PAD_Y = 0.08, 0.04     # text-box insets (in)
CELL_X, CELL_Y = 0.06, 0.025  # table-cell insets (in)

REPO = "https://github.com/schedule-intelligence/destination-opening-programme"
SITE = "https://schedule-intelligence.github.io/destination-opening-programme/"

SHORT_ASSET = {"MTP": "Mesa Theme Park", "LWP": "Lagoon Water Park", "DAR": "Dune Arena",
               "PBR": "Palm Boulevard", "PEW": "Enabling Works", "PRG": "Programme / Day 1"}

ACTION = {
    "D01": "add a predecessor and a successor to every open-ended activity",
    "D02": "replace negative lags (leads) with start-to-start or finish-to-finish logic",
    "D03": "replace lags that model work with explicit activities",
    "D04": "review non finish-to-start relationships",
    "D05": "replace hard constraints with logic or target milestones",
    "D06": "add the missing successor logic that causes the high float",
    "D07": "submit a recovery path for every negative-float activity",
    "D08": "split activities longer than 44 working days",
    "D09": "correct dates that sit on the wrong side of the data date",
    "D11": "re-forecast missed baseline finishes and record the cause",
    "D12": "repair the critical path so a delay flows through to Day 1",
    "D13": "recover Day 1 float to bring CPLI back to 0.95 or better",
    "D14": "close overdue baseline tasks to bring BEI back to 0.95 or better",
    "U01": "correct out-of-sequence progress",
    "U02": "remove actual dates after the data date",
    "U03": "set remaining duration to zero on completed activities",
    "U04": "add actual starts where progress is reported",
    "U05": "assign the missing activity codes",
    "U06": "rename duplicate activity names within the asset",
    "U07": "unlink level-of-effort activities from the driving path",
    "U08": "align the data date with the reporting cut-off",
    "U09": "update stale in-progress activities",
    "U10": "replace start-to-finish relationships with finish-to-start or start-to-start logic",
    "U11": "add new activities to the baseline through change control",
    "U12": "review lags longer than 20 working days",
}


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


# ----------------------------------------------------------------------------------------------- formatting
def _d(s) -> dt.date | None:
    if s is None or s == "":
        return None
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s)[:10])


def fd(s) -> str:
    """dd-Mmm-yyyy, the house date format."""
    d = _d(s)
    return d.strftime("%d-%b-%Y") if d else "–"


def fds(s) -> str:
    d = _d(s)
    return d.strftime("%d-%b") if d else "–"


def sg(n, unit: str = "") -> str:
    """Signed number: +7 / -7 / 0 (variances and float changes)."""
    if n is None:
        return "–"
    n = round(float(n))
    s = f"+{n}" if n > 0 else f"{n}"
    return f"{s} {unit}".strip()


def num(n, unit: str = "") -> str:
    if n is None:
        return "–"
    s = f"{float(n):.0f}" if float(n) == round(float(n)) else f"{float(n):.1f}"
    return f"{s} {unit}".strip()


def pl(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def join_and(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def lc_first(s: str) -> str:
    """Lower-case the first letter for use mid-sentence, leaving acronyms (MEP, BEI, IST) alone."""
    s = str(s)
    return s[0].lower() + s[1:] if len(s) > 1 and s[0].isupper() and s[1].islower() else s


def dqs(v) -> str:
    """DQ score as shown on the dashboard and in the narrative: one decimal, trailing .0 dropped (75.3, 80)."""
    return f"{float(v):.1f}".removesuffix(".0")


def ratio(v, threshold=None) -> str:
    """CPLI/BEI to 2 dp, or 3 dp when 2 dp would hide a miss (0.949 is shown as 0.949, not as a failing 0.95)."""
    if v is None:
        return "–"
    s = f"{float(v):.2f}"
    if threshold is not None and (float(v) < threshold) != (round(float(v), 2) < threshold):
        s = f"{float(v):.3f}"
    return s


def pts(v) -> str:
    """DQ points lost: whole or one decimal, two decimals for fractions below 0.1 (never a misleading 0.0)."""
    v = float(v)
    return f"{v:.2f}" if 0 < v < 0.1 else num(v)


def clean_narr(s: str, ctx: "Ctx | None" = None) -> str:
    """Narrative text from dashboard.json in house units: floats in wd (the narrative writes 'd'), ≤ for <=,
    arrows, and an overdue open decision said as 'overdue since' rather than 'by' a past date. Numbers unchanged."""
    s = str(s).replace("->", "→").replace("<=", "≤").replace(">=", "≥")
    s = re.sub(r"\bfloat ([+-]?\d+) d → ([+-]?\d+) d\b", r"float \1 wd → \2 wd", s)
    s = re.sub(r"\(([+-]?\d+) d float\)", r"(\1 wd float)", s)
    s = re.sub(r"\bTF ≤ (\d+) d\b", r"TF ≤ \1 wd", s)
    s = re.sub(r"(\d) cd\b", r"\1 d", s)               # the pack writes calendar days as d (Appendix B)
    s = re.sub(r"^0 milestones slipped", "No milestone slipped", s)
    if ctx is not None:
        for d in ctx.open_decisions():
            if d["overdue"]:
                s = re.sub(rf"({re.escape(d['decision_id'])}[^;.]*?) by {re.escape(fd(d['needed_by']))}",
                           rf"\1 overdue since {fd(d['needed_by'])}", s)
    return s


def excel_serial(s) -> int:
    return (_d(s) - dt.date(1899, 12, 30)).days


# ----------------------------------------------------------------------------------------------- text fitting
# Advance widths in em (thousandths), the wider of Segoe UI and Arial for each glyph, measured once from the
# font files; used only to estimate wrapping, so no font file is needed at run time.
_GLYPHS = (" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
           "–—·…→✓✗≤≥−•")
_WR = ("027802840392059105560889080002300333033304170684027804000278039005560556055605560556055605560556055605560278"
       "027806840684068405561015066706670722072206670611077807220278050006670556089807480778066707780722066706110722"
       "066709440667066706110302037903020684055603330556058805000589055603130589056602420242050002420861056605860588"
       "0589034805000339056605000723050005000500033402600334068405561000033310001000075007500685068506840406")
_WB = ("027803330493059205750889085002930369036904550707027804040278044305750575057505750575057505750575057505750333"
       "033307070707070706110975072207220722073706670611077807660317055607220611095707900778066707780722066706110723"
       "066710050667066706110369043603690707055603330556062005560619055603830619061102840284055902840916061106110620"
       "0619039805560389061105560797055605560500038903260389070705561000033310001000075007500708070807070422")
W_REG = {ch: int(_WR[4 * i:4 * i + 4]) / 1000 for i, ch in enumerate(_GLYPHS)}
W_BOLD = {ch: int(_WB[4 * i:4 * i + 4]) / 1000 for i, ch in enumerate(_GLYPHS)}
for _W in (W_REG, W_BOLD):     # non-breaking hyphen and space have the same advance as '-' and ' ' in Segoe UI
    _W["‑"], _W[" "] = _W["-"], _W[" "]
SAFETY = 1.06                 # head-room on measured widths
TITLE_HEADROOM = 0.95         # titles must fit two lines in 95 % of the box: renderers and fallback fonts differ

_MON = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_NB_HYPHEN = [re.compile(rf"\b\d{{1,2}}-(?:{_MON})(?:-\d{{2,4}})?\b"),   # 21-Oct-2027, 21-Oct
              re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                      # ISO dates (file names, controls)
              re.compile(r"\b[A-Z]{3}-[A-Z0-9]{3}-[A-Z0-9]{3,4}\b"),     # activity IDs (DAR-CON-1132)
              re.compile(r"\b(?:CR|IF|D|R|DOP)-[A-Z0-9]{2,3}\b")]        # register IDs (D-07, R-03, CR-003, IF-11)
_NB_SPACE = [re.compile(r"(?<=\d) (?=(?:wd|cd|d|pts|days)\b)"),            # 7 wd, +15 d
             re.compile(r"(?<=\b[A-C]) \+ (?=[A-C]\b)"),                 # A + B (+ C)
             re.compile(r"(?<=[A-Za-z]) (?=[A-Z]\b(?![\w‑-]))|(?<=\bDay) (?=1\b)")]  # Zone B, Recovery A, Day 1


_NB_HYPHEN += [re.compile(r"https?://\S+"),                                # URLs never break at their hyphens
               re.compile(r"\b[A-Za-z]+(?:-[A-Za-z]+){2,}\b")]           # Finish-On-or-Before, front-of-house
_NB_SPACE_EXTRA = re.compile(r"(?<=\d) (of|to) (?=[+\-−]?\d)")            # 40 of 40, 0 to 10


def nbh(s: str) -> str:
    """Keep dates, IDs, URLs, compounds, number-unit pairs, ranges and option sets on one line: non-breaking
    hyphens and spaces."""
    s = str(s)
    if "-" in s:
        for rx in _NB_HYPHEN:
            s = rx.sub(lambda m: m.group(0).replace("-", "‑"), s)
    if " of " in s or " to " in s:
        s = _NB_SPACE_EXTRA.sub(lambda m: " " + m.group(1) + " ", s)
    if " " in s:
        s = s.replace(" - ", " – ")          # spaced separator in names: an en dash kept with the word before
        s = _NB_SPACE[0].sub(" ", s)
        s = _NB_SPACE[1].sub(" + ", s)
        s = _NB_SPACE[1].sub(" + ", s)     # second pass for A + B + C (overlapping matches)
        s = _NB_SPACE[2].sub(" ", s)
    return s


def tw(s: str, bold: bool = False) -> float:
    """Width of ``s`` in em."""
    W = W_BOLD if bold else W_REG
    return sum(W.get(ch, 0.7) for ch in s) * SAFETY


def _wrap_runs(runs: list[tuple[str, bool]], max_em: float) -> list[str]:
    """Greedy word wrap of mixed regular/bold runs into lines no wider than ``max_em``."""
    words: list[tuple[str, list[float]]] = []
    cur, cws = "", []
    for text, bold in runs:
        W = W_BOLD if bold else W_REG
        for ch in text:
            if ch in " \n":
                if cur:
                    words.append((cur, cws))
                cur, cws = "", []
                if ch == "\n":
                    words.append(("\n", []))
            else:
                cur += ch
                cws.append(W.get(ch, 0.7) * SAFETY)
    if cur:
        words.append((cur, cws))
    sp = W_REG[" "] * SAFETY
    lines: list[str] = []
    line, lw = "", 0.0
    for w, cw in words:
        ww = sum(cw)
        if w == "\n":
            lines.append(line)
            line, lw = "", 0.0
            continue
        if ww > max_em:                                  # a word longer than the line breaks across lines
            if line:
                lines.append(line)
            line, lw = "", 0.0
            for ch, x in zip(w, cw):
                if lw + x > max_em and line:
                    lines.append(line)
                    line, lw = "", 0.0
                line, lw = line + ch, lw + x
            continue
        if not line:
            line, lw = w, ww
        elif lw + sp + ww <= max_em:
            line, lw = line + " " + w, lw + sp + ww
        else:
            lines.append(line)
            line, lw = w, ww
    lines.append(line)
    return lines


def _max_em(width_in: float, pt: float) -> float:
    return width_in * 72 / pt


def text_lines(text: str, width_in: float, pt: float, bold: bool = False) -> int:
    """Estimated rendered line count of ``text`` in a box of usable width ``width_in`` (inches)."""
    return len(_wrap_runs([(nbh(text), bold)], _max_em(width_in, pt)))


def title_fits(title: str, size: float = 24) -> bool:
    """True if an action title wraps to at most two lines at ``size`` pt, with renderer head-room."""
    return text_lines(title, (CW - 2 * PAD_X) * TITLE_HEADROOM, size, True) <= 2


def first_fit(*candidates: str) -> str:
    """The first candidate title that fits two lines at 24 pt (the last one otherwise)."""
    return next((t for t in candidates if title_fits(t)), candidates[-1])


def fit(text: str, width_in: float, pt: float, lines: int = 1, bold: bool = False) -> str:
    """Truncate ``text`` (with an ellipsis) so that it wraps to at most ``lines`` lines."""
    text = nbh(text)
    mx = _max_em(width_in, pt)
    wrapped = _wrap_runs([(text, bold)], mx)
    if len(wrapped) <= lines:
        return text
    keep = wrapped[:lines]
    last = keep[-1]
    while last and tw(last + "…", bold) > mx:
        last = last[:-1]
    if " " in last and last.rfind(" ") > len(last) * 0.6:      # prefer a word boundary
        last = last[: last.rfind(" ")]
    last = last.rstrip(" ,;:-–·(") + "…"
    return " ".join(keep[:-1] + [last])


def para_height(paras: list[dict], width_in: float, delta: float = 0) -> float:
    h = 0.0
    for p in paras:
        size = max(max(10.0, r["size"] - delta) for r in p["runs"])
        w = width_in - p.get("hang", 0)              # a bulleted paragraph wraps inside its hanging indent
        n = len(_wrap_runs([(r["text"], r["bold"]) for r in p["runs"]], _max_em(w, size)))
        h += n * size * LINE / 72 + p.get("after", 0) / 72
    return h


def R(text, size=12, bold=False, color=TEXT, italic=False, link=None) -> dict:
    return {"text": nbh(text), "size": size, "bold": bold, "color": color, "italic": italic, "link": link}


def P(*runs, align=None, after=0, hang=0) -> dict:
    """A paragraph; ``hang`` > 0 makes it a bullet with a hanging indent of ``hang`` inches."""
    return {"runs": list(runs), "align": align, "after": after, "hang": hang}


def BUL(text, size=12, color=TEXT, after=0) -> dict:
    """A bullet paragraph: a real bullet with a hanging indent, so wrapped lines align with the text."""
    return P(R(text, size, False, color), after=after, hang=round(size * 1.1 / 72, 3))


# ----------------------------------------------------------------------------------------------- data context
class Ctx:
    """Read-only view of dashboard.json for one data date."""

    def __init__(self, root: pathlib.Path, data_date: str):
        self.root = pathlib.Path(root)
        path = self.root / "docs" / "data" / "dashboard.json"
        self.D = json.loads(path.read_text(encoding="utf-8"))
        D = self.D
        self.meta = D["meta"]
        if data_date not in D["snapshots"]:
            raise ValueError(f"data date {data_date} not in dashboard.json (have {sorted(D['snapshots'])})")
        self.dd = data_date
        self.S = D["snapshots"][data_date]
        self.sm = self.S["summary"]
        self.snap = next(s for s in self.meta["snapshots"] if s["data_date"] == data_date)
        dates = sorted(D["snapshots"])
        k = dates.index(data_date)
        self.prev_dd = dates[k - 1] if k else None
        self.is_latest = data_date == self.meta["latest"]
        self.trend = [r for r in D["trends"]["summary"] if r["data_date"] <= data_date]
        self.prev_sm = self.trend[-2] if len(self.trend) > 1 else None
        self.A = {r[0]: dict(zip(D["activities"]["cols"], r)) for r in D["activities"]["rows"]}
        self.acts = [dict(zip(self.S["acts"]["cols"], r)) for r in self.S["acts"]["rows"]]
        self.act = {a["activity_id"]: a for a in self.acts}
        if self.prev_dd:
            P_ = D["snapshots"][self.prev_dd]["acts"]
            self.prev_act = {r[0]: dict(zip(P_["cols"], r)) for r in P_["rows"]}
        else:
            self.prev_act = {}
        self.owners = self.meta["owners"]
        self.role_to_code = {v["role"]: k for k, v in self.owners.items() if k != "UNASSIGNED"}
        self.target = self.meta["day1_target"]
        self.bl = self.sm["baseline"]
        self.reconciled = bool(self.sm.get("reconciled"))
        self.footer = (f"Source: DOP P6 XER · data date {fd(data_date)} · "
                       + ("reconciled ✓" if self.reconciled else "NOT reconciled ✗"))
        raw = self.S["narrative"]
        self.narr = {"headline": clean_narr(raw["headline"], self),
                     "messages": [clean_narr(m, self) for m in raw["messages"]],
                     "so_what": {k: clean_narr(v, self) for k, v in raw["so_what"].items()}}

    # -- lookups
    def name(self, aid: str) -> str:
        return self.A.get(aid, {}).get("activity_name", aid)

    def label(self, aid: str) -> str:
        """'DAR · MEP second fix - Zone C' (asset code plus name, for tables without an id column)."""
        return f"{self.A.get(aid, {}).get('asset_code', '')} · {short_name(self.name(aid))}"

    def id_label(self, aid: str) -> str:
        """'PEW-CON-1040 · HV cabling': the id tells apart activities with the same name and matches the ask text."""
        return f"{aid} · {short_name(self.name(aid))}"

    def owner_of(self, aid: str) -> str:
        return self.A.get(aid, {}).get("owner_code") or "UNASSIGNED"

    def role(self, code: str) -> str:
        return self.owners.get(code, {}).get("role", code)

    def code_for(self, who: str) -> str:
        """Owner code for a role ('Lead Commissioning Manager' -> ICA); bodies such as Steering Committee stay."""
        parts = [p.strip() for p in str(who).split(";") if p.strip()]
        out: list[str] = []
        for p in parts:
            c = self.role_to_code.get(p, p)
            if c not in out:
                out.append(c)
        return "; ".join(out) or "–"

    # -- registers as at the data date
    def decisions(self) -> list[dict]:
        out = []
        for r in self.D["decisions"]:
            if r["raised_data_date"] > self.dd:
                continue
            closed = bool(r["closed_on"]) and r["closed_on"] <= self.dd
            days = (_d(r["needed_by"]) - _d(self.dd)).days
            out.append({**r, "status": "Closed" if closed else "Open", "days_to_need": days,
                        "overdue": (not closed) and days < 0, "outcome": r["outcome"] if closed else ""})
        return out

    def open_decisions(self) -> list[dict]:
        ds = [d for d in self.decisions() if d["status"] == "Open"]
        return sorted(ds, key=lambda d: (not d["overdue"], d["needed_by"]))

    def changes(self) -> list[dict]:
        out = []
        for r in self.D["changes"]:
            if r["raised_data_date"] > self.dd:
                continue
            approved = bool(r["approval_date"]) and r["approval_date"] <= self.dd
            out.append({**r, "status": r["status"] if approved else "Pending"})
        return out

    def scenarios(self) -> list[dict]:
        return self.D["scenarios"] if self.is_latest else []

    def milestones(self) -> list[dict]:
        return self.S["milestones"]

    def incomplete_ms(self) -> list[dict]:
        return [m for m in self.S["milestones"] if m["status"] != "TK_Complete"]

    def var_key(self) -> str:
        return "var_bl1_d" if self.bl == "BL1" else "var_bl0_d"

    def longest_path(self, include_loe=False) -> list[dict]:
        lp = [a for a in self.acts if a["is_longest_path"] and a["status"] != "TK_Complete"]
        if not include_loe:
            lp = [a for a in lp if self.A[a["activity_id"]]["activity_type"] != "TT_LOE"]
        return sorted(lp, key=lambda a: (a["start"] or "", a["finish"] or ""))

    def lp_tasks(self) -> list[dict]:
        return [a for a in self.longest_path() if self.A[a["activity_id"]]["activity_type"] == "TT_Task"]

    def driver_asset(self) -> str | None:
        lp = self.lp_tasks()
        if not lp:
            return None
        c = Counter(self.A[a["activity_id"]]["asset_code"] for a in lp)
        return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def lookback(self) -> list[dict]:
        rows = []
        for a in self.acts:
            ev = a["lookback_event"]
            if not ev:
                continue
            p = self.prev_act.get(a["activity_id"], {})
            planned = p.get("start") if ev == "start" else (p.get("finish") or a["prev_finish"])
            actual = a["actual_start"] if ev == "start" else a["actual_finish"]
            rows.append({**a, "planned": planned, "actual": actual})
        return sorted(rows, key=lambda r: (bool(r["lookback_achieved"]), r["planned"] or ""))

    def lookahead(self) -> list[dict]:
        la = [a for a in self.acts if a["lookahead"]]
        return sorted(la, key=lambda a: (not (a["is_critical"] or a["is_longest_path"]),
                                         a["total_float_d"] if a["total_float_d"] is not None else 999,
                                         a["start"] or ""))

    def rag(self) -> list[dict]:
        """RAG by asset, the dashboard's rule: minimum total float of the asset's incomplete activities;
        Red < 0 wd, Amber 0 to near-critical days, Green above. The driving activity's owner is accountable."""
        nc = self.meta["near_critical_days"]
        out = []
        for code in self.meta["assets"]:
            inc = [a for a in self.acts if self.A[a["activity_id"]]["asset_code"] == code
                   and a["status"] != "TK_Complete" and a["total_float_d"] is not None]
            if not inc:
                out.append({"asset": code, "status": "Complete", "tf": None, "activity_id": None,
                            "why": "All activities complete", "owner": "PMO"})
                continue
            w = min(inc, key=lambda a: (a["total_float_d"], a["activity_id"]))
            tf = w["total_float_d"]
            status = "Red" if tf < 0 else "Amber" if tf <= nc else "Green"
            out.append({"asset": code, "status": status, "tf": tf, "activity_id": w["activity_id"],
                        "why": f"{sg(tf, 'wd')} · {short_name(self.name(w['activity_id']))}",
                        "owner": self.owner_of(w["activity_id"])})
        return out

    def check_owner(self, chk: dict) -> str:
        own = []
        for o in chk.get("offenders") or []:
            aid = o.split("->")[1].split(":")[0] if "->" in o else o
            own.append(self.owner_of(aid))
        if not own:
            return "PMO"
        c = Counter(own)
        return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    def failing_checks(self) -> list[dict]:
        """Checks that fail and cost points; informational checks (weight 0, e.g. U12 long lags) are listed apart."""
        f = [c for c in self.S["dcma"] if c["passed"] is False and c["weight"]]
        return sorted(f, key=lambda c: (-(c["weight"] - c["score"]), -(c["count"] or 0), c["check_id"]))

    def info_checks(self) -> list[dict]:
        return [c for c in self.S["dcma"] if c["passed"] is False and not c["weight"]]

    def offenders_of(self, chk: dict, owner: str) -> int:
        """How many of a check's offending items belong to ``owner`` (a relationship belongs to its successor's
        owner, as in check_owner)."""
        n = 0
        for o in chk.get("offenders") or []:
            aid = o.split("->")[1].split(":")[0] if "->" in o else o
            n += self.owner_of(aid) == owner
        return n

    def who(self, code: str) -> str:
        """Role and code for an ask, without repeating the code when the role already names it
        ('MWC Project Director', not 'MWC Project Director (MWC)')."""
        r = self.role(code)
        return r if code in r.split() else f"{r} ({code})"


def check_result(c: dict) -> str:
    v, t, k = c["value"], c["threshold"], c["kind"]
    if v is None:
        return "n/a"
    if k == "pct_max":
        return f"{v:.1f}% vs ≤ {num(t)}%"
    if k == "pct_min":
        return f"{v:.1f}% vs ≥ {num(t)}%"
    if k == "ratio_min":
        return f"{ratio(v, t)} vs ≥ {t:.2f}"
    if k == "count_max":
        return f"{num(v)} vs ≤ {num(t)}"
    return "pass" if c["passed"] else "fail"


def short_check(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name).strip()


def short_if(desc: str, assets: dict | None = None) -> str:
    """Interface description without the '(construction > T&C)' hand-off note; asset names become codes when
    ``assets`` ({code: name}) is given, so the full hand-off fits a table cell."""
    desc = re.sub(r"\s*\([^)]*>[^)]*\)", "", desc)
    for code, nm in sorted((assets or {}).items(), key=lambda kv: -len(kv[1])):
        desc = desc.replace(nm, code)
        desc = desc.replace(short_name(nm), code) if short_name(nm) != nm else desc
    return desc.replace("Palm Boulevard (Retail & Dining)", "Palm Boulevard")


def short_name(n: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", n).strip()


# ----------------------------------------------------------------------------------------------- deck
class Deck:
    def __init__(self, ctx: Ctx, kind: str):
        self.c = ctx
        self.kind = kind
        self.prs = Presentation()
        self.prs.slide_width = Inches(SW)
        self.prs.slide_height = Inches(SH)
        self.blank = self.prs.slide_layouts[6]
        self.n = 0
        self.warnings: list[str] = []

    # -- primitives
    def _strip_style(self, shp):
        st = shp._element.find(qn("p:style"))
        if st is not None:
            shp._element.remove(st)

    def rect(self, s, x, y, w, h, fill=None, line=None, name=None, lw=0.75):
        shp = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        self._strip_style(shp)
        if fill:
            shp.fill.solid()
            shp.fill.fore_color.rgb = rgb(fill)
        else:
            shp.fill.background()
        if line:
            shp.line.color.rgb = rgb(line)
            shp.line.width = Pt(lw)
        else:
            shp.line.fill.background()
        if name:
            shp.name = name
        return shp

    def _fill_tf(self, tf, paras, anchor=MSO_ANCHOR.TOP, delta=0.0, pad=(PAD_X, PAD_Y)):
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = Inches(pad[0])
        tf.margin_top = tf.margin_bottom = Inches(pad[1])
        tf.vertical_anchor = anchor
        for i, p in enumerate(paras):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            # always explicit: python-pptx autoshapes carry algn="ctr" on their first paragraph, which would centre
            # the first line of every filled box (tiles, ask boxes) and leave the rest left-aligned
            para.alignment = p.get("align") or PP_ALIGN.LEFT
            if p.get("after"):
                para.space_after = Pt(p["after"])
            if p.get("hang"):
                pPr = para._p.get_or_add_pPr()
                pPr.set("marL", str(int(Inches(p["hang"]))))
                pPr.set("indent", str(-int(Inches(p["hang"]))))
                bf = OxmlElement("a:buFont")
                bf.set("typeface", "Arial")
                bc = OxmlElement("a:buChar")
                bc.set("char", "•")
                pPr.append(bf)
                pPr.append(bc)
            for r in p["runs"]:
                run = para.add_run()
                run.text = r["text"]
                f = run.font
                f.name = FONT
                f.size = Pt(max(10.0, r["size"] - delta) if r["size"] >= 10 else r["size"])
                f.bold = r["bold"]
                f.italic = r["italic"]
                f.color.rgb = rgb(r["color"])
                if r.get("link"):                    # the visible URL uses non-breaking hyphens; the link is exact
                    run.hyperlink.address = r["link"]

    def _shrink(self, paras, w, h, label):
        """Smallest font reduction (in 0.5 pt steps, floor 10 pt) that makes ``paras`` fit; truncates if not."""
        usable_w, usable_h = w - 2 * PAD_X, h - 2 * PAD_Y
        max_size = max(r["size"] for p in paras for r in p["runs"])
        delta = 0.0
        while para_height(paras, usable_w, delta) > usable_h and max_size - delta > 10:
            delta += 0.5
        if para_height(paras, usable_w, delta) > usable_h:
            # truncate the longest paragraph's last run until the block fits
            for _ in range(60):
                p = max(paras, key=lambda p: len("".join(r["text"] for r in p["runs"])))
                r = p["runs"][-1]
                if len(r["text"]) < 8:
                    break
                r["text"] = r["text"][: int(len(r["text"]) * 0.9)].rstrip() + "…"
                if para_height(paras, usable_w, delta) <= usable_h:
                    break
            self.warnings.append(f"slide {self.n}: truncated text in '{label}'")
        return delta

    def text(self, s, x, y, w, h, paras, name=None, anchor=MSO_ANCHOR.TOP, fill=None, line=None):
        delta = self._shrink(paras, w, h, name or "text")
        if fill or line:
            shp = self.rect(s, x, y, w, h, fill=fill, line=line)
        else:
            shp = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        if name:
            shp.name = name
        self._fill_tf(shp.text_frame, paras, anchor=anchor, delta=delta)
        return shp

    # -- frame
    def slide(self, tag: str, title: str):
        s = self.prs.slides.add_slide(self.blank)
        self.n += 1
        bgf = s.background.fill
        bgf.solid()
        bgf.fore_color.rgb = rgb(SURFACE)
        self.text(s, ML, TAG_Y, CW, TAG_H, [P(R(tag.upper(), 10, True, TEAL))], name="Section tag")
        size = next((z for z in (24, 22, 20) if title_fits(title, z)), 20)
        if not title_fits(title, size):
            self.warnings.append(f"slide {self.n}: title truncated")
            title = fit(title, (CW - 2 * PAD_X) * TITLE_HEADROOM, size, 2, True)
        self.text(s, ML, TITLE_Y, CW, TITLE_H, [P(R(title, size, True, NAVY))], name="Title",
                  anchor=MSO_ANCHOR.MIDDLE)
        self.rect(s, ML, RULE_Y, 1.2, 0.04, fill=TEAL, name="Title rule")
        self.rect(s, ML, FOOT_LINE_Y, CW, 0.01, fill=BORDER, name="Footer rule")
        self.text(s, ML, FOOT_Y, 9.0, FOOT_H, [P(R(self.c.footer, 10, False, MUTED))], name="Footer",
                  anchor=MSO_ANCHOR.MIDDLE)
        self.text(s, ML + 9.2, FOOT_Y, CW - 9.2, FOOT_H,
                  [P(R(f"Fictional data  |  {self.n}", 10, False, MUTED), align=PP_ALIGN.RIGHT)],
                  name="Slide Number", anchor=MSO_ANCHOR.MIDDLE)
        return s

    def _fit(self, text, w, pt, lines=1, bold=False, label="text"):
        """fit() that records a layout warning when it has to cut text (a note or heading must never lose words
        silently)."""
        t = fit(text, w, pt, lines, bold)
        if t != nbh(text):
            self.warnings.append(f"slide {self.n}: truncated {label}: {text[:60]!r}")
        return t

    def heading(self, s, x, y, w, text, h=0.3):
        return self.text(s, x, y, w, h, [P(R(self._fit(text, w - 2 * PAD_X, 12, 1, True, "heading"), 12, True, NAVY))],
                         name="Heading", anchor=MSO_ANCHOR.BOTTOM)

    def caption(self, s, x, y, w, text, h=0.48):
        return self.text(s, x, y, w, h, [P(R("So what: ", 10.5, True, TEAL), R(text, 10.5, False, TEXT))],
                         name="So what")

    def note(self, s, x, y, w, text, h=None, lines=1):
        h = h if h is not None else 0.28 + (lines - 1) * 10 * LINE / 72
        return self.text(s, x, y, w, h, [P(R(self._fit(text, w - 2 * PAD_X, 10, lines, label="note"), 10, False,
                                             MUTED, True))], name="Note")

    def ask(self, s, label, text, y=ASK_Y, h=ASK_H, x=ML, w=CW, extra=None, accent=TEAL, tint="teal"):
        self.rect(s, x, y, 0.07, h, fill=accent, name="Ask accent")
        paras = [P(R(f"{label}: ", 12, True, NAVY), R(text, 12, False, TEXT))] if text else \
            [P(R(label, 12, True, NAVY))]
        for e in extra or []:
            paras.append(BUL(e, 11.5))
        return self.text(s, x + 0.07, y, w - 0.07, h, paras, name="Ask box", fill=TINT[tint],
                         anchor=MSO_ANCHOR.MIDDLE)

    def tile(self, s, x, y, w, h, label, value, sub, color=NAVY):
        self.rect(s, x, y, 0.07, h, fill=color, name="Tile accent")
        iw = w - 0.07 - 2 * PAD_X
        paras = [P(R(self._fit(label, iw, 10, 1, True, "tile label"), 10, True, MUTED)),
                 P(R(self._fit(value, iw, 20, 1, True, "tile value"), 20, True, color)),
                 P(R(self._fit(sub, iw, 10, 1, label="tile text"), 10, False, MUTED))]
        return self.text(s, x + 0.07, y, w - 0.07, h, paras, name="KPI tile", fill=SURFACE, line=BORDER,
                         anchor=MSO_ANCHOR.MIDDLE)

    def tiles(self, s, y, h, specs, x=ML, w=CW):
        n = len(specs)
        tw = (w - (n - 1) * GAP) / n
        for i, sp in enumerate(specs):
            self.tile(s, x + i * (tw + GAP), y, tw, h, *sp)

    # -- table
    def table(self, s, x, y, w, cols, rows, max_h, font=10, hdr=10, max_lines=2, max_rows=12, name="Table",
              partial_ok=False, stretch=False):
        """cols: [(header, width | None for flexible, align, lines)]; rows: [[value | {"text", "fill", "color", "bold"}]].
        Rows that would push the table below ``y + max_h`` are dropped; returns (bottom_y, shown). Dropping rows is
        a layout warning unless the caller states it (``partial_ok``) and prints a "Showing n of m" note.
        ``stretch`` spreads spare height over the body rows (at most 0.1 in each) so a short table does not leave an
        empty band above the ask box."""
        fixed = sum(c[1] for c in cols if c[1])
        flex = [c for c in cols if not c[1]]
        if flex:
            fw = (w - fixed) / len(flex)
            widths = [c[1] or fw for c in cols]
        else:
            widths = [c[1] * w / fixed for c in cols]
        hl = max(text_lines(c[0], wd - 2 * CELL_X, hdr, True) for c, wd in zip(cols, widths))
        hdr_h = min(3, hl) * hdr * LINE / 72 + 2 * CELL_Y + 0.03
        body, heights = [], []
        used = hdr_h
        for r in rows:
            cells, nl = [], 1
            for v, c, wd in zip(r, cols, widths):
                cell = v if isinstance(v, dict) else {"text": v}
                lines = c[3] if len(c) > 3 else max_lines
                t = fit("–" if cell["text"] in (None, "") else cell["text"], wd - 2 * CELL_X, font, lines,
                        cell.get("bold", False))
                nl = max(nl, text_lines(t, wd - 2 * CELL_X, font, cell.get("bold", False)))
                cells.append({**cell, "text": t})
            rh = nl * font * LINE / 72 + 2 * CELL_Y + 0.02
            if used + rh > max_h or len(body) >= max_rows:
                break
            used += rh
            body.append(cells)
            heights.append(rh)
        if len(body) < len(rows) and not partial_ok:
            self.warnings.append(f"slide {self.n}: table '{name}' shows {len(body)} of {len(rows)} rows without a note")
        if stretch and body and used < max_h:
            add = min(0.1, (max_h - used) / len(body))
            heights = [h + add for h in heights]
            used += add * len(body)
        gf = s.shapes.add_table(len(body) + 1, len(cols), Inches(x), Inches(y), Inches(w), Inches(used))
        gf.name = name
        tbl_el = gf._element.graphic.graphicData.tbl
        sid = tbl_el.tblPr.find(qn("a:tableStyleId"))
        if sid is None:
            sid = OxmlElement("a:tableStyleId")
            tbl_el.tblPr.append(sid)
        sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"          # "No Style, No Grid"
        t = gf.table
        t.first_row = True
        t.horz_banding = False
        for j, wd in enumerate(widths):
            t.columns[j].width = Inches(wd)
        t.rows[0].height = Inches(hdr_h)
        for i, rh in enumerate(heights, 1):
            t.rows[i].height = Inches(rh)
        for j, c in enumerate(cols):
            self._cell(t.cell(0, j), {"text": c[0], "fill": NAVY, "color": "FFFFFF", "bold": True}, hdr,
                       c[2], header=True)
        for i, cells in enumerate(body, 1):
            for j, (cell, c) in enumerate(zip(cells, cols)):
                cell.setdefault("fill", SURFACE if i % 2 else BG)
                self._cell(t.cell(i, j), cell, font, c[2])
        return y + used, len(body)

    def _cell(self, cell, spec, size, align, header=False):
        cell.margin_left = cell.margin_right = Inches(CELL_X)
        cell.margin_top = cell.margin_bottom = Inches(CELL_Y)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(spec.get("fill", SURFACE))
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
        run = p.add_run()
        run.text = nbh(spec["text"])
        f = run.font
        f.name = FONT
        f.size = Pt(size)
        f.bold = bool(spec.get("bold"))
        f.color.rgb = rgb(spec.get("color", TEXT))
        tcPr = cell._tc.get_or_add_tcPr()
        ln = OxmlElement("a:lnB")
        ln.set("w", "9525")
        sf = OxmlElement("a:solidFill")
        clr = OxmlElement("a:srgbClr")
        clr.set("val", NAVY if header else BORDER)
        sf.append(clr)
        ln.append(sf)
        tcPr.insert(0, ln)

    # -- charts
    def _style_chart(self, ch, legend=True):
        ch.has_title = False
        ch.font.name = FONT
        ch.font.size = Pt(10)
        ch.font.color.rgb = rgb(MUTED)
        ch.has_legend = legend
        if legend:
            ch.legend.position = XL_LEGEND_POSITION.BOTTOM
            ch.legend.include_in_layout = False
            ch.legend.font.size = Pt(10)
        va = ch.value_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = rgb(BORDER)
        va.major_gridlines.format.line.width = Pt(0.75)
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(10)
        ca = ch.category_axis
        ca.format.line.color.rgb = rgb(BORDER)
        ca.tick_labels.font.size = Pt(10)
        ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        ca.has_major_gridlines = False

    @staticmethod
    def _no_wrap(el):
        """Data labels on one line: renderers otherwise wrap a date label at its hyphen."""
        tx = el.find(qn("c:txPr"))
        if tx is not None:
            tx.find(qn("a:bodyPr")).set("wrap", "none")

    def _point_label(self, pt, fmt, position):
        """A point-level data label with its own position, number format and font (renderers do not all inherit
        the series-level settings into a point override)."""
        dl = pt.data_label
        dl.position = position
        dl.font.size = Pt(10)
        dl.font.color.rgb = rgb(TEXT)
        el = dl._dLbl
        nf = OxmlElement("c:numFmt")
        nf.set("formatCode", fmt)
        nf.set("sourceLinked", "0")
        el.find(qn("c:idx")).addnext(nf)
        self._no_wrap(el)

    def line_chart(self, s, x, y, w, h, cats, series, fmt="0", vmin=None, vmax=None, major=None,
                   labels_on=(0,), legend=True, name="Chart", label_fmt=None, label_pos=None):
        """series: [(name, values, color, dashed)]; label_fmt: number format of the data labels (default ``fmt``);
        label_pos: per-point 'above' / 'below' for the first labelled series (default above)."""
        cd = CategoryChartData(number_format=fmt)
        cd.categories = cats
        for nm, vals, _c, _d in series:
            cd.add_series(nm, vals, number_format=fmt)
        gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(x), Inches(y), Inches(w), Inches(h), cd)
        gf.name = name
        ch = gf.chart
        self._style_chart(ch, legend)
        va = ch.value_axis
        va.tick_labels.number_format = fmt
        va.tick_labels.number_format_is_linked = False
        if vmin is not None:
            va.minimum_scale = vmin
        if vmax is not None:
            va.maximum_scale = vmax
        if major:
            va.major_unit = major
        for i, (nm, vals, color, dashed) in enumerate(series):
            se = ch.plots[0].series[i]
            se.smooth = False
            se.format.line.color.rgb = rgb(color)
            se.format.line.width = Pt(1.5 if dashed else 2.5)
            if dashed:
                se.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
                se.marker.style = XL_MARKER_STYLE.NONE
            else:
                se.marker.style = XL_MARKER_STYLE.CIRCLE
                se.marker.size = 7
                se.marker.format.fill.solid()
                se.marker.format.fill.fore_color.rgb = rgb(color)
                se.marker.format.line.color.rgb = rgb(color)
            if i in labels_on:
                lf = label_fmt or fmt
                dl = se.data_labels
                dl.number_format = lf
                dl.number_format_is_linked = False
                dl.show_value = True
                dl.position = XL_LABEL_POSITION.ABOVE
                dl.font.size = Pt(10)
                dl.font.color.rgb = rgb(TEXT)
                self._no_wrap(dl._element)
                if label_pos and i == labels_on[0]:
                    for k, pos in enumerate(label_pos):
                        if pos == "below":
                            self._point_label(se.points[k], lf, XL_LABEL_POSITION.BELOW)
        return ch

    def bar_chart(self, s, x, y, w, h, cats, series, fmt="0", horizontal=False, point_colors=None,
                  legend=None, vmin=None, vmax=None, name="Chart"):
        """series: [(name, values, color)]; point_colors: per-point colours for a single series."""
        cd = CategoryChartData(number_format=fmt)
        cd.categories = cats
        for nm, vals, _c in series:
            cd.add_series(nm, vals, number_format=fmt)
        kind = XL_CHART_TYPE.BAR_CLUSTERED if horizontal else XL_CHART_TYPE.COLUMN_CLUSTERED
        gf = s.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), cd)
        gf.name = name
        ch = gf.chart
        self._style_chart(ch, legend if legend is not None else len(series) > 1)
        plot = ch.plots[0]
        plot.gap_width = 60
        plot.vary_by_categories = False
        if len(series) > 1:
            plot.overlap = -10
        va = ch.value_axis
        va.tick_labels.number_format = fmt
        va.tick_labels.number_format_is_linked = False
        # every bar carries its value label, so gridlines add nothing and would strike through the labels; the axis
        # is rounded to a nice step with head room beyond the longest bar so its label never meets the axis text
        va.has_major_gridlines = False
        if vmin is None and vmax is None:
            vals = [v for _, vs, _ in series for v in vs if v is not None]
            lo, hi = min(vals + [0]), max(vals + [0])
            span = (hi - lo) or 1
            step = next(m * 10 ** e for e in range(-1, 6) for m in (1, 2, 2.5, 5) if m * 10 ** e >= span / 5)
            vmin = math.floor((lo - 0.18 * span) / step) * step if lo < 0 else 0
            vmax = math.ceil((hi + 0.18 * span) / step) * step if hi > 0 else 0
            va.major_unit = step
        if vmin is not None:
            va.minimum_scale = vmin
        if vmax is not None:
            va.maximum_scale = vmax
        if horizontal:
            ch.category_axis.reverse_order = True
            ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        for i, (nm, vals, color) in enumerate(series):
            se = plot.series[i]
            se.invert_if_negative = False
            se.format.fill.solid()
            se.format.fill.fore_color.rgb = rgb(color)
            se.format.line.fill.background()
            if point_colors and i == 0:
                for k, pc in enumerate(point_colors):
                    pt = se.points[k]
                    pt.format.fill.solid()
                    pt.format.fill.fore_color.rgb = rgb(pc)
                # a coloured point without its own invertIfNegative is drawn as a positive bar by LibreOffice
                # (and labelled without its minus sign); state it explicitly on every point
                for dpt in se._element.findall(qn("c:dPt")):
                    if dpt.find(qn("c:invertIfNegative")) is None:
                        inv = OxmlElement("c:invertIfNegative")
                        inv.set("val", "0")
                        dpt.find(qn("c:idx")).addnext(inv)
            dl = se.data_labels
            dl.number_format = fmt
            dl.number_format_is_linked = False
            dl.show_value = True
            dl.position = XL_LABEL_POSITION.OUTSIDE_END
            dl.font.size = Pt(10)
            dl.font.color.rgb = rgb(TEXT)
        return ch

    # -- save
    def save(self, path: pathlib.Path):
        c = self.c
        stamp = dt.datetime.combine(_d(c.dd), dt.time(8, 0))
        cp = self.prs.core_properties
        cp.title = (f"DOP {'monthly steering committee pack' if self.kind == 'monthly' else 'fortnightly flash'} "
                    f"{fd(c.dd)}")
        cp.subject = "Destination Opening Programme (fictional) - schedule intelligence"
        cp.author = "DOP Programme Controls (PMO)"
        cp.last_modified_by = "dop.pptx_gen"
        cp.keywords = "fictional; P6 XER; schedule intelligence"
        cp.comments = c.meta.get("disclaimer", "")
        cp.created = stamp
        cp.modified = stamp
        cp.revision = 1
        buf = io.BytesIO()
        self.prs.save(buf)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_normalise_zip(buf.getvalue(), stamp))


def _normalise_zip(data: bytes, stamp: dt.datetime) -> bytes:
    """Rewrite a zip package with fixed timestamps (and fixed dates in embedded xlsx core properties)."""
    iso = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename.endswith(".xlsx"):
                blob = _normalise_zip(blob, stamp)
            elif info.filename == "docProps/core.xml":
                txt = blob.decode("utf-8")
                txt = re.sub(r"(<dcterms:(created|modified)[^>]*>)[^<]*(</dcterms:\2>)", rf"\g<1>{iso}\g<3>", txt)
                blob = txt.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=(stamp.year, stamp.month, stamp.day, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zout.writestr(zi, blob)
    return out.getvalue()


# ----------------------------------------------------------------------------------------------- slide content
def rag_cell(status: str) -> dict:
    col = {"Red": RED, "Amber": AMBER, "Green": GREEN, "Complete": SLATE}[status]
    return {"text": status, "fill": col, "color": "FFFFFF", "bold": True}


def tint_cell(text, kind=None, bold=False) -> dict:
    d = {"text": text, "bold": bold}
    if kind:
        d["fill"] = TINT[kind]
    return d


def var_cell(v) -> dict:
    return tint_cell(sg(v), "amber" if (v or 0) > 0 else None)


def tf_cell(v) -> dict:
    return tint_cell(sg(v) if v is not None else "–", "red" if v is not None and v < 0 else None,
                     bold=v is not None and v < 0)


def slip_cell(v) -> dict:
    return tint_cell(sg(v), "red" if (v or 0) > 0 else "green" if (v or 0) < 0 else None)


def kpi_specs(c: Ctx) -> list[tuple]:
    sm, p = c.sm, c.prev_sm
    tf = sm["day1_tf_d"]
    var_t = (_d(sm["day1_forecast"]) - _d(c.target)).days
    # both tiles quote the previous update the same, short way (a full date does not fit the DQ tile)
    dq_prev = f" · was {dqs(p['dq_score'])} on {fds(p['data_date'])}" if p else ""
    tf_prev = f"was {sg(p['day1_tf_d'], 'wd')} on {fds(p['data_date'])}" if p else "first update"
    return [
        ("Day 1 forecast", fd(sm["day1_forecast"]), f"target {fd(c.target)} ({sg(var_t, 'd')})",
         RED if var_t > 0 else GREEN),
        ("Day 1 total float", sg(tf, "wd"), tf_prev, RED if tf < 0 else AMBER if tf < 5 else GREEN),
        (f"Finish variance vs {c.bl}", sg(sm[f"day1_var_{c.bl.lower()}_d"], "d"),
         f"Day 1 · vs BL0 {sg(sm['day1_var_bl0_d'], 'd')}", RED if sm[f"day1_var_{c.bl.lower()}_d"] > 0 else GREEN),
        ("DQ score", f"{dqs(sm['dq_score'])} / 100", f"{sm['dq_rating']}{dq_prev}",
         GREEN if sm["dq_score"] >= 85 else AMBER if sm["dq_score"] >= 70 else RED),
        ("Reconciliation status", f"{sm['controls_passed']} / {sm['controls_total']}",
         "XER = model = JSON" if c.reconciled else "controls FAILED",
         TEAL if c.reconciled else RED),
    ]


def decision_lines(c: Ctx, limit=3) -> list[str]:
    out = []
    for d in c.open_decisions()[:limit]:
        if d["overdue"]:
            out.append(f"{d['decision_id']} · {d['owner']} · overdue since {fd(d['needed_by'])}: {d['ask']}")
        else:
            out.append(f"{d['decision_id']} · {d['owner']} · by {fd(d['needed_by'])}: {d['ask']}")
    return out


def s_exec_summary(dk: Deck, tag="Executive summary"):
    c = dk.c
    title = (c.narr["headline"].replace("Day 1 Opening is forecast for", "Day 1 forecast")
             .replace(" working days", " wd").replace("approving recovery", "approving"))
    # shorter wordings keep every number and date of the dashboard headline, in the same order
    t2 = title.replace(" beyond the ", " past the ")
    t3 = t2.replace(" returns it to ", " gives ")
    title = first_fit(title, t2, t3, t3.replace(" wd float)", " wd)"))
    s = dk.slide(tag, title)
    dk.tiles(s, BODY_Y, 0.95, kpi_specs(c))
    y0 = BODY_Y + 0.95 + 0.2
    lw = 6.7
    dk.heading(s, ML, y0, lw, "Key messages")
    lines = decision_lines(c)
    # the decisions have their own box below: do not repeat them as a key message
    msgs = [m for m in c.narr["messages"] if not (lines and re.match(r"^\d+ decisions? open", m))]
    paras = [BUL(m, 13, after=6) for m in msgs]
    dk.text(s, ML, y0 + 0.32, lw, 5.8 - (y0 + 0.32), paras, name="Messages")
    rx = ML + lw + 0.2
    rw = SW - ML - rx
    nc = c.meta["near_critical_days"]
    dk.heading(s, rx, y0, rw, f"RAG by asset (as dashboard): red TF < 0, amber ≤ {nc} wd")
    rag = sorted(c.rag(), key=lambda r: (r["tf"] if r["tf"] is not None else 9999, r["asset"]))   # worst first
    rows = [[SHORT_ASSET.get(r["asset"], r["asset"]), rag_cell(r["status"]), r["why"], r["owner"]] for r in rag]
    avail = 5.8 - (y0 + 0.34)
    why_w = rw - 1.45 - 0.6 - WOW - 2 * CELL_X
    need = (10 * LINE / 72 + 2 * CELL_Y + 0.03) + sum(
        (min(2, text_lines(r["why"], why_w, 10)) * 10 * LINE / 72 + 2 * CELL_Y + 0.02) for r in rag)
    why_lines = 2 if need <= avail else 1          # every asset must keep its row; shorten the reason instead
    dk.table(s, rx, y0 + 0.34, rw, [("Asset", 1.45, "l", 1), ("RAG", 0.6, "c", 1),
                                    ("Lowest total float · activity", None, "l", why_lines), ("Owner", WOW, "c", 1)],
             rows, avail, name="RAG table")
    if lines:
        dk.ask(s, "Decisions required", "", y=5.92, h=0.93, extra=lines)
    else:
        dk.ask(s, "Ask", "No decisions are open; the committee is asked to note the forecast.", y=5.92, h=0.93)
    return s


# contents list on the cover: one entry per monthly slide after the cover, in MONTHLY order (checked by the tests)
AGENDA = ["Executive summary", "Milestone outlook", "Critical path to Day 1", "Two-week look-back",
          "Two-week look-ahead", "Trend analysis", "Interfaces and readiness gap", "Top risks", "Decision log",
          "Recovery plan", "Change and baseline governance", "Schedule-quality actions",
          "Appendix A · lineage and method", "Appendix B · definitions"]


def s_cover(dk: Deck):
    c = dk.c
    snap = c.snap
    title = f"Destination Opening Programme steering committee pack for the {fd(c.dd)} update"   # the lede gives the answer
    s = dk.slide("Monthly steering committee pack · fictional programme", title)
    dk.text(s, ML, BODY_Y, CW, 0.7, [P(R(c.narr["headline"], 16, False, TEXT))], name="Headline")
    sm = c.sm
    bl_change = next((ch for ch in c.changes() if str(ch["baseline_effect"]).startswith(f"{c.bl} created")), None)
    specs = [
        ("Programme", c.meta["programme"]["code"], c.meta["programme"]["project"] + " · " +
         pl(sm["activities"], "activity", "activities"), NAVY),
        ("Data date", fd(c.dd), f"update {sm['label']} · cut-off {fd(snap['cutoff_expected'])}", NAVY),
        ("Baseline in force", c.bl, (f"{bl_change['change_id']} approved {fd(bl_change['approval_date'])}"
                                     if bl_change else snap["baseline_file"]), TEAL),
        ("DQ score", f"{dqs(sm['dq_score'])} / 100", f"{sm['dq_rating']} (Good ≥ 85, Fair ≥ 70)",
         GREEN if sm["dq_score"] >= 85 else AMBER if sm["dq_score"] >= 70 else RED),
    ]
    dk.tiles(s, BODY_Y + 0.82, 0.9, specs)
    y = BODY_Y + 0.82 + 0.9 + 0.15
    rec = ("Reconciled ✓" if c.reconciled else "NOT reconciled ✗")
    paras = [
        P(R("Reconciliation statement", 12, True, NAVY), after=4),
        P(R(f"{rec}  Source {snap['source_file']} (SHA-256 {snap['sha256'][:12]}) and baseline "
            f"{snap['baseline_file']} (SHA-256 {snap['baseline_sha256'][:12]}) were parsed, re-scheduled and "
            f"loaded into the star schema; {sm['controls_passed']} of {sm['controls_total']} controls agree "
            f"across source XER, model and dashboard JSON. Every number in this pack is read from that "
            f"reconciled dashboard file.", 12, False, TEXT)),
    ]
    dk.text(s, ML, y, CW, 0.85, paras, name="Reconciliation statement", fill=TINT["teal"])
    y += 0.85 + 0.13
    dk.heading(s, ML, y, CW, "In this pack")
    per = -(-len(AGENDA) // 4)
    colw = CW / 4
    for k in range(4):
        items = AGENDA[k * per:(k + 1) * per]
        paras = [P(R(f"{k * per + j + 2}  ", 10.5, True, TEAL), R(t, 10.5, False, TEXT), after=2)
                 for j, t in enumerate(items)]
        if paras:
            dk.text(s, ML + k * colw, y + 0.32, colw - 0.1, 0.97, paras, name="Agenda")
    y += 0.32 + 0.97 + 0.1
    paras = [
        P(R("Method and transparency", 11, True, NAVY), after=3),
        P(R("Fictional programme and data. Schedules are produced by a custom CPM engine that follows Primavera "
            "P6 conventions and are exported in genuine P6 XER format; no Primavera P6 licence was used. "
            "Floats and durations are in working days (wd); variances are in calendar days (d), positive = later. "
            "Dashboard: ", 10.5, False, MUTED), R(SITE, 10.5, False, MUTED, link=SITE)),
    ]
    dk.text(s, ML, y, CW, FOOT_LINE_Y - 0.12 - y, paras, name="Method note")
    return s


def s_milestones(dk: Deck):
    c = dk.c
    vk = c.var_key()
    ms = c.incomplete_ms()                         # one denominator on the slide: open milestones
    late = [m for m in ms if (m[vk] or 0) > 0]
    by_asset = Counter(c.A[m["activity_id"]]["asset_code"] for m in late)
    top_asset, top_n = (sorted(by_asset.items(), key=lambda kv: (-kv[1], kv[0]))[0] if by_asset else (None, 0))
    slipped = [m for m in ms if (m["movement_vs_prev_d"] or 0) > 0]
    prev = f" since {fd(c.prev_dd)}" if c.prev_dd else ""
    title = f"{len(late)} of {len(ms)} open milestones finish later than {c.bl}"
    if top_asset:
        title += f"; {c.meta['assets'][top_asset]} accounts for {top_n} of them"
    title += (f", and none slipped further{prev}." if not slipped else
              f", and {pl(len(slipped), 'milestone')} slipped further{prev}.")
    s = dk.slide("Milestone outlook", title)
    inc = c.incomplete_ms()
    rows_src = sorted(inc, key=lambda m: (-(m[vk] or 0), m["total_float_d"] if m["total_float_d"] is not None
                                          else 999, m["activity_id"]))
    rows = [[m["activity_id"], c.name(m["activity_id"]), m["owner_code"], fd(m["bl0_finish"]), fd(m["bl1_finish"]),
             fd(m["forecast_finish"]), var_cell(m["var_bl0_d"]), var_cell(m["var_bl1_d"]),
             slip_cell(m["movement_vs_prev_d"]), tf_cell(m["total_float_d"])] for m in rows_src]
    cols = [("Milestone", WID, "l", 1), ("Name", None, "l", 1), ("Owner", WOW, "c", 1), ("BL0 finish", WDT, "c", 1),
            ("BL1 finish", WDT, "c", 1), ("Forecast", WDT, "c", 1), ("Finish variance vs BL0 (d)", 0.95, "r", 1),
            ("Finish variance vs BL1 (d)", 0.95, "r", 1), ("Slip vs previous period (d)", 0.95, "r", 1),
            ("Total float (wd)", WNUM, "r", 1)]
    bottom, shown = dk.table(s, ML, BODY_Y, CW, cols, rows, 5.85 - BODY_Y, max_lines=1, partial_ok=True, stretch=True)
    dk.note(s, ML, bottom + 0.04, CW, f"Showing {shown} of {len(inc)} open milestones, largest variance vs {c.bl} "
            f"first. Full list: controls workbook, Milestone Variance sheet.")
    neg = sorted([m for m in inc if (m["total_float_d"] or 0) < 0],
                 key=lambda m: (m["total_float_d"], m["activity_id"]))
    picks, seen = [], set()
    for m in neg:
        if m["owner_code"] not in seen:
            picks.append(m)
            seen.add(m["owner_code"])
        if len(picks) == 2:
            break
    if picks:
        txt = (f"{pl(len(neg), 'open milestone')} carry negative float. " +
               "; ".join(f"{c.who(m['owner_code'])} to confirm a recovery date for {m['activity_id']} "
                         f"({lc_first(short_name(c.name(m['activity_id'])))}, TF {sg(m['total_float_d'], 'wd')})"
                         for m in picks) + ", by the next update.")
        dk.ask(s, "Ask", txt)
    else:
        dk.ask(s, "So what", "No open milestone carries negative float; owners hold their forecast dates.")
    return s


def cp_title(c: Ctx) -> str:
    asset = c.driver_asset()
    # each activity name is one unit: a title must not wrap in the middle of 'MEP second fix – Zone B'
    drivers = [nbh(lc_first(short_name(c.name(a["activity_id"])))).replace(" ", " ") for a in c.lp_tasks()[:3]]
    tf = c.sm["day1_tf_d"]
    where = c.meta["assets"].get(asset, "the programme")
    return first_fit(*[f"The longest path to Day 1 runs through {where}: {join_and(drivers[:k])}; Day 1 total float "
                       f"is {sg(tf, 'wd')}." for k in (3, 2, 1) if drivers[:k]],
                     f"The longest path to Day 1 runs through {where}; Day 1 total float is {sg(tf, 'wd')}.")


def cp_rows(c: Ctx) -> list[list]:
    rows = []
    for a in c.longest_path():
        rows.append([a["activity_id"], c.name(a["activity_id"]), c.owner_of(a["activity_id"]), fd(a["start"]),
                     fd(a["finish"]), tf_cell(a["total_float_d"]), slip_cell(a["slip_vs_prev_d"]),
                     var_cell(a["var_finish_bl_d"]),
                     {"TK_Active": "In progress", "TK_NotStart": "Not started"}.get(a["status"], a["status"])])
    return rows


def cp_ask(c: Ctx) -> str:
    first = c.lp_tasks()[:1]
    loe = [a for a in c.longest_path(include_loe=True) if c.A[a["activity_id"]]["activity_type"] == "TT_LOE"]
    parts = []
    if first:
        a = first[0]
        o = c.owner_of(a["activity_id"])
        parts.append(f"{c.who(o)} to hold the {fd(a['finish'])} finish of {short_name(c.name(a['activity_id']))}"
                     f" ({a['activity_id']}); a day lost there is a day lost at Day 1")
    if loe:
        o = c.owner_of(loe[0]["activity_id"])
        parts.append(f"{c.who(o)} to unlink the level-of-effort {loe[0]['activity_id']} from the driving path "
                     f"(LOE · U07: level of effort must not drive Day 1)")
    return "; ".join(parts) + "." if parts else "The longest path is stable; no owner action this period."


def s_critical_path(dk: Deck):
    c = dk.c
    sm = c.sm
    s = dk.slide("Critical path to Day 1", cp_title(c))
    nc = c.meta["near_critical_days"]
    dk.tiles(s, BODY_Y, 0.85, [
        ("Longest path", pl(sm["longest_path_count"], "activity", "activities"), "driving chain into Day 1", NAVY),
        ("Critical (TF ≤ 0)", str(sm["critical_count"]), "incomplete activities", RED if sm["critical_count"] else GREEN),
        ("Near-critical", str(sm["near_critical_count"]), f"0 < TF ≤ {nc} wd", AMBER),
        ("Negative float", str(sm["negative_float_count"]), f"lowest TF {sg(sm['min_float_d'], 'wd')}",
         RED if sm["negative_float_count"] else GREEN),
        ("CPLI", ratio(sm["cpli"], 0.95), "target ≥ 0.95", GREEN if sm["cpli"] >= 0.95 else RED),
    ])
    y = BODY_Y + 0.85 + 0.15
    cols = [("Activity", WID, "l", 1), ("Name", None, "l", 1), ("Owner", WOW, "c", 1), ("Start", WDT, "c", 1),
            ("Finish", WDT, "c", 1), ("Total float (wd)", WNUM, "r", 1), ("Slip vs previous period (d)", 0.95, "r", 1),
            (f"Finish variance vs {c.bl} (d)", 0.95, "r", 1), ("Status", 1.0, "c", 1)]
    rows = cp_rows(c)
    bottom, shown = dk.table(s, ML, y, CW, cols, rows, 5.70 - y, max_lines=1, partial_ok=True)
    dk.note(s, ML, bottom + 0.04, CW, cp_note(c, len(rows) - shown, any(r[7]["text"] == "–" for r in rows[:shown])),
            lines=2)
    dk.ask(s, "Ask", cp_ask(c))
    return s


def lp_loe(c: Ctx) -> list[str]:
    """Level-of-effort activities flagged on the longest path: a defect (check U07), shown apart from the path."""
    return [a["activity_id"] for a in c.longest_path(include_loe=True)
            if c.A[a["activity_id"]]["activity_type"] == "TT_LOE"]


def cp_note(c: Ctx, rest: int, dash: bool) -> str:
    """Reconciles the table with the 'Longest path' tile: the LOE on the driving path is tagged LOE · U07 and left
    out; floats are per activity calendar; '–' means the activity is not in the baseline in force."""
    loe = lp_loe(c)
    t = "Longest path in sequence."
    if loe:
        t += (f" {join_and(loe)} {'is' if len(loe) == 1 else 'are'} level of effort on the driving path, tagged "
              f"LOE · U07 (a defect the quality checks detect), and left out of this table.")
    if rest > 0:
        t += f" {rest} further activities to Day 1 are on the dashboard (Critical path tab)."
    t += " Floats are in working days of each activity's own calendar and reflect all its successors."
    if dash:
        t += f" '–' variance = not in {c.bl}."
    return t


def lb_rows(c: Ctx, compact=False) -> list[list]:
    rows = []
    for r in c.lookback():
        ok = bool(r["lookback_achieved"])
        ach = {"text": "Yes" if ok else "No", "fill": TINT["green" if ok else "red"], "bold": not ok}
        if compact:
            rows.append([c.id_label(r["activity_id"]), c.owner_of(r["activity_id"]),
                         r["lookback_event"].capitalize(), fd(r["planned"]), ach])
        else:
            rows.append([r["activity_id"], c.name(r["activity_id"]), c.owner_of(r["activity_id"]),
                         r["lookback_event"].capitalize(), fd(r["planned"]), fd(r["actual"]), ach,
                         tf_cell(r["total_float_d"])])
    return rows


def lb_title(c: Ctx) -> str:
    lb = c.lookback()
    n = len(lb)
    ok = sum(1 for r in lb if r["lookback_achieved"])
    if not n:
        return "No activities were planned to start or finish in the last two weeks; there is nothing to look back on."
    if ok == n:
        return (f"All {n} items the {fd(c.prev_dd)} update planned for the last two weeks were achieved; "
                f"short-term delivery is not the constraint on Day 1.")
    miss = [r for r in lb if not r["lookback_achieved"]]
    a = Counter(c.A[r["activity_id"]]["asset_code"] for r in miss).most_common(1)[0][0]
    miss_txt = "the one miss is in" if n - ok == 1 else f"the {n - ok} misses are concentrated in"
    return f"{ok} of {n} items planned for the last two weeks were achieved; {miss_txt} {c.meta['assets'][a]}."


def s_lookback(dk: Deck):
    c = dk.c
    s = dk.slide("Two-week look-back", lb_title(c))
    cols = [("Activity", WID, "l", 1), ("Name", None, "l", 1), ("Owner", WOW, "c", 1), ("Event", 0.75, "c", 1),
            ("Planned (previous update)", 1.2, "c", 1), ("Actual", WDT, "c", 1), ("Achieved", 0.85, "c", 1),
            ("Total float (wd)", WNUM, "r", 1)]
    rows = lb_rows(c)
    bottom, shown = dk.table(s, ML, BODY_Y, CW, cols, rows, 5.85 - BODY_Y, max_lines=1, partial_ok=True, stretch=True)
    dk.note(s, ML, bottom + 0.04, CW, f"Look-back item: activity the {fd(c.prev_dd)} update forecast to start or "
            f"finish in the 14 days before {fd(c.dd)}; '–' total float = complete." +
            (f" Showing {shown} of {len(rows)}." if shown < len(rows) else ""))
    miss = [r for r in c.lookback() if not r["lookback_achieved"]]
    if miss:
        owners = sorted({c.owner_of(r["activity_id"]) for r in miss})
        dk.ask(s, "Ask", f"{join_and(owners)} to re-forecast the {pl(len(miss), 'missed item')} with a recovery "
                         f"date and cause before the next update; misses on the longest path are escalated.")
    else:
        dk.ask(s, "So what", c.narr["so_what"]["lookback"] + " Attention belongs on the look-ahead and the longest "
               "path, not on short-term delivery.")
    return s


def la_rows(c: Ctx, compact=False) -> list[list]:
    rows = []
    for a in c.lookahead():
        ev = "Start & finish" if a["lookahead_start"] and a["lookahead_finish"] else \
            "Start" if a["lookahead_start"] else "Finish"
        crit = a["is_critical"] or a["is_longest_path"]
        flag = {"text": "Yes" if crit else "No", "fill": TINT["red"] if crit else None, "bold": crit}
        if not flag["fill"]:
            flag.pop("fill")
        date = a["start"] if ev == "Start" else a["finish"]
        if compact:
            rows.append([c.id_label(a["activity_id"]), c.owner_of(a["activity_id"]), "Both" if ev == "Start & finish"
                         else ev, fd(date), tf_cell(a["total_float_d"])])
        else:
            rows.append([a["activity_id"], c.name(a["activity_id"]), c.owner_of(a["activity_id"]), ev, fd(a["start"]),
                         fd(a["finish"]), tf_cell(a["total_float_d"]), flag])
    return rows


def la_title(c: Ctx) -> str:
    la = c.lookahead()
    crit = [a for a in la if a["is_critical"] or a["is_longest_path"]]
    if not crit:
        return (f"{len(la)} activities start or finish in the next 14 days and none is critical; owners confirm "
                f"them at the weekly look-ahead.")
    return (f"{len(la)} activities start or finish in the next 14 days; {len(crit)} "
            f"{'is' if len(crit) == 1 else 'are'} critical or on the longest path and need owner confirmation "
            f"this week.")


def la_ask(c: Ctx) -> str:
    crit = [a for a in c.lookahead() if a["is_critical"] or a["is_longest_path"]][:3]
    if not crit:
        return ""
    parts = []
    for a in crit:
        ev = "finish" if a["lookahead_finish"] and not a["lookahead_start"] else "start"
        parts.append(f"{c.who(c.owner_of(a['activity_id']))} to confirm the {a['activity_id']} {ev} on "
                     f"{fd(a['finish'] if ev == 'finish' else a['start'])}")
    tfs = [a["total_float_d"] or 0 for a in crit]
    fl = ("zero float" if all(t == 0 for t in tfs) else "negative float" if all(t < 0 for t in tfs)
          else "zero or negative float")
    return join_and(parts) + f"; {'it carries' if len(crit) == 1 else 'each carries'} {fl}, so any slip moves " \
                             f"its asset's milestones."


def s_lookahead(dk: Deck):
    c = dk.c
    s = dk.slide("Two-week look-ahead", la_title(c))
    cols = [("Activity", WID, "l", 1), ("Name", None, "l", 1), ("Owner", WOW, "c", 1), ("Event", 1.1, "c", 1),
            ("Start", WDT, "c", 1), ("Finish", WDT, "c", 1), ("Total float (wd)", WNUM, "r", 1),
            ("Critical / longest path", 1.05, "c", 1)]
    rows = la_rows(c)
    bottom, shown = dk.table(s, ML, BODY_Y, CW, cols, rows, 5.85 - BODY_Y, max_lines=1, partial_ok=True, stretch=True)
    dk.note(s, ML, bottom + 0.04, CW, f"Look-ahead item: forecast to start or finish from {fd(c.dd)} to "
            f"{fd(_d(c.dd) + dt.timedelta(days=13))}; critical items first."
            + (f" Showing {shown} of {len(rows)}; full list in the controls workbook, Look-ahead sheet."
               if shown < len(rows) else ""))
    txt = la_ask(c)
    if txt:
        dk.ask(s, "Ask", txt)
    else:
        dk.ask(s, "So what", c.narr["so_what"]["lookahead"])
    return s


def s_trends(dk: Deck):
    c = dk.c
    tr = c.trend
    n = len(tr)
    slipped = sum(1 for r in tr if (r["day1_movement_d"] or 0) > 0)
    low = min(tr, key=lambda r: (r["day1_tf_d"], r["data_date"]))
    last = tr[-1]
    head = f"Day 1 slipped in {slipped} of {pl(n, 'update')}"
    floor = f"{sg(low['day1_tf_d'], 'wd')} on {fd(low['data_date'])}"
    mv = last["day1_movement_d"] if n > 1 else 0
    move_long = (f"; the {fd(c.dd)} update recovered {abs(mv)} days" if mv < 0 else
                 f"; the {fd(c.dd)} update lost a further {mv} days" if mv > 0 else "")
    move_short = (f", then recovered {abs(mv)} days by {fd(c.dd)}" if mv < 0 else
                  f", then lost {mv} more days by {fd(c.dd)}" if mv > 0 else "")
    dq_long = dq_short = ""
    if c.prev_sm:
        dqd = last["dq_score"] - c.prev_sm["dq_score"]
        verb = "fell to" if dqd < 0 else "rose to" if dqd > 0 else "held at"
        dq_long = f"{', but' if dqd < 0 else ', and'} schedule quality {verb} {dqs(last['dq_score'])} ({last['dq_rating']})"
        dq_short = f"; DQ {verb} {dqs(last['dq_score'])} ({last['dq_rating']})"
    title = first_fit(f"{head} and float bottomed at {floor}{move_long}{dq_long}.",
                      f"{head}; float bottomed at {floor}{move_short}{dq_short}.",
                      f"{head}; float hit {floor}{move_short}{dq_short}.")
    s = dk.slide("Trend analysis", title)
    cats = [fds(r["data_date"]) for r in tr]
    cw = (CW - GAP * 2) / 2
    ch_h, hd_h, cap_h = 1.75, 0.3, 0.48
    cells = [(ML, BODY_Y - 0.05), (ML + cw + GAP * 2, BODY_Y - 0.05),
             (ML, BODY_Y - 0.05 + hd_h + ch_h + cap_h + 0.1), (ML + cw + GAP * 2, BODY_Y - 0.05 + hd_h + ch_h + cap_h + 0.1)]
    # 1 Day 1 forecast trend
    x, y = cells[0]
    dk.heading(s, x, y, cw, "Day 1 forecast by update (target dashed)")
    vals = [excel_serial(r["day1_forecast"]) for r in tr]
    tgt = excel_serial(c.target)
    lo, hi = min(vals + [tgt]) - 7, max(vals + [tgt]) + 7
    # a label drawn above a point just under the target line would sit on the line: put it below instead
    dk.line_chart(s, x, y + hd_h, cw, ch_h, cats, [("Day 1 forecast", vals, NAVY, False),
                                                   ("Target", [tgt] * n, RED, True)],
                  fmt="dd-mmm-yy", vmin=lo, vmax=hi, major=7, legend=False, name="Chart Day 1 forecast",
                  label_fmt='dd"‑"mmm', label_pos=["below" if 0 <= tgt - v <= 9 else "above" for v in vals])
    dk.caption(s, x, y + hd_h + ch_h, cw, c.narr["so_what"]["day1_trend"] + f" Target {fd(c.target)}.")
    # 2 slippage trend
    x, y = cells[1]
    dk.heading(s, x, y, cw, "Slip vs previous period, Day 1 (calendar days)")
    mv = [r["day1_movement_d"] for r in tr]
    dk.bar_chart(s, x, y + hd_h, cw, ch_h, cats, [("Day 1 slip vs previous period (d)", mv, NAVY)],
                 point_colors=[RED if v > 0 else GREEN if v < 0 else SLATE for v in mv], name="Chart slippage")
    big = max(tr, key=lambda r: (r["day1_movement_d"], r["data_date"]))
    cr = next((ch for ch in c.changes() if ch["raised_data_date"] == big["data_date"] and ch["day1_impact_days"]), None)
    cap = f"Largest slip {sg(big['day1_movement_d'], 'd')} on {fd(big['data_date'])}"
    cap += f" ({cr['change_id']}, {lc_first(cr['title'])})." if cr else "."
    cap += " First bar is measured against BL0."
    dk.caption(s, x, y + hd_h + ch_h, cw, cap)
    # 3 float erosion
    x, y = cells[2]
    dk.heading(s, x, y, cw, "Day 1 total float by update (working days)")
    tf = [r["day1_tf_d"] for r in tr]
    nc = c.meta["near_critical_days"]                 # the deck's RAG rule: red < 0, amber 0 to nc wd
    dk.bar_chart(s, x, y + hd_h, cw, ch_h, cats, [("Day 1 total float (wd)", tf, NAVY)],
                 point_colors=[RED if v < 0 else AMBER if v <= nc else NAVY for v in tf], name="Chart float")
    first_neg = next((r for r in tr if r["day1_tf_d"] < 0), None)
    cap = (f"Float turned negative on {fd(first_neg['data_date'])} and stands at {sg(last['day1_tf_d'], 'wd')}; "
           if first_neg else f"Float stands at {sg(last['day1_tf_d'], 'wd')}; ")
    cap += f"{pl(last['negative_float_count'], 'activity', 'activities')} carry negative float."
    dk.caption(s, x, y + hd_h + ch_h, cw, cap)
    # 4 DQ trend
    x, y = cells[3]
    dk.heading(s, x, y, cw, "DQ score by update (Good ≥ 85, Fair ≥ 70)")
    dq = [r["dq_score"] for r in tr]
    dk.line_chart(s, x, y + hd_h, cw, ch_h, cats, [("DQ score", dq, TEAL, False), ("Good (85)", [85] * n, GREEN, True),
                                                   ("Fair (70)", [70] * n, AMBER, True)],
                  fmt="0", vmin=60 if min(dq) >= 65 else 50, vmax=100, major=10, legend=False, name="Chart DQ",
                  label_fmt="0.0", label_pos=["below" if any(0 <= t - v <= 7 for t in (85, 70)) else "above" for v in dq])
    sm = c.sm
    dk.caption(s, x, y + hd_h + ch_h, cw, f"DQ {dqs(sm['dq_score'])}/100 ({sm['dq_rating']}); CPLI "
               f"{ratio(sm['cpli'], 0.95)}, BEI {ratio(sm['bei'], 0.95)} (targets ≥ 0.95). Failing checks and owner "
               f"actions: slide {MONTHLY.index(s_quality) + 1}.")
    return s


def readiness_rows(c: Ctx) -> list[dict]:
    by = {}
    for r in c.S["readiness"]:
        by.setdefault(r["asset_code"], {})[r["stage"]] = r
    out = []
    for a, st in by.items():
        cc, d1 = st.get("Construction complete"), st.get("Day 1 ready")
        if not cc or not d1:
            continue
        need = (_d(d1["forecast"]) - _d(cc["forecast"])).days
        avail = (_d(d1["need_by"]) - _d(cc["forecast"])).days
        worst = max(st.values(), key=lambda r: (r["gap_d"] if r["gap_d"] is not None else -999))
        out.append({"asset": a, "cc": cc["forecast"], "d1": d1["forecast"], "need_by": d1["need_by"],
                    "gap": d1["gap_d"], "need": need, "avail": avail, "owner": c.owner_of(worst["activity_id"]),
                    "worst_stage": worst["stage"]})
    return out


def s_interfaces(dk: Deck):
    c = dk.c
    rr = readiness_rows(c)
    itf = c.S["interfaces"]
    late = sorted([i for i in itf if i["status"] == "Late"], key=lambda i: (-i["gap_days"], i["interface_id"]))
    worst = max(rr, key=lambda r: (r["gap"], r["asset"])) if rr else None
    if worst and worst["gap"] > 0:
        # readiness is measured against the latest finish that still protects Day 1 (late finish), not against an
        # interface need-by date (the receiver's baseline start): say which, so the two tables cannot contradict
        lead = f"{c.meta['assets'][worst['asset']]} is the readiness constraint: Day 1 ready {fd(worst['d1'])} is"
        tail = f"{len(late)} of {len(itf)} interfaces are late."
        title = first_fit(f"{lead} {worst['gap']} days past the latest date that protects Day 1; {tail}",
                          f"{lead} {worst['gap']} days later than Day 1 allows; {tail}")
    else:
        title = (f"Every asset reaches Day 1 ready before its need-by date; {len(late)} of {len(itf)} interfaces are "
                 f"late against the receiver's need date.")
    s = dk.slide("Interfaces and readiness gap", title)
    lw = 5.9
    dk.heading(s, ML, BODY_Y - 0.05, lw, "Construction complete to Day 1 ready: days needed vs available")
    cats = [SHORT_ASSET.get(r["asset"], r["asset"]) for r in rr]
    ch_h = 1.9
    dk.bar_chart(s, ML, BODY_Y + 0.25, lw, ch_h, cats,
                 [("Needed (forecast)", [r["need"] for r in rr], NAVY),
                  ("Available (to latest finish)", [r["avail"] for r in rr], TEAL)],
                 point_colors=[RED if r["need"] > r["avail"] else NAVY for r in rr],
                 horizontal=True, legend=True, name="Chart readiness")
    if worst:
        others = [r["avail"] - r["need"] for r in rr if r["asset"] != worst["asset"]]
        cap = (f"{SHORT_ASSET[worst['asset']]} needs {worst['need']} days but has {worst['avail']}"
               + (f"; the other assets have at least {min(others)} days in hand." if others else "."))
    else:
        cap = "No readiness data."
    yc = BODY_Y + 0.25 + ch_h
    dk.caption(s, ML, yc, lw, cap)
    rows = [[r["asset"], fd(r["cc"]), fd(r["d1"]), fd(r["need_by"]),
             tint_cell(sg(r["gap"]), "red" if r["gap"] > 0 else "green"), r["owner"]] for r in rr]
    b1, _ = dk.table(s, ML, yc + 0.5, lw, [("Asset", None, "l", 1), ("Construction complete", WDT, "c", 1),
                                           ("Day 1 ready", WDT, "c", 1), ("Latest finish", WDT, "c", 1),
                                           ("Readiness gap (d)", 0.85, "r", 1), ("Owner", WOW, "c", 1)],
                     rows, 5.85 - (yc + 0.5), max_lines=1, name="Readiness table")
    dk.note(s, ML, b1 + 0.04, lw, "Gap = Day 1 ready − latest finish. Owner = owner of the worst stage.")
    rx = ML + lw + 0.3
    rw = SW - ML - rx
    dk.heading(s, rx, BODY_Y - 0.05, rw, f"Late interfaces ({len(late)} of {len(itf)}), worst first")
    rows = [[i["interface_id"], short_if(i["description"], c.meta["assets"]), i["giver_owner"], i["receiver_owner"],
             fd(i["need_by"]), tint_cell(sg(i["gap_days"]), "red", True)] for i in late]
    bottom, shown = dk.table(s, rx, BODY_Y + 0.29, rw, [("ID", 0.6, "l", 1), ("Interface", None, "l", 2),
                                                         ("Owner", WOW, "c", 1), ("Receiver", 0.78, "c", 1),
                                                         ("Need-by", WDT, "c", 1), ("Interface gap (d)", 0.8, "r", 1)],
                             rows, 5.85 - (BODY_Y + 0.29), partial_ok=True, name="Interface table")
    dk.note(s, rx, bottom + 0.04, rw, "Owner = giver; need-by = receiver's baseline start; gap positive = late."
            + (f" Showing {shown} of {len(late)}." if shown < len(late) else ""))
    picks, seen = [], set()
    for i in late:
        if i["giver_owner"] not in seen:
            picks.append(i)
            seen.add(i["giver_owner"])
        if len(picks) == 2:
            break
    if picks:
        dk.ask(s, "Ask", "; ".join(f"{c.who(i['giver_owner'])} to recover {i['interface_id']} "
                                   f"{short_if(i['description'])} ({sg(i['gap_days'], 'd')})" for i in picks) + ".")
    else:
        dk.ask(s, "So what", c.narr["so_what"]["readiness"])
    return s


def s_risks(dk: Deck):
    c = dk.c
    risks = sorted(c.S["risks"], key=lambda r: (-r["score"], -r["schedule_impact_days"], r["risk_id"]))
    on_neg = [r for r in risks if r["min_linked_float_d"] is not None and r["min_linked_float_d"] < 0]
    top = max(risks, key=lambda r: (r["schedule_impact_days"], r["score"])) if risks else None
    n_high = sum(1 for r in risks if r["rating"] == "High")
    if top:
        rid, days, what = top["risk_id"], top["schedule_impact_days"], lc_first(top["title"])
        lead = f"{len(on_neg)} of {len(risks)} risks sit on negative-float work and {n_high} are rated High"
        title = first_fit(f"{lead}; {what} ({rid}) carries the largest exposure at {days} days.",
                          f"{lead}; {rid}, {what}, is the largest exposure at {days} days.",
                          f"{lead}; {rid} carries the largest exposure at {days} days.")
    else:
        title = "No risks are open in the register for this update."
    s = dk.slide("Top risks", title)
    rows = []
    for r in risks:
        rows.append([r["risk_id"], r["title"], r["owner_code"], str(r["score"]),
                     {"text": r["rating"], "fill": {"High": RED, "Medium": AMBER, "Low": GREEN}[r["rating"]],
                      "color": "FFFFFF", "bold": True},
                     sg(r["trend"]) if r["trend"] else "0", str(r["schedule_impact_days"]),
                     tf_cell(r["min_linked_float_d"]), r["mitigation"], r["mitigation_owner"]])
    cols = [("Risk", 0.6, "l", 1), ("Title", 2.75, "l", 2), ("Owner", WOW, "c", 1), ("Risk score", 0.62, "r", 1),
            ("Rating", 0.8, "c", 1), ("Score change", 0.7, "r", 1), ("Schedule impact (d)", 0.8, "r", 1),
            ("Lowest linked TF (wd)", 0.85, "r", 1), ("Mitigation", None, "l", 2), ("Mitigation owner", 1.65, "l", 2)]
    bottom, shown = dk.table(s, ML, BODY_Y, CW, cols, rows, 5.85 - BODY_Y, partial_ok=True)
    dk.note(s, ML, bottom + 0.04, CW, "Risk score = probability (1-5) x impact (1-5); High ≥ 15. Score change vs "
            "previous update, negative = improving." + (f" Showing {shown} of {len(risks)} by score."
                                                         if shown < len(risks) else ""))
    if top:
        second = next((r for r in risks if r["risk_id"] != top["risk_id"] and r["min_linked_float_d"] is not None
                       and r["min_linked_float_d"] < 0), None)
        def mit(r):  # a mitigation in brackets, its own semicolons as commas, so the ask has one ';' per request
            return lc_first(r["mitigation"]).replace("; ", ", ")
        txt = f"{top['mitigation_owner']} to report on the {top['risk_id']} mitigation ({mit(top)})"
        if second:
            txt += f"; {second['mitigation_owner']} to confirm the {second['risk_id']} mitigation ({mit(second)})"
        dk.ask(s, "Ask", txt + " at the next Steering Committee.")
    return s


def decisions_title(c: Ctx) -> str:
    op = c.open_decisions()
    if not op:
        return "No decisions are open; every decision raised to date has been closed."
    due = [d for d in op if not d["overdue"]]
    od = [d for d in op if d["overdue"]]
    t = f"{pl(len(op), 'decision')} {'is' if len(op) == 1 else 'are'} open"
    if due:
        t += ": " + " and ".join(
            (f"{d['decision_id']} is needed by {fd(d['needed_by'])}" if i == 0 else
             f"{d['decision_id']} by {fd(d['needed_by'])}") for i, d in enumerate(due))
    if not od:
        return t + "."
    ids = join_and([d["decision_id"] for d in od])
    tail = f"{ids} {'has' if len(od) == 1 else 'have'} been overdue since {fd(min(d['needed_by'] for d in od))}"
    return first_fit(t + (", and " if due else ": ") + tail + ".", t + ("; " if due else ": ") + tail + ".")


def decision_status_cell(d) -> dict:
    if d["status"] == "Closed":
        return tint_cell("Closed", "green")
    return tint_cell("Overdue", "red", True) if d["overdue"] else tint_cell("Open", "amber", True)


def s_decisions(dk: Deck):
    c = dk.c
    s = dk.slide("Decision log", decisions_title(c))
    ds = c.decisions()
    ds = sorted(ds, key=lambda d: (d["status"] != "Open", not d["overdue"], d["needed_by"] if d["status"] == "Open"
                                   else "", "" if d["status"] == "Open" else d["decision_id"]), reverse=False)
    ds = [d for d in ds if d["status"] == "Open"] + sorted([d for d in ds if d["status"] != "Open"],
                                                           key=lambda d: d["needed_by"], reverse=True)
    rows = []
    for d in ds:
        la = c.act.get(d["linked_activity"], {})
        rows.append([d["decision_id"], d["ask"], d["owner"], fd(d["needed_by"]), decision_status_cell(d),
                     sg(d["days_to_need"]) if d["status"] == "Open" else "–", d["linked_activity"],
                     tf_cell(la.get("total_float_d") if la.get("status") != "TK_Complete" else None),
                     d["outcome"] or "Awaiting decision"])
    cols = [("ID", 0.6, "l", 1), ("Decision required", None, "l", 2), ("Owner", 1.65, "l", 2),
            ("Needed by", WDT, "c", 1), ("Status", 0.85, "c", 1), ("Days to need", 0.72, "r", 1),
            ("Linked activity", WID, "l", 1), ("Total float (wd)", 0.75, "r", 1), ("Outcome", 2.0, "l", 2)]
    bottom, shown = dk.table(s, ML, BODY_Y, CW, cols, rows, 5.85 - BODY_Y, partial_ok=True)
    if shown < len(rows):
        dk.note(s, ML, bottom + 0.04, CW, f"Showing {shown} of {len(rows)} decisions; open first, then the most "
                f"recently closed. Full log: dashboard, Risks, decisions & recovery tab.")
    op = c.open_decisions()
    if op:
        parts = []
        for d in op:
            if d["overdue"]:
                parts.append(f"{d['owner']} to close overdue {d['decision_id']} now")
            else:
                parts.append(f"{d['owner']} to decide {d['decision_id']} by {fd(d['needed_by'])}")
        dk.ask(s, "Ask", "; ".join(parts) + ".")
    else:
        dk.ask(s, "So what", "No open decisions; the committee is asked to note the log.")
    return s


def scen_label(r: dict) -> str:
    if r["scenario_id"] == "BASE":
        return "Base (no recovery)"
    if "," in r["options"]:
        return r["scenario_id"].replace("+", " + ")
    return f"{r['scenario_id']}: {r['name'].split(':')[0].split(' with ')[0]}"


def s_recovery(dk: Deck):
    c = dk.c
    sc = c.scenarios()
    rec = next((r for r in sc if r["recommended"]), None)
    if not sc or not rec:
        s = dk.slide("Recovery plan", "Recovery scenarios are modelled on the latest update only; none apply to this "
                     "data date.")
        dk.ask(s, "So what", "See the latest pack for recovery options.")
        return s
    singles = [r for r in sc if r["scenario_id"] not in ("BASE",) and "," not in r["options"]]
    margin = 5
    ok_single = [r for r in singles if r["day1_tf_d"] >= margin]
    title = (f"Recovery {rec['options'].replace(',', ' + ')} returns Day 1 to {fd(rec['day1_forecast'])} with "
             f"{sg(rec['day1_tf_d'], 'wd')} of float; ")
    title += (f"no single option gives the {sg(margin, 'wd')} margin the programme needs." if not ok_single else
              f"{join_and([r['scenario_id'] for r in ok_single])} alone would also give a {sg(margin, 'wd')} margin.")
    s = dk.slide("Recovery plan", title)
    lw = 4.5
    dk.heading(s, ML, BODY_Y - 0.05, lw, "Day 1 total float by scenario (wd)")
    cats = [r["scenario_id"].replace("BASE", "Base").replace("+", " + ") for r in sc]
    tf = [r["day1_tf_d"] for r in sc]
    dk.bar_chart(s, ML, BODY_Y + 0.25, lw, 3.25, cats, [("Day 1 total float (wd)", tf, SLATE)],
                 point_colors=[TEAL if r["recommended"] else RED if r["day1_tf_d"] < 0 else SLATE for r in sc],
                 name="Chart scenarios")
    c_only = next((r for r in singles if r["scenario_id"] == "C"), None)
    cap = (f"Recommended {rec['scenario_id'].replace('+', ' + ')} (teal) gains {sg(rec['float_gain_d'], 'wd')} and "
           f"leaves {sg(rec['day1_tf_d'], 'wd')}")
    if c_only:
        cap += f"; C alone gains {sg(c_only['float_gain_d'], 'wd')} and leaves Day 1 at {sg(c_only['day1_tf_d'], 'wd')}."
    else:
        cap += "."
    dk.caption(s, ML, BODY_Y + 3.5, lw, cap, h=0.75)
    rx = ML + lw + 0.3
    rw = SW - ML - rx
    rows = []
    for r in sc:
        f = r["recommended"]
        rows.append([{"text": scen_label(r), "bold": f, **({"fill": TINT["teal"]} if f else {})},
                     fd(r["day1_forecast"]), tf_cell(r["day1_tf_d"]), sg(r["float_gain_d"]), str(r["neg_float_count"]),
                     r["residual_risk"], r["decision"] or "–", c.code_for(r["owner"]) if r["owner"] else "–"])
    cols = [("Scenario", None, "l", 2), ("Day 1 forecast", WDT, "c", 1), ("Day 1 total float (wd)", 0.8, "r", 1),
            ("Float gain (wd)", 0.75, "r", 1), ("Negative-float activities", 0.9, "r", 1),
            ("Residual risk", 0.8, "c", 1), ("Decision", 0.92, "c", 2), ("Owner", 0.9, "c", 2)]
    bottom, _ = dk.table(s, rx, BODY_Y - 0.05, rw, cols, rows, 3.1)
    yb = bottom + 0.15
    paras = [P(R("Recommendation: ", 12, True, NAVY),
               R(f"approve {rec['options'].replace(',', ' + ')} ({rec['decision']}). It is the smallest option set "
                 f"that leaves at least {sg(margin, 'wd')} of Day 1 float, the programme's minimum margin; residual "
                 f"risk {rec['residual_risk']}.", 12, False, TEXT), after=4),
             P(R("Enabling cost: ", 11, True, NAVY), R(rec["cost"] + ".", 11, False, TEXT)),
             P(R("Method: ", 11, True, NAVY), R("each option is a set of duration, logic and calendar changes "
                                                "rescheduled by the CPM engine on the latest XER.", 11, False, TEXT))]
    dk.text(s, rx, yb, rw, 5.8 - yb, paras, name="Recommendation", fill=TINT["navy"])
    ids = [x.strip() for x in rec["decision"].split(",")]
    lines = []
    for d in c.decisions():
        if d["decision_id"] in ids:
            lines.append(f"{d['decision_id']} · {d['owner']} · by {fd(d['needed_by'])}: {d['ask']}")
    dk.ask(s, "What we need, from whom, by when", "", y=5.92, h=0.93, extra=lines)
    return s


def s_governance(dk: Deck):
    c = dk.c
    ch = c.changes()
    bl_cr = next((x for x in ch if str(x["baseline_effect"]).startswith(f"{c.bl} created")), None)
    bl0_cr = next((x for x in ch if str(x["baseline_effect"]).startswith("BL0 created")), None)
    nobl = [x for x in ch if x["day1_impact_days"] and "No re-baseline" in str(x["baseline_effect"])]
    pending = [x for x in ch if x["status"] == "Pending"]
    this = [x for x in ch if x["raised_data_date"] == c.dd]
    long_, short = f"{c.bl} remains the baseline in force", f"{c.bl} stays in force"
    if bl_cr:
        long_ += f" (approved {fd(bl_cr['approval_date'])} under {bl_cr['change_id']})"
        short += f" ({bl_cr['change_id']} approved {fd(bl_cr['approval_date'])})"
    if nobl:
        x = max(nobl, key=lambda x: x["day1_impact_days"])
        long_ += f"; {x['change_id']} added {x['day1_impact_days']} days to Day 1 without a re-baseline"
        short += f"; {x['change_id']} added {x['day1_impact_days']} days to Day 1 with no re-baseline"
    if pending:
        ids, verb = join_and([p['change_id'] for p in pending]), "is" if len(pending) == 1 else "are"
        long_ += f", and {ids} {verb} pending"
        short += f"; {ids} {verb} pending"
    s = dk.slide("Change and baseline governance", first_fit(long_ + ".", short + "."))
    day1 = next((m for m in c.milestones() if m["activity_id"] == c.meta["day1_id"]), None)
    specs = [
        ("BL0 (original baseline)", fd(day1["bl0_finish"]) if day1 else "–",
         f"Day 1 · approved {fd(bl0_cr['approval_date'])} ({bl0_cr['change_id']})" if bl0_cr else "Day 1 in BL0",
         SLATE),
        ("BL1 (baseline in force)" if c.bl == "BL1" else "BL1 (not yet approved)",
         fd(day1["bl1_finish"]) if day1 else "–",
         (f"Day 1 in BL1 · {bl_cr['baseline_effect'].replace('BL1 created', 'issued')}" if bl_cr and c.bl == "BL1"
          else "Day 1 in BL1"), TEAL),
        ("Day 1 forecast", fd(c.sm["day1_forecast"]),
         f"{sg(c.sm['day1_var_bl1_d'], 'd')} vs BL1 · {sg(c.sm['day1_var_bl0_d'], 'd')} vs BL0", RED),
        ("Changes this period", str(len(this)), join_and([f"{x['change_id']} {x['status'].lower()}" for x in this])
         or "none raised", AMBER if this else GREEN),
    ]
    dk.tiles(s, BODY_Y, 0.85, specs)
    y = BODY_Y + 0.85 + 0.15
    rows = []
    for x in sorted(ch, key=lambda x: x["change_id"], reverse=True):
        st = {"Approved": "green", "Pending": "amber"}.get(x["status"])
        rows.append([x["change_id"], x["title"], x["change_type"], fd(x["raised_data_date"]),
                     fd(x["approval_date"]) if x["approval_date"] else "–", tint_cell(x["status"], st),
                     x["baseline_effect"], sg(x["day1_impact_days"]) if x["day1_impact_days"] else "–",
                     x["approver"]])
    cols = [("Change", 0.78, "l", 1), ("Title", None, "l", 3), ("Type", 1.0, "l", 2),
            ("Reported in update", WDT, "c", 1), ("Approved", WDT, "c", 1), ("Status", 0.85, "c", 1),
            ("Baseline effect", 2.1, "l", 2), ("Day 1 impact (d)", 0.85, "r", 1), ("Owner", 1.55, "l", 2)]
    bottom, shown = dk.table(s, ML, y, CW, cols, rows, 5.70 - y, partial_ok=True)
    dk.note(s, ML, bottom + 0.04, CW, "Newest first. Owner = approver. Day 1 impact in calendar days at the update "
            "that first reported the change; impacts are not additive, as later progress and recovery also move Day 1."
            + (f" Showing {shown} of {len(rows)}; full log: output/csv/fact_change.csv." if shown < len(rows) else ""),
            lines=2)
    txt = f"variance stays reported against {c.bl}"
    if pending:
        txt += "; " + "; ".join(f"{p['change_id']} is {p['baseline_effect'][0].lower() + p['baseline_effect'][1:]}"
                                for p in pending)
    txt += "; no re-baseline is proposed this period."
    dk.ask(s, "So what", txt[0].upper() + txt[1:])
    return s


def scorecard_rows(c: Ctx) -> list[list]:
    rows = []
    for o in sorted(c.S["owner_scorecard"], key=lambda o: (o["owner_dq"], o["owner_code"])):
        ns = {k[2:]: v for k, v in o.items() if k.startswith("n_") and v}
        main = sorted(ns.items(), key=lambda kv: (-kv[1], kv[0]))[0] if ns else None
        dq = o["owner_dq"]
        rows.append([o["owner_code"], str(o["activities"]), str(o["flagged"]),
                     tint_cell(f"{dq:.0f}%", "red" if dq < 60 else "amber" if dq < 80 else "green"),
                     str(o["update_issues"]), str(o["logic_issues"]), f"{main[0]} ({main[1]})" if main else "–"])
    return rows


def checks_rows(c: Ctx) -> list[list]:
    return [[f["check_id"], short_check(f["check_name"]), check_result(f), pts(f["weight"] - f["score"]),
             str(f["count"] if f["count"] is not None else "–"), c.check_owner(f)] for f in c.failing_checks()]


def dq_title(c: Ctx) -> str:
    sm, p = c.sm, c.prev_sm
    fc = [lc_first(short_check(f["check_name"])) for f in c.failing_checks()[:3]]
    low = [o["owner_code"] for o in sorted(c.S["owner_scorecard"], key=lambda o: (o["owner_dq"], o["owner_code"]))[:3]]
    if p:
        verb = "fell to" if sm["dq_score"] < p["dq_score"] else "rose to" if sm["dq_score"] > p["dq_score"] \
            else "held at"
        move = f" {verb} {dqs(sm['dq_score'])}/100 ({sm['dq_rating']})" + \
            ("" if verb == "held at" else f" from {dqs(p['dq_score'])}")
    else:
        move = f" is {dqs(sm['dq_score'])}/100 ({sm['dq_rating']})"
    checks = [f"; {join_and(fc[:k])} lose most points" for k in (3, 2) if fc] or [""]
    owners = f"; {join_and(low)} have the lowest Owner DQ" if low else ""
    owners_short = f"; {join_and(low)} score lowest" if low else ""
    return first_fit(*[f"Schedule quality{move}{ck}{owners}." for ck in checks],
                     *[f"DQ{move}{ck}{owners_short}." for ck in checks],
                     f"DQ{move}{owners_short}.")


def s_quality(dk: Deck):
    c = dk.c
    s = dk.slide("Schedule-quality actions for schedule owners", dq_title(c))
    lw = 5.95
    dk.heading(s, ML, BODY_Y - 0.05, lw, "Owner scorecard, lowest Owner DQ first")
    cols = [("Owner", 0.7, "c", 1), ("Activities", 0.85, "r", 1), ("Flagged", 0.8, "r", 1),
            ("Owner DQ", 0.85, "r", 1), ("Update issues", 0.85, "r", 1), ("Logic issues", 0.85, "r", 1),
            ("Main check", 1.05, "c", 1)]
    tbl_b = 4.95
    b1, _ = dk.table(s, ML, BODY_Y + 0.29, lw, cols, scorecard_rows(c), tbl_b - (BODY_Y + 0.29), max_lines=1,
                     name="Owner scorecard", stretch=True)
    # the two DQ measures are different: say so, and what the issue columns count
    n1 = dk.note(s, ML, b1 + 0.03, lw, "Owner DQ = share of the owner's activities with no flag (programme DQ = "
                 "weighted check score). Logic: D01, D05, U07; update: U01, U03–U05, U09.", lines=2)
    rx = ML + lw + 0.3
    rw = SW - ML - rx
    fails = c.failing_checks()
    dk.heading(s, rx, BODY_Y - 0.05, rw, f"Failing checks ({len(fails)}), most points lost first")
    cols = [("Check", 0.6, "l", 1), ("Name", None, "l", 1), ("Result vs threshold", 1.45, "c", 1),
            ("Points lost", 0.7, "r", 1), ("Items", 0.6, "r", 1), ("Owner", WOW, "c", 1)]
    b2, _ = dk.table(s, rx, BODY_Y + 0.29, rw, cols, checks_rows(c), tbl_b - (BODY_Y + 0.29), max_lines=1,
                     name="Failing checks", stretch=True)
    info = c.info_checks()
    n2 = dk.note(s, rx, b2 + 0.03, rw, ("Weight 0 (no points): " + "; ".join(
        f"{f['check_id']} {lc_first(short_check(f['check_name']))} ({pl(f['count'] or 0, 'item')})" for f in info) + ". "
        if info else "") + "Owner = owner of most offending items.", lines=2)
    y = max(n1.top + n1.height, n2.top + n2.height) / 914400 + 0.1
    lines = []
    for f in fails[:4]:
        o = c.check_owner(f)
        lines.append(f"{c.who(o)}: {ACTION.get(f['check_id'], 'review the check')} — {f['check_id']} "
                     f"{lc_first(short_check(f['check_name']))}: {c.offenders_of(f, o)} of "
                     f"{pl(f['count'] or 0, 'item')}")
    bottom = FOOT_LINE_Y - 0.1
    if lines:
        paras = [P(R("Actions for schedule owners before the next update", 12, True, NAVY))] + \
            [BUL(e, 11.5) for e in lines]
        h = min(bottom - y, para_height(paras, CW - 0.07 - 2 * PAD_X) + 2 * PAD_Y + 0.12)
        dk.ask(s, "Actions for schedule owners before the next update", "", y=bottom - h, h=h, extra=lines)
    else:
        dk.ask(s, "So what", "Every check passes; owners keep the update discipline.", y=bottom - 0.6, h=0.6)
    return s


APPENDIX_MEASURES = ["Day 1 forecast", "Day 1 total float", "Total float", "Finish variance vs BL1",
                     "Slip vs previous period", "Interface gap", "Readiness gap", "DQ score",
                     "CPLI", "BEI", "Reconciliation status"]


RECON_KEYS = ["R01", "R07", "R08", "R11", "R12", "R13", "R14", "R15", "R16", "R05", "R06", "R10"]


def recon_rows(c: Ctx) -> list[list]:
    rec = {r["control_id"]: r for r in c.S["reconciliation"]}
    rows = []
    for k in RECON_KEYS:
        r = rec.get(k)
        if not r:
            continue
        sv, dv = str(r["source_value"]), str(r["dashboard_value"])
        if k == "R15":
            sv, dv = sv[:12] + "…", dv[:12] + "…"
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", sv) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dv):
            sv, dv = fd(sv), fd(dv)                     # dates in the house format, like the rest of the pack
        # R12 excludes level-of-effort activities, so it differs from the 'Critical' tile, which counts them
        ctl = {"R12": "Critical activities (excl. LOE)", "R16": "Re-schedule = P6 dates"}.get(k, r["control"])
        rows.append([k, ctl, sv, dv, tint_cell("Pass" if r["passed"] else "Fail",
                                                        "green" if r["passed"] else "red", not r["passed"]), "PMO"])
    return rows


RECON_COLS = [("Control", 0.65, "l", 1), ("Description", None, "l", 1), ("Source (XER)", 1.2, "r", 1),
              ("Dashboard (JSON)", 1.2, "r", 1), ("Result", 0.6, "c", 1), ("Owner", WOW, "c", 1)]


def s_appendix_lineage(dk: Deck):
    c = dk.c
    sm = c.sm
    title = (f"Every number in this pack traces to {c.snap['source_file']} through one reconciled model: "
             f"{sm['controls_passed']} of {sm['controls_total']} controls passed.")
    s = dk.slide("Appendix A · data lineage, reconciliation and method", title)
    dk.heading(s, ML, BODY_Y - 0.05, CW, "Data lineage: each step feeds the next; a failed control stops the run")
    steps = c.D["lineage"]
    gap, bh = 0.1, 1.22
    bw = (CW - gap * (len(steps) - 1)) / max(1, len(steps))
    y = BODY_Y + 0.3
    short_step = {"CPM re-schedule + quality": "Re-schedule + quality"}   # keeps every step heading on one line
    for i, st in enumerate(steps):
        dk.text(s, ML + i * (bw + gap), y, bw, bh,
                [P(R(f"{i + 1}  {short_step.get(st['step'], st['step'])}", 10.5, True, NAVY)),
                 P(R(st["detail"].replace("->", "→"), 10, False, MUTED))],
                name="Lineage step", fill=TINT["navy"] if i % 2 == 0 else BG)
    y += bh + 0.12
    lw = 7.2
    allp = sm["controls_passed"] == sm["controls_total"]
    dk.heading(s, ML, y, lw, f"Key reconciliation controls ({'all ' if allp else ''}{sm['controls_passed']}"
                             f"{'' if allp else ' of ' + str(sm['controls_total'])} controls pass)")
    rows = recon_rows(c)
    bottom, shown = dk.table(s, ML, y + 0.32, lw, RECON_COLS, rows, 6.55 - (y + 0.32), max_lines=1, partial_ok=True)
    if shown < len(rows):
        dk.note(s, ML, bottom + 0.02, lw, f"{shown} of {len(rows)} key controls shown; all controls in the controls "
                f"workbook, Reconciliation sheet.")
    rx = ML + lw + 0.3
    rw = SW - ML - rx
    own = [(k, v["name"]) for k, v in c.owners.items() if k != "UNASSIGNED"]
    owner_runs = [R("Owner codes: ", 10, True, NAVY)]
    for i, (k, nm) in enumerate(own):                # bold code, then its organisation: 'MEP MEP & Systems ...' reads
        owner_runs += [R(k, 10, True, TEXT), R(" " + nm + (" · " if i < len(own) - 1 else "."), 10, False, TEXT)]
    docs = ", ".join(d["title"] for d in c.D.get("governance_docs", []))
    paras = [P(R("Method", 11, True, NAVY), after=2),
             P(R("Fictional programme and data. Schedules are produced by a custom CPM engine that follows Primavera P6 "
                 "conventions (retained logic, TF = LF − EF) and are exported in genuine P6 XER format; no Primavera "
                 "P6 licence was used.", 10, False, TEXT), after=4),
             P(*owner_runs, after=4),
             P(R("Governance: ", 10, True, NAVY), R(f"{docs}, all in the ", 10, False, TEXT),
               R("GitHub repository", 10, False, TEXT, link=REPO), R(".", 10, False, TEXT))]
    h = min(FOOT_LINE_Y - 0.12 - (y + 0.04), para_height(paras, rw - 2 * PAD_X) + 2 * PAD_Y + 0.12)
    dk.text(s, rx, y + 0.04, rw, h, paras, name="Method note", fill=BG)
    return s


def s_appendix_definitions(dk: Deck):
    c = dk.c
    title = first_fit("Every measure in this pack has one definition, shared with the dashboard and the Power BI model; "
                      "floats are in working days and variances in calendar days.",
                      "One definition per measure, shared with the dashboard and the Power BI model; floats are in "
                      "working days, variances in calendar days.",
                      "One definition per measure, shared with the dashboard and Power BI; floats in working days, "
                      "variances in calendar days.")
    s = dk.slide("Appendix B · definitions", title)
    defs = {d["measure"]: d for d in c.D["definitions"]}
    unit = {"working days": "wd", "calendar days": "d", "points": "points", "%": "%"}
    rows = [[f"{m} ({unit[defs[m]['unit']]})" if defs[m]["unit"] in unit else m, clean_narr(defs[m]["definition"]),
             clean_narr(defs[m]["formula"]), defs[m]["owner"]] for m in APPENDIX_MEASURES if m in defs]
    nc = c.meta["near_critical_days"]
    rows.insert(2, ["RAG by asset", f"Minimum total float of the asset's incomplete activities: Red below 0 wd, Amber "
                    f"0 to {nc} wd, Green above (same rule as the dashboard).",
                    "minimum total float (wd) of incomplete activities", "Programme Controls Manager"])
    bottom, shown = dk.table(s, ML, BODY_Y, CW, [("Measure", 2.2, "l", 1), ("Definition", None, "l", 2),
                                                  ("Formula", 2.6, "l", 2), ("Owner", 2.2, "l", 1)],
                             rows, 5.85 - BODY_Y, partial_ok=True)
    dk.note(s, ML, bottom + 0.04, CW, f"{shown} of {len(defs)} measures shown; all are defined in DATA_DICTIONARY.md "
            f"and in dashboard.json (definitions).")
    dk.ask(s, "So what", "The dashboard, the Power BI model and this pack read the same reconciled file and the same "
           "definitions, so a number quoted at the steering committee can be traced to its XER field.")
    return s


# ----------------------------------------------------------------------------------------------- fortnightly
def s_f_milestones(dk: Deck):
    c = dk.c
    vk = c.var_key()
    ms = c.incomplete_ms()
    moved = [m for m in ms if m["movement_vs_prev_d"]]
    later = [m for m in moved if m["movement_vs_prev_d"] > 0]
    earlier = [m for m in moved if m["movement_vs_prev_d"] < 0]
    prev = fd(c.prev_dd) if c.prev_dd else "the baseline"
    if later:
        w = max(later, key=lambda m: (m["movement_vs_prev_d"], m["activity_id"]))
        title = (f"{pl(len(later), 'milestone')} slipped since {prev}, worst {short_name(c.name(w['activity_id']))} "
                 f"{w['activity_id']} by {w['movement_vs_prev_d']} days; {len(earlier)} moved earlier.")
    elif earlier:
        lo = min(m["movement_vs_prev_d"] for m in earlier)
        hi = max(m["movement_vs_prev_d"] for m in earlier)
        a = Counter(c.A[m["activity_id"]]["asset_code"] for m in earlier).most_common(1)[0][0]
        rng = f"{abs(hi)}-{abs(lo)}" if hi != lo else f"{abs(lo)}"
        title = (f"No milestone slipped since {prev}; {len(earlier)} moved {rng} days earlier, led by "
                 f"{c.meta['assets'][a]}.")
    else:
        title = f"No milestone moved since {prev}; forecasts hold against {c.bl}."
    s = dk.slide("Fortnightly flash · milestone movement", title)
    rows_src = sorted(moved, key=lambda m: (-abs(m["movement_vs_prev_d"]), m["activity_id"])) or \
        sorted(ms, key=lambda m: (-(m[vk] or 0), m["activity_id"]))
    rows = []
    for m in rows_src:
        pf = _d(m["forecast_finish"]) - dt.timedelta(days=m["movement_vs_prev_d"] or 0)
        rows.append([m["activity_id"], c.name(m["activity_id"]), m["owner_code"], fd(pf), fd(m["forecast_finish"]),
                     slip_cell(m["movement_vs_prev_d"]), var_cell(m[vk]), tf_cell(m["total_float_d"])])
    cols = [("Milestone", WID, "l", 1), ("Name", None, "l", 1), ("Owner", WOW, "c", 1),
            ("Previous forecast", 1.05, "c", 1), ("Forecast", WDT, "c", 1), ("Slip vs previous period (d)", 1.2, "r", 1),
            (f"Finish variance vs {c.bl} (d)", 1.2, "r", 1), ("Total float (wd)", 0.95, "r", 1)]
    bottom, shown = dk.table(s, ML, BODY_Y, CW, cols, rows, 5.85 - BODY_Y, max_lines=1, partial_ok=True, stretch=True)
    dk.note(s, ML, bottom + 0.04, CW, f"Milestones whose forecast moved since {prev}, largest movement first."
            + (f" Showing {shown} of {len(rows)}." if shown < len(rows) else ""))
    dk.ask(s, "So what", c.narr["so_what"]["milestones"] + " " + c.narr["so_what"]["day1_trend"])
    return s


def s_f_lookbackahead(dk: Deck):
    c = dk.c
    lb = c.lookback()
    la = c.lookahead()
    ok = sum(1 for r in lb if r["lookback_achieved"])
    crit = [a for a in la if a["is_critical"] or a["is_longest_path"]]
    title = (f"{ok} of {len(lb)} look-back items were achieved, and {len(la)} activities start or finish in the next "
             f"14 days; {len(crit)} of them {'is' if len(crit) == 1 else 'are'} critical.")
    s = dk.slide("Fortnightly flash · look-back and look-ahead", title)
    hw = (CW - 0.3) / 2
    dk.heading(s, ML, BODY_Y - 0.05, hw, f"Look-back: last 14 days ({ok} of {len(lb)} achieved)")
    cols = [("Activity", None, "l", 2), ("Owner", WOW, "c", 1), ("Event", 0.62, "c", 1),
            ("Planned", WDT, "c", 1), ("Achieved", 0.82, "c", 1)]
    b1, s1 = dk.table(s, ML, BODY_Y + 0.29, hw, cols, lb_rows(c, compact=True), 5.6 - (BODY_Y + 0.29), max_lines=1,
                      partial_ok=True)
    rx = ML + hw + 0.3
    dk.heading(s, rx, BODY_Y - 0.05, hw, f"Look-ahead: next 14 days ({len(crit)} critical)")
    cols = [("Activity", None, "l", 2), ("Owner", WOW, "c", 1), ("Event", 0.62, "c", 1),
            ("Date", WDT, "c", 1), ("Total float (wd)", 0.95, "r", 1)]
    b2, s2 = dk.table(s, rx, BODY_Y + 0.29, hw, cols, la_rows(c, compact=True), 5.6 - (BODY_Y + 0.29), max_lines=1,
                      partial_ok=True)
    if s1 < len(lb):
        dk.note(s, ML, b1 + 0.04, hw, f"Showing {s1} of {len(lb)}; misses first.")
    if s2 < len(la):
        dk.note(s, rx, b2 + 0.04, hw, f"Showing {s2} of {len(la)}; critical first. Full list: controls workbook.")
    txt = la_ask(c)
    dk.ask(s, "Ask" if txt else "So what", txt or c.narr["so_what"]["lookahead"])
    return s


def s_f_critical(dk: Deck):
    c = dk.c
    s = dk.slide("Fortnightly flash · critical path status", cp_title(c))
    lw = 4.0
    tr = c.trend
    dk.heading(s, ML, BODY_Y - 0.05, lw, "Day 1 total float by update (wd)")
    tf = [r["day1_tf_d"] for r in tr]
    dk.bar_chart(s, ML, BODY_Y + 0.25, lw, 3.0, [fds(r["data_date"]) for r in tr],
                 [("Day 1 total float (wd)", tf, NAVY)],
                 point_colors=[RED if v < 0 else AMBER if v <= c.meta["near_critical_days"] else NAVY for v in tf],
                 name="Chart float")
    dk.caption(s, ML, BODY_Y + 3.25, lw, c.narr["so_what"]["critical_path"], h=0.62)
    rx = ML + lw + 0.3
    rw = SW - ML - rx
    dk.heading(s, rx, BODY_Y - 0.05, rw, "Longest path in sequence (level of effort excluded)")
    rows = [[r[0], r[1], r[2], r[4], r[5], r[6]] for r in cp_rows(c)]
    cols = [("Activity", WID, "l", 1), ("Name", None, "l", 2), ("Owner", WOW, "c", 1), ("Finish", WDT, "c", 1),
            ("Total float (wd)", WNUM, "r", 1), ("Slip vs previous period (d)", 0.95, "r", 1)]
    bottom, shown = dk.table(s, rx, BODY_Y + 0.29, rw, cols, rows, 5.70 - (BODY_Y + 0.29), max_lines=1,
                             partial_ok=True)
    if shown < len(rows):
        loe = lp_loe(c)
        dk.note(s, rx, bottom + 0.04, rw, f"Showing {shown} of {len(rows)} longest-path activities, in sequence"
                + (f"; {len(rows) + len(loe)} with the level-of-effort {join_and(loe)}, tagged LOE · U07 (a defect)."
                   if loe else "."), lines=2)
    dk.ask(s, "Ask", cp_ask(c))
    return s


def s_f_decisions(dk: Deck):
    c = dk.c
    s = dk.slide("Fortnightly flash · decisions and escalations", decisions_title(c))
    dk.heading(s, ML, BODY_Y - 0.05, CW, "Open decisions")
    op = c.open_decisions()
    rows = [[d["decision_id"], d["ask"], d["owner"], fd(d["needed_by"]), decision_status_cell(d), sg(d["days_to_need"]),
             d["linked_activity"]] for d in op]
    cols = [("ID", 0.6, "l", 1), ("Decision required", None, "l", 2), ("Owner", 2.1, "l", 2), ("Needed by", WDT, "c", 1),
            ("Status", 0.9, "c", 1), ("Days to need", 1.0, "r", 1), ("Linked activity", WID + 0.1, "c", 1)]
    if rows:
        b1, _ = dk.table(s, ML, BODY_Y + 0.29, CW, cols, rows, 2.0, max_lines=1)
    else:
        b1 = dk.note(s, ML, BODY_Y + 0.29, CW, "No open decisions.").top / 914400 + 0.26
    y = b1 + 0.2
    risks = sorted([r for r in c.S["risks"] if r["rating"] == "High"],
                   key=lambda r: (-r["score"], -r["schedule_impact_days"], r["risk_id"]))
    dk.heading(s, ML, y, CW, f"Escalations: High risks ({len(risks)})")
    rows = [[r["risk_id"], r["title"], r["owner_code"], str(r["score"]), str(r["schedule_impact_days"]),
             tf_cell(r["min_linked_float_d"]), r["mitigation"]] for r in risks]
    cols = [("Risk", 0.6, "l", 1), ("Title", 3.7, "l", 2), ("Owner", WOW, "c", 1), ("Risk score", 0.7, "r", 1),
            ("Schedule impact (d)", 0.85, "r", 1), ("Lowest linked TF (wd)", 0.9, "r", 1), ("Mitigation", None, "l", 2)]
    dk.table(s, ML, y + 0.34, CW, cols, rows, 6.12 - (y + 0.34), max_lines=1, name="High risks")
    if op:
        parts = [f"{d['owner']} to close overdue {d['decision_id']} now" if d["overdue"] else
                 f"{d['owner']} to decide {d['decision_id']} by {fd(d['needed_by'])}" for d in op]
        dk.ask(s, "Ask", "; ".join(parts) + ".")
    else:
        dk.ask(s, "So what", "No decisions are open this fortnight.")
    return s


def s_f_quality(dk: Deck):
    c = dk.c
    sm, p = c.sm, c.prev_sm
    dqd = f", {sm['dq_score'] - p['dq_score']:+.1f} pts vs the last update" if p else ""
    title = (f"Schedule quality is {dqs(sm['dq_score'])}/100 ({sm['dq_rating']}){dqd}; "
             + (f"all {sm['controls_total']} reconciliation controls pass, so the numbers are safe to use."
                if c.reconciled else "reconciliation controls FAIL and the numbers must not be used."))
    s = dk.slide("Fortnightly flash · data quality and reconciliation", title)
    dk.tiles(s, BODY_Y, 0.8, [
        ("DQ score", f"{dqs(sm['dq_score'])} / 100", sm["dq_rating"],
         GREEN if sm["dq_score"] >= 85 else AMBER if sm["dq_score"] >= 70 else RED),
        ("CPLI", ratio(sm["cpli"], 0.95), "target ≥ 0.95", GREEN if sm["cpli"] >= 0.95 else RED),
        ("BEI", ratio(sm["bei"], 0.95), "target ≥ 0.95", GREEN if sm["bei"] >= 0.95 else RED),
        ("Reconciliation status", f"{sm['controls_passed']} / {sm['controls_total']}", "controls passed",
         TEAL if c.reconciled else RED),
    ])
    y = BODY_Y + 0.8 + 0.1
    lw = 5.7
    fails = c.failing_checks()
    dk.heading(s, ML, y, lw, f"Failing checks ({len(fails)}), most points lost first")
    cols = [("Check", 0.6, "l", 1), ("Name", None, "l", 1), ("Result vs threshold", 1.45, "c", 1),
            ("Points lost", 0.7, "r", 1), ("Owner", WOW, "c", 1)]
    rows = [[r[0], r[1], r[2], r[3], r[5]] for r in checks_rows(c)]
    # weight-0 checks (no points) are listed on the monthly schedule-quality slide; the flash keeps every failing row
    dk.table(s, ML, y + 0.34, lw, cols, rows, 6.12 - (y + 0.34), max_lines=1, name="Failing checks")
    rx = ML + lw + 0.3
    rw = SW - ML - rx
    dk.heading(s, rx, y, rw, "Key reconciliation controls: source XER vs dashboard JSON")
    rec = recon_rows(c)
    b2, shown = dk.table(s, rx, y + 0.34, rw, RECON_COLS, rec, 5.84 - (y + 0.34), max_lines=1, partial_ok=True)
    if shown < len(rec):
        dk.note(s, rx, b2 + 0.02, rw, f"{shown} of {len(rec)} key controls shown; all {sm['controls_total']} in the "
                f"controls workbook, Reconciliation sheet.")
    if fails:
        parts = []
        for f in fails[:2]:
            o = c.check_owner(f)
            parts.append(f"{c.role(o)} ({o}) to {ACTION.get(f['check_id'], 'review the check')} ({f['check_id']})")
        dk.ask(s, "Ask", "; ".join(parts) + " before the next update.")
    else:
        dk.ask(s, "So what", "Every check passes.")
    return s


# ----------------------------------------------------------------------------------------------- entry point
MONTHLY = [s_cover, s_exec_summary, s_milestones, s_critical_path, s_lookback, s_lookahead, s_trends, s_interfaces,
           s_risks, s_decisions, s_recovery, s_governance, s_quality, s_appendix_lineage, s_appendix_definitions]
FORTNIGHTLY = [lambda dk: s_exec_summary(dk, "Fortnightly flash · headline"), s_f_milestones, s_f_lookbackahead,
               s_f_critical, s_f_decisions, s_f_quality]


def build_deck(root: pathlib.Path, data_date: str, pack: str) -> Deck:
    if pack not in ("monthly", "fortnightly"):
        raise ValueError("pack must be 'monthly' or 'fortnightly'")
    ctx = Ctx(root, data_date)
    dk = Deck(ctx, pack)
    for fn in (MONTHLY if pack == "monthly" else FORTNIGHTLY):
        fn(dk)
    return dk


def pack_name(data_date: str, pack: str) -> str:
    return f"DOP_monthly_pack_{data_date}.pptx" if pack == "monthly" else f"DOP_fortnightly_flash_{data_date}.pptx"


def build_pack(root: pathlib.Path, data_date: str, pack: str, out_dir: pathlib.Path | None = None) -> pathlib.Path:
    """Build the monthly or fortnightly pack for ``data_date`` and return the written path."""
    root = pathlib.Path(root)
    dk = build_deck(root, data_date, pack)
    out = pathlib.Path(out_dir) if out_dir else root / "output" / "pptx"
    path = out / pack_name(data_date, pack)
    dk.save(path)
    for w in dk.warnings:
        print(f"[pptx] warning: {w}")
    return path
