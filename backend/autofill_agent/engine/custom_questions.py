"""Grounded handling of free-form application questions (doc §23, §24, §34).

Everything here is derived from the resume text or refuses. "How many years of X" is computed from
dated positions that mention X; "Describe your X experience" is assembled from resume bullets that
mention X. If the resume does not support an answer, nothing is produced (NEEDS_USER_INPUT).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from autofill_agent.engine.descriptor import FieldDescriptor

_STOP = {"a", "an", "the", "you", "your", "do", "does", "did", "please", "of", "to", "is", "are", "in", "for", "and", "or",
         "this", "that", "we", "our", "us", "have", "has", "any", "can", "will", "would", "if", "so", "be", "with", "as", "on", "what", "at", "how", "who", "which", "tell", "about"}


def question_text(d: FieldDescriptor) -> str:
    for t in (d.legend, d.label, d.aria_label, d.placeholder, d.nearby_text):
        if t and t.strip():
            return " ".join(t.split())
    return ""


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)]
            if suf in ("ing", "ed") and len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":
                w = w[:-1]
            return w
    return w


def question_hash(text: str) -> str:
    """Stable id for the *meaning* of a question: stemmed lowercase words, no stop words, order-independent."""
    words = sorted({_stem(w) for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in _STOP})
    return hashlib.sha256(" ".join(words).encode()).hexdigest()


# Questions about this specific job/company must not be reused for other companies.
JOB_SPECIFIC = re.compile(r"\b(this (role|job|position|company|team|opportunity)|our (company|team|mission)|why (do you want|are you interested|us|this)|"
                          r"interested in (this|working)|what (attracts|excites|interests) you)\b", re.I)


@dataclass
class Intent:
    kind: str  # years_of | describe | have | none
    topic: str | None = None


_TOPIC_STOP = {"professional", "work", "working", "relevant", "total", "overall", "related", "industry", "hands-on", "hands on", "prior", "previous"}


def _clean_topic(t: str) -> str | None:
    t = re.sub(r"(?i)^(the|a|an|using|with|in|of|working with)\s+", "", t.strip(" ?.:,;\"'"))
    t = re.sub(r"(?i)\s+(do you have|have you|you have|did you)$", "", t).strip(" ?.:,;\"'")
    if not t or len(t) > 60 or t.lower() in _TOPIC_STOP:
        return None
    return t


def detect_intent(text: str) -> Intent:
    q = " ".join(text.split())
    if m := re.search(r"(?i)\byears?\s+of\s+(?:professional |work |hands[- ]on |relevant |prior )?(.+?)\s+experience\b", q):
        if t := _clean_topic(m.group(1)):
            return Intent("years_of", t)
    if m := re.search(r"(?i)\byears?(?:\s+of\s+(?:\w+\s+)?experience)?\s+(?:do you have\s+)?(?:with|in|using|working with)\s+(.+?)(?:\?|$|\.)", q):
        if t := _clean_topic(m.group(1)):
            return Intent("years_of", t)
    if m := re.search(r"(?i)\bhow long have you (?:worked|been working|used|been using)\s+(?:with|in|on)?\s*(.+?)(?:\?|$)", q):
        if t := _clean_topic(m.group(1)):
            return Intent("years_of", t)
    if m := re.search(r"(?i)\b(?:describe|tell us about|explain|summari[sz]e)\s+(?:your|any|the)?\s*(?:\w+\s+)?(?:experience|background|work)\s+(?:with|in|using|on)\s+(.+?)(?:\?|$|\.)", q):
        if t := _clean_topic(m.group(1)):
            return Intent("describe", t)
    if m := re.search(r"(?i)\b(?:describe|tell us about|explain)\s+(?:your|any)\s+(.+?)\s+experience\b", q):
        if t := _clean_topic(m.group(1)):
            return Intent("describe", t)
    if m := re.search(r"(?i)\bdo you have (?:any |prior |hands[- ]on )?(?:experience|knowledge|familiarity|exposure)\s+(?:with|in|using|of)\s+(.+?)(?:\?|$)", q):
        if t := _clean_topic(m.group(1)):
            return Intent("have", t)
    if m := re.search(r"(?i)\bare you (?:familiar|proficient|experienced|comfortable) (?:with|in|using)\s+(.+?)(?:\?|$)", q):
        if t := _clean_topic(m.group(1)):
            return Intent("have", t)
    return Intent("none")


def _topic_patterns(topic: str) -> list[re.Pattern[str]]:
    parts = [p.strip() for p in re.split(r"\s*(?:/|,|\bor\b|\band\b)\s*", topic) if p.strip()] or [topic]
    return [re.compile(rf"(?<![\w+#]){re.escape(p)}(?![\w+#])", re.I) for p in parts]


@dataclass
class Evidence:
    positions: list[dict[str, Any]] = field(default_factory=list)  # positions whose text mentions the topic
    in_skills: bool = False
    in_certs: bool = False


def _pos_text(p: dict[str, Any]) -> str:
    return " ".join(str(p.get(k) or "") for k in ("title", "company", "description"))


def find_evidence(resume: dict[str, Any] | None, topic: str) -> Evidence:
    ev = Evidence()
    if not resume:
        return ev
    pats = _topic_patterns(topic)
    for p in resume.get("experience") or []:
        if any(pt.search(_pos_text(p)) for pt in pats):
            ev.positions.append(p)
    ev.in_skills = any(pt.search(s) for s in resume.get("skills") or [] for pt in pats)
    ev.in_certs = any(pt.search(c.get("name") or "") for c in resume.get("certifications") or [] for pt in pats)
    return ev


def _interval(p: dict[str, Any], today: date) -> tuple[int, int] | None:
    s = p.get("start_date")
    if not s or not re.match(r"^\d{4}(-\d{2})?", s):
        return None
    sm = int(s[:4]) * 12 + (int(s[5:7]) if len(s) >= 7 else 1)
    if p.get("current"):
        em = today.year * 12 + today.month
    else:
        e = p.get("end_date")
        if not e or not re.match(r"^\d{4}(-\d{2})?", e):
            return None
        em = int(e[:4]) * 12 + (int(e[5:7]) if len(e) >= 7 else 1)
    return (sm, em) if em >= sm else None


def union_months(positions: list[dict[str, Any]], today: date) -> int | None:
    """Total months covered by the positions, counting overlaps once; None if none have usable dates."""
    ivs = sorted(iv for iv in (_interval(p, today) for p in positions) if iv)
    if not ivs:
        return None
    total, (cs, ce) = 0, ivs[0]
    for s, e in ivs[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            total += ce - cs
            cs, ce = s, e
    return total + (ce - cs)


def years_from(positions: list[dict[str, Any]], today: date) -> int | None:
    months = union_months(positions, today)
    return None if months is None else months // 12


def describe_draft(ev: Evidence, topic: str) -> str | None:
    """Stitch resume bullets that mention the topic. Quotes the resume; adds nothing."""
    pats = _topic_patterns(topic)
    chunks: list[str] = []
    for p in ev.positions[:3]:
        lines = [ln.strip() for ln in (p.get("description") or "").split("\n") if ln.strip()]
        hits = [ln for ln in lines if any(pt.search(ln) for pt in pats)][:2]
        if not hits:
            continue
        head = ", ".join(x for x in (p.get("company"), p.get("title")) if x)
        chunks.append(f"{head}: " + " ".join(h if h.endswith((".", "!", "?")) else h + "." for h in hits) if head else " ".join(hits))
    return "\n".join(chunks) or None
