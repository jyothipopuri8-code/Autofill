"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pathlib import Path

from autofill_agent import __version__
from autofill_agent.api import answers, applications, data, health, profile, resumes, sessions, settings_api
from autofill_agent.config import Settings, get_settings
from autofill_agent.db import Database
from autofill_agent.logging_setup import configure_logging
from autofill_agent.middleware import BodyLimitMiddleware, OriginGuardMiddleware
from autofill_agent.security import load_or_create_token

log = logging.getLogger("autofill_agent")

# Host header allow-list blocks DNS-rebinding attacks against the loopback API.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    configure_logging(settings.log_dir, settings.log_level)

    db = Database(settings.database_url)
    db.create_all()
    token = load_or_create_token(settings.token_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("Agent %s started; data dir %s", __version__, settings.data_dir)
        yield
        db.dispose()
        log.info("Agent stopped")

    app = FastAPI(
        title="Local Job Application Autofill Agent",
        version=__version__,
        lifespan=lifespan,
        # Interactive docs only in developer mode; they are not needed by the extension.
        docs_url="/docs" if settings.developer_mode else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.developer_mode else None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.install_token = token
    app.state.ai = None
    if settings.ollama_enabled:
        from autofill_agent.ai import OllamaDrafter

        app.state.ai = OllamaDrafter(settings.ollama_url, settings.ollama_model)

    # Starlette runs the last-added middleware first: host check, then origin guard, then CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(
        OriginGuardMiddleware,
        allowed_origins=settings.allowed_origins,
        own_origins=[f"http://127.0.0.1:{settings.port}", f"http://localhost:{settings.port}"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    # Added last so it runs first: oversized bodies are refused before anything reads them.
    app.add_middleware(BodyLimitMiddleware, json_limit=8 * 1024 * 1024, upload_limit=settings.max_resume_bytes + 1024 * 1024)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never echo internals (paths, SQL, stack frames) to a caller; the redacted log has the details.
        log.error("Unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__, exc_info=settings.developer_mode)
        return JSONResponse({"detail": "Internal error"}, status_code=500)

    app.include_router(health.router)
    app.include_router(profile.router)
    app.include_router(answers.router)
    app.include_router(resumes.router)
    app.include_router(sessions.router)
    app.include_router(applications.router)
    app.include_router(settings_api.router)
    app.include_router(data.router)
    # Static review page: no personal data in these files, all data comes via the authenticated API.
    app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "ui", html=True), name="ui")
    return app
