"""Per-client fixed-window rate limiter guarding run submission.

Keyed by the authenticated principal when present, else the client host, so a
caller can't flood the queue / OpenAI spend. In-process by default;
Redis-backed (shared across replicas) when configured.
"""

from __future__ import annotations

import threading
import time

from fastapi import Depends, Request

from ..config import Settings, get_settings
from .auth import API_PRINCIPAL, require_principal
from .exceptions import AppError


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    default_message = "Too many requests; please slow down."


class FixedWindowLimiter:
    """Allow at most ``limit`` hits per ``window_s`` per key (sliding within the
    window — old hits are evicted as they age out)."""

    def __init__(self, *, limit: int, window_s: float, clock=time.monotonic):
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            recent = [t for t in self._hits.get(key, ()) if t > cutoff]
            if len(recent) >= self._limit:
                self._hits[key] = recent  # keep the (full) window; reject
                return False
            recent.append(now)
            self._hits[key] = recent
            return True


class RedisFixedWindowLimiter:
    """Shared fixed-window limiter over Redis (INCR + EXPIRE), drop-in for
    ``FixedWindowLimiter``.

    The count is global across replicas. The first hit in a window sets the
    key's TTL; the key expires when the window elapses, starting fresh."""

    def __init__(self, *, limit: int, window_s: int, redis_client):
        self._limit = limit
        self._window = window_s
        self._redis = redis_client

    def allow(self, key: str) -> bool:
        rk = f"ratelimit:{key}"
        count = self._redis.incr(rk)
        if count == 1:
            # First hit opens the window; the key self-expires to reset it.
            self._redis.expire(rk, self._window)
        return count <= self._limit


_lock = threading.Lock()


def _build_limiter(settings: Settings):
    """Redis-backed (shared across replicas) when REDIS_URL is set, else in-process."""
    if settings.redis_enabled:
        import redis

        return RedisFixedWindowLimiter(
            limit=settings.rate_limit_runs,
            window_s=settings.rate_limit_window_s,
            redis_client=redis.from_url(settings.redis_url),
        )
    return FixedWindowLimiter(
        limit=settings.rate_limit_runs, window_s=settings.rate_limit_window_s
    )


def _limiter(request: Request, settings: Settings):
    """Process-wide limiter, lazily built onto ``app.state`` (mirrors get_runner,
    so it works whether or not the lifespan ran)."""
    lim = getattr(request.app.state, "rate_limiter", None)
    if lim is None:
        with _lock:
            lim = getattr(request.app.state, "rate_limiter", None)
            if lim is None:
                lim = _build_limiter(settings)
                request.app.state.rate_limiter = lim
    return lim


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "anonymous"


def rate_limit_runs(
    request: Request,
    principal: str | None = Depends(require_principal),
    settings: Settings = Depends(get_settings),
) -> None:
    """Dependency: reject run submission past the per-client window with 429."""
    if settings.rate_limit_runs <= 0:
        return  # disabled
    # The shared static token returns API_PRINCIPAL for everyone, so keying by it
    # collapses all callers into one bucket. Always use IP for per-caller isolation;
    # reserve the principal key for future per-user identity schemes.
    key = _client_key(request) if (not principal or principal == API_PRINCIPAL) else principal
    if not _limiter(request, settings).allow(key):
        raise RateLimitError()
