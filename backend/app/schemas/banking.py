"""Pydantic schemas for banking operations, transfers, savings, cards, bills, and support."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _validate_positive_decimal(v: Decimal) -> Decimal:
    if v <= Decimal("0"):
        raise ValueError("Amount must be greater than zero.")
    if v > Decimal("100000000.00"):
        raise ValueError("Amount exceeds single-transaction prototype limit.")
    return v


class AccountOut(BaseModel):
    id: uuid.UUID
    account_number: str
    account_name: str
    currency: str
    available_balance: Decimal
    ledger_balance: Decimal
    status: str
    demo_funded: bool = False
    created_at: datetime


class TransactionOut(BaseModel):
    id: uuid.UUID
    reference: str
    category: str
    direction: str
    amount: Decimal
    fee: Decimal
    currency: str
    status: str
    narration: str
    counterparty_name: Optional[str]
    counterparty_account: Optional[str]
    counterparty_bank: Optional[str]
    metadata_json: Optional[dict[str, Any]]
    created_at: datetime


class DepositRequest(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    narration: str = Field(default="Simulated NGN Deposit", max_length=255)
    idempotency_key: Optional[str] = Field(default=None, max_length=120)

    _check_amount = field_validator("amount")(_validate_positive_decimal)


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    narration: str = Field(default="Simulated NGN Withdrawal", max_length=255)
    idempotency_key: Optional[str] = Field(default=None, max_length=120)

    _check_amount = field_validator("amount")(_validate_positive_decimal)


class InternalTransferRequest(BaseModel):
    recipient_account_number: str = Field(min_length=10, max_length=10, pattern=r"^\d{10}$")
    amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    narration: str = Field(default="BraveBank Transfer", max_length=255)
    idempotency_key: Optional[str] = Field(default=None, max_length=120)

    _check_amount = field_validator("amount")(_validate_positive_decimal)


class ExternalAccountResolveRequest(BaseModel):
    bank_code: str = Field(min_length=3, max_length=16)
    account_number: str = Field(min_length=10, max_length=10, pattern=r"^\d{10}$")


class ExternalTransferRequest(BaseModel):
    bank_code: str = Field(min_length=3, max_length=16)
    account_number: str = Field(min_length=10, max_length=10, pattern=r"^\d{10}$")
    account_name: str = Field(min_length=2, max_length=160)
    amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    narration: str = Field(default="External Bank Transfer (Simulated)", max_length=255)
    idempotency_key: Optional[str] = Field(default=None, max_length=120)

    _check_amount = field_validator("amount")(_validate_positive_decimal)


class BeneficiaryCreateRequest(BaseModel):
    nickname: str = Field(min_length=2, max_length=80)
    account_number: str = Field(min_length=10, max_length=20, pattern=r"^\d{10}$")
    account_name: str = Field(min_length=2, max_length=160)
    bank_code: str = Field(min_length=3, max_length=16)
    bank_name: str = Field(min_length=2, max_length=120)
    is_internal: bool = False


class SavingsGoalCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    target_amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    target_date: Optional[date] = None

    _check_target = field_validator("target_amount")(_validate_positive_decimal)


class SavingsContributeRequest(BaseModel):
    goal_id: uuid.UUID
    amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")

    _check_amount = field_validator("amount")(_validate_positive_decimal)


class VirtualCardCreateRequest(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    brand: str = Field(default="Verve", pattern=r"^(Verve|Mastercard)$")
    spending_limit: Decimal = Field(default=Decimal("500000.00"), gt=Decimal("0"), decimal_places=2)


class BillPaymentRequest(BaseModel):
    category: str = Field(pattern=r"^(airtime|data|electricity|television|education)$")
    provider: str = Field(min_length=2, max_length=80)
    customer_reference: str = Field(min_length=4, max_length=80)
    amount: Decimal = Field(gt=Decimal("0"), decimal_places=2)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    idempotency_key: Optional[str] = Field(default=None, max_length=120)

    _check_amount = field_validator("amount")(_validate_positive_decimal)


class SupportTicketCreateRequest(BaseModel):
    category: str = Field(min_length=2, max_length=50)
    subject: str = Field(min_length=4, max_length=140)
    message: str = Field(min_length=10, max_length=2000)
