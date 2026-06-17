"""LangSmith tracing config (observability only)."""

from app.config import Settings
from app.core.observability import configure_tracing


def test_tracing_off_without_key():
    env: dict = {}
    assert configure_tracing(Settings(), env=env) is False
    assert env == {}  # nothing leaked into the environment


def test_tracing_on_with_key():
    env: dict = {}
    settings = Settings(langsmith_api_key="ls-abc", langsmith_project="booking-agent")
    assert configure_tracing(settings, env=env) is True
    assert env["LANGSMITH_TRACING"] == "true"
    assert env["LANGSMITH_API_KEY"] == "ls-abc"
    assert env["LANGSMITH_PROJECT"] == "booking-agent"


def test_settings_tracing_enabled_flag():
    assert Settings().tracing_enabled is False
    assert Settings(langsmith_api_key="ls-x").tracing_enabled is True
