"""Aggregated v1 API router."""

from fastapi import APIRouter

from . import health, runs

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(runs.router)
