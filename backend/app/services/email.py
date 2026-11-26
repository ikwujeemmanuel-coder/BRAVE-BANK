"""Central email delivery service using Brevo HTTP transactional email API and test mock outbox."""

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email
import httpx

from backend.app.config import get_settings

logger = logging.getLogger("bravebank.email")

BREVO_OFFICIAL_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


class EmailDeliveryError(RuntimeError):
    """Raised when email delivery fails or email transport is misconfigured."""


@dataclass
class MockEmailMessage:
    recipient: str
    subject: str
    text_body: str
    html_body: Optional[str]
    sent_at: datetime


def _redact_sensitive(text: str, *secrets_to_redact: Optional[str]) -> str:
    """Remove API keys, credentials, or verification codes from diagnostic strings."""
    cleaned = str(text or "")
    for secret in secrets_to_redact:
        if secret and secret.strip():
            cleaned = cleaned.replace(secret.strip(), "[REDACTED]")
    cleaned = re.sub(r"xkeysib-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", cleaned)
    cleaned = re.sub(r"\b\d{6}\b", "[REDACTED_CODE]", cleaned)
    return cleaned


def _validate_email_address(raw_address: Optional[str], field_label: str) -> str:
    if not raw_address or not raw_address.strip():
        raise EmailDeliveryError(
            f"Email delivery is not configured: {field_label} is missing."
        )
    candidate = raw_address.strip()
    try:
        info = validate_email(candidate, check_deliverability=False)
        return info.normalized.lower()
    except EmailNotValidError as exc:
        raise EmailDeliveryError(
            f"Invalid email configuration for {field_label}."
        ) from exc


def _format_expiration_period(expire_seconds: int) -> str:
    seconds = max(1, int(expire_seconds))
    if seconds % 60 == 0:
        minutes = seconds // 60
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    return "1 second" if seconds == 1 else f"{seconds} seconds"


