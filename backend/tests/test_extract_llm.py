"""OpenAI extraction path: prefer LLM when keyed, fall back to rules on any
issue. The real network call is faked by injecting a stub langchain_openai."""

import sys
import types

from app.graph.nodes.extract_booking_request import (
    _extract_with_llm,
    _normalize_date,
    extract_booking_request,
)
from app.graph.state import BookingRequest

MSG = "book John Doe, email john@example.com, phone 0400000000"


def _install_fake_llm(monkeypatch, *, result=None, raises=False):
    seen: dict = {"kwargs": None, "prompt": None}
    mod = types.ModuleType("langchain_openai")

    class _Structured:
        def invoke(self, prompt):
            seen["prompt"] = prompt
            if raises:
                raise RuntimeError("api down")
            return result

    class ChatOpenAI:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def with_structured_output(self, schema):
            return _Structured()

    mod.ChatOpenAI = ChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", mod)
    return seen


def test_normalize_date_returns_none_on_garbage():
    assert _normalize_date("definitely not a date") is None


def test_no_key_skips_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _extract_with_llm(MSG) is None


def test_keyed_but_langchain_missing_falls_back(monkeypatch):
    # Key present but the optional langchain_openai import fails -> None. A None entry in
    # sys.modules forces ImportError whether or not the package is installed, so the fallback
    # branch stays covered under the CI install (which includes the `llm` extra).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "langchain_openai", None)
    assert _extract_with_llm(MSG) is None


def test_llm_used_when_keyed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    expected = BookingRequest(customer_name="LLM Person", email="llm@example.com")
    _install_fake_llm(monkeypatch, result=expected)

    assert _extract_with_llm(MSG) == expected
    # The node prefers the LLM result over the rule parser.
    out = extract_booking_request({"raw_message": MSG})
    assert out["booking_request"].customer_name == "LLM Person"


def test_llm_caps_output_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = _install_fake_llm(monkeypatch, result=BookingRequest())
    _extract_with_llm("book a plumber")
    assert seen["kwargs"]["max_tokens"] == 256  # extraction guardrail (default)


def test_llm_truncates_a_huge_message(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "50")
    seen = _install_fake_llm(monkeypatch, result=BookingRequest())
    _extract_with_llm("x" * 5000)
    # Only the truncated message is appended after the static instruction.
    body = seen["prompt"].split("Message: ", 1)[1]
    assert body == "x" * 50


def test_llm_captures_customer_preference(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    expected = BookingRequest(
        customer_name="Jo", email="jo@example.com", preferences="calm with anxious dogs"
    )
    _install_fake_llm(monkeypatch, result=expected)
    out = extract_booking_request({"raw_message": MSG + ", I have anxious dogs"})
    assert out["booking_request"].preferences == "calm with anxious dogs"


def test_llm_error_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _install_fake_llm(monkeypatch, raises=True)

    assert _extract_with_llm(MSG) is None
    # Node still produces a result via the deterministic rules.
    out = extract_booking_request({"raw_message": MSG})
    assert out["booking_request"].email == "john@example.com"
