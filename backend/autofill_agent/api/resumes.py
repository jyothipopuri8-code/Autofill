"""Resume manager: upload, select, hash, archive, delete (doc §9, §10, §22)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autofill_agent.api.deps import get_session
from autofill_agent.api.schemas import ResumeDataOut, ResumeIntegrityOut, ResumeOut
from autofill_agent.db.enums import ResumeStatus
from autofill_agent.db.models import Resume, utcnow
from autofill_agent.resume_parser import ResumeParseError, parse_resume_file
from autofill_agent.resume_schema import ResumeData
from autofill_agent.resume_store import ResumeUploadError, sanitize_filename, save_upload, sha256_of
from autofill_agent.security import require_token

log = logging.getLogger("autofill_agent.resumes")

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"], dependencies=[Depends(require_token)])


def _get(s: Session, resume_id: int) -> Resume:
    resume = s.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(404, "No such resume")
    return resume


@router.post("", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
def upload_resume(request: Request, file: UploadFile = File(...), s: Session = Depends(get_session)) -> Resume:
    settings = request.app.state.settings
    display_name = sanitize_filename(file.filename)
    if not display_name:
        raise HTTPException(400, "A filename is required")

    try:
        stored = save_upload(file.file, display_name, settings.resume_dir, settings.max_resume_bytes)
    except ResumeUploadError as e:
        raise HTTPException(e.status_code, e.detail) from None

    existing = s.scalar(select(Resume).where(Resume.sha256 == stored.sha256))
    if existing is not None:
        # Identical bytes are already stored under this name; keep that file.
        raise HTTPException(409, f"This exact resume is already stored as '{existing.filename}' (id {existing.id})")

    resume = Resume(
        filename=display_name,
        stored_path=str(stored.path),
        sha256=stored.sha256,
        mime_type=stored.mime_type,
        size_bytes=stored.size,
    )
    s.add(resume)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, "This resume is already stored") from None
    log.info("Stored resume id=%s sha256=%s size=%s", resume.id, resume.sha256[:12], resume.size_bytes)
    return resume


@router.get("", response_model=list[ResumeOut])
def list_resumes(include_archived: bool = Query(False), s: Session = Depends(get_session)):
    stmt = select(Resume).order_by(Resume.uploaded_at.desc(), Resume.id.desc())
    if not include_archived:
        stmt = stmt.where(Resume.archived_at.is_(None))
    return list(s.scalars(stmt))


@router.get("/current", response_model=ResumeOut)
def current_resume(s: Session = Depends(get_session)) -> Resume:
    resume = s.scalar(select(Resume).where(Resume.is_current.is_(True)))
    if resume is None:
        raise HTTPException(404, "No current resume selected")
    return resume


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(resume_id: int, s: Session = Depends(get_session)) -> Resume:
    return _get(s, resume_id)


@router.post("/{resume_id}/set-current", response_model=ResumeOut)
def set_current(resume_id: int, s: Session = Depends(get_session)) -> Resume:
    resume = _get(s, resume_id)
    if resume.archived_at is not None:
        raise HTTPException(409, "Archived resumes cannot be current; unarchive it first")
    # Clear first so the one-current-resume unique index is never violated mid-transaction.
    s.execute(update(Resume).where(Resume.is_current.is_(True)).values(is_current=False))
    s.refresh(resume)
    resume.is_current = True
    s.commit()
    return resume


@router.post("/{resume_id}/archive", response_model=ResumeOut)
def archive(resume_id: int, s: Session = Depends(get_session)) -> Resume:
    resume = _get(s, resume_id)
    resume.archived_at = resume.archived_at or utcnow()
    resume.is_current = False
    s.commit()
    return resume


@router.post("/{resume_id}/unarchive", response_model=ResumeOut)
def unarchive(resume_id: int, s: Session = Depends(get_session)) -> Resume:
    resume = _get(s, resume_id)
    resume.archived_at = None
    s.commit()
    return resume


@router.get("/{resume_id}/integrity", response_model=ResumeIntegrityOut)
def integrity(resume_id: int, s: Session = Depends(get_session)) -> ResumeIntegrityOut:
    """Confirm the file still exists and still matches its recorded SHA-256 (doc §22)."""
    resume = _get(s, resume_id)
    actual = sha256_of(Path(resume.stored_path))
    return ResumeIntegrityOut(
        id=resume.id,
        file_exists=actual is not None,
        sha256_matches=actual == resume.sha256,
        expected_sha256=resume.sha256,
        actual_sha256=actual,
    )


def _data_out(resume: Resume) -> ResumeDataOut:
    return ResumeDataOut(
        resume_id=resume.id,
        status=resume.status,
        verified=resume.status is ResumeStatus.VERIFIED,
        parsed_data=resume.parsed_data,
        verified_data=resume.verified_data,
        effective_data=resume.verified_data or resume.parsed_data,
    )


def _require_intact_file(resume: Resume) -> Path:
    path = Path(resume.stored_path)
    actual = sha256_of(path)
    if actual is None:
        raise HTTPException(409, "The stored resume file is missing")
    if actual != resume.sha256:
        raise HTTPException(409, "The stored resume file no longer matches its SHA-256; re-upload it")
    return path


@router.post("/{resume_id}/parse", response_model=ResumeDataOut)
def parse_resume(resume_id: int, s: Session = Depends(get_session)) -> ResumeDataOut:
    """Extract structured data from the stored file (doc §5 step 3).

    Re-parsing replaces the parser output and returns the resume to PARSED (unverified).
    Any corrections already saved are kept so they are not lost.
    """
    resume = _get(s, resume_id)
    path = _require_intact_file(resume)
    try:
        parsed = parse_resume_file(path)
    except ResumeParseError as e:
        raise HTTPException(422, str(e)) from None
    resume.parsed_data = parsed.model_dump(mode="json")
    resume.parsed_at = utcnow()
    resume.status = ResumeStatus.PARSED
    resume.verified_at = None
    s.commit()
    return _data_out(resume)


@router.get("/{resume_id}/data", response_model=ResumeDataOut)
def get_resume_data(resume_id: int, s: Session = Depends(get_session)) -> ResumeDataOut:
    return _data_out(_get(s, resume_id))


@router.put("/{resume_id}/verified-data", response_model=ResumeDataOut)
def save_corrections(resume_id: int, body: ResumeData, s: Session = Depends(get_session)) -> ResumeDataOut:
    """Save the user's corrected data as a draft. Editing a verified resume returns it to unverified."""
    resume = _get(s, resume_id)
    resume.verified_data = body.model_dump(mode="json")
    resume.verified_at = None
    resume.status = ResumeStatus.PARSED if resume.parsed_at else ResumeStatus.UPLOADED
    s.commit()
    return _data_out(resume)


@router.post("/{resume_id}/verify", response_model=ResumeDataOut)
def verify_resume(resume_id: int, s: Session = Depends(get_session)) -> ResumeDataOut:
    """The user confirms the data is accurate. Uses saved corrections, or the parse as-is if none."""
    resume = _get(s, resume_id)
    _require_intact_file(resume)
    if resume.verified_data is None:
        if resume.parsed_data is None:
            raise HTTPException(409, "Parse the resume (or enter its data) before verifying")
        data = dict(resume.parsed_data)
        data.pop("warnings", None)
        resume.verified_data = ResumeData.model_validate(data).model_dump(mode="json")
    resume.status = ResumeStatus.VERIFIED
    resume.verified_at = utcnow()
    s.commit()
    return _data_out(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: int, s: Session = Depends(get_session)) -> Response:
    """Delete the record and the stored file. Application history keeps its filename/hash snapshot."""
    resume = _get(s, resume_id)
    path = Path(resume.stored_path)
    s.delete(resume)
    s.commit()
    path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
