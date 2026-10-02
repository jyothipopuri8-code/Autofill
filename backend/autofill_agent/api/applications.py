"""Application history and tracking (doc §33, §41). Final statuses are set by the user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from autofill_agent.api.deps import get_session
from autofill_agent.api.sessions import _app_out
from autofill_agent.db.enums import ApplicationStatus, SessionStatus
from autofill_agent.db.models import Application, ApplicationSession, SessionAnswer, utcnow
from autofill_agent.security import require_token

router = APIRouter(prefix="/api/v1/applications", tags=["applications"], dependencies=[Depends(require_token)])


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ApplicationStatus


def _get(s: Session, app_id: int) -> Application:
    a = s.get(Application, app_id)
    if a is None:
        raise HTTPException(404, "No such application")
    return a


@router.get("")
def list_applications(status_filter: str | None = Query(None, alias="status"), q: str | None = Query(None, max_length=200),
                      limit: int = Query(100, ge=1, le=500), s: Session = Depends(get_session)):
    stmt = select(Application).order_by(Application.created_at.desc(), Application.id.desc())
    if status_filter:
        try:
            stmt = stmt.where(Application.status.in_([ApplicationStatus(x) for x in status_filter.upper().split(",")]))
        except ValueError:
            raise HTTPException(422, "unknown status") from None
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func

        stmt = stmt.where(or_(func.lower(Application.company).like(like), func.lower(Application.job_title).like(like)))
    return [_app_out(a) for a in s.scalars(stmt.limit(limit))]


@router.get("/{app_id}")
def get_application(app_id: int, s: Session = Depends(get_session)):
    a = _get(s, app_id)
    sessions = list(s.scalars(select(ApplicationSession).where(ApplicationSession.application_id == a.id)))
    rows = list(s.scalars(select(SessionAnswer).where(SessionAnswer.session_id.in_([x.id for x in sessions])))) if sessions else []
    return {
        **_app_out(a),
        "sessions": [{"id": x.id, "status": x.status.value, "updated_at": x.updated_at} for x in sessions],
        "questions": [
            {"page_index": r.page_index, "label": r.label, "canonical_field": r.canonical_field, "status": r.status.value,
             "answer": r.final_value if r.final_value is not None else r.proposed_value, "source": r.source.value}
            for r in sorted(rows, key=lambda r: (r.page_index, r.id or 0)) if r.label
        ],
    }


@router.patch("/{app_id}")
def set_status(app_id: int, body: StatusIn, s: Session = Depends(get_session)):
    """Only the user changes the final status (for example after submitting on the employer's site)."""
    a = _get(s, app_id)
    a.status = body.status
    if body.status is ApplicationStatus.SUBMITTED and a.submitted_at is None:
        a.submitted_at = utcnow()
        for sess in s.scalars(select(ApplicationSession).where(ApplicationSession.application_id == a.id)):
            sess.status = SessionStatus.COMPLETED
    s.commit()
    return _app_out(a)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(app_id: int, s: Session = Depends(get_session)) -> Response:
    s.delete(_get(s, app_id))
    s.commit()
    return Response(status_code=204)
