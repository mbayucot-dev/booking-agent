"""SMTP-backed confirmation email sender.

Real implementation of the abstract ``EmailSender`` (app.graph.email). Builds a
multipart/alternative message (plain + HTML) with an optional .ics attachment
and sends over SMTP. The smtplib connection is injectable (``smtp_factory``) so
tests can supply a fake and never touch the network.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage

from ..config import Settings, get_settings
from ..graph.email import EmailMessage

# Default connection timeout (seconds) so a wedged SMTP server can't hang a run.
_TIMEOUT = 10


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    use_tls: bool
    mail_from: str

    @classmethod
    def from_settings(cls, settings: Settings) -> SmtpConfig:
        if not settings.smtp_configured:
            raise ValueError("SMTP is not configured (need SMTP_HOST and MAIL_FROM)")
        return cls(
            host=settings.smtp_host,  # type: ignore[arg-type]
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            mail_from=settings.mail_from,  # type: ignore[arg-type]
        )


@dataclass
class SmtpEmailSender:
    """Sends :class:`EmailMessage` over SMTP. Implements the EmailSender protocol."""

    config: SmtpConfig
    # Injectable so tests can supply a fake SMTP-like object (no network).
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP

    def _build(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self.config.mail_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        if message.ics is not None:
            # Attach as a real calendar part so mail clients offer "add to
            # calendar". method=REQUEST mirrors the ICS body's METHOD.
            mime.add_attachment(
                message.ics.encode("utf-8"),
                maintype="text",
                subtype="calendar",
                filename=message.ics_filename,
                params={"method": "REQUEST"},
            )
        return mime

    def send(self, message: EmailMessage) -> dict:
        mime = self._build(message)
        with self.smtp_factory(self.config.host, self.config.port, timeout=_TIMEOUT) as server:
            if self.config.use_tls:
                server.starttls()
            if self.config.username and self.config.password:
                server.login(self.config.username, self.config.password)
            server.send_message(mime)
        return {"id": mime.get("Message-Id"), "provider": "smtp"}


def build_email_sender(settings: Settings | None = None) -> SmtpEmailSender:
    """Construct an SMTP sender from settings (raises if SMTP isn't configured)."""
    settings = settings or get_settings()
    return SmtpEmailSender(config=SmtpConfig.from_settings(settings))
