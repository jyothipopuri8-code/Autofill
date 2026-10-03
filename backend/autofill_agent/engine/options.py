"""Choose the dropdown/radio option that corresponds to an answer (doc §12, §13).

Never guesses: when several options fit equally or none does, no option is returned and
the caller treats the field as needing the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from autofill_agent.engine.descriptor import Option

_PLACEHOLDERS = re.compile(r"^(select|choose|please select|please choose|--+|-|none selected|select one|select an option|pick one)\.*$", re.I)

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

COUNTRY_ALIASES = [
    {"united states", "united states of america", "usa", "us", "u s", "u s a", "america"},
    {"united kingdom", "uk", "u k", "great britain", "gb", "england"},
    {"canada", "ca"},
    {"india", "in"},
    {"germany", "de", "deutschland"},
    {"australia", "au"},
]


@dataclass
class OptionMatch:
    option: Option | None
    factor: float = 0.0
    note: str | None = None


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+]+", " ", (s or "").lower())).strip()


def usable(options: list[Option]) -> list[Option]:
    return [o for o in options if (o.label or o.value).strip() and not _PLACEHOLDERS.match((o.label or o.value).strip())]


def _yes_no(text: str) -> bool | None:
    t = _norm(text)
    if re.match(r"^(yes|y|true|i am|i do|i have|i will|i can|affirmative)\b", t) and not re.match(r"^(i am not|i do not|i don t|i will not|i have not|i can not)", t):
        return True
    if re.match(r"^(no|n|false|i am not|i do not|i don t|i will not|i have not|i can not|not)\b", t):
        return False
    return None


def _degree_level(text: str) -> str | None:
    t = _norm(text)
    if re.search(r"\b(ph d|phd|doctor|doctorate|doctoral)\b", t):
        return "doctor"
    if re.search(r"\b(master|masters|ms|m s|msc|ma|m a|mba|meng)\b", t):
        return "master"
    if re.search(r"\b(bachelor|bachelors|bs|b s|bsc|ba|b a|beng|undergraduate)\b", t):
        return "bachelor"
    if re.search(r"\b(associate|associates|aa|a a|as|a s)\b", t):
        return "associate"
    if re.search(r"\b(high school|ged|secondary)\b", t):
        return "highschool"
    return None


_DECLINE = re.compile(r"decline|prefer not|do not wish|don t wish|not wish|choose not|rather not|not to (say|disclose|answer)|not want to (answer|say)")
_GENDER = {"male": {"male", "man", "m"}, "female": {"female", "woman", "f"}, "nonbinary": {"non binary", "nonbinary", "genderqueer", "gender non conforming"}}


def _state_key(s: str) -> str | None:
    t = s.strip().rstrip(".")
    if t.upper() in US_STATES:
        return t.upper()
    return _STATE_BY_NAME.get(t.lower())


def _country_key(s: str) -> int | None:
    t = _norm(s)
    for i, group in enumerate(COUNTRY_ALIASES):
        if t in group:
            return i
    return None


def _unique(cands: list[Option], factor: float, note: str | None = None) -> OptionMatch:
    if len(cands) == 1:
        return OptionMatch(cands[0], factor, note)
    return OptionMatch(None, 0.0, "More than one option fits" if cands else None)


def _place_parts(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,/]", text) if x.strip()]


def _match_place(value: str, opts: list[Option]) -> OptionMatch | None:
    """A "City, ST" answer against place-search results such as "Austin, Texas, United States".

    The city must match exactly, the state (abbreviation or name) must match when we know it, and a country that
    is listed must be the United States. Several matches (two Austins in the same state is not a thing, but two
    results for one place can be) are not guessed between.
    """
    want = _place_parts(value)
    if not want:
        return None
    city = _norm(want[0])
    state = _state_key(want[1]) if len(want) > 1 else None
    us = _country_key("United States")
    hits = []
    for o in opts:
        parts = _place_parts(o.label)
        if not parts or _norm(parts[0]) != city:
            continue
        if state and not any(_state_key(x) == state for x in parts[1:3]):
            continue
        countries = [_country_key(x) for x in parts[1:] if _country_key(x) is not None]
        if countries and us not in countries:
            continue
        hits.append(o)
    return _unique(hits, 0.97, "Matched the city and state") if hits else None


def match_option(value: str | None, options: list[Option], canonical: str | None = None) -> OptionMatch:
    opts = usable(options)
    if not value or not opts:
        return OptionMatch(None)
    v = _norm(value)

    exact = [o for o in opts if v in (_norm(o.label), _norm(o.value))]
    if exact:
        return _unique(exact, 1.0)

    canonical = canonical or ""
    if canonical == "location.location":
        placed = _match_place(value, opts)
        if placed:
            return placed
    if canonical.endswith("location.state") or canonical == "location.state":
        key = _state_key(value)
        if key:
            hits = [o for o in opts if _state_key(o.label) == key or _state_key(o.value) == key]
            if hits:
                return _unique(hits, 0.99)
    if canonical == "location.country":
        k = _country_key(value)
        if k is not None:
            hits = [o for o in opts if _country_key(o.label) == k or _country_key(o.value) == k]
            if hits:
                return _unique(hits, 0.99)

    yn = _yes_no(value) if _norm(value) in {"yes", "no", "true", "false"} else None
    if yn is not None:
        hits = [o for o in opts if _yes_no(o.label or o.value) is yn]
        if hits:
            return _unique(hits, 0.98 if len(hits) == 1 else 0.0)

    if canonical.startswith("sensitive."):
        if _DECLINE.search(v):
            hits = [o for o in opts if _DECLINE.search(_norm(o.label))]
            if hits:
                return _unique(hits, 0.95)
        if canonical == "sensitive.gender":
            for syns in _GENDER.values():
                if v in syns:
                    hits = [o for o in opts if _norm(o.label) in syns or _norm(o.value) in syns]
                    if hits:
                        return _unique(hits, 0.97)

    if canonical in ("education.degree", "calc.highest_degree"):
        lvl = _degree_level(value)
        if lvl:
            hits = [o for o in opts if _degree_level(o.label) == lvl]
            if hits:
                return _unique(hits, 1.0, "Matched by degree level")

    if canonical == "contact.phone_device_type":
        syn = {"mobile": {"mobile", "cell", "cellular"}, "home": {"home", "landline"}, "work": {"work", "office", "business"}}
        for syns in syn.values():
            if v in syns:
                hits = [o for o in opts if _norm(o.label) in syns]
                if hits:
                    return _unique(hits, 0.97)

    if canonical == "contact.phone_country_code":
        digits = re.sub(r"\D", "", value)
        hits = [o for o in opts if re.search(rf"(^|[\s(+]){digits}($|[\s)])", o.label + " " + o.value) and "+" in (o.label + o.value) or _norm(o.value) == digits]
        if hits:
            return _unique(hits, 0.9, "Matched by calling code")

    # Month names/numbers for month dropdowns.
    if re.fullmatch(r"\d{1,2}", v) and all(re.fullmatch(r"\d{1,2}|[a-z]+", _norm(o.label)) for o in opts):
        n = int(v)
        months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
        if 1 <= n <= 12:
            hits = [o for o in opts if _norm(o.label) in (months[n - 1], months[n - 1][:3], str(n), f"{n:02d}") or _norm(o.value) in (str(n), f"{n:02d}", months[n - 1])]
            if hits:
                return _unique(hits, 0.99)

    tokens = set(v.split())
    sup = [o for o in opts if tokens and tokens <= set(_norm(o.label).split())]
    if sup:
        return _unique(sup, 0.9, "Matched by words in the option")
    sub = [o for o in opts if len(_norm(o.label).split()) >= 2 and set(_norm(o.label).split()) <= tokens]
    if sub:
        return _unique(sub, 0.88, "Matched by words in the answer")
    return OptionMatch(None)


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def _month_number(label: str) -> int | None:
    n = _norm(label)
    if n.isdigit() and 1 <= int(n) <= 12:
        return int(n)
    for i, name in enumerate(_MONTHS, 1):
        if n == name or (len(n) >= 3 and name.startswith(n) and n in (name[:3], name[:4])):
            return i
    return None


def match_date_option(iso: str | None, options: list[Option]) -> OptionMatch:
    """Pick the option of a month, year or month-and-year dropdown for an internal date (doc §20).

    Never guesses a missing part: a month dropdown with a year-only date yields no option and a note.
    """
    from autofill_agent.engine.dates import format_date, parse_iso

    p = parse_iso(iso)
    opts = [o for o in usable(options) if not re.fullmatch(r"(?i)(month|year|mm|yyyy|yy|day|dd)", (o.label or o.value).strip())]
    if p is None or not opts:
        return OptionMatch(None)
    year, month, _day = p

    if all(_month_number(o.label or o.value) is not None for o in opts):
        if month is None:
            return OptionMatch(None, 0.0, "The month is not on file for this date")
        return _unique([o for o in opts if _month_number(o.label or o.value) == month], 0.99)

    if all(re.fullmatch(r"\d{4}", (o.label or o.value).strip()) for o in opts):
        return _unique([o for o in opts if (o.label or o.value).strip() == str(year)], 0.99)

    for fmt in ("MMMM YYYY", "MMM YYYY", "MM/YYYY", "M/YYYY", "YYYY-MM", "MM-YYYY", "YYYY/MM", "MM/DD/YYYY", "YYYY-MM-DD"):
        f = format_date(iso, fmt)
        if f is None:
            continue
        hits = [o for o in opts if _norm(o.label) == _norm(f) or _norm(o.value) == _norm(f)]
        if hits:
            return _unique(hits, 0.97)
    return OptionMatch(None)
