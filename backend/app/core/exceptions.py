"""Domain exceptions + centralized handlers producing a consistent envelope.

Services raise semantic exceptions (``NotFoundError``, ``NotConnectedError``);
they are translated to HTTP responses in one place so routers stay thin and
clients never see internal stack traces. Every error carries the request's
correlation id.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base application error. Subclasses set status_code/code/message."""

    status_code: int = 500
    code: str = "internal_error"
    default_message: str = "Internal server error"

    def __init__(self, message: str | None = None, *, details: Any = None):
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "Conflict"


class SlotTakenError(ConflictError):
    code = "slot_taken"
    default_message = "That slot is already booked"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"
    default_message = "Validation failed"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Unauthorized"


class NotConnectedError(AppError):
    status_code = 404
    code = "not_connected"
    default_message = "Not connected"


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(code: str, message: str, details: Any, request: Request) -> dict:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    rid = _request_id(request)
    if rid:
        body["request_id"] = rid
    return {"error": body}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details, request),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "Validation failed", exc.errors(), request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("http_error", str(exc.detail), None, request),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception):
        # Never leak internals; the correlation id ties the 500 to server logs.
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "Internal server error", None, request),
        )
