"""FastAPI application entry point.

Composition root: settings, logging, security middleware (CORS + headers),
request-context/correlation-id middleware, centralized exception handlers, and
the versioned API router. Interactive docs are disabled in production.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import api_router
from .config import get_settings
from .core.exceptions import register_exception_handlers
from .core.logging import RequestContextMiddleware, setup_logging
from .core.observability import configure_tracing
from .core.security import SecurityHeadersMiddleware

log = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed default staff so jobs can be assigned. Best-effort: if the schema
    # isn't provisioned yet (run `alembic upgrade head`), log and continue.
    from .api.deps import build_runner
    from .db import SessionLocal
    from .services.availability import seed_default_staff
    from .services.embeddings import build_embedder

    try:
        # Embed cleaner bios on seed so the semantic preference match works out
        # of the box (no-op embedder without an OpenAI key).
        seed_default_staff(SessionLocal, embedder=build_embedder(get_settings()))
    except Exception:  # pragma: no cover - depends on external DB state
        log.warning("staff seeding skipped (run `alembic upgrade head`?)")
    # Shared runner as an app-scoped singleton; its checkpointer persists paused runs.
    app.state.runner = build_runner()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    configure_tracing(settings)  # LangSmith tracing when LANGSMITH_API_KEY is set
    app = FastAPI(
        title="AI Booking Workflow",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
