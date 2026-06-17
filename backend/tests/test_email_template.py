"""Confirmation email rendering: body content, ICS invite, calendar deep links."""

from datetime import datetime
from urllib.parse import quote

from app.services.email_template import (
    BookingEmailContext,
    build_ics,
    google_calendar_url,
    outlook_calendar_url,
    render_confirmation,
)

CTX = BookingEmailContext(
    customer_name="John Doe",
    service="contact work",
    date="2026-06-20",
    time="10:00",
    staff="Alex Taylor",
    address="12 Queen St Brisbane",
    email="john@example.com",
    reference="rec-0003",
    business_name="Acme Services",
    tz="Australia/Brisbane",
    duration_min=90,
)


def test_render_confirmation_includes_all_details():
    out = render_confirmation(CTX)
    for value in (
        "John Doe",
        "contact work",
        "2026-06-20",
        "10:00",
        "Alex Taylor",
        "12 Queen St Brisbane",
    ):
        assert value in out["text"]
        assert value in out["html"]
    # subject mentions the service.
    assert "contact work" in out["subject"]
    # reference row surfaced.
    assert "rec-0003" in out["html"]


def test_build_ics_has_event_with_correct_window():
    ics = build_ics(CTX)
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:contact work" in ics
    assert "LOCATION:12 Queen St Brisbane" in ics
    assert f"UID:{CTX.uid}" in ics
    # DTEND = DTSTART + duration_min (90 min -> 11:30).
    assert "DTSTART:20260620T100000" in ics
    assert "DTEND:20260620T113000" in ics


def test_calendar_urls_encode_dates():
    google = google_calendar_url(CTX)
    outlook = outlook_calendar_url(CTX)
    # Google packs dates as start/end; the slash is percent-encoded.
    assert quote("20260620T100000/20260620T113000", safe="") in google
    # Outlook uses ISO datetimes.
    assert quote(datetime(2026, 6, 20, 10, 0).isoformat(), safe="") in outlook


def test_no_schedule_omits_calendar_artifacts():
    ctx = BookingEmailContext(
        customer_name=None,
        service=None,
        date=None,
        time=None,
        staff=None,
        address=None,
        email="x@example.com",
    )
    assert ctx.has_schedule is False
    assert build_ics(ctx) is None
    assert google_calendar_url(ctx) is None
    assert outlook_calendar_url(ctx) is None

    out = render_confirmation(ctx)
    # No calendar buttons, schedule shown as to-be-confirmed.
    assert "Add to Google Calendar" not in out["html"]
    assert "Add to Outlook" not in out["html"]
    assert "To be confirmed" in out["text"]
    # Greeting without a name.
    assert out["text"].startswith("Hi,")
