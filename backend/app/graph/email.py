"""Email seam for the graph layer.

Like the audit/event seams, the graph depends on an abstract ``EmailSender``,
not on SMTP. The real :class:`SmtpEmailSender` lives in the services layer;
tests/dev use :class:`DryRunEmailSender`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    ics: str | None = None
    ics_filename: str = "booking.ics"


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> dict: ...


@dataclass
class DryRunEmailSender:
    """Records messages instead of sending (default until SMTP is wired)."""

    sent: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> dict:
        self.sent.append(message)
        return {"id": None, "provider": "dry-run", "dry_run": True}
