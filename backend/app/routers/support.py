"""In-app notifications, customer support tickets, and FAQs."""

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.support import Notification, SupportTicket
from backend.app.models.user import User
from backend.app.schemas.banking import SupportTicketCreateRequest
from backend.app.security.dependencies import get_current_user
from backend.app.services.audit import create_notification

router = APIRouter(prefix="/api", tags=["notifications-and-support"])

FAQS = [
    {
        "question": "Is BRAVEBANK a licensed commercial bank?",
        "answer": "No. BRAVEBANK is a simulated Nigerian digital banking prototype built for demonstration and engineering evaluation. No real money moves.",
    },
    {
        "question": "Why does BRAVEBANK use my Nigerian phone number as primary ID?",
        "answer": "Phone-first onboarding reflects mobile-first Nigerian fintech workflows. Email linking is optional and can be completed anytime in Settings.",
    },
    {
        "question": "How do I set or reset my 4-digit transaction PIN?",
        "answer": "Open Settings -> Security & PIN to set your 4-digit transaction PIN, update an existing PIN, or reset via 6-digit OTP.",
    },
    {
        "question": "Are internal transfers instant and atomic?",
        "answer": "Yes. Internal transfers lock both sender and recipient rows in PostgreSQL and record paired debit/credit ledger entries atomically.",
    },
]


@router.get("/notifications")
def list_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(desc(Notification.created_at))
        .limit(40)
    ).all()
    return [
        {
            "id": str(n.id),
            "category": n.category,
            "title": n.title,
            "message": n.message,
            "is_read": n.is_read,
            "created_at": n.created_at,
        }
        for n in rows
    ]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    item.is_read = True
    db.commit()
    return {"id": str(item.id), "is_read": True}


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"message": "All notifications marked as read."}


@router.get("/support/faqs")
def get_faqs():
    return FAQS


@router.get("/support/tickets")
def list_tickets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(SupportTicket)
        .where(SupportTicket.user_id == current_user.id)
        .order_by(desc(SupportTicket.created_at))
    ).all()
    return [
        {
            "id": str(t.id),
            "reference": t.reference,
            "category": t.category,
            "subject": t.subject,
            "message": t.message,
            "status": t.status,
            "admin_response": t.admin_response,
            "created_at": t.created_at,
        }
        for t in rows
    ]


@router.post("/support/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: SupportTicketCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ref = f"SUP-{secrets.token_hex(4).upper()}"
    ticket = SupportTicket(
        user_id=current_user.id,
        reference=ref,
        category=payload.category.strip(),
        subject=payload.subject.strip(),
        message=payload.message.strip(),
        status="open",
        admin_response="Thank you for contacting BRAVEBANK Support. A specialist is reviewing your request.",
    )
    db.add(ticket)
    create_notification(
        db,
        current_user.id,
        "account",
        "Support Ticket Logged",
        f"Support ticket {ref} ({ticket.subject}) has been opened.",
    )
    db.commit()
    db.refresh(ticket)
    return {
        "id": str(ticket.id),
        "reference": ticket.reference,
        "category": ticket.category,
        "subject": ticket.subject,
        "message": ticket.message,
        "status": ticket.status,
        "admin_response": ticket.admin_response,
        "created_at": ticket.created_at,
    }
