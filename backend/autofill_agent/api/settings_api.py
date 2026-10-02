"""Operating mode and read-only agent settings (doc §29)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from autofill_agent import session_service as svc
from autofill_agent.api.deps import get_session
from autofill_agent.security import require_token

router = APIRouter(prefix="/api/v1/settings", tags=["settings"], dependencies=[Depends(require_token)])


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["SAFE", "STANDARD", "MANUAL_ASSIST"]


def _out(request: Request, s: Session) -> dict:
    st = request.app.state.settings
    return {
        "mode": svc.get_mode(s), "modes": list(svc.MODES), "developer_mode": st.developer_mode,
        "ai": {"enabled": getattr(request.app.state, "ai", None) is not None, "model": st.ollama_model if st.ollama_enabled else None},
    }


@router.get("")
def get_settings_(request: Request, s: Session = Depends(get_session)):
    return _out(request, s)


@router.put("")
def put_settings(body: SettingsIn, request: Request, s: Session = Depends(get_session)):
    svc.set_mode(s, body.mode)
    s.commit()
    return _out(request, s)
