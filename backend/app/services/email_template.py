"""Confirmation email rendering: HTML + text body, an ICS calendar invite, and
Add-to-Calendar deep links (Google / Outlook).

Pure functions (stdlib only) — no I/O — so they are trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode


@dataclass
class BookingEmailContext:
    customer_name: str | None
    service: str | None
    date: str | None  # ISO date
    time: str | None  # HH:MM
    staff: str | None
    address: str | None
    email: str
    reference: str | None = None
    business_name: str = "Your Service Team"
    tz: str = "Australia/Brisbane"
    duration_min: int = 60

    @property
    def has_schedule(self) -> bool:
        return bool(self.date and self.time)

    def _start_end(self) -> tuple[datetime, datetime]:
        start = datetime.fromisoformat(f"{self.date}T{self.time}:00")
        return start, start + timedelta(minutes=self.duration_min)

    @property
    def uid(self) -> str:
        base = self.reference or f"{self.date}-{self.time}-{self.email}"
        return f"{base}@booking-workflow".replace(" ", "")


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(ctx: BookingEmailContext) -> str | None:
    if not ctx.has_schedule:
        return None
    start, end = ctx._start_end()
    summary = ctx.service or "Service booking"
    description = f"Booking for {ctx.customer_name or 'you'} with {ctx.business_name}." + (
        f" Technician: {ctx.staff}." if ctx.staff else ""
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Booking Workflow//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{ctx.uid}",
        f"DTSTAMP:{_fmt_dt(start)}",
        f"DTSTART:{_fmt_dt(start)}",
        f"DTEND:{_fmt_dt(end)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(description)}",
        f"LOCATION:{_ics_escape(ctx.address or '')}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def google_calendar_url(ctx: BookingEmailContext) -> str | None:
    if not ctx.has_schedule:
        return None
    start, end = ctx._start_end()
    params = {
        "action": "TEMPLATE",
        "text": ctx.service or "Service booking",
        "dates": f"{_fmt_dt(start)}/{_fmt_dt(end)}",
        "details": f"Booking with {ctx.business_name}"
        + (f" — technician {ctx.staff}" if ctx.staff else ""),
        "location": ctx.address or "",
        "ctz": ctx.tz,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote)


def outlook_calendar_url(ctx: BookingEmailContext) -> str | None:
    if not ctx.has_schedule:
        return None
    start, end = ctx._start_end()
    params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": ctx.service or "Service booking",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "location": ctx.address or "",
        "body": f"Booking with {ctx.business_name}",
    }
    return "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(
        params, quote_via=quote
    )


def _detail_rows(ctx: BookingEmailContext) -> list[tuple[str, str]]:
    when = f"{ctx.date} at {ctx.time}" if ctx.has_schedule else "To be confirmed"
    rows = [
        ("Service", ctx.service or "—"),
        ("When", when),
        ("Technician", ctx.staff or "To be assigned"),
        ("Address", ctx.address or "—"),
    ]
    if ctx.reference:
        rows.append(("Reference", ctx.reference))
    return rows


def render_confirmation(ctx: BookingEmailContext) -> dict:
    """Return {subject, text, html} for the confirmation email."""
    subject = f"Booking confirmed — {ctx.service or 'your service'}"
    if ctx.has_schedule:
        subject += f" on {ctx.date} at {ctx.time}"

    rows = _detail_rows(ctx)
    google = google_calendar_url(ctx)
    outlook = outlook_calendar_url(ctx)
    greeting = f"Hi {ctx.customer_name}," if ctx.customer_name else "Hi,"

    # --- text ---
    text_lines = [
        greeting,
        "",
        f"Your booking with {ctx.business_name} is confirmed. Details:",
        "",
    ]
    text_lines += [f"  {label}: {value}" for label, value in rows]
    if google:
        text_lines += ["", f"Add to Google Calendar: {google}"]
    if outlook:
        text_lines += [f"Add to Outlook: {outlook}"]
    text_lines += ["", "A calendar invite (.ics) is attached.", "", ctx.business_name]
    text = "\n".join(text_lines)

    # --- html ---
    detail_html = "".join(
        f'<tr><td style="padding:6px 12px;color:#64748b;">{label}</td>'
        f'<td style="padding:6px 12px;font-weight:600;">{value}</td></tr>'
        for label, value in rows
    )
    buttons = ""
    if google:
        buttons += (
            f'<a href="{google}" style="display:inline-block;padding:10px 16px;'
            f"margin:4px;background:#2563eb;color:#fff;border-radius:6px;"
            f'text-decoration:none;">Add to Google Calendar</a>'
        )
    if outlook:
        buttons += (
            f'<a href="{outlook}" style="display:inline-block;padding:10px 16px;'
            f"margin:4px;background:#0f172a;color:#fff;border-radius:6px;"
            f'text-decoration:none;">Add to Outlook</a>'
        )
    html = f"""\
<div style="font-family:system-ui,Arial,sans-serif;max-width:560px;margin:auto;">
  <h2 style="color:#0f172a;">Booking confirmed ✅</h2>
  <p>{greeting}</p>
  <p>Your booking with <strong>{ctx.business_name}</strong> is confirmed.</p>
  <table style="border-collapse:collapse;width:100%;background:#f8fafc;border-radius:8px;">
    {detail_html}
  </table>
  <div style="margin:20px 0;">{buttons}</div>
  <p style="color:#64748b;font-size:13px;">A calendar invite (.ics) is attached so
  you can add this to any calendar app.</p>
  <p style="color:#64748b;font-size:13px;">— {ctx.business_name}</p>
</div>"""

    return {"subject": subject, "text": text, "html": html}
