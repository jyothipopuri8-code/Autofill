"""Fixed profile and sensitive-field preferences (doc §6, §7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autofill_agent.api.deps import get_session
from autofill_agent.api.schemas import ProfileIn, ProfileOut, SensitivePrefIn, SensitivePrefOut
from autofill_agent.db.enums import SensitiveField
from autofill_agent.db.models import Profile, SensitivePreference
from autofill_agent.security import require_token

router = APIRouter(prefix="/api/v1/profile", tags=["profile"], dependencies=[Depends(require_token)])


def _get_or_create(s: Session) -> Profile:
    profile = s.get(Profile, 1)
    if profile is None:
        profile = Profile(id=1)
        s.add(profile)
        s.flush()
    return profile


@router.get("", response_model=ProfileOut)
def get_profile(s: Session = Depends(get_session)) -> Profile:
    profile = _get_or_create(s)
    s.commit()
    return profile


@router.patch("", response_model=ProfileOut)
def update_profile(body: ProfileIn, s: Session = Depends(get_session)) -> Profile:
    profile = _get_or_create(s)
    for name, value in body.model_dump(exclude_unset=True).items():
        if name == "work_authorization_verified" and value is None:
            value = False
        setattr(profile, name, value)
    s.commit()
    return profile


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(s: Session = Depends(get_session)) -> Response:
    """Delete all profile information, including sensitive-field preferences (doc §41)."""
    profile = s.get(Profile, 1)
    if profile is not None:
        s.delete(profile)
    for pref in s.scalars(select(SensitivePreference)):
        s.delete(pref)
    s.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sensitive", response_model=list[SensitivePrefOut])
def list_sensitive(s: Session = Depends(get_session)) -> list[SensitivePrefOut]:
    """Every sensitive field with its policy; fields never configured are ASK_ME."""
    stored = {p.field: p for p in s.scalars(select(SensitivePreference))}
    return [
        SensitivePrefOut.model_validate(stored[f]) if f in stored else SensitivePrefOut(field=f)
        for f in SensitiveField
    ]


@router.put("/sensitive/{field}", response_model=SensitivePrefOut)
def set_sensitive(field: SensitiveField, body: SensitivePrefIn, s: Session = Depends(get_session)) -> SensitivePreference:
    pref = s.scalar(select(SensitivePreference).where(SensitivePreference.field == field))
    if pref is None:
        pref = SensitivePreference(field=field)
        s.add(pref)
    pref.policy = body.policy
    pref.value = body.value
    s.commit()
    return pref
