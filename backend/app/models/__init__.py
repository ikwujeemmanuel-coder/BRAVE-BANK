"""SQLAlchemy model registry for BraveBank."""

from backend.app.database import Base
from backend.app.models.banking import Account, Bank, Beneficiary, LedgerEntry, Transaction
from backend.app.models.services import (
    BillPayment,
    SavingsAccount,
    SavingsContribution,
    SavingsGoal,
    VirtualCard,
)
from backend.app.models.support import AuditLog, Notification, SupportTicket
from backend.app.models.user import Credential, LoginSession, OtpRecord, TransactionPin, User

__all__ = [
    "Base",
    "User",
    "Credential",
    "TransactionPin",
    "OtpRecord",
    "LoginSession",
    "Account",
    "Transaction",
    "LedgerEntry",
    "Bank",
    "Beneficiary",
    "SavingsAccount",
    "SavingsGoal",
    "SavingsContribution",
    "VirtualCard",
    "BillPayment",
    "Notification",
    "SupportTicket",
    "AuditLog",
]
