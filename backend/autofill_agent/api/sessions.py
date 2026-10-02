"""Application sessions: create, recover, analyze pages, record answers, validate, final review (doc §5, §31-§34, §38, §39)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from autofill_agent import session_service as svc
from autofill_agent.api.deps import get_session
from autofill_agent.db.enums import (
    AnswerSource, ApplicationStatus, AtsProvider, FieldOwnership, FieldStatus, SessionStatus,
)
from autofill_agent.db.models import (
    Application, ApplicationSession, ApprovedAnswer, Profile, Resume, SessionAnswer, utcnow,
)
from autofill_agent.duplicates import find_duplicates
from autofill_agent.engine import resolver
from autofill_agent.engine.custom_questions import JOB_SPECIFIC
from autofill_agent.engine.descriptor import FieldDescriptor
from autofill_agent.resume_store import sha256_of
from autofill_agent.security import require_token

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"], dependencies=[Depends(require_token)])

Text = Annotated[str, Field(max_length=2000)]


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(None, max_length=200)
    job_title: str | None = Field(None, max_length=200)
    job_id: str | None = Field(None, max_length=100)
    url: str | None = Field(None, max_length=2048)
    location: str | None = Field(None, max_length=200)
    job_description: str | None = Field(None, max_length=60000)
    ats: AtsProvider = AtsProvider.UNKNOWN
    resume_id: int | None = None
    force: bool = False

    @field_validator("ats", mode="before")
    @classmethod
    def _ats(cls, v):
        return v.upper() if isinstance(v, str) else v

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v is not None and not re.match(r"^https?://", v):
            raise ValueError("url must be http(s)")
        return v

    @model_validator(mode="after")
    def _something(self):
        if not (self.url or self.company):
            raise ValueError("provide at least a url or a company")
        return self


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SessionStatus | None = None
    current_page_url: str | None = Field(None, max_length=2048)
    current_page_index: int | None = Field(None, ge=0, le=500)
    company: str | None = Field(None, max_length=200)
    job_title: str | None = Field(None, max_length=200)
    job_id: str | None = Field(None, max_length=100)
    location: str | None = Field(None, max_length=200)
    job_description: str | None = Field(None, max_length=60000)
    ats: AtsProvider | None = None

    @field_validator("ats", mode="before")
    @classmethod
    def _ats(cls, v):
        return v.upper() if isinstance(v, str) else v


class AnalyzeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_index: int = Field(0, ge=0, le=500)
    url: str | None = Field(None, max_length=2048)
    ats: str | None = Field(None, max_length=32)
    fields: list[FieldDescriptor] = Field(max_length=500)


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_index: int = Field(0, ge=0, le=500)
    field_key: str = Field(min_length=1, max_length=500)
    value: str = Field(max_length=8000)
    remember: bool = False


class ConflictResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_field: str = Field(max_length=100)
    choice: Literal["profile", "resume", "custom"]
    value: str | None = Field(None, max_length=500)


class ResumeChoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_id: int


class FillItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str = Field(min_length=1, max_length=500)
    outcome: Literal["FILLED", "FAILED_TO_FILL", "SKIPPED"]
    ownership: FieldOwnership = FieldOwnership.AGENT_FILLED
    value: str | None = Field(None, max_length=8000)
    error: str | None = Field(None, max_length=300)


class FillReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page_index: int = Field(0, ge=0, le=500)
    fields: list[FillItem] = Field(max_length=500)


class ValidateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page_index: int = Field(0, ge=0, le=500)
    ats: str | None = Field(None, max_length=32)
    fields: list[FieldDescriptor] = Field(max_length=500)


def _get(s: Session, session_id: int) -> ApplicationSession:
    sess = s.get(ApplicationSession, session_id)
    if sess is None:
        raise HTTPException(404, "No such session")
    return sess


def _app_out(a: Application) -> dict:
    return {
        "id": a.id, "company": a.company, "job_title": a.job_title, "job_id": a.job_id, "job_url": a.job_url, "location": a.location,
        "ats": a.ats.value, "status": a.status.value, "resume_id": a.resume_id, "resume_filename": a.resume_filename,
        "resume_sha256": a.resume_sha256, "created_at": a.created_at, "updated_at": a.updated_at, "submitted_at": a.submitted_at,
    }


def session_out(s: Session, sess: ApplicationSession, detail: bool = False) -> dict:
    rows = list(s.scalars(select(SessionAnswer).where(SessionAnswer.session_id == sess.id)))
    out = {
        "id": sess.id, "application_id": sess.application_id, "status": sess.status.value, "current_page_url": sess.current_page_url,
        "current_page_index": sess.current_page_index, "created_at": sess.created_at, "updated_at": sess.updated_at,
        "application": _app_out(sess.application), "counts": svc.counts(rows),
    }
    if detail:
        out["resume"] = svc.resume_state(s, sess.application, sess)
        out["errors"] = sess.errors or []
    return out


def _duplicate_payload(s: Session, matches) -> dict:
    items = []
    for m in matches[:5]:
        a = m.application
        active = s.scalar(select(ApplicationSession).where(
            ApplicationSession.application_id == a.id, ApplicationSession.status.in_([SessionStatus.ACTIVE, SessionStatus.PAUSED]))
            .order_by(ApplicationSession.id.desc()))
        items.append({**_app_out(a), "reason": m.reason, "strength": m.strength, "active_session_id": active.id if active else None})
    return {"code": "POSSIBLE_DUPLICATE", "message": "POSSIBLE DUPLICATE APPLICATION", "matches": items}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(body: SessionCreate, s: Session = Depends(get_session)):
    resume = s.get(Resume, body.resume_id) if body.resume_id else s.scalar(select(Resume).where(Resume.is_current.is_(True)))
    if resume is None:
        raise HTTPException(409, "Select a resume for this application first" if not body.resume_id else "No such resume")
    if resume.archived_at is not None:
        raise HTTPException(409, "That resume is archived")

    if not body.force:
        matches = find_duplicates(list(s.scalars(select(Application))), body.company, body.job_title, body.job_id, body.url)
        if matches:
            return JSONResponse(status_code=409, content=_jsonable({"detail": _duplicate_payload(s, matches)}))

    app = Application(
        company=body.company, job_title=body.job_title, job_id=body.job_id, job_url=body.url, location=body.location,
        job_description=body.job_description, ats=body.ats, status=ApplicationStatus.STARTED,
        resume_id=resume.id, resume_filename=resume.filename, resume_sha256=resume.sha256,
    )
    sess = ApplicationSession(application=app, status=SessionStatus.ACTIVE, current_page_url=body.url, overrides={})
    s.add(sess)
    s.commit()
    return JSONResponse(status_code=201, content=_jsonable(session_out(s, sess, detail=True)))


def _jsonable(obj):
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(obj)


@router.get("")
def list_sessions(status_filter: str | None = Query(None, alias="status"), url: str | None = Query(None, max_length=2048),
                  s: Session = Depends(get_session)):
    """Incomplete sessions by default (ACTIVE and PAUSED), newest first, for recovery after a restart (doc §32)."""
    stmt = select(ApplicationSession).order_by(ApplicationSession.updated_at.desc(), ApplicationSession.id.desc())
    if status_filter:
        try:
            wanted = [SessionStatus(x) for x in status_filter.upper().split(",")]
        except ValueError:
            raise HTTPException(422, "unknown status") from None
        stmt = stmt.where(ApplicationSession.status.in_(wanted))
    else:
        stmt = stmt.where(ApplicationSession.status.in_([SessionStatus.ACTIVE, SessionStatus.PAUSED]))
    sessions = list(s.scalars(stmt.limit(200)))
    if url:
        from autofill_agent.duplicates import norm_url

        nu = norm_url(url)
        sessions = [x for x in sessions if norm_url(x.application.job_url) == nu or norm_url(x.current_page_url) == nu]
    return [session_out(s, x) for x in sessions]


@router.get("/{session_id}")
def get_session_detail(session_id: int, s: Session = Depends(get_session)):
    return session_out(s, _get(s, session_id), detail=True)


@router.patch("/{session_id}")
def patch_session(session_id: int, body: SessionPatch, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("status", "current_page_url", "current_page_index"):
        if k in data and data[k] is not None:
            setattr(sess, k, data[k])
    for k in ("company", "job_title", "job_id", "location", "job_description", "ats"):
        if k in data and data[k] is not None:
            setattr(sess.application, k, data[k])
    s.commit()
    return session_out(s, sess, detail=True)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, delete_application: bool = False, s: Session = Depends(get_session)) -> Response:
    sess = _get(s, session_id)
    app = sess.application
    s.delete(sess)
    s.flush()
    if delete_application and not s.scalars(select(ApplicationSession).where(ApplicationSession.application_id == app.id)).first():
        s.delete(app)
    s.commit()
    return Response(status_code=204)


# --- scanning and answers -----------------------------------------------------


def _row(s: Session, session_id: int, page_index: int, key: str) -> SessionAnswer:
    row = s.scalar(select(SessionAnswer).where(
        SessionAnswer.session_id == session_id, SessionAnswer.page_index == page_index, SessionAnswer.field_key == key))
    if row is None:
        raise HTTPException(404, "Unknown field; analyze the page first")
    return row


@router.post("/{session_id}/analyze")
def analyze_page(session_id: int, body: AnalyzeIn, request: Request, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    if sess.status in (SessionStatus.COMPLETED, SessionStatus.ABANDONED):
        raise HTTPException(409, f"This session is {sess.status.value.lower()}")
    if body.url:
        sess.current_page_url = body.url
    results, ctx = svc.analyze(s, sess, body.page_index, body.fields, body.ats, getattr(request.app.state, "ai", None))
    sess.status = SessionStatus.ACTIVE
    mode = svc.get_mode(s)
    s.commit()

    out = []
    for r in results:
        d = r.to_dict()
        d["auto"] = mode == "STANDARD" and r.action == "fill" and not r.sensitive and r.band == "READY"
        out.append(d)
    rows = list(s.scalars(select(SessionAnswer).where(SessionAnswer.session_id == sess.id)))
    return {
        "session_id": sess.id, "page_index": body.page_index, "mode": mode, "results": out,
        "counts": svc.counts([r for r in rows if r.page_index == body.page_index]),
        "needs_attention": svc.attention_items([r for r in rows if r.page_index == body.page_index]),
        "resume": svc.resume_state(s, sess.application, sess),
        "section_counts": {
            "experience": len((ctx.resume.data.get("experience") or [])) if ctx.resume else 0,
            "education": len((ctx.resume.data.get("education") or [])) if ctx.resume else 0,
            "certification": len((ctx.resume.data.get("certifications") or [])) if ctx.resume else 0,
            "language": len((ctx.resume.data.get("languages") or [])) if ctx.resume else 0,
        },
    }


@router.get("/{session_id}/attention")
def needs_attention(session_id: int, include_optional: bool = False, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    rows = list(s.scalars(select(SessionAnswer).where(SessionAnswer.session_id == sess.id)))
    items = svc.attention_items(rows, include_optional)
    rs = svc.resume_state(s, sess.application, sess)
    return {"count": len(items), "items": items, "resume_blocked": rs["blocked"]}


@router.post("/{session_id}/answers")
def save_answer(session_id: int, body: AnswerIn, s: Session = Depends(get_session)):
    """The user's answer for this application; it outranks every other source (doc §5 step 12)."""
    sess = _get(s, session_id)
    row = _row(s, session_id, body.page_index, body.field_key)
    res = row.result or {}
    if row.action in ("user_action",) and row.canonical_field in ("legal.consent", "legal.signature", "security.captcha"):
        raise HTTPException(409, "This must be completed by you on the page; the agent will not provide it")
    if row.canonical_field == "security.password":
        raise HTTPException(409, "Passwords are never stored or filled by the agent")
    canonical = row.canonical_field
    if canonical:
        okey = f"{canonical}[{row.section_index or 0}]" if row.section else canonical
    else:
        qh = res.get("question_hash")
        if not qh:
            raise HTTPException(422, "This field has no question text to attach an answer to")
        okey = f"q:{qh}"
    sess.overrides = {**(sess.overrides or {}), okey: body.value}
    row.user_override = True
    row.final_value = body.value

    remembered = False
    note = None
    qh = res.get("question_hash")
    if body.remember:
        if row.sensitive or (canonical or "").startswith(("legal.", "security.", "sensitive.")):
            note = "Sensitive answers are not remembered; set a policy in your profile instead."
        elif not qh:
            note = "No question text to remember this under."
        else:
            prof = s.get(Profile, 1)
            src = row.source
            for old in s.scalars(select(ApprovedAnswer).where(ApprovedAnswer.question_hash == qh, ApprovedAnswer.superseded.is_(False))):
                old.superseded = True
            s.add(ApprovedAnswer(
                canonical_field=canonical, question_text=(row.label or "")[:2000], question_hash=qh, answer=body.value,
                resume_sha256=sess.application.resume_sha256 if res.get("source") in ("RESUME", "CALCULATED") else None,
                profile_version=prof.updated_at if prof and res.get("source") == "PROFILE" else None,
                company=sess.application.company if JOB_SPECIFIC.search(row.label or "") else None,
                depends_on_resume=res.get("source") in ("RESUME", "CALCULATED"), depends_on_profile=res.get("source") == "PROFILE",
                source_session_id=sess.id,
            ))
            remembered = True
    s.commit()
    return {"override_key": okey, "remembered": remembered, "note": note}


