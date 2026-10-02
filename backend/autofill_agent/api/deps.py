"""Shared request dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    """One SQLAlchemy session per request. Handlers commit explicitly; anything
    uncommitted when the request ends (including on error) is rolled back."""
    session = request.app.state.db.SessionLocal()
    try:
        yield session
    finally:
        session.close()
