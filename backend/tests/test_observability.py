"""Centralized error handlers, the error envelope, correlation id, and logging."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import NotFoundError, register_exception_handlers
from app.core.logging import RequestContextMiddleware, setup_logging


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.get("/notfound")
    def _notfound():
        raise NotFoundError("nope", details={"id": 1})

    @app.get("/boom")
    def _boom():
        raise RuntimeError("unexpected")

    @app.get("/teapot")
    def _teapot():
        raise StarletteHTTPException(status_code=418, detail="teapot")

    class Body(BaseModel):
        n: int

    @app.post("/validate")
    def _validate(body: Body):
        return {"n": body.n}

    return app


def test_app_error_envelope_with_details_and_request_id():
    c = TestClient(_app(), raise_server_exceptions=False)
    r = c.get("/notfound")
    assert r.status_code == 404
    body = r.json()["error"]
    assert body["code"] == "not_found"
    assert body["message"] == "nope"
    assert body["details"] == {"id": 1}
    assert body["request_id"]  # correlation id from middleware
    assert r.headers["X-Request-ID"] == body["request_id"]


def test_unexpected_exception_is_sanitized_500():
    c = TestClient(_app(), raise_server_exceptions=False)
    r = c.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "unexpected" not in r.text  # internals not leaked


def test_http_exception_uses_envelope():
    c = TestClient(_app(), raise_server_exceptions=False)
    r = c.get("/teapot")
    assert r.status_code == 418
    assert r.json()["error"]["code"] == "http_error"


def test_request_validation_error_envelope():
    c = TestClient(_app(), raise_server_exceptions=False)
    r = c.post("/validate", json={"n": "not-an-int"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert isinstance(r.json()["error"]["details"], list)


def test_setup_logging_adds_handler_when_none():
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    try:
        setup_logging()
        assert root.handlers
    finally:
        root.handlers[:] = saved
