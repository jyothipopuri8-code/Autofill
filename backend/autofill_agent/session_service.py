"""Building the engine context from the database and persisting session state."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from autofill_agent.db.enums import AnswerSource, ApplicationStatus, FieldOwnership, FieldStatus, SessionStatus
from autofill_agent.db.models import (
    AppSetting, Application, ApplicationSession, ApprovedAnswer, LibraryAnswer, Profile, Resume,
    SensitivePreference, SessionAnswer, utcnow,
)
from autofill_agent.engine.descriptor import FieldDescriptor
from autofill_agent.engine.resolver import (
    ApprovedEntry, Context, FieldResult, LibraryEntry, ResumeInfo, classify_after_fill, resolve_all,
)
from autofill_agent.engine.taxonomy import SENSITIVE_KEY_TO_FIELD
from autofill_agent.resume_store import sha256_of

MODES = ("SAFE", "STANDARD", "MANUAL_ASSIST")
DEFAULT_MODE = "SAFE"
RESUME_CONFIRMED_KEY = "resume.confirmed_sha"
_PROFILE_COLS = [c.name for c in Profile.__table__.columns]


def version_of(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=None).isoformat() if dt else None


def get_mode(s: Session) -> str:
    row = s.get(AppSetting, "mode")
    return row.value if row and row.value in MODES else DEFAULT_MODE


def set_mode(s: Session, mode: str) -> None:
    row = s.get(AppSetting, "mode")
    if row is None:
        s.add(AppSetting(key="mode", value=mode))
    else:
        row.value = mode


def resume_state(s: Session, app: Application, sess: ApplicationSession) -> dict[str, Any]:
    expected = s.get(Resume, app.resume_id) if app.resume_id else None
    current = s.scalar(select(Resume).where(Resume.is_current.is_(True)))
    blocked: str | None = None
    warning: str | None = None
    if expected is None:
        blocked = "The resume this application started with was deleted; choose a resume to use."
    else:
        actual = sha256_of(Path(expected.stored_path))
        if actual != expected.sha256:
            blocked = "The stored resume file is missing or has changed; re-upload it and choose it again."
        elif current is not None and current.sha256 != expected.sha256 and (sess.overrides or {}).get(RESUME_CONFIRMED_KEY) != expected.sha256:
            blocked = (f"The current resume ('{current.filename}') differs from the one this application started with "
                       f"('{expected.filename}'). Choose which resume to use.")
        if expected.status.value != "VERIFIED":
            warning = "This resume's parsed data has not been verified."
    brief = lambda r: None if r is None else {"id": r.id, "filename": r.filename, "sha256": r.sha256, "verified": r.status.value == "VERIFIED"}
    return {"expected": brief(expected), "current": brief(current), "blocked": blocked, "warning": warning}


def build_context(s: Session, sess: ApplicationSession, ai: Any = None, today: date | None = None) -> Context:
    app = sess.application
    prof = s.get(Profile, 1)
    profile = {c: getattr(prof, c) for c in _PROFILE_COLS} if prof else {}

    sensitive: dict[str, tuple[str, str | None]] = {}
    prefs = {p.field: p for p in s.scalars(select(SensitivePreference))}
    for key, fld in SENSITIVE_KEY_TO_FIELD.items():
        if fld in prefs:
            sensitive[key] = (prefs[fld].policy.value, prefs[fld].value)

    library = {a.key: LibraryEntry(a.value, a.policy.value, a.verification.value == "VERIFIED") for a in s.scalars(select(LibraryAnswer))}

    rs = resume_state(s, app, sess)
    resume_row = s.get(Resume, app.resume_id) if app.resume_id else None
    resume = None
    if resume_row is not None:
        data = dict(resume_row.verified_data or resume_row.parsed_data or {})
        data.pop("warnings", None)
        resume = ResumeInfo(data, resume_row.status.value == "VERIFIED", resume_row.sha256, resume_row.filename)

    approved = [
        ApprovedEntry(a.question_hash, a.canonical_field, a.answer, a.resume_sha256, version_of(a.profile_version), a.company,
                      a.depends_on_resume, a.depends_on_profile)
        for a in s.scalars(select(ApprovedAnswer).where(ApprovedAnswer.superseded.is_(False)))
    ]
    return Context(
        profile=profile, profile_version=version_of(prof.updated_at) if prof else None,
        work_auth_verified=bool(prof and prof.work_authorization_verified), sensitive=sensitive, library=library,
        resume=resume, resume_blocked=rs["blocked"], overrides=dict(sess.overrides or {}), approved=approved,
        job={"company": app.company, "title": app.job_title, "description": app.job_description, "location": app.location},
        today=today or date.today(), ai=ai,
    )


def analyze(s: Session, sess: ApplicationSession, page_index: int, descriptors: list[FieldDescriptor], ats: str | None,
            ai: Any = None) -> tuple[list[FieldResult], Context]:
    ctx = build_context(s, sess, ai)
    results = resolve_all(descriptors, ctx, ats or sess.application.ats.value)
    persist_results(s, sess, page_index, descriptors, results)
    sess.current_page_index = page_index
    return results, ctx


def persist_results(s: Session, sess: ApplicationSession, page_index: int, descriptors: list[FieldDescriptor], results: list[FieldResult]) -> None:
    existing = {r.field_key: r for r in s.scalars(
        select(SessionAnswer).where(SessionAnswer.session_id == sess.id, SessionAnswer.page_index == page_index))}
    seen: set[str] = set()
    for d, r in zip(descriptors, results):
        seen.add(d.key)
        row = existing.get(d.key) or SessionAnswer(session_id=sess.id, page_index=page_index, field_key=d.key)
        if row.id is None:
            s.add(row)
        row.label = r.label
        row.canonical_field = r.canonical_field
        row.required = r.required
        row.proposed_value = r.value
        row.source = r.source
        row.confidence = r.confidence
        row.status = r.status
        row.ownership = d.ownership
        row.section = r.section
        row.section_index = r.section_index
        row.action = r.action
        row.reason = r.reason
        row.sensitive = r.sensitive
        row.band = r.band
        row.result = r.to_dict()
        if r.source is AnswerSource.USER_CURRENT:
            row.user_override = True
        if d.ownership in (FieldOwnership.USER_FILLED, FieldOwnership.USER_MODIFIED_AGENT_VALUE) and d.current_value:
            row.final_value = d.current_value
    for key, row in existing.items():
        if key not in seen:
            s.delete(row)


def counts(rows: list[SessionAnswer]) -> dict[str, int]:
    c = {"detected": len(rows), "complete": 0, "missing_required": 0, "needs_review": 0, "user_action_required": 0,
         "failed_to_fill": 0, "skipped": 0, "optional_empty": 0, "pending": 0}
    m = {FieldStatus.FILLED: "complete", FieldStatus.MISSING_REQUIRED: "missing_required", FieldStatus.NEEDS_REVIEW: "needs_review",
         FieldStatus.USER_ACTION_REQUIRED: "user_action_required", FieldStatus.FAILED_TO_FILL: "failed_to_fill",
         FieldStatus.SKIPPED: "skipped", FieldStatus.OPTIONAL_EMPTY: "optional_empty", FieldStatus.PENDING: "pending"}
    for r in rows:
        c[m[r.status]] += 1
    return c


def validate(s: Session, sess: ApplicationSession, page_index: int, descriptors: list[FieldDescriptor], ats: str | None,
             ai: Any = None) -> list[dict[str, Any]]:
    rows = {r.field_key: r for r in s.scalars(select(SessionAnswer).where(SessionAnswer.session_id == sess.id, SessionAnswer.page_index == page_index))}
    ctx = None
    out = []
    for d in descriptors:
        row = rows.get(d.key)
        if row is None or not row.result:
            # A field we have not analyzed (e.g. appeared after a DOM change): classify it fresh.
            ctx = ctx or build_context(s, sess, ai)
            from autofill_agent.engine.resolver import resolve_field

            fresh = resolve_field(d.model_copy(update={"ownership": FieldOwnership.EMPTY, "current_value": None}), ctx, ats or sess.application.ats.value)
            expected = fresh.to_dict()
            row = SessionAnswer(session_id=sess.id, page_index=page_index, field_key=d.key, label=fresh.label,
                                canonical_field=fresh.canonical_field, required=d.required, result=expected, action=fresh.action,
                                section=fresh.section, section_index=fresh.section_index, sensitive=fresh.sensitive)
            s.add(row)
        status = classify_after_fill(row.result, d)
        row.status = status
        row.ownership = d.ownership
        if d.current_value and d.ownership is not FieldOwnership.EMPTY:
            row.final_value = d.current_value[:4000]
        out.append({"key": d.key, "status": status.value, "label": row.label, "required": d.required, "action": row.action})
    return out


ATTENTION_ACTIONS = {"ask", "confirm", "conflict", "user_action"}


def attention_items(rows: list[SessionAnswer], include_optional: bool = False) -> list[dict[str, Any]]:
    items = []
    for r in sorted(rows, key=lambda r: (r.page_index, r.id or 0)):
        if r.status in (FieldStatus.FILLED, FieldStatus.SKIPPED, FieldStatus.PENDING):
            continue
        res = r.result or {}
        action = r.action
        if action not in ATTENTION_ACTIONS and r.status not in (FieldStatus.MISSING_REQUIRED, FieldStatus.FAILED_TO_FILL, FieldStatus.NEEDS_REVIEW):
            continue
        if not include_optional and not r.required and action == "ask" and not r.sensitive:
            continue
        items.append({
            "page_index": r.page_index, "key": r.field_key, "label": r.label, "canonical_field": r.canonical_field,
            "action": action, "status": r.status.value, "reason": r.reason, "required": r.required, "sensitive": r.sensitive,
            "suggestion": res.get("suggestion") or (res.get("value") if action in ("confirm", "review") else None),
            "conflict": res.get("conflict"), "kind": res.get("kind"),
        })
    return items


def final_review(s: Session, sess: ApplicationSession) -> dict[str, Any]:
    app = sess.application
    rows = list(s.scalars(select(SessionAnswer).where(SessionAnswer.session_id == sess.id)))
    rs = resume_state(s, app, sess)
    bad_status = {FieldStatus.MISSING_REQUIRED, FieldStatus.PENDING, FieldStatus.FAILED_TO_FILL}

    def check(cid: str, label: str, ok: bool, detail: str | None = None) -> dict[str, Any]:
        return {"id": cid, "label": label, "ok": ok, "detail": None if ok else detail}

    sect = lambda name: [r for r in rows if r.section == name]
    checks = [
        check("resume_selected", "Correct resume selected", rs["blocked"] is None and rs["expected"] is not None, rs["blocked"]),
        check("resume_hash", "Resume hash verified", rs["expected"] is not None and sha256_of(Path(s.get(Resume, app.resume_id).stored_path)) == app.resume_sha256 if rs["expected"] else False,
              "The stored resume file does not match its recorded SHA-256"),
        check("required_complete", "Required fields completed", not any(r.required and r.status in bad_status and r.action not in ("skip",) for r in rows),
              "Some required fields are still empty"),
        check("experience_complete", "Experience completed", not any(r.status in bad_status for r in sect("experience") if r.action != "skip"),
              "Work experience fields are incomplete"),
        check("education_complete", "Education completed", not any(r.status in bad_status for r in sect("education") if r.action != "skip"),
              "Education fields are incomplete"),
        check("custom_reviewed", "Custom questions reviewed",
              not any(r.canonical_field is None and r.action in ("ask", "confirm", "review") and r.status in (FieldStatus.MISSING_REQUIRED, FieldStatus.NEEDS_REVIEW) for r in rows),
              "Some custom questions still need your answer or review"),
        check("sensitive_reviewed", "Sensitive questions reviewed",
              not any(r.sensitive and r.action != "skip" and r.status in (FieldStatus.MISSING_REQUIRED, FieldStatus.NEEDS_REVIEW, FieldStatus.PENDING) for r in rows),
              "Sensitive questions are waiting for your decision"),
        check("conflicts_resolved", "No unresolved conflicts", not any(r.action == "conflict" and r.status is not FieldStatus.FILLED for r in rows),
              "Profile and resume still disagree on some details"),
        check("legal_done", "Legal actions completed by you", not any(r.action == "user_action" and r.status is FieldStatus.USER_ACTION_REQUIRED for r in rows),
              "Consents, signatures, CAPTCHAs or uploads are still waiting for you"),
        check("no_failures", "No autofill failures", not any(r.status is FieldStatus.FAILED_TO_FILL for r in rows), "Some fields failed to fill"),
        check("validated", "Every detected field validated", bool(rows) and not any(r.status is FieldStatus.PENDING for r in rows),
              "Scan and validate the page first" if not rows else "Some fields have not been filled or validated yet"),
    ]
    ready = all(c["ok"] for c in checks)
    if ready and app.status in (ApplicationStatus.STARTED, ApplicationStatus.IN_PROGRESS):
        app.status = ApplicationStatus.READY_FOR_REVIEW
    return {"ready": ready, "headline": "READY FOR USER REVIEW" if ready else "NOT READY", "checks": checks,
            "note": "This does not mean the application has been submitted. Review it and submit it yourself."}
