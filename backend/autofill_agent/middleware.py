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
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
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


class BodyLimitMiddleware:
    """Reject oversized request bodies before they are read (a local process or page could otherwise exhaust memory).

    Resume uploads get ``upload_limit`` (the configured resume size plus multipart overhead); everything else is JSON
    from the extension or dashboard and gets ``json_limit``.
    """

    def __init__(self, app, json_limit: int, upload_limit: int) -> None:
        self.app = app
        self.json_limit = json_limit
        self.upload_limit = upload_limit

    def _limit(self, scope) -> int:
        path = scope.get("path", "")
        return self.upload_limit if scope.get("method") == "POST" and path.rstrip("/") == "/api/v1/resumes" else self.json_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope)
        declared = next((v for k, v in scope["headers"] if k == b"content-length"), None)
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True
            if too_big:
                await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                return
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)


class _TooLarge(Exception):
    pass
