"""Health and status endpoints (doc §5 step 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from autofill_agent import __version__
from autofill_agent.security import require_token

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Unauthenticated liveness check. Reveals nothing beyond "running"."""
    return {"status": "ok"}


@router.get("/status", dependencies=[Depends(require_token)])
def agent_status(request: Request) -> dict[str, object]:
    """Authenticated readiness check: confirms the token works and the database is reachable."""
    db_ok = request.app.state.db.ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "database": "ok" if db_ok else "unavailable",
        "authenticated": True,
        "developer_mode": request.app.state.settings.developer_mode,
    }
