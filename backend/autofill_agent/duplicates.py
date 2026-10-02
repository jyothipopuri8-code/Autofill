"""Possible-duplicate application detection (doc §34)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from autofill_agent.db.models import Application

_COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|incorporated)\b\.?", re.I)
_KEEP_PARAMS = {"gh_jid", "jid", "id", "job", "jobid", "job_id", "jobreq", "requisitionid", "reqid", "req_id", "lever-source"}
_LEVEL = {"sr", "senior", "jr", "junior", "i", "ii", "iii", "lead", "staff", "principal"}


def norm_company(c: str | None) -> str:
    c = _COMPANY_SUFFIX.sub(" ", (c or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", c).strip()


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return ""
    keep = sorted((k.lower(), v) for k, v in parse_qsl(p.query) if k.lower() in _KEEP_PARAMS)
    path = re.sub(r"/(apply|application)/?$", "", p.path.rstrip("/"), flags=re.I)
    q = "&".join(f"{k}={v}" for k, v in keep)
    return f"{p.netloc.lower().removeprefix('www.')}{path.lower()}" + (f"?{q}" if q else "")


def _title_tokens(t: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", (t or "").lower())} - _LEVEL


def title_similarity(a: str | None, b: str | None) -> float:
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class DuplicateMatch:
    application: Application
    reason: str
    strength: str  # strong | likely


def find_duplicates(existing: list[Application], company: str | None, title: str | None, job_id: str | None, url: str | None) -> list[DuplicateMatch]:
    out: list[DuplicateMatch] = []
    nc, nu = norm_company(company), norm_url(url)
    for a in existing:
        same_company = bool(nc) and norm_company(a.company) == nc
        if nu and norm_url(a.job_url) == nu:
            out.append(DuplicateMatch(a, "Same job URL", "strong"))
        elif job_id and a.job_id and job_id.strip().lower() == a.job_id.strip().lower() and (same_company or not nc or not a.company):
            out.append(DuplicateMatch(a, "Same company and job ID", "strong"))
        elif same_company and title and title_similarity(title, a.job_title) >= 0.8:
            out.append(DuplicateMatch(a, "Same company and a very similar job title", "likely"))
    out.sort(key=lambda m: (m.strength != "strong", -(m.application.created_at.timestamp() if m.application.created_at else 0)))
    return out
