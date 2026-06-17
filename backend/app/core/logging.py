"""Logging setup and a request-context middleware.

Assigns/propagates a correlation id (``X-Request-ID``) per request, exposes it
on ``request.state.request_id`` (used by the error envelope), echoes it on the
response, and emits a structured access log line per request.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"


def setup_logging(level: int | str = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level.upper() if isinstance(level, str) else level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger_name: str = "app.access"):
        super().__init__(app)
        self._log = get_logger(logger_name)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        self._log.info(
            "%s %s -> %s (%dms) request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
