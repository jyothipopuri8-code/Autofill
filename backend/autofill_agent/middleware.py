"""Origin validation and security headers.

CORSMiddleware only controls what browsers may *read*; it does not stop a
web page from sending a request. This middleware rejects any request whose
Origin is present and not a registered extension origin, so a malicious
site open in the same browser cannot reach the API at all.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


# The bundled review page is served by the agent itself, so it may load only its own files.
UI_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class OriginGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str], own_origins: list[str] | None = None) -> None:
        super().__init__(app)
        # own_origins: this agent's own address, so its bundled UI can call its API.
        # A web page cannot forge an Origin header, so other sites remain blocked.
        self.allowed = set(allowed_origins) | set(own_origins or [])

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed:
            response: Response = JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        else:
            response = await call_next(request)
        headers = dict(SECURITY_HEADERS)
        if request.url.path == "/ui" or request.url.path.startswith("/ui/"):
            headers["Content-Security-Policy"] = UI_CSP
        for k, v in headers.items():
            response.headers.setdefault(k, v)
        return response
