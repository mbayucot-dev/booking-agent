"""Settings parsing and capability flags."""

from app.config import Settings, get_settings


def _settings(**over) -> Settings:
    base = dict(openai_api_key=None, openai_model="gpt-4o-mini")
    base.update(over)
    return Settings(**base)


def test_use_real_openai_flag():
    assert _settings(openai_api_key="sk-x").use_real_openai is True
    assert _settings(openai_api_key=None).use_real_openai is False


def test_smtp_configured_requires_host_and_from():
    assert _settings().smtp_configured is False
    assert _settings(smtp_host="smtp.x").smtp_configured is False  # mail_from missing
    assert _settings(smtp_host="smtp.x", mail_from="a@x").smtp_configured is True


def test_cors_and_docs_flags():
    # api_auth_token required in prod (fail-closed), so set it here.
    s = _settings(
        environment="production", cors_origins="http://a, http://b", api_auth_token="secret"
    )
    assert s.is_production is True
    assert s.docs_enabled is False
    assert s.cors_origin_list == ["http://a", "http://b"]


def test_hubspot_sync_enabled_flag_and_token():
    assert _settings().hubspot_sync_enabled is False  # no token
    assert _settings(hubspot_access_token="t").hubspot_sync_enabled is True  # default flag on
    # Flag explicitly off → standalone mode, no real push even with a token.
    assert (
        _settings(hubspot_access_token="t", feature_hubspot_sync=False).hubspot_sync_enabled
        is False
    )


def test_llm_cost_guardrail_defaults_and_overrides():
    s = _settings()
    assert (s.extraction_max_tokens, s.selection_max_tokens, s.max_message_chars) == (
        256,
        128,
        2000,
    )
    over = _settings(extraction_max_tokens=64, selection_max_tokens=32, max_message_chars=500)
    assert (over.extraction_max_tokens, over.selection_max_tokens, over.max_message_chars) == (
        64,
        32,
        500,
    )


def test_get_settings_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("BUSINESS_OPEN_HOUR", "9")
    monkeypatch.setenv("FEATURE_HUBSPOT_SYNC", "false")
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "500")
    s = get_settings()
    assert s.use_real_openai is True
    assert s.openai_model == "gpt-4o"
    assert s.business_open_hour == 9
    assert s.feature_hubspot_sync is False  # env override parsed
    assert s.max_message_chars == 500  # env override parsed
