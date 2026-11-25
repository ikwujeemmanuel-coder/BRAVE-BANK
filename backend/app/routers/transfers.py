"""Internal transfers, simulated Nigerian external transfers, and beneficiary management."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.banking import Account, Bank, Beneficiary
from backend.app.models.user import User
from backend.app.schemas.banking import (
    BeneficiaryCreateRequest,
    ExternalAccountResolveRequest,
    ExternalTransferRequest,
    InternalTransferRequest,
    TransactionOut,
)
from backend.app.security.dependencies import get_client_ip, get_current_user
from backend.app.services.accounts import ensure_default_banks, resolve_mock_external_account
from backend.app.services.ledger import execute_internal_transfer
from backend.app.services.phone import normalize_nigerian_phone

router = APIRouter(prefix="/api/transfers", tags=["transfers"])

EXTERNAL_TRANSFER_UNAVAILABLE_MESSAGE = (
    "External bank transfers are currently unavailable. "
    "BraveBank cannot transfer real funds to other banks in this demo environment."
)


def _get_primary_account(db: Session, user: User) -> Account:
    account = db.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at).limit(1)
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    return account


@router.get("/lookup-internal")
def lookup_internal_recipient(
    query: str = Query(..., min_length=10, max_length=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cleaned = query.strip()
    recipient_account = None

    if cleaned.isdigit() and len(cleaned) == 10:
        recipient_account = db.scalar(
            select(Account).where(Account.account_number == cleaned)
        )

    if recipient_account is None:
        try:
            normalized_phone = normalize_nigerian_phone(cleaned)
        except ValueError as exc:
            if cleaned.isdigit() and len(cleaned) == 10:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No BraveBank recipient matched that phone or account number.",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Enter a valid 10-digit BraveBank account number or Nigerian phone number.",
            ) from exc

        recipient_user = db.scalar(select(User).where(User.phone_number == normalized_phone))
        if recipient_user is not None:
            recipient_account = db.scalar(
                select(Account)
                .where(Account.user_id == recipient_user.id)
                .order_by(Account.created_at)
                .limit(1)
            )

    if recipient_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No BraveBank recipient matched that phone or account number.",
        )

    if recipient_account.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is your own BraveBank account.",
        )

    recipient_user = db.get(User, recipient_account.user_id)
    if (
        recipient_account.status != "active"
        or recipient_user is None
        or not recipient_user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient account is inactive or unavailable.",
        )

    return {
        "account_number": recipient_account.account_number,
        "account_name": recipient_account.account_name,
        "bank_name": "BRAVEBANK",
        "status": recipient_account.status,
        "is_internal": True,
    }


@router.post("/internal", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def internal_transfer(
    payload: InternalTransferRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sender_account = _get_primary_account(db, current_user)
    recipient_account = db.scalar(
        select(Account).where(Account.account_number == payload.recipient_account_number)
    )
    if recipient_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient BraveBank account number not found.",
        )

    tx = execute_internal_transfer(
        db=db,
        sender=current_user,
        sender_account=sender_account,
        recipient_account=recipient_account,
        amount=payload.amount,
        pin=payload.pin,
        narration=payload.narration.strip() or "BraveBank Transfer",
        idempotency_key=payload.idempotency_key,
        ip_address=get_client_ip(request),
    )
    return TransactionOut.model_validate(tx, from_attributes=True)


@router.get("/banks")
def list_nigerian_banks(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_default_banks(db)
    banks = db.scalars(
        select(Bank).where(Bank.is_active.is_(True)).order_by(Bank.name)
    ).all()
    return [
        {"id": str(b.id), "code": b.code, "name": b.name, "nip_code": b.nip_code}
        for b in banks
    ]


@router.post("/external/resolve")
def resolve_external_account(
    payload: ExternalAccountResolveRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_default_banks(db)
    bank = db.scalar(select(Bank).where(Bank.code == payload.bank_code, Bank.is_active.is_(True)))
    if bank is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected bank not found.")

    resolved_name = resolve_mock_external_account(bank.code, payload.account_number)
    return {
        "bank_code": bank.code,
        "bank_name": bank.name,
        "account_number": payload.account_number,
        "account_name": resolved_name,
        "simulated": True,
        "external_transfers_available": False,
    }


@router.post("/external", response_model=TransactionOut)
def external_transfer(
    payload: ExternalTransferRequest,
    _: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=EXTERNAL_TRANSFER_UNAVAILABLE_MESSAGE,
    )


@router.get("/beneficiaries")
def list_beneficiaries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Beneficiary)
        .where(Beneficiary.user_id == current_user.id)
        .order_by(desc(Beneficiary.created_at))
    ).all()
    return [
        {
            "id": str(b.id),
            "nickname": b.nickname,
            "account_number": b.account_number,
            "account_name": b.account_name,
            "bank_code": b.bank_code,
            "bank_name": b.bank_name,
            "is_internal": b.is_internal,
            "created_at": b.created_at,
        }
        for b in rows
    ]


@router.post("/beneficiaries", status_code=status.HTTP_201_CREATED)
def add_beneficiary(
    payload: BeneficiaryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(Beneficiary).where(
            Beneficiary.user_id == current_user.id,
            Beneficiary.account_number == payload.account_number,
            Beneficiary.bank_code == payload.bank_code,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This beneficiary is already saved.",
        )

    item = Beneficiary(
        user_id=current_user.id,
        nickname=payload.nickname.strip(),
        account_number=payload.account_number,
        account_name=payload.account_name.strip().upper(),
        bank_code=payload.bank_code,
        bank_name=payload.bank_name.strip(),
        is_internal=payload.is_internal,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": str(item.id),
        "nickname": item.nickname,
        "account_number": item.account_number,
        "account_name": item.account_name,
        "bank_code": item.bank_code,
        "bank_name": item.bank_name,
        "is_internal": item.is_internal,
        "created_at": item.created_at,
    }


@router.delete("/beneficiaries/{beneficiary_id}")
def delete_beneficiary(
    beneficiary_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(Beneficiary, beneficiary_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found.")
    db.delete(item)
    db.commit()
    return {"message": "Beneficiary deleted."}
