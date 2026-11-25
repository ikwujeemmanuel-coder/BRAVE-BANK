"""Savings goals, simulated virtual cards, and Nigerian bill payment endpoints."""

import hashlib
import secrets
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.banking import Account
from backend.app.models.services import (
    BillPayment,
    SavingsAccount,
    SavingsContribution,
    SavingsGoal,
    VirtualCard,
)
from backend.app.models.user import User
from backend.app.schemas.banking import (
    BillPaymentRequest,
    SavingsContributeRequest,
    SavingsGoalCreateRequest,
    VirtualCardCreateRequest,
)
from backend.app.security.dependencies import get_client_ip, get_current_user
from backend.app.services.accounts import generate_unique_savings_number
from backend.app.services.audit import create_notification, log_audit
from backend.app.services.ledger import execute_debit, quantize_ngn

router = APIRouter(prefix="/api", tags=["banking-services"])

BILL_PROVIDERS = {
    "airtime": ["MTN Nigeria", "Airtel Nigeria", "Glo Mobile", "9mobile"],
    "data": ["MTN Data", "Airtel Data", "Glo Data", "9mobile Data"],
    "electricity": ["IKEDC (Ikeja Electric)", "EKEDC (Eko Electric)", "AEDC (Abuja Electric)", "IBEDC"],
    "television": ["DStv", "GOtv", "StarTimes"],
    "education": ["WAEC Result Checker", "JAMB e-PIN", "NECO Token"],
}


def _get_primary_account(db: Session, user: User) -> Account:
    account = db.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at).limit(1)
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    return account


def _get_or_create_savings_account(db: Session, user: User) -> SavingsAccount:
    savings = db.scalar(select(SavingsAccount).where(SavingsAccount.user_id == user.id))
    if savings is None:
        savings = SavingsAccount(
            user_id=user.id,
            account_number=generate_unique_savings_number(db),
            balance=Decimal("0.00"),
            annual_interest_rate=Decimal("12.50"),
            accrued_interest=Decimal("0.00"),
        )
        db.add(savings)
        db.flush()
    return savings


@router.get("/savings")
def get_savings_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    savings = _get_or_create_savings_account(db, current_user)
    db.commit()
    goals = db.scalars(
        select(SavingsGoal)
        .where(SavingsGoal.user_id == current_user.id)
        .order_by(desc(SavingsGoal.created_at))
    ).all()
    contributions = db.scalars(
        select(SavingsContribution)
        .where(SavingsContribution.user_id == current_user.id)
        .order_by(desc(SavingsContribution.created_at))
        .limit(20)
    ).all()
    return {
        "savings_account": {
            "id": str(savings.id),
            "account_number": savings.account_number,
            "balance": savings.balance,
            "annual_interest_rate": savings.annual_interest_rate,
            "accrued_interest": savings.accrued_interest,
        },
        "goals": [
            {
                "id": str(g.id),
                "title": g.title,
                "target_amount": g.target_amount,
                "current_amount": g.current_amount,
                "target_date": g.target_date,
                "status": g.status,
                "progress_percent": float(
                    min(Decimal("100.00"), (g.current_amount / g.target_amount) * Decimal("100"))
                ),
            }
            for g in goals
        ],
        "contributions": [
            {
                "id": str(c.id),
                "goal_id": str(c.goal_id),
                "amount": c.amount,
                "created_at": c.created_at,
            }
            for c in contributions
        ],
    }


