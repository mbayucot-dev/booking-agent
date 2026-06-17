"""FastAPI dependencies (the DI wiring shared across routers)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from ..services.run_service import WorkflowRunner

_lock = threading.Lock()


def build_runner() -> WorkflowRunner:
    """Construct the application's WorkflowRunner (DB-backed booking + real
    integrations when configured)."""
    from ..db import SessionLocal
    from ..services.run_service import build_default_runner

    return build_default_runner(SessionLocal)


def get_runner(request: Request) -> WorkflowRunner:
    """The process-wide runner stored on ``app.state`` — its in-memory checkpointer
    must persist paused runs across requests. Falls back to a thread-safe build if
    the lifespan didn't run (e.g. some test setups)."""
    runner = getattr(request.app.state, "runner", None)
    if runner is None:
        with _lock:
            runner = getattr(request.app.state, "runner", None)
            if runner is None:
                runner = build_runner()
                request.app.state.runner = runner
    return runner
