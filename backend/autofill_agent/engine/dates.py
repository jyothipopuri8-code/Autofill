"""Date normalization and per-site formatting (doc §20).

Internal dates are ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``. A site format is produced only
when every component it needs is known; missing parts are never invented.
"""

from __future__ import annotations

import re

from autofill_agent.engine.descriptor import FieldDescriptor

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_ISO = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def parse_iso(value: str | None) -> tuple[int, int | None, int | None] | None:
    if not value:
        return None
    m = _ISO.match(value.strip())
    if not m:
        return None
    y = int(m[1])
    mo = int(m[2]) if m[2] else None
    d = int(m[3]) if m[3] else None
    if mo is not None and not 1 <= mo <= 12:
        return None
    if d is not None and not 1 <= d <= 31:
        return None
    return y, mo, d


def date_parts(value: str | None) -> dict[str, int | None] | None:
    p = parse_iso(value)
    return None if p is None else {"year": p[0], "month": p[1], "day": p[2]}


_TOKEN = re.compile(r"YYYY|YY|MMMM|MMM|MM|M|DD|D")


def format_date(value: str | None, fmt: str | None) -> str | None:
    """Format an internal date; ``None`` if a required component is unknown."""
    p = parse_iso(value)
    if p is None:
        return None
    if not fmt:
        return value
    y, mo, d = p
    needs_month = bool(re.search(r"MMMM|MMM|MM|M(?!M)", fmt))
    needs_day = bool(re.search(r"DD|D", fmt))
    if (needs_month and mo is None) or (needs_day and d is None):
        return None

    def sub(m: re.Match[str]) -> str:
        t = m.group(0)
        return {
            "YYYY": f"{y:04d}", "YY": f"{y % 100:02d}",
            "MMMM": MONTH_NAMES[mo - 1] if mo else "", "MMM": MONTH_NAMES[mo - 1][:3] if mo else "",
            "MM": f"{mo:02d}" if mo else "", "M": str(mo) if mo else "",
            "DD": f"{d:02d}" if d else "", "D": str(d) if d else "",
        }[t]

    return _TOKEN.sub(sub, fmt)


def infer_format(d: FieldDescriptor) -> str | None:
    """Best guess of the format a site expects, from explicit hints, placeholder or input type."""
    if d.date_format:
        return d.date_format
    itype = (d.input_type or "").lower()
    if itype == "date":
        return "YYYY-MM-DD"
    if itype == "month":
        return "YYYY-MM"
    ph = (d.placeholder or "").strip()
    if ph:
        norm = re.sub(r"(?i)yyyy", "YYYY", ph)
        norm = re.sub(r"(?i)mmmm", "MMMM", norm)
        norm = re.sub(r"(?i)(?<![A-Za-z])mm(?![A-Za-z])", "MM", norm)
        norm = re.sub(r"(?i)(?<![A-Za-z])dd(?![A-Za-z])", "DD", norm)
        if "YYYY" in norm and re.fullmatch(r"[YMD /.\-]+|MMMM YYYY|MMM YYYY", norm):
            return norm
        if re.fullmatch(r"(?i)month\s*,?\s*year", ph):
            return "MMMM YYYY"
    return None


def months_between(start: str, end: str) -> int:
    """Whole months from start to end, both ``YYYY[-MM]`` (missing month counts as January)."""
    s, e = parse_iso(start), parse_iso(end)
    if not s or not e:
        return 0
    return max(0, (e[0] * 12 + (e[1] or 1)) - (s[0] * 12 + (s[1] or 1)))
