"""Question memory management, data export and data deletion (doc §23, §35)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from autofill_agent.api.deps import get_session
from autofill_agent.api.schemas import LibraryAnswerOut, ProfileOut, SensitivePrefOut
from autofill_agent.db.models import (
    AppSetting, Application, ApplicationSession, ApprovedAnswer, LibraryAnswer, Profile, Resume,
    SensitivePreference, SessionAnswer,
)
from autofill_agent.security import require_token

log = logging.getLogger("autofill_agent")

router = APIRouter(prefix="/api/v1", tags=["data"], dependencies=[Depends(require_token)])

CONFIRM_PHRASE = "DELETE MY DATA"


def _memory_out(a: ApprovedAnswer) -> dict:
    return {
        "id": a.id, "question": a.question_text, "canonical_field": a.canonical_field, "answer": a.answer,
        "company": a.company, "depends_on_resume": a.depends_on_resume, "depends_on_profile": a.depends_on_profile,
        "created_at": a.created_at,
    }


@router.get("/memory")
def list_memory(s: Session = Depends(get_session)):
    """Answers the agent remembered from your approvals, so you can see and remove them."""
    rows = s.scalars(select(ApprovedAnswer).where(ApprovedAnswer.superseded.is_(False)).order_by(ApprovedAnswer.created_at.desc()))
    return [_memory_out(a) for a in rows]


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def forget(memory_id: int, s: Session = Depends(get_session)) -> Response:
    a = s.get(ApprovedAnswer, memory_id)
    if a is None:
        raise HTTPException(404, "No such remembered answer")
    s.delete(a)
    s.commit()
    return Response(status_code=204)


@router.get("/data/export")
def export_data(s: Session = Depends(get_session)):
    """Everything except resume files, as one JSON document you can keep."""
    profile = s.get(Profile, 1)
    apps = list(s.scalars(select(Application).order_by(Application.id)))
    body = {
        "profile": ProfileOut.model_validate(profile).model_dump(mode="json") if profile else None,
        "sensitive_preferences": [SensitivePrefOut.model_validate(p).model_dump(mode="json") for p in s.scalars(select(SensitivePreference))],
        "answer_library": [LibraryAnswerOut.model_validate(a).model_dump(mode="json") for a in s.scalars(select(LibraryAnswer))],
        "remembered_answers": [_memory_out(a) for a in s.scalars(select(ApprovedAnswer).where(ApprovedAnswer.superseded.is_(False)))],
        "applications": [
            {"company": a.company, "job_title": a.job_title, "job_id": a.job_id, "url": a.job_url, "location": a.location, "ats": a.ats.value,
             "status": a.status.value, "resume_filename": a.resume_filename, "resume_sha256": a.resume_sha256,
             "created_at": a.created_at.isoformat(), "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None}
            for a in apps
        ],
        "resumes": [{"filename": r.filename, "sha256": r.sha256, "status": r.status.value, "verified_data": r.verified_data}
                    for r in s.scalars(select(Resume).where(Resume.archived_at.is_(None)))],
    }
    return JSONResponse(jsonable_encoder(body), headers={"Content-Disposition": 'attachment; filename="autofill-agent-export.json"', "Cache-Control": "no-store"})


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["applications", "memory", "all"]
    confirm: str


@router.post("/data/delete")
def delete_data(body: DeleteIn, request: Request, s: Session = Depends(get_session)):
    """Permanently erase local data. ``all`` removes the profile, answers, resumes (and their files) and history."""
    if body.confirm != CONFIRM_PHRASE:
        raise HTTPException(422, f'Type "{CONFIRM_PHRASE}" to confirm')
    counts: dict[str, int] = {}
    if body.scope in ("applications", "all"):
        s.execute(delete(SessionAnswer)); s.execute(delete(ApplicationSession))
        counts["applications"] = s.execute(delete(Application)).rowcount or 0
    if body.scope in ("memory", "all"):
        counts["remembered_answers"] = s.execute(delete(ApprovedAnswer)).rowcount or 0
    files = 0
    if body.scope == "all":
        paths = [Path(p) for p in s.scalars(select(Resume.stored_path))]
        counts["resumes"] = s.execute(delete(Resume)).rowcount or 0
        counts["answers"] = s.execute(delete(LibraryAnswer)).rowcount or 0
        s.execute(delete(SensitivePreference)); s.execute(delete(Profile)); s.execute(delete(AppSetting))
        resume_dir = request.app.state.settings.resume_dir.resolve()
        for p in paths:
            try:
                if p.resolve().is_relative_to(resume_dir):
                    p.unlink(missing_ok=True)
                    files += 1
            except OSError:
                log.warning("Could not remove a stored resume file")
        # Anything left over in the resume folder is an orphan from an earlier session.
        for p in resume_dir.glob("*"):
            if p.is_file():
                p.unlink(missing_ok=True)
    s.commit()
    log.info("Data deleted: scope=%s", body.scope)
    return {"deleted": counts, "files_removed": files}
