"""Map a detected form control to a canonical field with a match score (doc §12, §14, §15).

Deterministic only: autocomplete tokens, input types, label/legend/aria text, name/id/placeholder,
nearby text and known ATS naming. The score says how sure the *mapping* is; the answer's own
reliability is combined with it later (see ``confidence``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from autofill_agent.engine.descriptor import FieldDescriptor
from autofill_agent.engine.taxonomy import SPECS, Spec, normalize, patterns

# Known ATS naming (normalised name/id -> canonical). Applied only when the ATS is known.
ATS_ALIASES: dict[str, list[tuple[str, str]]] = {
    "GREENHOUSE": [
        (r"^job application gender$", "sensitive.gender"),
        (r"^job application race$", "sensitive.race"),
        (r"^job application hispanic ethnicity$", "sensitive.hispanic_latino"),
        (r"^job application veteran status$", "sensitive.veteran_status"),
        (r"^job application disability status$", "sensitive.disability_status"),
        (r"^job application location$", "location.location"),
        (r"^(job application )?first name$", "personal.first_name"),
        (r"^(job application )?last name$", "personal.last_name"),
        (r"^(job application )?email$", "contact.email"),
        (r"^(job application )?phone$", "contact.phone"),
    ],
    "LEVER": [
        (r"^name$", "personal.full_name"),
        (r"^email$", "contact.email"),
        (r"^phone$", "contact.phone"),
        (r"^org$", "calc.current_company"),
        (r"^urls linked ?in$", "contact.linkedin"),
        (r"^urls git ?hub$", "contact.github"),
        (r"^urls portfolio$", "contact.portfolio"),
        (r"^urls (other|website)$", "contact.website"),
        (r"^eeo gender$", "sensitive.gender"),
        (r"^eeo race$", "sensitive.race"),
        (r"^eeo veteran$", "sensitive.veteran_status"),
        (r"^eeo disability$", "sensitive.disability_status"),
    ],
    "WORKDAY": [
        (r"legal name section first name$", "personal.first_name"),
        (r"legal name section last name$", "personal.last_name"),
        (r"legal name section middle name$", "personal.middle_name"),
        (r"address section address line 1$", "location.address_line1"),
        (r"address section address line 2$", "location.address_line2"),
        (r"address section city$", "location.city"),
        (r"address section country region$", "location.state"),
        (r"address section postal code$", "location.postal_code"),
        (r"(country phone code|phone country code)$", "contact.phone_country_code"),
        (r"phone number$", "contact.phone"),
        (r"phone device type$", "contact.phone_device_type"),
        (r"phone extension$", "contact.phone_extension"),
        (r"^country$", "location.country"),
    ],
    "ASHBY": [
        (r"^system ?field name$", "personal.full_name"),
        (r"^system ?field email$", "contact.email"),
        (r"^system ?field resume$", "resume.file"),
    ],
}
_alias_compiled: dict[str, list[tuple[re.Pattern[str], str]]] = {
    ats: [(re.compile(p), c) for p, c in rules] for ats, rules in ATS_ALIASES.items()
}

_AC_IGNORE = {"shipping", "billing", "home", "work", "mobile", "fax", "pager", "on", "off"}


@dataclass
class Match:
    canonical: str | None
    score: float = 0.0
    signals: list[str] = field(default_factory=list)
    ambiguous: bool = False
    alternatives: list[tuple[str, float]] = field(default_factory=list)


def _label_texts(d: FieldDescriptor) -> list[str]:
    texts = [normalize(d.legend), normalize(d.label), normalize(d.aria_label)]
    return [t for t in texts if t]


def _score_spec(spec: Spec, d: FieldDescriptor, ats: str | None) -> tuple[float, list[str]]:
    pats = patterns(spec)
    labels = _label_texts(d)
    primary = labels[0] if labels else ""
    attrs = [normalize(d.name), normalize(d.id)]
    attrs = [a for a in attrs if a]
    placeholder = normalize(d.placeholder)
    nearby = normalize(d.nearby_text)

    signals: dict[str, float] = {}

    tokens = [t for t in normalize(d.autocomplete).split() if t not in _AC_IGNORE and not t.startswith("section")]
    if tokens and any(t in spec.autocomplete or t.replace(" ", "-") in spec.autocomplete for t in tokens):
        signals["autocomplete"] = 0.99
    elif d.autocomplete:
        raw = [t for t in d.autocomplete.lower().split() if t not in _AC_IGNORE and not t.startswith("section")]
        if any(t in spec.autocomplete for t in raw):
            signals["autocomplete"] = 0.99

    itype = (d.input_type or "").lower()
    if itype and itype in spec.input_types:
        signals["input_type"] = 0.97 if itype == "email" else 0.9

    denied = any(p.search(t) for p in pats["deny"] for t in labels)

    if not denied:
        for text in labels:
            if any(p.search(text) for p in pats["label"]):
                words = len(text.split())
                signals["label"] = max(signals.get("label", 0), 0.96 if words <= 8 else 0.95 if words <= 16 else 0.92)
        if not labels and placeholder and any(p.search(placeholder) for p in pats["label"]):
            signals["placeholder"] = 0.88
        elif placeholder and any(p.search(placeholder) for p in pats["label"]):
            signals["placeholder"] = 0.88
        if not labels and nearby and any(p.search(nearby) for p in pats["label"]):
            signals["nearby"] = 0.72
    for a in attrs:
        if any(p.search(a) for p in pats["attr"]):
            signals["attr"] = 0.92
        elif not labels and any(p.search(a) for p in pats["label"]):
            signals["attr"] = max(signals.get("attr", 0), 0.84)

    if ats and ats in _alias_compiled:
        for a in attrs:
            for p, canonical in _alias_compiled[ats]:
                if canonical == spec.key and p.search(a):
                    signals["ats_alias"] = 0.97

    if not signals:
        return 0.0, []
    best = max(signals.values())
    bonus = 0.015 * (len(signals) - 1)
    score = min(0.99, best + bonus)
    if spec.kinds and d.kind not in spec.kinds:
        score *= 0.5
    return score, sorted(signals)


def classify(d: FieldDescriptor, ats: str | None = None) -> Match:
    ats = ats.upper() if ats else None

    if d.kind == "password" or (d.input_type or "").lower() == "password":
        return Match("security.password", 1.0, ["input_type"])
    if d.kind == "captcha":
        return Match("security.captcha", 1.0, ["kind"])

    in_section = d.section.name if d.section else None
    scored: list[tuple[float, int, Spec, list[str]]] = []
    for order, spec in enumerate(SPECS):
        if spec.section != in_section:
            continue
        score, signals = _score_spec(spec, d, ats)
        if score > 0:
            scored.append((score, -order, spec, signals))

    if not scored:
        return Match(None)
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    top_score, _, top, signals = scored[0]
    alternatives = [(s.key, round(sc, 3)) for sc, _, s, _ in scored[1:4]]
    ambiguous = False
    for sc, _, other, _ in scored[1:]:
        if top_score - sc <= 0.03 and other.key.split(".")[0] != top.key.split(".")[0]:
            ambiguous = True
            break
    if ambiguous:
        top_score -= 0.1
    return Match(top.key, round(max(top_score, 0.0), 3), signals, ambiguous, alternatives)