@router.post("/savings/goals", status_code=status.HTTP_201_CREATED)
def create_savings_goal(
    payload: SavingsGoalCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    savings = _get_or_create_savings_account(db, current_user)
    goal = SavingsGoal(
        user_id=current_user.id,
        savings_account_id=savings.id,
        title=payload.title.strip(),
        target_amount=quantize_ngn(payload.target_amount),
        current_amount=Decimal("0.00"),
        target_date=payload.target_date,
        status="active",
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return {
        "id": str(goal.id),
        "title": goal.title,
        "target_amount": goal.target_amount,
        "current_amount": goal.current_amount,
        "target_date": goal.target_date,
        "status": goal.status,
    }


@router.post("/savings/contribute", status_code=status.HTTP_201_CREATED)
def contribute_to_savings_goal(
    payload: SavingsContributeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.get(SavingsGoal, payload.goal_id)
    if goal is None or goal.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Savings goal not found.")

    account = _get_primary_account(db, current_user)
    savings = _get_or_create_savings_account(db, current_user)
    amount = quantize_ngn(payload.amount)

    tx = execute_debit(
        db=db,
        user=current_user,
        account=account,
        amount=amount,
        pin=payload.pin,
        category="savings_contribution",
        narration=f"Contribution to savings goal: {goal.title}",
        counterparty_name=goal.title,
        counterparty_account=savings.account_number,
        counterparty_bank="BRAVEBANK Savings Vault",
        ip_address=get_client_ip(request),
        audit_action="savings.contribute",
        notification_title="Savings Contribution Posted",
    )

    savings.balance = quantize_ngn(savings.balance + amount)
    goal.current_amount = quantize_ngn(goal.current_amount + amount)
    if goal.current_amount >= goal.target_amount:
        goal.status = "completed"
    db.add(
        SavingsContribution(
            user_id=current_user.id,
            goal_id=goal.id,
            savings_account_id=savings.id,
            transaction_id=tx.id,
            amount=amount,
        )
    )
    db.commit()

    return {
        "transaction_reference": tx.reference,
        "savings_balance": savings.balance,
        "goal_current_amount": goal.current_amount,
        "goal_status": goal.status,
    }


@router.post("/savings/simulate-interest")
def simulate_monthly_interest(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    savings = _get_or_create_savings_account(db, current_user)
    if savings.balance <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contribute funds to your savings vault before simulating interest.",
        )

    monthly_rate = (savings.annual_interest_rate / Decimal("100")) / Decimal("12")
    interest = quantize_ngn(savings.balance * monthly_rate)
    if interest < Decimal("0.01"):
        interest = Decimal("0.01")

    savings.balance = quantize_ngn(savings.balance + interest)
    savings.accrued_interest = quantize_ngn(savings.accrued_interest + interest)
    create_notification(
        db,
        current_user.id,
        "account",
        "Simulated Interest Credited",
        f"NGN {interest:,.2f} simulated monthly interest was added to your savings vault.",
    )
    db.commit()

    return {
        "interest_credited": interest,
        "savings_balance": savings.balance,
        "accrued_interest": savings.accrued_interest,
        "simulated": True,
    }


@router.get("/cards")
def list_virtual_cards(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cards = db.scalars(
        select(VirtualCard)
        .where(VirtualCard.user_id == current_user.id)
        .order_by(desc(VirtualCard.created_at))
    ).all()
    return [
        {
            "id": str(c.id),
            "label": c.label,
            "brand": c.brand,
            "masked_pan": c.masked_pan,
            "last4": c.last4,
            "expiry": f"{c.expiry_month:02d}/{str(c.expiry_year)[-2:]}",
            "status": c.status,
            "spending_limit": c.spending_limit,
            "simulated": True,
        }
        for c in cards
    ]


@router.post("/cards", status_code=status.HTTP_201_CREATED)
def create_virtual_card(
    payload: VirtualCardCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = _get_primary_account(db, current_user)
    prefix = "5061" if payload.brand == "Verve" else "5399"
    last4 = f"{secrets.randbelow(10000):04d}"
    masked_pan = f"{prefix} •••• •••• {last4}"
    token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()

    card = VirtualCard(
        user_id=current_user.id,
        account_id=account.id,
        label=payload.label.strip(),
        brand=payload.brand,
        masked_pan=masked_pan,
        last4=last4,
        expiry_month=11,
        expiry_year=2029,
        card_token_hash=token_hash,
        status="active",
        spending_limit=quantize_ngn(payload.spending_limit),
    )
    db.add(card)
    create_notification(
        db,
        current_user.id,
        "account",
        "Virtual Card Created",
        f"Simulated {card.brand} virtual card ending in {card.last4} is ready.",
    )
    log_audit(db, action="card.created", resource_type="virtual_card", user_id=current_user.id)
    db.commit()
    db.refresh(card)

    return {
        "id": str(card.id),
        "label": card.label,
        "brand": card.brand,
        "masked_pan": card.masked_pan,
        "last4": card.last4,
        "expiry": f"{card.expiry_month:02d}/{str(card.expiry_year)[-2:]}",
        "status": card.status,
        "spending_limit": card.spending_limit,
        "simulated": True,
    }


@router.post("/cards/{card_id}/toggle-freeze")
def toggle_card_freeze(
    card_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = db.get(VirtualCard, card_id)
    if card is None or card.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Virtual card not found.")

    card.status = "frozen" if card.status == "active" else "active"
    log_audit(
        db,
        action=f"card.{card.status}",
        resource_type="virtual_card",
        user_id=current_user.id,
        resource_id=str(card.id),
    )
    db.commit()
    return {"id": str(card.id), "status": card.status}


@router.get("/bills/providers")
def get_bill_providers(_: User = Depends(get_current_user)):
    return BILL_PROVIDERS


@router.post("/bills/pay", status_code=status.HTTP_201_CREATED)
def pay_bill(
    payload: BillPaymentRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = BILL_PROVIDERS.get(payload.category, [])
    if payload.provider not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid bill provider for the selected category.",
        )

    account = _get_primary_account(db, current_user)
    tx = execute_debit(
        db=db,
        user=current_user,
        account=account,
        amount=payload.amount,
        pin=payload.pin,
        category="bill_payment",
        narration=f"{payload.category.title()} bill payment - {payload.provider} ({payload.customer_reference})",
        counterparty_name=payload.provider,
        counterparty_account=payload.customer_reference,
        counterparty_bank="Nigeria Billers (Simulated)",
        idempotency_key=payload.idempotency_key,
        ip_address=get_client_ip(request),
        metadata={"simulated": True, "bill_category": payload.category, "provider": payload.provider},
        audit_action="bill.paid",
        notification_title="Bill Payment Successful",
    )

    token_or_receipt = (
        f"TOKEN-{secrets.randbelow(10**12):012d}"
        if payload.category in {"electricity", "education"}
        else f"BILL-{secrets.token_hex(4).upper()}"
    )

    bill = BillPayment(
        user_id=current_user.id,
        account_id=account.id,
        transaction_id=tx.id,
        category=payload.category,
        provider=payload.provider,
        customer_reference=payload.customer_reference.strip(),
        amount=quantize_ngn(payload.amount),
        token_or_receipt=token_or_receipt,
        status="completed",
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)

    return {
        "id": str(bill.id),
        "reference": tx.reference,
        "category": bill.category,
        "provider": bill.provider,
        "customer_reference": bill.customer_reference,
        "amount": bill.amount,
        "token_or_receipt": bill.token_or_receipt,
        "status": bill.status,
        "created_at": bill.created_at,
        "simulated": True,
    }


@router.get("/bills/history")
def list_bill_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(BillPayment)
        .where(BillPayment.user_id == current_user.id)
        .order_by(desc(BillPayment.created_at))
        .limit(30)
    ).all()
    return [
        {
            "id": str(b.id),
            "category": b.category,
            "provider": b.provider,
            "customer_reference": b.customer_reference,
            "amount": b.amount,
            "token_or_receipt": b.token_or_receipt,
            "status": b.status,
            "created_at": b.created_at,
        }
        for b in rows
    ]
