"""Working-time calendars.

Time is an integer number of hours on a continuous clock: ``t = date.toordinal() * 24 + hour``.
Every calendar has an 8-hour working day 08:00-16:00 on its working weekdays, minus exception dates.

A calendar maps a time to its *work position*: the cumulative number of working hours before that
time. ``pos`` is monotone non-decreasing. Converting a position back to a time is ambiguous at day
boundaries (16:00 on a working day and 08:00 on the next working day have the same position), so two
inverse functions exist:

* ``start_at(p)``: the latest time with that position. Used for start-type dates: work begins at 08:00.
* ``finish_at(p)``: the earliest time with that position. Used for finish-type dates: work ends at 16:00.
"""
from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass, field

DAY_START = 8
DAY_END = 16
HOURS_PER_DAY = DAY_END - DAY_START  # 8

# Python weekday(): Mon=0 ... Sun=6. P6 clndr_data day numbers: Sun=1 ... Sat=7.
PY_TO_P6_DAY = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7}
P6_TO_PY_DAY = {v: k for k, v in PY_TO_P6_DAY.items()}

RANGE_START = dt.date(2024, 1, 1)
RANGE_END = dt.date(2030, 12, 31)


def to_time(d: dt.date | dt.datetime, hour: int | None = None) -> int:
    if isinstance(d, dt.datetime):
        return d.date().toordinal() * 24 + (d.hour if hour is None else hour)
    return d.toordinal() * 24 + (DAY_START if hour is None else hour)


def from_time(t: int) -> dt.datetime:
    d = dt.date.fromordinal(t // 24)
    return dt.datetime(d.year, d.month, d.day, t % 24)


def fmt_time(t: int | None) -> str:
    return "" if t is None else from_time(t).strftime("%Y-%m-%d %H:%M")


def parse_time(s: str) -> int | None:
    if not s:
        return None
    return to_time(dt.datetime.strptime(s[:16], "%Y-%m-%d %H:%M"))


@dataclass
class Calendar:
    clndr_id: int
    name: str
    workweek: tuple[int, ...]          # python weekdays that are working days
    holidays: frozenset[dt.date] = frozenset()
    _days: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self.holidays = frozenset(self.holidays)
        self.workweek = tuple(sorted(self.workweek))
        days = []
        d = RANGE_START
        one = dt.timedelta(days=1)
        while d <= RANGE_END:
            if d.weekday() in self.workweek and d not in self.holidays:
                days.append(d.toordinal())
            d += one
        self._days = days

    # ------------------------------------------------------------------ positions
    def is_workday(self, d: dt.date) -> bool:
        i = bisect.bisect_left(self._days, d.toordinal())
        return i < len(self._days) and self._days[i] == d.toordinal()

    def pos(self, t: int) -> int:
        day, hr = divmod(t, 24)
        i = bisect.bisect_left(self._days, day)
        if i < len(self._days) and self._days[i] == day:
            return i * HOURS_PER_DAY + min(max(hr - DAY_START, 0), HOURS_PER_DAY)
        return i * HOURS_PER_DAY

    def start_at(self, p: int) -> int:
        i, off = divmod(p, HOURS_PER_DAY)
        i = max(0, min(i, len(self._days) - 1))
        return self._days[i] * 24 + DAY_START + off

    def finish_at(self, p: int) -> int:
        i, off = divmod(p, HOURS_PER_DAY)
        if off == 0 and p > 0:
            return self._days[min(i - 1, len(self._days) - 1)] * 24 + DAY_END
        return self.start_at(p)

    def work_hours(self, t1: int, t2: int) -> int:
        """Working hours between two times (negative if t2 < t1)."""
        return self.pos(t2) - self.pos(t1)

    def add(self, t: int, hours: int, finish: bool = True) -> int:
        p = self.pos(t) + hours
        return self.finish_at(p) if finish else self.start_at(p)

    def workdays_between(self, d1: dt.date, d2: dt.date) -> int:
        return (self.pos(to_time(d2)) - self.pos(to_time(d1))) // HOURS_PER_DAY

    # ------------------------------------------------------------------ XER clndr_data
    def to_clndr_data(self) -> str:
        """P6-style clndr_data (single line, as written into the XER CALENDAR table)."""
        parts = ["(0||CalendarData()(", "(0||DaysOfWeek()("]
        for p6d in range(1, 8):
            pyd = P6_TO_PY_DAY[p6d]
            if pyd in self.workweek:
                parts.append(f"(0||{p6d}()((0||0(s|{DAY_START:02d}:00|f|{DAY_END:02d}:00)())))")
            else:
                parts.append(f"(0||{p6d}()())")
        parts.append("))(0||VIEW(ShowTotal|Y)())(0||Exceptions()(")
        for i, h in enumerate(sorted(self.holidays)):
            serial = (h - dt.date(1899, 12, 30)).days
            parts.append(f"(0||{i}(d|{serial})())")
        parts.append(")))")
        return "".join(parts)

    @classmethod
    def from_clndr_data(cls, clndr_id: int, name: str, data: str) -> "Calendar":
        import re
        week = []
        dow = data.split("DaysOfWeek()(", 1)[1].split("(0||VIEW", 1)[0]
        for m in re.finditer(r"\(0\|\|(\d)\(\)\((.*?)\)\)", dow):
            p6d, body = int(m.group(1)), m.group(2)
            if "s|" in body:
                week.append(P6_TO_PY_DAY[p6d])
        # days with empty bodies look like "(0||7()())" which the regex above does not match as working
        hol = set()
        if "Exceptions()(" in data:
            exc = data.split("Exceptions()(", 1)[1]
            for m in re.finditer(r"\(d\|(\d+)\)", exc):
                hol.add(dt.date(1899, 12, 30) + dt.timedelta(days=int(m.group(1))))
        return cls(clndr_id, name, tuple(sorted(week)), frozenset(hol))


# ---------------------------------------------------------------------- programme calendars
SAT_THU = (5, 6, 0, 1, 2, 3)   # Sat..Thu (Friday off)
SUN_THU = (6, 0, 1, 2, 3)      # Sun..Thu
ALL_WEEK = (0, 1, 2, 3, 4, 5, 6)


def _block(start: dt.date, days: int) -> set[dt.date]:
    return {start + dt.timedelta(days=i) for i in range(days)}


PUBLIC_HOLIDAYS = frozenset(
    _block(dt.date(2026, 3, 19), 4) | _block(dt.date(2026, 5, 26), 5) | {dt.date(2026, 9, 23)}
    | {dt.date(2027, 2, 22)} | _block(dt.date(2027, 3, 9), 4) | _block(dt.date(2027, 5, 16), 5)
    | {dt.date(2027, 9, 23)} | _block(dt.date(2025, 3, 30), 4) | _block(dt.date(2025, 6, 5), 5)
    | {dt.date(2025, 9, 23)}
)
NATIONAL_DAYS = frozenset({dt.date(2026, 9, 23), dt.date(2027, 9, 23), dt.date(2025, 9, 23)})


def programme_calendars() -> dict[int, Calendar]:
    return {
        1: Calendar(1, "DOP 6-Day Site (Sat-Thu)", SAT_THU, PUBLIC_HOLIDAYS),
        2: Calendar(2, "DOP 5-Day Office (Sun-Thu)", SUN_THU, PUBLIC_HOLIDAYS),
        3: Calendar(3, "DOP 7-Day T&C / Trials", ALL_WEEK, NATIONAL_DAYS),
    }
