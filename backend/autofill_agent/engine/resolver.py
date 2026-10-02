"""Resolve what to put in a field, from where, and how sure we are (doc §5 steps 11-15, §21, §23, §27).

Source priority: this application's user answer, verified profile/library, the session's tailored
resume, a previously approved answer, a deterministic calculation, (optional) AI draft, ask the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from autofill_agent.db.enums import AnswerSource, FieldOwnership, FieldStatus
from autofill_agent.engine import custom_questions as cq
from autofill_agent.engine.dates import date_parts, format_date, infer_format
from autofill_agent.engine.descriptor import FieldDescriptor, Option
from autofill_agent.engine.matching import Match, classify
from autofill_agent.engine.options import match_option, usable
from autofill_agent.engine.taxonomy import BY_KEY, normalize

SOURCE_FACTOR = {
    AnswerSource.USER_CURRENT: 1.0,
    AnswerSource.PROFILE: 1.0,
    AnswerSource.APPROVED_ANSWER: 0.95,
    AnswerSource.CALCULATED: 0.88,
    AnswerSource.AI_DRAFT: 0.6,
}
RESUME_VERIFIED, RESUME_UNVERIFIED = 0.99, 0.90

BOOLEAN_FIELDS = {
    "work_auth.authorized_to_work", "work_auth.sponsorship_now", "work_auth.sponsorship_future", "work_auth.sponsorship_any",
    "preferences.relocate", "preferences.remote", "preferences.hybrid", "preferences.onsite", "preferences.background_check",
    "experience.current",
}
# Library keys backing a canonical field (the library carries a policy; the profile is the fallback).
LIBRARY_KEYS = {
    "preferences.desired_salary": "desired_salary", "preferences.security_clearance": "security_clearance",
    "preferences.background_check": "background_check_willing", "preferences.relocate": "willing_to_relocate",
    "preferences.travel": "travel_percentage", "preferences.remote": "remote_preference", "preferences.hybrid": "hybrid_preference",
    "preferences.start_date": "available_start_date", "preferences.referral_source": "referral_source",
}
PROFILE_ATTRS = {
    "personal.first_name": "first_name", "personal.middle_name": "middle_name", "personal.last_name": "last_name",
    "personal.preferred_name": "preferred_name", "personal.pronouns": "pronouns",
    "contact.email": "email", "contact.phone": "phone", "contact.phone_country_code": "phone_country_code",
    "contact.phone_device_type": "phone_device_type", "contact.phone_extension": "phone_extension",
    "contact.linkedin": "linkedin_url", "contact.github": "github_url", "contact.portfolio": "portfolio_url", "contact.website": "website_url",
    "location.address_line1": "address_line1", "location.address_line2": "address_line2", "location.city": "city",
    "location.state": "state", "location.country": "country", "location.postal_code": "postal_code",
    "work_auth.authorized_to_work": "authorized_to_work_us", "work_auth.sponsorship_now": "require_sponsorship_now",
    "work_auth.sponsorship_future": "require_sponsorship_future",
    "preferences.relocate": "willing_to_relocate", "preferences.travel": "travel_willingness", "preferences.remote": "remote_preference",
    "preferences.hybrid": "hybrid_preference", "preferences.onsite": "onsite_preference",
    "preferences.start_date": "available_start_date", "preferences.referral_source": "referral_source",
}
WORK_AUTH_FIELDS = {"work_auth.authorized_to_work", "work_auth.sponsorship_now", "work_auth.sponsorship_future", "work_auth.sponsorship_any"}
# Contact facts that exist both in the profile and on the resume: a disagreement is a conflict (doc §5 step 13).
CONFLICT_FIELDS = {
    "personal.first_name": "first_name", "personal.last_name": "last_name", "contact.email": "email", "contact.phone": "phone",
    "contact.linkedin": "linkedin_url", "contact.github": "github_url",
}
EXPERIENCE_FIELDS = {"experience.title": "title", "experience.company": "company", "experience.location": "location",
                     "experience.description": "description"}
EDU_FIELDS = {"education.school": "school", "education.degree": "degree", "education.field_of_study": "field_of_study"}
CERT_FIELDS = {"certification.name": "name", "certification.number": "number"}
LANG_FIELDS = {"language.language": "language", "language.proficiency": "proficiency"}
LEGAL_CATEGORIES = {"legal"}


@dataclass
class LibraryEntry:
    value: str | None
    policy: str  # AUTOFILL | ASK_ME | NEVER_FILL
    verified: bool = False


@dataclass
class ApprovedEntry:
    question_hash: str
    canonical_field: str | None
    answer: str
    resume_sha256: str | None = None
    profile_version: str | None = None
    company: str | None = None
    depends_on_resume: bool = False
    depends_on_profile: bool = False


@dataclass
class ResumeInfo:
    data: dict[str, Any]
    verified: bool
    sha256: str
    filename: str = ""


@dataclass
class Context:
    profile: dict[str, Any] = field(default_factory=dict)
    profile_version: str | None = None
    work_auth_verified: bool = False
    sensitive: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # canonical -> (policy, value)
    library: dict[str, LibraryEntry] = field(default_factory=dict)
    resume: ResumeInfo | None = None
    resume_blocked: str | None = None  # reason when the session's resume is not the selected/valid one
    overrides: dict[str, str] = field(default_factory=dict)
    approved: list[ApprovedEntry] = field(default_factory=list)
    job: dict[str, str | None] = field(default_factory=dict)
    today: date = field(default_factory=date.today)
    ai: Any = None  # optional callable(topic, question, resume, job) -> str | None


@dataclass
class Candidate:
    value: str | None
    source: AnswerSource
    factor: float = 1.0
    reason: str | None = None
    suggestion_only: bool = False
    iso_date: bool = False
    boolean: bool = False


@dataclass
class FieldResult:
    key: str
    canonical_field: str | None
    label: str | None
    kind: str
    section: str | None
    section_index: int | None
    required: bool
    value: str | None
    checked: bool | None
    option: dict[str, str] | None
    parts: dict[str, int | None] | None
    source: AnswerSource
    confidence: int
    band: str
    action: str
    status: FieldStatus
    reason: str | None
    sensitive: bool
    conflict: dict[str, Any] | None
    suggestion: str | None
    match_score: float
    signals: list[str]
    question_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["source"] = self.source.value
        d["status"] = self.status.value
        return d


# --- helpers -----------------------------------------------------------------


def band_for(confidence: int) -> str:
    return "READY" if confidence >= 95 else "REVIEW" if confidence >= 80 else "DO_NOT_FILL"


def _norm_compare(canonical: str, v: str | None) -> str:
    v = (v or "").strip().lower()
    if canonical == "contact.phone":
        return re.sub(r"\D", "", v)[-10:]
    if canonical in ("contact.linkedin", "contact.github"):
        return re.sub(r"^https?://(www\.)?", "", v).rstrip("/")
    return re.sub(r"\s+", " ", v)


def _bool_text(v: Any) -> str | None:
    if v is True:
        return "Yes"
    if v is False:
        return "No"
    return None


def fit_phone(value: str, d: FieldDescriptor) -> str | None:
    if not d.maxlength or len(value) <= d.maxlength:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) <= d.maxlength else None


def _resume_contact(ctx: Context, canonical: str) -> str | None:
    if not ctx.resume or ctx.resume_blocked:
        return None
    c = (ctx.resume.data.get("contact") or {})
    key = {"personal.first_name": "first_name", "personal.last_name": "last_name", "contact.email": "email", "contact.phone": "phone",
           "contact.linkedin": "linkedin_url", "contact.github": "github_url", "contact.website": "website_url"}.get(canonical)
    if canonical in ("location.city", "location.state"):
        loc = c.get("location") or ""
        m = re.match(r"^\s*([^,]+),\s*([A-Za-z]{2})\s*$", loc)
        if m:
            return m.group(1).strip() if canonical == "location.city" else m.group(2).upper()
        return None
    return c.get(key) if key else None


def _profile_value(canonical: str, ctx: Context) -> Any:
    p = ctx.profile
    if canonical == "personal.full_name":
        parts = [p.get("first_name"), p.get("last_name")]
        return " ".join(x for x in parts if x) if all(parts) else None
    if canonical == "location.location":
        parts = [p.get("city"), p.get("state")]
        return ", ".join(x for x in parts if x) if all(parts) else None
    if canonical == "work_auth.sponsorship_any":
        now, fut = p.get("require_sponsorship_now"), p.get("require_sponsorship_future")
        if now is True or fut is True:
            return True
        return False if now is False and fut is False else None
    attr = PROFILE_ATTRS.get(canonical)
    return p.get(attr) if attr else None


def _recent_position(resume: dict[str, Any]) -> dict[str, Any] | None:
    exps = resume.get("experience") or []
    if not exps:
        return None
    cur = [e for e in exps if e.get("current")]
    return (cur or sorted(exps, key=lambda e: e.get("end_date") or e.get("start_date") or "", reverse=True))[0]


def _highest_degree(resume: dict[str, Any]) -> str | None:
    from autofill_agent.engine.options import _degree_level

    order = ["highschool", "associate", "bachelor", "master", "doctor"]
    best, best_rank = None, -1
    for e in resume.get("education") or []:
        lvl = _degree_level(e.get("degree") or "")
        if lvl and order.index(lvl) > best_rank:
            best, best_rank = e.get("degree"), order.index(lvl)
    return best


# --- candidate retrieval ------------------------------------------------------


def _resume_factor(ctx: Context) -> float:
    return RESUME_VERIFIED if ctx.resume and ctx.resume.verified else RESUME_UNVERIFIED


def _section_candidate(canonical: str, idx: int, ctx: Context) -> Candidate | tuple[str, str] | None:
    """Value from the session's resume for a repeatable section; ('skip', reason) if the record doesn't exist."""
    if not ctx.resume:
        return None
    sec = canonical.split(".")[0]
    key = {"experience": "experience", "education": "education", "certification": "certifications", "language": "languages"}[sec]
    rows = ctx.resume.data.get(key) or []
    if idx >= len(rows):
        return ("skip", f"Your resume has no {sec} entry #{idx + 1}")
    row = rows[idx]
    factor, src = _resume_factor(ctx), AnswerSource.RESUME
    attr = {**EXPERIENCE_FIELDS, **EDU_FIELDS, **CERT_FIELDS, **LANG_FIELDS}.get(canonical)
    if attr:
        v = row.get(attr)
        return Candidate(v, src, factor) if v else ("unknown", "Not on your resume")
    if canonical == "experience.current":
        return Candidate("Yes" if row.get("current") else "No", src, factor, boolean=True)
    if canonical in ("experience.start_date", "education.start_date"):
        v = row.get("start_date")
        return Candidate(v, src, factor, iso_date=True) if v else ("unknown", "No start date on your resume")
    if canonical == "experience.end_date":
        if row.get("current"):
            return ("skip", "Current position: leave the end date empty")
        v = row.get("end_date")
        return Candidate(v, src, factor, iso_date=True) if v else ("unknown", "No end date on your resume")
    if canonical == "education.graduation_date":
        v = row.get("graduation_date") or row.get("expected_graduation_date")
        return Candidate(v, src, factor, iso_date=True) if v else ("unknown", "No graduation date on your resume")
    if canonical in ("certification.issued_date", "certification.expiration_date"):
        v = row.get("issued_date" if canonical.endswith("issued_date") else "expiration_date")
        return Candidate(v, src, factor, iso_date=True) if v else ("unknown", "Not on your resume")
    return None


def _approved_candidate(canonical: str | None, qhash: str | None, ctx: Context) -> Candidate | None:
    for a in ctx.approved:
        same = (a.question_hash == qhash and qhash) or (canonical and a.canonical_field == canonical)
        if not same:
            continue
        if a.company and (a.company or "").lower() != (ctx.job.get("company") or "").lower():
            continue
        if a.depends_on_resume and a.resume_sha256 and (not ctx.resume or a.resume_sha256 != ctx.resume.sha256):
            continue
        if a.depends_on_profile and a.profile_version and a.profile_version != ctx.profile_version:
            continue
        return Candidate(a.answer, AnswerSource.APPROVED_ANSWER, SOURCE_FACTOR[AnswerSource.APPROVED_ANSWER], "Previously approved answer")
    return None


def get_candidate(canonical: str | None, d: FieldDescriptor, ctx: Context, qhash: str | None, qtext: str):
    """Walk the priority list. Returns Candidate, ("skip"|"unknown"|"block", reason) or None."""
    spec = BY_KEY.get(canonical) if canonical else None
    idx = d.section.index if d.section else 0
    okey = f"{canonical}[{idx}]" if spec and spec.section else canonical

    # 1. This application's own answer
    for k in (okey, f"q:{qhash}" if qhash else None):
        if k and k in ctx.overrides and ctx.overrides[k] not in (None, ""):
            return Candidate(ctx.overrides[k], AnswerSource.USER_CURRENT, 1.0, "Your answer for this application")

    if canonical is None:
        return _custom_candidate(d, ctx, qhash, qtext)

    # Sensitive: only explicit policies, never inferred
    if spec and spec.sensitive:
        policy, value = ctx.sensitive.get(canonical, ("ASK_ME", None))
        if policy == "NEVER_FILL":
            return ("skip", "Policy: NEVER_FILL")
        if policy == "AUTOFILL" and value:
            return Candidate(value, AnswerSource.PROFILE, 1.0, "Your stored answer (policy AUTOFILL)")
        return ("unknown", "Policy: ASK_ME" if policy != "AUTOFILL" else "No stored answer")

    # Resume-based
    if spec and spec.section:
        if ctx.resume_blocked:
            return ("block", ctx.resume_blocked)
        if not ctx.resume:
            return ("unknown", "No resume selected for this application")
        return _section_candidate(canonical, idx, ctx)

    if canonical in WORK_AUTH_FIELDS:
        if not ctx.work_auth_verified:
            return ("unknown", "Work authorization is not marked verified in your profile")
        v = _bool_text(_profile_value(canonical, ctx))
        return Candidate(v, AnswerSource.PROFILE, 1.0, "Verified profile", boolean=True) if v else ("unknown", "Not provided in your profile")

    # Library (carries a policy), then the profile
    lib = ctx.library.get(LIBRARY_KEYS.get(canonical, ""))
    if lib:
        if lib.policy == "NEVER_FILL":
            return ("skip", "Policy: NEVER_FILL")
        if lib.policy == "ASK_ME":
            return Candidate(lib.value, AnswerSource.PROFILE, 1.0, "Policy: ASK_ME", suggestion_only=True)
        if lib.value:
            return Candidate(lib.value, AnswerSource.PROFILE, 1.0 if lib.verified else 0.93,
                             "Your saved answer" + ("" if lib.verified else " (unverified)"), boolean=canonical in BOOLEAN_FIELDS)

    pv = _profile_value(canonical, ctx)
    if pv is not None and pv != "":
        if isinstance(pv, bool):
            return Candidate(_bool_text(pv), AnswerSource.PROFILE, 1.0, "Your profile", boolean=True)
        if isinstance(pv, date):
            return Candidate(pv.isoformat(), AnswerSource.PROFILE, 1.0, "Your profile", iso_date=True)
        return Candidate(str(pv), AnswerSource.PROFILE, 1.0, "Your profile")

    # Resume as fallback for contact details (and conflicts are handled by the caller)
    rv = _resume_contact(ctx, canonical)
    if rv:
        return Candidate(rv, AnswerSource.RESUME, _resume_factor(ctx), "From your resume")

    # Derived from the resume
    if canonical.startswith("calc.") and ctx.resume and not ctx.resume_blocked:
        data = ctx.resume.data
        if canonical in ("calc.current_company", "calc.current_title"):
            pos = _recent_position(data)
            v = pos and pos.get("company" if canonical.endswith("company") else "title")
            if v:
                return Candidate(v, AnswerSource.RESUME, _resume_factor(ctx), "Most recent position on your resume")
        if canonical == "calc.years_experience":
            months = cq.union_months(data.get("experience") or [], ctx.today)
            if months is not None:
                return Candidate(str(months // 12), AnswerSource.CALCULATED, SOURCE_FACTOR[AnswerSource.CALCULATED],
                                 "Calculated from the dated positions on your resume")
        if canonical == "calc.highest_degree":
            v = _highest_degree(data)
            if v:
                return Candidate(v, AnswerSource.RESUME, _resume_factor(ctx), "Highest degree on your resume")
    if canonical.startswith("calc.") and ctx.resume_blocked:
        return ("block", ctx.resume_blocked)

    appr = _approved_candidate(canonical, qhash, ctx)
    if appr:
        return appr
    return ("unknown", "No verified answer available")


def _custom_candidate(d: FieldDescriptor, ctx: Context, qhash: str | None, qtext: str):
    """Unmapped question: memory, then answers grounded in the resume, else ask."""
    appr = _approved_candidate(None, qhash, ctx)
    if appr:
        return appr
    intent = cq.detect_intent(qtext)
    if intent.kind == "none" or not intent.topic:
        if ctx.ai and d.kind == "textarea" and ctx.resume and not ctx.resume_blocked and qtext:
            text = ctx.ai(None, qtext, ctx.resume.data, ctx.job)
            if text:
                return Candidate(text, AnswerSource.AI_DRAFT, SOURCE_FACTOR[AnswerSource.AI_DRAFT], "Local AI draft grounded in your resume; review before use")
        return ("unknown", "Cannot answer from your verified information")
    if ctx.resume_blocked:
        return ("block", ctx.resume_blocked)
    if not ctx.resume:
        return ("unknown", "No resume selected to answer from")
    ev = cq.find_evidence(ctx.resume.data, intent.topic)
    rf = _resume_factor(ctx)
    if intent.kind == "years_of":
        yrs = cq.years_from(ev.positions, ctx.today)
        if yrs is None:
            why = "Listed in your skills but no dated role on your resume mentions it" if ev.in_skills else "Cannot verify from current resume"
            return ("unknown", why)
        return Candidate(str(yrs), AnswerSource.CALCULATED, SOURCE_FACTOR[AnswerSource.CALCULATED] * (rf / RESUME_VERIFIED),
                         f"Calculated from dated positions that mention {intent.topic}")
    if intent.kind == "have":
        if ev.positions or ev.in_skills or ev.in_certs:
            return Candidate("Yes", AnswerSource.RESUME, rf * 0.9, f"{intent.topic} appears on your resume", boolean=True)
        return ("unknown", "Cannot verify from current resume")
    if intent.kind == "describe":
        draft = cq.describe_draft(ev, intent.topic)
        if draft:
            return Candidate(draft, AnswerSource.RESUME, 0.7, "Assembled from resume bullets that mention it; edit before use")
        if ctx.ai:
            text = ctx.ai(intent.topic, qtext, ctx.resume.data, ctx.job)
            if text:
                return Candidate(text, AnswerSource.AI_DRAFT, SOURCE_FACTOR[AnswerSource.AI_DRAFT], "Local AI draft grounded in your resume; review before use")
        return ("unknown", "Cannot verify from current resume")
    return ("unknown", "Cannot answer from your verified information")


# --- field resolution ---------------------------------------------------------


def _new(d: FieldDescriptor, match: Match, qhash: str | None, **kw) -> FieldResult:
    spec = BY_KEY.get(match.canonical) if match.canonical else None
    base = dict(
        key=d.key, canonical_field=match.canonical, label=d.label or d.legend or d.aria_label, kind=d.kind,
        section=d.section.name if d.section else None, section_index=d.section.index if d.section else None,
        required=d.required, value=None, checked=None, option=None, parts=None, source=AnswerSource.NONE,
        confidence=0, band="DO_NOT_FILL", action="ask", status=FieldStatus.OPTIONAL_EMPTY, reason=None,
        sensitive=bool(spec and spec.sensitive), conflict=None, suggestion=None, match_score=match.score,
        signals=match.signals, question_hash=qhash,
    )
    base.update(kw)
    return FieldResult(**base)


def _ask(d, match, qhash, reason, suggestion=None, sensitive=None) -> FieldResult:
    r = _new(d, match, qhash, action="ask", reason=reason, suggestion=suggestion,
             status=FieldStatus.MISSING_REQUIRED if d.required else FieldStatus.OPTIONAL_EMPTY)
    if sensitive is not None:
        r.sensitive = sensitive
    return r


def resolve_field(d: FieldDescriptor, ctx: Context, ats: str | None = None) -> FieldResult:
    match = classify(d, ats)
    canonical = match.canonical
    spec = BY_KEY.get(canonical) if canonical else None
    qtext = cq.question_text(d)
    qhash = cq.question_hash(qtext) if qtext else None

    if not d.visible or d.disabled:
        return _new(d, match, qhash, action="skip", status=FieldStatus.SKIPPED, reason="Hidden or disabled field")

    # Never-handled categories
    if canonical == "security.password":
        return _new(d, match, qhash, action="skip", status=FieldStatus.SKIPPED, reason="Passwords are never handled by the agent")
    if canonical == "security.captcha":
        return _new(d, match, qhash, action="user_action", status=FieldStatus.USER_ACTION_REQUIRED, reason="CAPTCHA must be completed by you")
    if spec and spec.category == "legal":
        return _new(d, match, qhash, action="user_action", status=FieldStatus.USER_ACTION_REQUIRED,
                    reason="Legal acknowledgements and signatures must be completed by you")
    if canonical == "other.cover_letter" or (d.kind == "file" and canonical != "resume.file"):
        return _new(d, match, qhash, action="user_action", status=FieldStatus.USER_ACTION_REQUIRED, reason="Upload this file yourself")
    if canonical == "resume.file":
        if ctx.resume_blocked or not ctx.resume:
            return _new(d, match, qhash, action="user_action", status=FieldStatus.USER_ACTION_REQUIRED,
                        reason=ctx.resume_blocked or "No resume selected for this application")
        return _new(d, match, qhash, action="attach", status=FieldStatus.PENDING, value=ctx.resume.filename, source=AnswerSource.RESUME,
                    confidence=100, band="READY", reason="Verified resume for this application")

    # Respect what is already in the field (doc §27)
    non_empty = bool((d.current_value or "").strip())
    if d.ownership in (FieldOwnership.USER_FILLED, FieldOwnership.USER_MODIFIED_AGENT_VALUE):
        return _new(d, match, qhash, action="keep", status=FieldStatus.FILLED, value=d.current_value, source=AnswerSource.USER_CURRENT,
                    confidence=100, band="READY", reason="You entered this value; it will not be overwritten")
    if d.ownership is FieldOwnership.AGENT_FILLED and non_empty:
        return _new(d, match, qhash, action="keep", status=FieldStatus.FILLED, value=d.current_value, source=AnswerSource.PROFILE,
                    confidence=100, band="READY", reason="Already filled by the agent")

    cand = get_candidate(canonical, d, ctx, qhash, qtext)

    # Conflicts between profile and resume (contact details only)
    conflict = None
    if canonical in CONFLICT_FIELDS and ctx.resume and not ctx.resume_blocked and canonical not in ctx.overrides:
        pv, rv = _profile_value(canonical, ctx), _resume_contact(ctx, canonical)
        if pv and rv and _norm_compare(canonical, str(pv)) != _norm_compare(canonical, rv):
            conflict = {"canonical_field": canonical, "profile_value": str(pv), "resume_value": rv}
    if conflict:
        return _new(d, match, qhash, action="conflict", status=FieldStatus.NEEDS_REVIEW, conflict=conflict,
                    reason="Your profile and resume disagree; choose which to use")

    if cand is None:
        return _ask(d, match, qhash, "No answer available")
    if isinstance(cand, tuple):
        kind, reason = cand
        if kind == "skip":
            return _new(d, match, qhash, action="skip", status=FieldStatus.SKIPPED, reason=reason)
        if kind == "block":
            return _new(d, match, qhash, action="user_action", status=FieldStatus.USER_ACTION_REQUIRED, reason=reason)
        return _ask(d, match, qhash, reason)

    if cand.suggestion_only or not cand.value:
        return _ask(d, match, qhash, cand.reason or "Needs your answer", suggestion=cand.value)

    value, reason = cand.value, cand.reason
    factor_note = 1.0
    option: dict[str, str] | None = None
    checked: bool | None = None
    parts = None

    if cand.iso_date:
        parts = date_parts(value)
        fmt = infer_format(d)
        guessed = False
        if fmt is None and d.kind not in ("date", "month_year", "select", "custom_select"):
            fmt = "MM/DD/YYYY" if canonical == "preferences.start_date" else "MM/YYYY"
            guessed = True
        if d.kind in ("month_year", "select", "custom_select") and not (d.options and canonical):
            pass
        formatted = format_date(value, fmt) if fmt else value
        if formatted is None:
            return _ask(d, match, qhash, "The date on file is missing a part this field needs", suggestion=value)
        value = formatted
        if guessed:
            factor_note *= 0.93
            reason = (reason or "") + " (date format guessed)"

    opts = usable(d.options)
    if opts and d.kind in ("select", "custom_select", "radio_group", "checkbox_group", "autocomplete") or (opts and d.kind == "unknown"):
        om = match_option(cand.value if not cand.iso_date else value, d.options, canonical)
        if om.option is None and cand.iso_date:
            om = match_option(cand.value, d.options, canonical)
        if om.option is None:
            note = om.note or f"None of the options match '{value}'"
            return _ask(d, match, qhash, note, suggestion=value)
        option = {"value": om.option.value, "label": om.option.label}
        factor_note *= om.factor

    if d.kind == "checkbox" and cand.boolean:
        checked = value == "Yes"
    if canonical == "contact.phone":
        fitted = fit_phone(value, d)
        if fitted is None:
            return _ask(d, match, qhash, "Your phone number doesn't fit this field", suggestion=value)
        value = fitted
    if d.maxlength and isinstance(value, str) and len(value) > d.maxlength and d.kind in ("text", "textarea"):
        return _ask(d, match, qhash, f"Answer is longer than this field's {d.maxlength} character limit", suggestion=value)

    if cand.source in (AnswerSource.RESUME,):
        source_factor = cand.factor
    else:
        source_factor = cand.factor
    conf = max(0, min(100, round(100 * min(match.score if canonical else 0.85, 1.0) * source_factor * factor_note)))
    if canonical is None:
        conf = max(0, min(100, round(100 * (0.97 if cand.source is AnswerSource.APPROVED_ANSWER else 0.85) * source_factor * factor_note)))
    if cand.source is AnswerSource.USER_CURRENT:
        conf = 100  # the user's own answer for this application
    b = band_for(conf)

    # Existing non-empty site default that differs from our answer: let the user decide
    if non_empty and d.ownership is FieldOwnership.SITE_DEFAULT:
        same = _norm_compare(canonical or "", d.current_value) in {_norm_compare(canonical or "", value), _norm_compare(canonical or "", option["label"] if option else None)}
        if same:
            return _new(d, match, qhash, action="keep", status=FieldStatus.FILLED, value=d.current_value, source=cand.source,
                        confidence=conf, band=b, reason="Already set to the same value")
        b = "REVIEW" if b == "READY" else b
        reason = "Site default differs from your answer"

    action = {"READY": "fill", "REVIEW": "review", "DO_NOT_FILL": "confirm"}[b]
    status = FieldStatus.PENDING if action == "fill" else FieldStatus.NEEDS_REVIEW
    return _new(d, match, qhash, value=value, checked=checked, option=option, parts=parts, source=cand.source, confidence=conf,
                band=b, action=action, status=status, reason=reason)


def resolve_all(descriptors: list[FieldDescriptor], ctx: Context, ats: str | None = None) -> list[FieldResult]:
    return [resolve_field(d, ctx, ats) for d in descriptors]


def classify_after_fill(expected: dict[str, Any], d: FieldDescriptor) -> FieldStatus:
    """Validation status of a field after the page was (partly) filled (doc §17, §38).

    ``expected`` is the stored engine result (``FieldResult.to_dict()``) for this field.
    """
    current = (d.current_value or "").strip()
    empty = current == "" or current.lower() in {"false", "off", "unchecked"}
    action = expected.get("action")
    if action == "skip":
        return FieldStatus.SKIPPED
    if action == "user_action":
        return FieldStatus.USER_ACTION_REQUIRED if empty else FieldStatus.FILLED
    if d.ownership in (FieldOwnership.USER_FILLED, FieldOwnership.USER_MODIFIED_AGENT_VALUE):
        return FieldStatus.FILLED if not empty else (FieldStatus.MISSING_REQUIRED if d.required else FieldStatus.OPTIONAL_EMPTY)
    if empty:
        if d.ownership is FieldOwnership.AGENT_FILLED:
            return FieldStatus.FAILED_TO_FILL
        return FieldStatus.MISSING_REQUIRED if d.required else FieldStatus.OPTIONAL_EMPTY
    if d.ownership is FieldOwnership.AGENT_FILLED:
        canon = expected.get("canonical_field") or ""
        opt = expected.get("option") or {}
        exp = {_norm_compare(canon, x) for x in (expected.get("value"), opt.get("label"), opt.get("value")) if x}
        if exp and _norm_compare(canon, current) not in exp and expected.get("kind") != "checkbox":
            return FieldStatus.NEEDS_REVIEW
        return FieldStatus.FILLED
    if action in ("review", "confirm", "conflict", "ask"):
        # A value is present that we did not put there and have not vouched for.
        return FieldStatus.FILLED if d.ownership is FieldOwnership.SITE_DEFAULT and action == "keep" else FieldStatus.NEEDS_REVIEW
    return FieldStatus.FILLED
