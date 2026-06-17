"""LangSmith tracing setup (observability only).

LangChain auto-traces every ``ChatOpenAI`` / ``OpenAIEmbeddings`` call when the
``LANGSMITH_*`` env vars are present, so enabling tracing is just promoting our
settings into the environment before any LLM call runs. No key → no-op, so dev
and tests stay offline. Prompts are NOT stored here — they live in
``app.core.prompts``.
"""

from __future__ import annotations

import os

from ..config import Settings, get_settings


def configure_tracing(settings: Settings | None = None, env: dict | None = None) -> bool:
    """Enable LangSmith tracing when an API key is configured. Returns whether
    tracing was switched on. ``env`` defaults to ``os.environ`` (injectable for
    tests)."""
    settings = settings or get_settings()
    env = env if env is not None else os.environ
    if not settings.tracing_enabled:
        return False
    env["LANGSMITH_TRACING"] = "true"
    env["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    env["LANGSMITH_PROJECT"] = settings.langsmith_project
    return True
