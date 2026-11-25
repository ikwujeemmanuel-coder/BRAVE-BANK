"""Email delivery provider supporting dev/test mock outbox and production SMTP."""

import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from backend.app.config import get_settings

logger = logging.getLogger("bravebank.email")


class EmailDeliveryError(RuntimeError):
    """Raised when sending an email fails or email transport is not configured."""


@dataclass
class MockEmailMessage:
    recipient: str
    subject: str
    text_body: str
    sent_at: datetime


class EmailProvider(ABC):
    """Abstract email provider interface."""

    @abstractmethod
    def send_email(self, recipient: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
        """Send an email to the recipient address."""


class MockEmailProvider(EmailProvider):
    """Development/Test mock email provider storing dispatched emails in memory."""

    def __init__(self) -> None:
        self.outbox: deque[MockEmailMessage] = deque(maxlen=100)

    def send_email(self, recipient: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
        entry = MockEmailMessage(
            recipient=recipient.strip().lower(),
            subject=subject,
            text_body=text_body,
            sent_at=datetime.now(timezone.utc),
        )
        self.outbox.appendleft(entry)
        logger.info("[DEV MOCK EMAIL] To %s | Subject: %s | %s", entry.recipient, subject, text_body)


class SMTPEmailProvider(EmailProvider):
    """Real SMTP transport for production/configured environments."""

    def send_email(self, recipient: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            raise EmailDeliveryError(
                "Email service is not configured. Please set SMTP_HOST and credentials before sending email OTPs."
            )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = recipient.strip().lower()
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        try:
            context = ssl.create_default_context()
            if settings.smtp_port == 465 and not settings.smtp_use_tls:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=15) as server:
                    if settings.smtp_user and settings.smtp_password:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    server.ehlo()
                    if settings.smtp_use_tls:
                        server.starttls(context=context)
                        server.ehlo()
                    if settings.smtp_user and settings.smtp_password:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(msg)
        except Exception as exc:
            logger.exception("SMTP email delivery failed for %s: %s", recipient, exc)
            raise EmailDeliveryError(
                "Unable to deliver verification email at this time. Please verify SMTP settings or try again later."
            ) from exc


class ProductionEmailNotConfiguredProvider(EmailProvider):
    """Fails explicitly instead of claiming mock email delivery succeeded in production."""

    def send_email(self, recipient: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
        raise EmailDeliveryError(
            "Production email delivery is not configured. Configure EMAIL_PROVIDER=smtp and SMTP credentials."
        )


_mock_email_provider = MockEmailProvider()
_smtp_email_provider = SMTPEmailProvider()


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.email_provider.strip().lower()
    if provider == "smtp":
        return _smtp_email_provider
    if provider == "mock":
        if settings.app_env == "production":
            return ProductionEmailNotConfiguredProvider()
        return _mock_email_provider
    return ProductionEmailNotConfiguredProvider()


def get_dev_email_outbox(recipient: Optional[str] = None) -> list[dict[str, str]]:
    settings = get_settings()
    if not settings.is_development:
        return []
    target = recipient.strip().lower() if recipient else None
    return [
        {
            "recipient": item.recipient,
            "subject": item.subject,
            "text_body": item.text_body,
            "sent_at": item.sent_at.isoformat(),
        }
        for item in _mock_email_provider.outbox
        if target is None or item.recipient == target
    ]
