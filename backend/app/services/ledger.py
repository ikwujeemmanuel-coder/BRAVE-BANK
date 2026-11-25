"""Atomic Decimal-based ledger and banking transaction engine."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.banking import Account, LedgerEntry, Transaction
from backend.app.models.user import TransactionPin, User
from backend.app.security.hashing import verify_pin
from backend.app.services.audit import create_notification, log_audit

TWO_DP = Decimal("0.01")


def quantize_ngn(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def generate_reference(prefix: str = "BBK") -> str:
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand_part = secrets.token_hex(4).upper()
    return f"{prefix}-{date_part}-{rand_part}"


def format_ngn(amount: Decimal) -> str:
    return f"NGN {quantize_ngn(amount):,.2f}"


def check_idempotency(db: Session, idempotency_key: Optional[str]) -> Optional[Transaction]:
    if not idempotency_key:
        return None
    existing = db.scalar(
        select(Transaction).where(Transaction.idempotency_key == idempotency_key)
    )
    return existing


def verify_transaction_pin_or_raise(db: Session, user_id: uuid.UUID, raw_pin: str) -> None:
    pin_record = db.scalar(select(TransactionPin).where(TransactionPin.user_id == user_id))
    if pin_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please set your 4-digit transaction PIN in Settings before making transfers or withdrawals.",
        )

    now = datetime.now(timezone.utc)
    if pin_record.locked_until and pin_record.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Transaction PIN is temporarily locked due to multiple invalid attempts. Try again later.",
        )

    if not verify_pin(raw_pin, pin_record.pin_hash):
        pin_record.failed_attempts += 1
        if pin_record.failed_attempts >= 5:
            pin_record.locked_until = now + timedelta(minutes=15)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 4-digit transaction PIN.",
        )

    if pin_record.failed_attempts > 0 or pin_record.locked_until is not None:
        pin_record.failed_attempts = 0
        pin_record.locked_until = None
        db.flush()


def lock_account_for_update(db: Session, account_id: uuid.UUID) -> Account:
    account = db.scalar(
        select(Account).where(Account.id == account_id).with_for_update()
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is currently frozen or inactive.",
        )
    return account


def lock_two_accounts_ordered(
    db: Session, account_id_a: uuid.UUID, account_id_b: uuid.UUID
) -> tuple[Account, Account]:
    """Acquire row-level locks in deterministic UUID order to prevent deadlocks."""
    if str(account_id_a) <= str(account_id_b):
        first = lock_account_for_update(db, account_id_a)
        second = lock_account_for_update(db, account_id_b)
        return first, second
    second = lock_account_for_update(db, account_id_b)
    first = lock_account_for_update(db, account_id_a)
    return first, second


def execute_deposit(
    db: Session,
    user: User,
    account: Account,
    amount: Decimal,
    narration: str = "Simulated NGN Account Deposit",
    category: str = "deposit",
    idempotency_key: Optional[str] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Transaction:
    amount = quantize_ngn(amount)
    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be greater than zero.",
        )

    existing = check_idempotency(db, idempotency_key)
    if existing is not None:
        if existing.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate reference.")
        return existing

    locked = lock_account_for_update(db, account.id)
    if locked.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    before = quantize_ngn(locked.available_balance)
    after = quantize_ngn(before + amount)
    locked.available_balance = after
    locked.ledger_balance = quantize_ngn(locked.ledger_balance + amount)

    tx = Transaction(
        reference=generate_reference("DEP"),
        idempotency_key=idempotency_key,
        account_id=locked.id,
        user_id=user.id,
        category=category,
        direction="credit",
        amount=amount,
        fee=Decimal("0.00"),
        currency="NGN",
        status="completed",
        narration=narration,
        counterparty_name=user.first_name + " " + user.surname,
        counterparty_account=locked.account_number,
        counterparty_bank="BRAVEBANK (Simulated)",
        metadata_json=metadata or {"simulated": True},
    )
    db.add(tx)
    db.flush()

    db.add(
        LedgerEntry(
            transaction_id=tx.id,
            account_id=locked.id,
            entry_type="credit",
            amount=amount,
            balance_before=before,
            balance_after=after,
            description=narration,
        )
    )
    create_notification(
        db,
        user.id,
        "transaction",
        "Account Credited",
        f"Your account {locked.account_number} was credited with {format_ngn(amount)}. Ref: {tx.reference}",
    )
    log_audit(
        db,
        action="account.deposit",
        resource_type="transaction",
        user_id=user.id,
        resource_id=str(tx.id),
        ip_address=ip_address,
        details={"amount": str(amount), "reference": tx.reference},
    )
    db.commit()
    db.refresh(tx)
    return tx


def execute_debit(
    db: Session,
    user: User,
    account: Account,
    amount: Decimal,
    pin: str,
    category: str,
    narration: str,
    counterparty_name: Optional[str] = None,
    counterparty_account: Optional[str] = None,
    counterparty_bank: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    audit_action: str = "account.debit",
    notification_title: str = "Account Debited",
) -> Transaction:
    amount = quantize_ngn(amount)
    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be greater than zero.",
        )

    existing = check_idempotency(db, idempotency_key)
    if existing is not None:
        if existing.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate reference.")
        return existing

    verify_transaction_pin_or_raise(db, user.id, pin)

    locked = lock_account_for_update(db, account.id)
    if locked.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    before = quantize_ngn(locked.available_balance)
    if before < amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient balance for this transaction.",
        )

    after = quantize_ngn(before - amount)
    locked.available_balance = after
    locked.ledger_balance = quantize_ngn(locked.ledger_balance - amount)

    tx = Transaction(
        reference=generate_reference("TXN"),
        idempotency_key=idempotency_key,
        account_id=locked.id,
        user_id=user.id,
        category=category,
        direction="debit",
        amount=amount,
        fee=Decimal("0.00"),
        currency="NGN",
        status="completed",
        narration=narration,
        counterparty_name=counterparty_name,
        counterparty_account=counterparty_account,
        counterparty_bank=counterparty_bank,
        metadata_json=metadata or {"simulated": True},
    )
    db.add(tx)
    db.flush()

    db.add(
        LedgerEntry(
            transaction_id=tx.id,
            account_id=locked.id,
            entry_type="debit",
            amount=amount,
            balance_before=before,
            balance_after=after,
            description=narration,
        )
    )
    create_notification(
        db,
        user.id,
        "transaction",
        notification_title,
        f"{format_ngn(amount)} was debited from {locked.account_number}. Ref: {tx.reference}",
    )
    log_audit(
        db,
        action=audit_action,
        resource_type="transaction",
        user_id=user.id,
        resource_id=str(tx.id),
        ip_address=ip_address,
        details={"amount": str(amount), "category": category, "reference": tx.reference},
    )
    db.commit()
    db.refresh(tx)
    return tx


def execute_internal_transfer(
    db: Session,
    sender: User,
    sender_account: Account,
    recipient_account: Account,
    amount: Decimal,
    pin: str,
    narration: str = "BraveBank Transfer",
    idempotency_key: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Transaction:
    amount = quantize_ngn(amount)
    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transfer amount must be greater than zero.",
        )

    if sender_account.id == recipient_account.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot transfer funds to the same account.",
        )

    existing = check_idempotency(db, idempotency_key)
    if existing is not None:
        if existing.user_id != sender.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate reference.")
        return existing

    verify_transaction_pin_or_raise(db, sender.id, pin)

    locked_sender, locked_recipient = lock_two_accounts_ordered(
        db, sender_account.id, recipient_account.id
    )
    if locked_sender.user_id != sender.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    sender_before = quantize_ngn(locked_sender.available_balance)
    if sender_before < amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient balance for this transfer.",
        )

    recipient_before = quantize_ngn(locked_recipient.available_balance)
    sender_after = quantize_ngn(sender_before - amount)
    recipient_after = quantize_ngn(recipient_before + amount)

    locked_sender.available_balance = sender_after
    locked_sender.ledger_balance = quantize_ngn(locked_sender.ledger_balance - amount)
    locked_recipient.available_balance = recipient_after
    locked_recipient.ledger_balance = quantize_ngn(locked_recipient.ledger_balance + amount)

    base_ref = generate_reference("TRF")
    debit_tx = Transaction(
        reference=base_ref,
        idempotency_key=idempotency_key,
        account_id=locked_sender.id,
        user_id=sender.id,
        category="internal_transfer",
        direction="debit",
        amount=amount,
        fee=Decimal("0.00"),
        currency="NGN",
        status="completed",
        narration=narration,
        counterparty_name=locked_recipient.account_name,
        counterparty_account=locked_recipient.account_number,
        counterparty_bank="BRAVEBANK",
        metadata_json={"simulated": True, "transfer_type": "internal"},
    )
    credit_tx = Transaction(
        reference=f"{base_ref}-CR",
        idempotency_key=None,
        account_id=locked_recipient.id,
        user_id=locked_recipient.user_id,
        category="internal_transfer",
        direction="credit",
        amount=amount,
        fee=Decimal("0.00"),
        currency="NGN",
        status="completed",
        narration=narration,
        counterparty_name=locked_sender.account_name,
        counterparty_account=locked_sender.account_number,
        counterparty_bank="BRAVEBANK",
        metadata_json={"simulated": True, "transfer_type": "internal", "paired_reference": base_ref},
    )
    db.add_all([debit_tx, credit_tx])
    db.flush()

    db.add_all(
        [
            LedgerEntry(
                transaction_id=debit_tx.id,
                account_id=locked_sender.id,
                entry_type="debit",
                amount=amount,
                balance_before=sender_before,
                balance_after=sender_after,
                description=f"Transfer to {locked_recipient.account_number}: {narration}",
            ),
            LedgerEntry(
                transaction_id=credit_tx.id,
                account_id=locked_recipient.id,
                entry_type="credit",
                amount=amount,
                balance_before=recipient_before,
                balance_after=recipient_after,
                description=f"Transfer from {locked_sender.account_number}: {narration}",
            ),
        ]
    )

    create_notification(
        db,
        sender.id,
        "transaction",
        "Transfer Sent",
        f"Sent {format_ngn(amount)} to {locked_recipient.account_name} ({locked_recipient.account_number}). Ref: {base_ref}",
    )
    create_notification(
        db,
        locked_recipient.user_id,
        "transaction",
        "Transfer Received",
        f"Received {format_ngn(amount)} from {locked_sender.account_name} ({locked_sender.account_number}). Ref: {credit_tx.reference}",
    )
    log_audit(
        db,
        action="transfer.internal",
        resource_type="transaction",
        user_id=sender.id,
        resource_id=str(debit_tx.id),
        ip_address=ip_address,
        details={
            "amount": str(amount),
            "from_account": locked_sender.account_number,
            "to_account": locked_recipient.account_number,
            "reference": base_ref,
        },
    )
    db.commit()
    db.refresh(debit_tx)
    return debit_tx
