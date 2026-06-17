"""SMTP sender: message assembly + connection behaviour, with a fake SMTP.

No real network — a fake SMTP-like object captures the calls and the sent MIME
message so we can assert on headers, the HTML alternative, and the ICS part.
"""

import pytest

from app.config import Settings
from app.graph.email import EmailMessage
from app.services.email_smtp import SmtpConfig, SmtpEmailSender, build_email_sender


class FakeSMTP:
    """Records starttls/login/send_message; usable as a context manager."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls = False
        self.login_args = None
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent = msg


def _msg(ics="BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"):
    return EmailMessage(
        to="john@example.com",
        subject="Booking confirmed",
        text="plain body",
        html="<p>html body</p>",
        ics=ics,
    )


def _config(use_tls=True, username="postmaster@x", password="pw"):
    return SmtpConfig(
        host="smtp.example.com",
        port=587,
        username=username,
        password=password,
        use_tls=use_tls,
        mail_from="bookings@example.com",
    )


def setup_function():
    FakeSMTP.instances.clear()


def test_send_builds_message_and_attaches_ics():
    sender = SmtpEmailSender(config=_config(), smtp_factory=FakeSMTP)
    result = sender.send(_msg())

    assert result["provider"] == "smtp"
    smtp = FakeSMTP.instances[-1]
    msg = smtp.sent
    assert msg["From"] == "bookings@example.com"
    assert msg["To"] == "john@example.com"
    assert msg["Subject"] == "Booking confirmed"

    # HTML alternative present.
    html_parts = [p for p in msg.walk() if p.get_content_type() == "text/html"]
    assert html_parts and "html body" in html_parts[0].get_content()

    # ICS attached as text/calendar with the given filename + REQUEST method.
    cal = [p for p in msg.walk() if p.get_content_type() == "text/calendar"]
    assert cal
    assert cal[0].get_filename() == "booking.ics"
    assert cal[0].get_param("method") == "REQUEST"


def test_starttls_and_login_when_creds_present():
    sender = SmtpEmailSender(config=_config(use_tls=True), smtp_factory=FakeSMTP)
    sender.send(_msg())
    smtp = FakeSMTP.instances[-1]
    assert smtp.tls is True
    assert smtp.login_args == ("postmaster@x", "pw")
    assert smtp.timeout is not None  # timeout is set


def test_no_tls_and_no_login_without_creds():
    cfg = _config(use_tls=False, username=None, password=None)
    sender = SmtpEmailSender(config=cfg, smtp_factory=FakeSMTP)
    sender.send(_msg(ics=None))  # no ICS path
    smtp = FakeSMTP.instances[-1]
    assert smtp.tls is False
    assert smtp.login_args is None
    # No calendar part when ics is None.
    assert not [p for p in smtp.sent.walk() if p.get_content_type() == "text/calendar"]


def test_from_settings_raises_when_not_configured():
    with pytest.raises(ValueError):
        SmtpConfig.from_settings(Settings(openai_api_key=None, openai_model="m"))


def test_from_settings_and_build_email_sender():
    configured = Settings(
        openai_api_key=None,
        openai_model="m",
        smtp_host="smtp.example.com",
        mail_from="bookings@example.com",
    )
    cfg = SmtpConfig.from_settings(configured)
    assert cfg.host == "smtp.example.com"
    assert cfg.mail_from == "bookings@example.com"

    sender = build_email_sender(configured)
    assert isinstance(sender, SmtpEmailSender)
    assert sender.config.host == "smtp.example.com"
