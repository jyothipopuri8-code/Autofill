"""Resume manager: upload, select, hash, archive, delete (doc §9, §10, §22)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autofill_agent.api.deps import get_session
from autofill_agent.api.schemas import ResumeIntegrityOut, ResumeOut
from autofill_agent.db.models import Resume, utcnow
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


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: int, s: Session = Depends(get_session)) -> Response:
    """Delete the record and the stored file. Application history keeps its filename/hash snapshot."""
    resume = _get(s, resume_id)
    path = Path(resume.stored_path)
    s.delete(resume)
    s.commit()
    path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
