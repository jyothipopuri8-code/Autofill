"""Install-token authentication and request origin checks.

On first start the agent generates a random token and stores it in the data
directory with owner-only permissions. The browser extension is given that
token once (pairing, Phase 10) and sends it as ``Authorization: Bearer``.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_BYTES = 32

_bearer = HTTPBearer(auto_error=False)


def load_or_create_token(path: Path) -> str:
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(TOKEN_BYTES)
    # Create with 0600 from the start so the token is never world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    expected: str = request.app.state.install_token
    supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid installation token",
            headers={"WWW-Authenticate": "Bearer"},
        )
