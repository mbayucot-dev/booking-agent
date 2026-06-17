"""extract_booking_request node.

Turns the raw chat message into a structured :class:`BookingRequest`.
``_extract_with_llm`` runs when an OpenAI key is configured; on any failure (or
no key) it degrades silently to ``_extract_with_rules``, so the workflow always
makes progress.
"""

from __future__ import annotations

import re

from dateutil import parser as dateparser

from ..state import BookingRequest, BookingState

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# AU-style phone: optional +61, then 8-12 digits possibly spaced/dashed.
PHONE_RE = re.compile(r"(?:\+?61[\s-]?)?(?:0?\d[\s-]?){8,12}")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b", re.IGNORECASE)
NAME_RE = re.compile(r"\bfor\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
SERVICE_RE = re.compile(
    r"\bfor\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\s+for\s+(.+?)\s+on\b", re.IGNORECASE
)
ADDRESS_RE = re.compile(r"\baddress\s+(.+?)\s*[.\n]*$", re.IGNORECASE)
DATE_RE = re.compile(r"\bon\s+([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?)", re.IGNORECASE)


def _normalize_time(match: re.Match) -> str:
    hour = int(match.group(1)) % 12
    minute = int(match.group(2) or 0)
    if match.group(3).lower() == "pm":
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def _normalize_date(text: str) -> str | None:
    try:
        # default fills in a sensible year/day; we only keep the date part.
        return dateparser.parse(text, fuzzy=True).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _extract_with_rules(message: str) -> BookingRequest:
    email = EMAIL_RE.search(message)
    name = NAME_RE.search(message)
    service = SERVICE_RE.search(message)
    address = ADDRESS_RE.search(message)
    time_m = TIME_RE.search(message)
    date_m = DATE_RE.search(message)

    # Phone: search the message minus the email to avoid matching digits in it.
    masked = EMAIL_RE.sub(" ", message)
    phone_m = PHONE_RE.search(masked)
    phone = None
    if phone_m:
        digits = re.sub(r"\D", "", phone_m.group(0))
        if len(digits) >= 8:
            phone = digits

    return BookingRequest(
        customer_name=name.group(1).strip() if name else None,
        service=service.group(1).strip() if service else None,
        date=_normalize_date(date_m.group(1)) if date_m else None,
        time=_normalize_time(time_m) if time_m else None,
        email=email.group(0) if email else None,
        phone=phone,
        address=address.group(1).strip() if address else None,
    )


def _extract_with_llm(message: str) -> BookingRequest | None:
    """Best-effort structured extraction via OpenAI. Returns None on any issue (caller falls back to rules)."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.use_real_openai:
        return None
    try:
        from langchain_openai import ChatOpenAI  # imported lazily / optionally
    except ImportError:
        return None
    try:
        from app.core.prompts import BOOKING_EXTRACTION

        # Bounded timeout/tokens so a slow OpenAI call can't tie up the worker.
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            timeout=10,
            max_retries=2,
            max_tokens=settings.extraction_max_tokens,
        ).with_structured_output(BookingRequest)
        # Cap the untrusted message so a huge paste can't inflate the prompt; it's
        # appended, never .format-interpolated.
        truncated = message[: settings.max_message_chars]
        return llm.invoke(f"{BOOKING_EXTRACTION.text}\n\nMessage: {truncated}")
    except Exception:  # network/parse/etc — degrade to rules
        return None


def extract_booking_request(state: BookingState) -> BookingState:
    message = state.get("raw_message", "")
    booking = _extract_with_llm(message) or _extract_with_rules(message)
    return {"booking_request": booking}
