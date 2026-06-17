"""Health checks: liveness (process up) and readiness (DB reachable)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from ...db import SessionLocal
from ...schemas.common import HealthResponse

router = APIRouter(tags=["health"])

SERVICE = "booking-workflow"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is up."""
    return HealthResponse(status="ok", service=SERVICE)


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is unreachable"}},
)
def ready(response: Response) -> HealthResponse:
    """Readiness: dependencies (the database) are reachable. The 503 is declared
    above so it appears in OpenAPI, with the same body shape."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return HealthResponse(status="unavailable", service=SERVICE)
    return HealthResponse(status="ok", service=SERVICE)