@router.post("/{session_id}/conflicts/resolve")
def resolve_conflict(session_id: int, body: ConflictResolveIn, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    ctx = svc.build_context(s, sess)
    if body.canonical_field not in resolver.CONFLICT_FIELDS:
        raise HTTPException(422, "That field has no profile/resume conflict to resolve")
    if body.choice == "custom":
        if not body.value or not body.value.strip():
            raise HTTPException(422, "Enter the value to use")
        value = body.value.strip()
    elif body.choice == "profile":
        value = resolver._profile_value(body.canonical_field, ctx)
    else:
        value = resolver._resume_contact(ctx, body.canonical_field)
    if not value:
        raise HTTPException(409, f"There is no {body.choice} value for that field")
    sess.overrides = {**(sess.overrides or {}), body.canonical_field: str(value)}
    s.commit()
    return {"canonical_field": body.canonical_field, "value": str(value)}


@router.post("/{session_id}/resume")
def choose_resume(session_id: int, body: ResumeChoiceIn, s: Session = Depends(get_session)):
    """Explicitly choose which resume this application uses (doc §10)."""
    sess = _get(s, session_id)
    resume = s.get(Resume, body.resume_id)
    if resume is None:
        raise HTTPException(404, "No such resume")
    if resume.archived_at is not None:
        raise HTTPException(409, "That resume is archived")
    app = sess.application
    app.resume_id, app.resume_filename, app.resume_sha256 = resume.id, resume.filename, resume.sha256
    sess.overrides = {**(sess.overrides or {}), svc.RESUME_CONFIRMED_KEY: resume.sha256}
    s.commit()
    return session_out(s, sess, detail=True)


@router.get("/{session_id}/resume-file")
def resume_file(session_id: int, s: Session = Depends(get_session)):
    """The exact resume for this application, only if it is intact and not blocked (doc §22)."""
    sess = _get(s, session_id)
    rs = svc.resume_state(s, sess.application, sess)
    if rs["blocked"]:
        raise HTTPException(409, rs["blocked"])
    resume = s.get(Resume, sess.application.resume_id)
    from pathlib import Path

    path = Path(resume.stored_path)
    if sha256_of(path) != sess.application.resume_sha256:
        raise HTTPException(409, "The stored resume file does not match its recorded SHA-256")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", resume.filename)
    return Response(content=path.read_bytes(), media_type=resume.mime_type, headers={
        "X-Resume-SHA256": resume.sha256, "X-Resume-Filename": safe_name,
        "Content-Disposition": f'attachment; filename="{safe_name}"'})


@router.post("/{session_id}/fill-report")
def fill_report(session_id: int, body: FillReport, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    rows = {r.field_key: r for r in s.scalars(select(SessionAnswer).where(
        SessionAnswer.session_id == sess.id, SessionAnswer.page_index == body.page_index))}
    updated = 0
    for item in body.fields:
        row = rows.get(item.key)
        if row is None:
            continue
        row.status = FieldStatus(item.outcome)
        row.ownership = item.ownership
        if item.value is not None:
            row.final_value = item.value
        if item.outcome == "FAILED_TO_FILL":
            row.reason = f"Could not fill this automatically: {item.error}" if item.error else "Could not fill this automatically"
        updated += 1
    if updated and sess.application.status is ApplicationStatus.STARTED:
        sess.application.status = ApplicationStatus.IN_PROGRESS
    s.commit()
    return {"updated": updated}


@router.post("/{session_id}/validate")
def validate_page(session_id: int, body: ValidateIn, request: Request, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    out = svc.validate(s, sess, body.page_index, body.fields, body.ats, getattr(request.app.state, "ai", None))
    s.commit()
    rows = list(s.scalars(select(SessionAnswer).where(SessionAnswer.session_id == sess.id, SessionAnswer.page_index == body.page_index)))
    return {"fields": out, "counts": svc.counts(rows), "needs_attention": svc.attention_items(rows)}


@router.get("/{session_id}/final-review")
def get_final_review(session_id: int, s: Session = Depends(get_session)):
    sess = _get(s, session_id)
    result = svc.final_review(s, sess)
    s.commit()
    return result
