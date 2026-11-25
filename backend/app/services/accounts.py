"""Account number generation, Nigerian bank directory seeding, and mock name lookup."""

import hashlib
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.banking import Account, Bank
from backend.app.models.services import SavingsAccount

NIGERIAN_BANKS = [
    {"code": "058", "name": "Guaranty Trust Bank (GTBank)", "nip_code": "000013"},
    {"code": "011", "name": "First Bank of Nigeria", "nip_code": "000016"},
    {"code": "033", "name": "United Bank for Africa (UBA)", "nip_code": "000004"},
    {"code": "044", "name": "Access Bank", "nip_code": "000014"},
    {"code": "057", "name": "Zenith Bank", "nip_code": "000015"},
    {"code": "035", "name": "Wema Bank", "nip_code": "000017"},
    {"code": "232", "name": "Sterling Bank", "nip_code": "000001"},
    {"code": "070", "name": "Fidelity Bank", "nip_code": "000007"},
    {"code": "214", "name": "First City Monument Bank (FCMB)", "nip_code": "000003"},
    {"code": "090267", "name": "Kuda Microfinance Bank", "nip_code": "090267"},
    {"code": "999992", "name": "OPay Digital Services", "nip_code": "100004"},
    {"code": "999991", "name": "PalmPay", "nip_code": "100033"},
]

_MOCK_FIRST_NAMES = [
    "CHINEDUM",
    "OLUWASEUN",
    "AISHA",
    "IBRAHIM",
    "TEMITOPE",
    "NGOZI",
    "YUSUF",
    "ADAOBI",
    "BABATUNDE",
    "ZAINAB",
]
_MOCK_SURNAMES = [
    "OKAFOR",
    "ADEBAYO",
    "BELLO",
    "DANJUMA",
    "EZE",
    "OGUNLEYE",
    "SANI",
    "NWOSU",
    "BALOGUN",
    "MUSA",
]


def generate_unique_account_number(db: Session) -> str:
    """Generate a unique 10-digit internal BraveBank account number starting with 30."""
    for _ in range(25):
        candidate = f"30{secrets.randbelow(100_000_000):08d}"
        exists = db.scalar(select(Account.id).where(Account.account_number == candidate))
        if exists is None:
            return candidate
    raise RuntimeError("Unable to allocate unique BraveBank account number.")


def generate_unique_savings_number(db: Session) -> str:
    """Generate a unique 10-digit BraveBank savings account number starting with 80."""
    for _ in range(25):
        candidate = f"80{secrets.randbelow(100_000_000):08d}"
        exists = db.scalar(
            select(SavingsAccount.id).where(SavingsAccount.account_number == candidate)
        )
        if exists is None:
            return candidate
    raise RuntimeError("Unable to allocate unique BraveBank savings account number.")


def ensure_default_banks(db: Session) -> None:
    """Populate the Nigerian bank directory if empty."""
    existing = db.scalar(select(Bank.id).limit(1))
    if existing is not None:
        return
    for item in NIGERIAN_BANKS:
        db.add(Bank(**item, is_active=True))
    db.commit()


def resolve_mock_external_account(bank_code: str, account_number: str) -> str:
    """Deterministic simulated Nigerian bank name enquiry for prototype testing."""
    digest = hashlib.sha256(f"{bank_code}:{account_number}".encode("utf-8")).digest()
    first = _MOCK_FIRST_NAMES[digest[0] % len(_MOCK_FIRST_NAMES)]
    last = _MOCK_SURNAMES[digest[1] % len(_MOCK_SURNAMES)]
    middle = _MOCK_FIRST_NAMES[digest[2] % len(_MOCK_FIRST_NAMES)]
    return f"{last} {first} {middle}"
