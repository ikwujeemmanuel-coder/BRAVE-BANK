"""Transaction history, search, filtering, and receipt detail endpoints."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.banking import LedgerEntry, Transaction
from backend.app.models.user import User
from backend.app.schemas.banking import TransactionOut
from backend.app.security.dependencies import get_current_user

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def list_transactions(
    search: Optional[str] = Query(default=None, max_length=100),
    category: Optional[str] = Query(default=None, max_length=40),
    direction: Optional[str] = Query(default=None, max_length=10),
    tx_status: Optional[str] = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Transaction).where(Transaction.user_id == current_user.id)
    count_stmt = select(func.count(Transaction.id)).where(Transaction.user_id == current_user.id)

    if category:
        stmt = stmt.where(Transaction.category == category)
        count_stmt = count_stmt.where(Transaction.category == category)
    if direction:
        stmt = stmt.where(Transaction.direction == direction)
        count_stmt = count_stmt.where(Transaction.direction == direction)
    if tx_status:
        stmt = stmt.where(Transaction.status == tx_status)
        count_stmt = count_stmt.where(Transaction.status == tx_status)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        cond = or_(
            Transaction.reference.ilike(pattern),
            Transaction.narration.ilike(pattern),
            Transaction.counterparty_name.ilike(pattern),
            Transaction.counterparty_account.ilike(pattern),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(desc(Transaction.created_at)).offset(offset).limit(limit)
    ).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [TransactionOut.model_validate(r, from_attributes=True) for r in rows],
    }


@router.get("/{transaction_id}")
def get_transaction_detail(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tx = db.get(Transaction, transaction_id)
    if tx is None or tx.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")

    entries = db.scalars(
        select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id)
    ).all()

    return {
        "transaction": TransactionOut.model_validate(tx, from_attributes=True),
        "ledger_entries": [
            {
                "id": str(e.id),
                "entry_type": e.entry_type,
                "amount": e.amount,
                "balance_before": e.balance_before,
                "balance_after": e.balance_after,
                "description": e.description,
                "created_at": e.created_at,
            }
            for e in entries
        ],
        "receipt": {
            "bank": "BRAVEBANK",
            "reference": tx.reference,
            "currency": tx.currency,
            "amount": tx.amount,
            "fee": tx.fee,
            "status": tx.status,
            "category": tx.category,
            "direction": tx.direction,
            "counterparty_name": tx.counterparty_name,
            "counterparty_account": tx.counterparty_account,
            "counterparty_bank": tx.counterparty_bank,
            "narration": tx.narration,
            "timestamp": tx.created_at,
            "disclosure": "Simulated digital banking receipt — BraveBank Prototype",
        },
    }
