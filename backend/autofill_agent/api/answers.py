"""Reusable canonical answer library (doc §11)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autofill_agent.api.deps import get_session
from autofill_agent.api.schemas import LibraryAnswerIn, LibraryAnswerOut, valid_answer_key
from autofill_agent.db.enums import SensitiveField
from autofill_agent.db.models import LibraryAnswer
from autofill_agent.security import require_token

router = APIRouter(prefix="/api/v1/answers", tags=["answers"], dependencies=[Depends(require_token)])

# Suggested keys from the design doc. Custom keys are allowed.
STANDARD_KEYS: dict[str, str] = {
    "desired_salary": "compensation",
    "willing_to_relocate": "preferences",
    "travel_percentage": "preferences",
    "available_start_date": "preferences",
    "remote_preference": "preferences",
    "hybrid_preference": "preferences",
    "security_clearance": "eligibility",
    "background_check_willing": "eligibility",
    "referral_source": "referral",
}
_SENSITIVE_KEYS = {f.value for f in SensitiveField}


def _checked_key(key: str) -> str:
    if not valid_answer_key(key):
        raise HTTPException(422, "key must be lowercase letters, digits and underscores, starting with a letter")
    if key in _SENSITIVE_KEYS:
        raise HTTPException(422, f"'{key}' is a sensitive field; configure it under /api/v1/profile/sensitive")
    return key


@router.get("/standard-keys")
def standard_keys() -> dict[str, str]:
    return STANDARD_KEYS


@router.get("", response_model=list[LibraryAnswerOut])
def list_answers(category: str | None = Query(None, max_length=64), s: Session = Depends(get_session)):
    stmt = select(LibraryAnswer).order_by(LibraryAnswer.category, LibraryAnswer.key)
    if category:
        stmt = stmt.where(LibraryAnswer.category == category)
    return list(s.scalars(stmt))


def _get(s: Session, key: str) -> LibraryAnswer:
    answer = s.scalar(select(LibraryAnswer).where(LibraryAnswer.key == key))
    if answer is None:
        raise HTTPException(404, "No such answer")
    return answer


@router.get("/{key}", response_model=LibraryAnswerOut)
def get_answer(key: str, s: Session = Depends(get_session)) -> LibraryAnswer:
    return _get(s, key)


@router.put("/{key}", response_model=LibraryAnswerOut)
def put_answer(key: str, body: LibraryAnswerIn, s: Session = Depends(get_session)) -> LibraryAnswer:
    key = _checked_key(key)
    answer = s.scalar(select(LibraryAnswer).where(LibraryAnswer.key == key))
    if answer is None:
        answer = LibraryAnswer(key=key)
        s.add(answer)
    answer.category = body.category
    answer.value = body.value
    answer.policy = body.policy
    answer.verification = body.verification
    answer.notes = body.notes
    s.commit()
    return answer


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer(key: str, s: Session = Depends(get_session)) -> Response:
    s.delete(_get(s, key))
    s.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
