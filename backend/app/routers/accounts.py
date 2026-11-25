"""Customer account, dashboard summary, deposit, and withdrawal endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.banking import Account, Transaction
from backend.app.models.services import SavingsAccount, SavingsGoal
from backend.app.models.support import Notification
from backend.app.models.user import User
from backend.app.schemas.banking import AccountOut, DepositRequest, TransactionOut, WithdrawRequest
from backend.app.security.dependencies import get_current_user
from backend.app.services.ledger import execute_debit, execute_deposit

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _get_primary_account(db: Session, user: User) -> Account:
    account = db.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at).limit(1)
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer account not found.")
    return account


@router.get("/me", response_model=AccountOut)
def get_my_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = _get_primary_account(db, current_user)
    return AccountOut.model_validate(account, from_attributes=True)


@router.get("/dashboard")
def get_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = _get_primary_account(db, current_user)

    total_received = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), Decimal("0.00"))).where(
            Transaction.account_id == account.id,
            Transaction.direction == "credit",
            Transaction.status == "completed",
        )
    ) or Decimal("0.00")

    total_sent = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), Decimal("0.00"))).where(
            Transaction.account_id == account.id,
            Transaction.direction == "debit",
            Transaction.status == "completed",
        )
    ) or Decimal("0.00")

    unread_notifications = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    ) or 0

    recent_txs = db.scalars(
        select(Transaction)
        .where(Transaction.account_id == account.id)
        .order_by(desc(Transaction.created_at))
        .limit(6)
    ).all()

    savings = db.scalar(select(SavingsAccount).where(SavingsAccount.user_id == current_user.id))
    goals_count = db.scalar(
        select(func.count(SavingsGoal.id)).where(SavingsGoal.user_id == current_user.id)
    ) or 0

    # Real 7-day inflow/outflow activity calculated from PostgreSQL transactions
    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=6)
    week_txs = db.scalars(
        select(Transaction).where(
            Transaction.account_id == account.id,
            Transaction.status == "completed",
            Transaction.created_at >= datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc),
        )
    ).all()

    daily_map = {
        start_day + timedelta(days=i): {"inflow": Decimal("0.00"), "outflow": Decimal("0.00")}
        for i in range(7)
    }
    for tx in week_txs:
        tx_day = tx.created_at.astimezone(timezone.utc).date()
        if tx_day in daily_map:
            if tx.direction == "credit":
                daily_map[tx_day]["inflow"] += tx.amount
            else:
                daily_map[tx_day]["outflow"] += tx.amount

    weekly_activity = [
        {
            "day": day.strftime("%a"),
            "date": day.isoformat(),
            "inflow": str(vals["inflow"]),
            "outflow": str(vals["outflow"]),
        }
        for day, vals in daily_map.items()
    ]

    return {
        "account": AccountOut.model_validate(account, from_attributes=True),
        "secondary_currency": {
            "currency": "USD",
            "status": "coming_soon",
            "enabled": False,
        },
        "total_received": total_received,
        "total_sent": total_sent,
        "unread_notifications": unread_notifications,
        "savings_summary": {
            "balance": savings.balance if savings else Decimal("0.00"),
            "goals_count": goals_count,
            "annual_interest_rate": savings.annual_interest_rate if savings else Decimal("12.50"),
        },
        "weekly_activity": weekly_activity,
        "recent_transactions": [
            TransactionOut.model_validate(tx, from_attributes=True) for tx in recent_txs
        ],
        "prototype_disclosure": (
            "BRAVEBANK is a simulated Nigerian digital banking prototype. "
            "All balances, transfers, cards, and bill payments are simulated."
        ),
    }


@router.post("/deposit", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def deposit_funds(
    payload: DepositRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_primary_account(db, current_user)
    tx = execute_deposit(
        db=db,
        user=current_user,
        account=account,
        amount=payload.amount,
        narration=payload.narration.strip() or "Simulated NGN Deposit",
        idempotency_key=payload.idempotency_key,
        ip_address=request.client.host if request.client else None,
    )
    return TransactionOut.model_validate(tx, from_attributes=True)


@router.post("/withdraw", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def withdraw_funds(
    payload: WithdrawRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_primary_account(db, current_user)
    tx = execute_debit(
        db=db,
        user=current_user,
        account=account,
        amount=payload.amount,
        pin=payload.pin,
        category="withdrawal",
        narration=payload.narration.strip() or "Simulated NGN Withdrawal",
        counterparty_name=f"{current_user.first_name} {current_user.surname}".upper(),
        counterparty_account=account.account_number,
        counterparty_bank="BRAVEBANK Cash Out (Simulated)",
        idempotency_key=payload.idempotency_key,
        ip_address=request.client.host if request.client else None,
        audit_action="account.withdraw",
        notification_title="Withdrawal Completed",
    )
    return TransactionOut.model_validate(tx, from_attributes=True)
