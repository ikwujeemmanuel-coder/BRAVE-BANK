"""SMS provider abstraction with development mock delivery."""

import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.app.config import get_settings

logger = logging.getLogger("bravebank.sms")


@dataclass
class MockSMSMessage:
    phone_number: str
    message: str
    sent_at: datetime


class SMSProvider(ABC):
    """Abstract SMS interface for Nigerian SMS gateway integration (e.g. Termii)."""

    @abstractmethod
    def send_sms(self, phone_number: str, message: str) -> None:
        """Dispatch an SMS message to a recipient phone number."""


class MockSMSProvider(SMSProvider):
    """Development-only mock SMS provider that records messages locally."""

    def __init__(self) -> None:
        self.outbox: deque[MockSMSMessage] = deque(maxlen=100)

    def send_sms(self, phone_number: str, message: str) -> None:
        entry = MockSMSMessage(
            phone_number=phone_number,
            message=message,
            sent_at=datetime.now(timezone.utc),
        )
        self.outbox.appendleft(entry)
        logger.info("[DEV MOCK SMS] To %s: %s", phone_number, message)


class ProductionSMSNotConfiguredProvider(SMSProvider):
    """Safeguard refusing silent mock claims in production until real gateway is wired."""

    def send_sms(self, phone_number: str, message: str) -> None:
        raise RuntimeError(
            "Production SMS gateway is not configured. Configure a Nigerian SMS provider before sending live SMS."
        )


_mock_provider = MockSMSProvider()


def get_sms_provider() -> SMSProvider:
    settings = get_settings()
    if settings.sms_provider.lower() == "mock":
        if settings.app_env == "production":
            return ProductionSMSNotConfiguredProvider()
        return _mock_provider
    return ProductionSMSNotConfiguredProvider()


def get_dev_outbox(phone_number: Optional[str] = None) -> list[dict[str, str]]:
    settings = get_settings()
    if not settings.is_development:
        return []
    messages = [
        {
            "phone_number": item.phone_number,
            "message": item.message,
            "sent_at": item.sent_at.isoformat(),
        }
        for item in _mock_provider.outbox
        if phone_number is None or item.phone_number == phone_number
    ]
    return messages
