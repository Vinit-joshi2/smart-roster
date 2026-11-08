"""Small date helpers. Dates are 'YYYY-MM-DD' strings everywhere (same as the original JS app)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse(s: str) -> date:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def add_days(s: str, n: int) -> str:
    return (parse(s) + timedelta(days=n)).isoformat()


def dow(s: str) -> int:
    """0 = Sunday ... 6 = Saturday (JS convention, so rules/sample data port 1:1)."""
    return (parse(s).weekday() + 1) % 7


def month_days(month: str) -> list[str]:
    y, m = (int(x) for x in month.split("-"))
    n = calendar.monthrange(y, m)[1]
    return [f"{y:04d}-{m:02d}-{d:02d}" for d in range(1, n + 1)]


def day_num(s: str) -> int:
    return int(s[8:10])


def label(s: str) -> str:
    d = parse(s)
    return f"{DOW_NAMES[dow(s)]} {d.day} {MONTH_NAMES[d.month - 1]}"


def month_label(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return f"{MONTH_NAMES[m - 1]} {y}"


def range_days(a: str, b: str) -> list[str]:
    out, d = [], a
    while d <= b:
        out.append(d)
        d = add_days(d, 1)
    return out


def week_segments(days: list[str]) -> list[list[str]]:
    """Split consecutive days into Monday-start weeks (first/last may be partial)."""
    segs, cur = [], []
    for d in days:
        if cur and dow(d) == 1:
            segs.append(cur)
            cur = []
        cur.append(d)
    if cur:
        segs.append(cur)
    return segs
