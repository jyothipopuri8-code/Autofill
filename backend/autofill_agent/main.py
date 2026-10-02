"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from autofill_agent import __version__
from autofill_agent.api import health
from autofill_agent.config import Settings, get_settings
from autofill_agent.db import Database
from autofill_agent.logging_setup import configure_logging
from autofill_agent.middleware import OriginGuardMiddleware
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

    # Starlette runs the last-added middleware first: host check, then origin guard, then CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    app.include_router(health.router)
    return app