class EmailProvider(ABC):
    """Abstract email provider interface."""

    @abstractmethod
    def send_email(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> Optional[str]:
        """Submit an email to the provider and return a provider message ID if supplied."""


class MockEmailProvider(EmailProvider):
    """Development/Test mock email provider storing dispatched emails in memory."""

    def __init__(self) -> None:
        self.outbox: deque[MockEmailMessage] = deque(maxlen=100)

    def send_email(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> Optional[str]:
        normalized_recipient = _validate_email_address(recipient, "recipient email")
        entry = MockEmailMessage(
            recipient=normalized_recipient,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            sent_at=datetime.now(timezone.utc),
        )
        self.outbox.appendleft(entry)
        # Never log message body or OTP values
        logger.info("[DEV MOCK EMAIL] Queued email | Subject: %s", subject)
        return None


class BrevoEmailProvider(EmailProvider):
    """Transactional email transport via Brevo's HTTPS v3 API."""

    def _prepare_request(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> tuple[str, dict[str, str], dict[str, Any], httpx.Timeout, str]:
        settings = get_settings()

        api_key = (settings.brevo_api_key or "").strip()
        if not api_key:
            logger.error("Brevo email delivery aborted: BREVO_API_KEY is not configured.")
            raise EmailDeliveryError(
                "Email delivery service is not configured. Missing provider credentials."
            )

        sender_email = _validate_email_address(
            settings.email_from_address, "EMAIL_FROM_ADDRESS"
        )
        sender_name = (settings.email_from_name or "BraveBank").strip() or "BraveBank"
        recipient_email = _validate_email_address(recipient, "recipient email")

        endpoint = (settings.brevo_api_url or BREVO_OFFICIAL_ENDPOINT).strip()
        parsed_endpoint = urlparse(endpoint)
        if parsed_endpoint.scheme.lower() != "https" or not parsed_endpoint.netloc:
            logger.error("Brevo email delivery aborted: endpoint must be a valid HTTPS URL.")
            raise EmailDeliveryError(
                "Email delivery configuration is invalid. Secure HTTPS transport is required."
            )

        clean_subject = (subject or "").strip()
        clean_text = (text_body or "").strip()
        if not clean_subject or not clean_text:
            raise EmailDeliveryError(
                "Email delivery request is incomplete. Subject and body are required."
            )

        timeout_seconds = max(1.0, float(settings.brevo_timeout_seconds or 10.0))
        timeout = httpx.Timeout(timeout=timeout_seconds, connect=min(5.0, timeout_seconds))

        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resolved_html = html_body or (
            "<div style='font-family:Arial,sans-serif;line-height:1.5;color:#0f172a'>"
            f"<p>{html_escape(clean_text).replace(chr(10), '<br>')}</p></div>"
        )
        payload: dict[str, Any] = {
            "sender": {
                "name": sender_name,
                "email": sender_email,
            },
            "to": [{"email": recipient_email}],
            "subject": clean_subject,
            "htmlContent": resolved_html,
            "textContent": clean_text,
        }
        return endpoint, headers, payload, timeout, api_key

    def _handle_response(self, response: httpx.Response, api_key: str) -> Optional[str]:
        status_code = response.status_code
        provider_code = ""
        provider_msg = ""
        parsed_body: Any = None

        try:
            parsed_body = response.json()
            if isinstance(parsed_body, dict):
                provider_code = _redact_sensitive(str(parsed_body.get("code") or ""), api_key)
                provider_msg = _redact_sensitive(str(parsed_body.get("message") or ""), api_key)
        except ValueError:
            parsed_body = None

        if 200 <= status_code < 300:
            raw_msg_id = (
                (parsed_body.get("messageId") or parsed_body.get("messageIds"))
                if isinstance(parsed_body, dict)
                else None
            )
            if not raw_msg_id:
                logger.error(
                    "Brevo returned HTTP %s with unexpected/malformed response payload.",
                    status_code,
                )
                raise EmailDeliveryError(
                    "Unexpected response from email delivery provider. Please try again later."
                )
            msg_id_str = (
                ", ".join(str(item) for item in raw_msg_id)
                if isinstance(raw_msg_id, list)
                else str(raw_msg_id)
            )
            logger.info(
                "Brevo transactional email request accepted (status=%s, messageId=%s).",
                status_code,
                msg_id_str,
            )
            return msg_id_str

        logger.error(
            "Brevo transactional email rejected (status=%s, code=%s, detail=%s).",
            status_code,
            provider_code or "unknown",
            provider_msg[:200] if provider_msg else "no_detail",
        )

        if status_code == 401:
            raise EmailDeliveryError(
                "Email delivery authentication failed. Please contact support."
            )
        if status_code == 402:
            raise EmailDeliveryError(
                "Email delivery provider quota or account sending limit reached. Please contact support."
            )
        if status_code == 403:
            raise EmailDeliveryError(
                "Email sender or account is not authorized by the email provider. Please verify sender and account configuration."
            )
        if status_code in {400, 422}:
            raise EmailDeliveryError(
                "Email delivery request was rejected by the email provider."
            )
        if status_code == 429:
            raise EmailDeliveryError(
                "Email delivery is temporarily rate-limited. Please wait a moment and try again."
            )
        if status_code >= 500:
            raise EmailDeliveryError(
                "Email delivery service is temporarily unavailable. Please try again later."
            )
        raise EmailDeliveryError(
            "Unable to submit verification email at this time. Please try again later."
        )

    def send_email(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> Optional[str]:
        endpoint, headers, payload, timeout, api_key = self._prepare_request(
            recipient=recipient,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Brevo HTTPS request timed out (%s).", type(exc).__name__)
            raise EmailDeliveryError(
                "Email delivery request timed out. Please try again shortly."
            ) from exc
        except httpx.RequestError as exc:
            safe_detail = _redact_sensitive(str(exc), api_key)
            logger.error(
                "Brevo HTTPS network failure (%s): %s",
                type(exc).__name__,
                safe_detail[:200],
            )
            raise EmailDeliveryError(
                "Unable to connect to the email delivery service. Please try again shortly."
            ) from exc

        return self._handle_response(response, api_key)

    async def send_email_async(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> Optional[str]:
        endpoint, headers, payload, timeout, api_key = self._prepare_request(
            recipient=recipient,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Brevo async HTTPS request timed out (%s).", type(exc).__name__)
            raise EmailDeliveryError(
                "Email delivery request timed out. Please try again shortly."
            ) from exc
        except httpx.RequestError as exc:
            safe_detail = _redact_sensitive(str(exc), api_key)
            logger.error(
                "Brevo async HTTPS network failure (%s): %s",
                type(exc).__name__,
                safe_detail[:200],
            )
            raise EmailDeliveryError(
                "Unable to connect to the email delivery service. Please try again shortly."
            ) from exc

        return self._handle_response(response, api_key)


class ProductionEmailNotConfiguredProvider(EmailProvider):
    """Fails explicitly instead of claiming mock email delivery succeeded in production."""

    def send_email(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> Optional[str]:
        raise EmailDeliveryError(
            "Production email delivery is not configured. Configure EMAIL_PROVIDER=brevo, BREVO_API_KEY, and EMAIL_FROM_ADDRESS."
        )


_mock_email_provider = MockEmailProvider()
_brevo_email_provider = BrevoEmailProvider()


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    provider = settings.email_provider.strip().lower()
    if provider == "brevo":
        return _brevo_email_provider
    if provider == "mock":
        if settings.app_env == "production":
            return ProductionEmailNotConfiguredProvider()
        return _mock_email_provider
    return ProductionEmailNotConfiguredProvider()


def build_otp_email_content(
    code: str,
    purpose: str,
    expire_seconds: int,
) -> tuple[str, str, str]:
    """Build branded subject, textContent, and htmlContent for BraveBank OTP emails."""
    expiry_text = _format_expiration_period(expire_seconds)
    escaped_code = html_escape(code)

    if purpose == "email_registration":
        subject = "BraveBank — Your Email Verification Code"
        heading = "Verify Your Email Address"
        reason = (
            "You are receiving this email because you started creating a BraveBank "
            "account using this email address."
        )
    elif purpose == "password_reset":
        subject = "BraveBank — Your Password Reset Verification Code"
        heading = "Reset Your BraveBank Password"
        reason = (
            "You are receiving this email because a password reset was requested "
            "for your BraveBank account."
        )
    elif purpose == "pin_reset":
        subject = "BraveBank — Your Transaction PIN Reset Verification Code"
        heading = "Reset Your Transaction PIN"
        reason = (
            "You are receiving this email because a 4-digit transaction PIN reset "
            "was requested for your BraveBank account."
        )
    else:
        subject = "BraveBank — Verify Your Email Address"
        heading = "Confirm Your Email Address"
        reason = (
            "You are receiving this email because you requested to verify this "
            "email address on your BraveBank profile."
        )

    text_body = (
        f"Your BraveBank verification code is: {code}\n\n"
        f"{reason}\n"
        f"This verification code expires in {expiry_text}.\n\n"
        "Security warning: Never share this code or your transaction PIN with anyone, "
        "including anyone claiming to be BraveBank staff.\n\n"
        "If you did not request this verification code, you can safely ignore this email."
    )

    html_body = (
        "<div style='font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;"
        "padding:28px;border:1px solid #dbe6ff;border-radius:16px;background:#ffffff;color:#0f172a'>"
        "<div style='margin-bottom:18px'>"
        "<span style='font-size:22px;font-weight:800;letter-spacing:0.5px;color:#0f172a'>BRAVE</span>"
        "<span style='font-size:22px;font-weight:800;letter-spacing:0.5px;color:#007bff'>BANK</span>"
        "<div style='font-size:12px;color:#64748b;margin-top:2px'>Banking Without Limits</div>"
        "</div>"
        f"<h2 style='margin:0 0 10px;font-size:19px;color:#0f172a'>{html_escape(heading)}</h2>"
        f"<p style='margin:0 0 18px;font-size:14px;line-height:1.6;color:#334155'>{html_escape(reason)}</p>"
        "<div style='font-size:30px;font-weight:800;letter-spacing:8px;color:#007bff;"
        "background:#f3f6ff;border:1px solid #dbe6ff;padding:16px 20px;border-radius:12px;"
        f"text-align:center;margin:0 0 18px'>{escaped_code}</div>"
        f"<p style='margin:0 0 10px;font-size:13px;line-height:1.5;color:#334155'>"
        f"This code expires in <strong>{html_escape(expiry_text)}</strong>.</p>"
        "<p style='margin:0 0 10px;font-size:13px;line-height:1.5;color:#b91c1c;font-weight:600'>"
        "Do not share this verification code with anyone. BraveBank will never ask you for this code.</p>"
        "<p style='margin:0;font-size:12px;line-height:1.5;color:#64748b'>"
        "If you did not request this email, you can safely ignore it.</p>"
        "</div>"
    )
    return subject, text_body, html_body


def send_transactional_email(
    recipient: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> Optional[str]:
    """Dispatch any transactional email through the configured central email provider."""
    provider = get_email_provider()
    return provider.send_email(
        recipient=recipient,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def send_otp_email(
    recipient: str,
    code: str,
    purpose: str,
    expire_seconds: int,
) -> Optional[str]:
    """Build and send a BraveBank OTP email through the central email provider."""
    subject, text_body, html_body = build_otp_email_content(
        code=code,
        purpose=purpose,
        expire_seconds=expire_seconds,
    )
    return send_transactional_email(
        recipient=recipient,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )


def get_dev_email_outbox(recipient: Optional[str] = None) -> list[dict[str, str]]:
    """Return in-memory mock emails for automated tests only (never active in production)."""
    settings = get_settings()
    if not settings.is_development:
        return []
    target = recipient.strip().lower() if recipient else None
    return [
        {
            "recipient": item.recipient,
            "subject": item.subject,
            "text_body": item.text_body,
            "html_body": item.html_body or "",
            "sent_at": item.sent_at.isoformat(),
        }
        for item in _mock_email_provider.outbox
        if target is None or item.recipient == target
    ]
