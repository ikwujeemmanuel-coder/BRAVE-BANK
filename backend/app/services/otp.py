"""Six-digit OTP generation, cooldown enforcement, hashing, and verification."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models.user import OtpRecord
from backend.app.security.hashing import hash_otp, verify_otp_hash
from backend.app.services.email import send_otp_email
from backend.app.services.sms import get_sms_provider


def mask_email(email: str) -> str:
    cleaned = email.strip().lower()
    if "@" not in cleaned:
        return cleaned
    local, domain = cleaned.split("@", 1)
    if len(local) <= 1:
        masked_local = f"{local}***"
    elif len(local) == 2:
        masked_local = f"{local[0]}***{local[1]}"
    else:
        masked_local = f"{local[:2]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def issue_email_otp(
    db: Session,
    target_email: str,
    purpose: str,
    phone_number: str = "",
    user_id: Optional[uuid.UUID] = None,
) -> tuple[OtpRecord, Optional[str]]:
    """Create and send a hashed 6-digit OTP via Email ONLY, enforcing resend cooldown."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    normalized_email = target_email.strip().lower()

    latest = db.scalar(
        select(OtpRecord)
        .where(
            OtpRecord.target_email == normalized_email,
            OtpRecord.purpose == purpose,
            OtpRecord.invalidated_at.is_(None),
            OtpRecord.verified_at.is_(None),
        )
        .order_by(desc(OtpRecord.created_at))
        .limit(1)
    )

    if latest is not None:
        elapsed = (now - latest.last_sent_at).total_seconds()
        if elapsed < settings.otp_resend_cooldown_seconds:
            remaining = int(settings.otp_resend_cooldown_seconds - elapsed) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {remaining} seconds before requesting a new verification code.",
            )

    db.execute(
        update(OtpRecord)
        .where(
            OtpRecord.target_email == normalized_email,
            OtpRecord.purpose == purpose,
            OtpRecord.invalidated_at.is_(None),
            OtpRecord.verified_at.is_(None),
        )
        .values(invalidated_at=now)
    )

    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    record = OtpRecord(
        user_id=user_id,
        phone_number=phone_number[:20],
        target_email=normalized_email,
        purpose=purpose,
        code_hash=hash_otp(normalized_email, purpose, raw_code),
        attempts=0,
        max_attempts=settings.otp_max_attempts,
        expires_at=now + timedelta(seconds=settings.otp_expire_seconds),
        last_sent_at=now,
    )
    db.add(record)
    db.flush()

    try:
        send_otp_email(
            recipient=normalized_email,
            code=raw_code,
            purpose=purpose,
            expire_seconds=settings.otp_expire_seconds,
        )
    except Exception:
        db.rollback()
        raise

    return record, None


def verify_email_otp_code(
    db: Session,
    target_email: str,
    purpose: str,
    code: str,
) -> OtpRecord:
    """Verify a 6-digit Email OTP against expiry, attempt limit, and HMAC hash."""
    now = datetime.now(timezone.utc)
    normalized_email = target_email.strip().lower()
    record = db.scalar(
        select(OtpRecord)
        .where(
            OtpRecord.target_email == normalized_email,
            OtpRecord.purpose == purpose,
            OtpRecord.invalidated_at.is_(None),
            OtpRecord.verified_at.is_(None),
        )
        .order_by(desc(OtpRecord.created_at))
        .limit(1)
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active email verification code found. Please request a new code.",
        )

    if record.expires_at <= now:
        record.invalidated_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new code.",
        )

    if record.attempts >= record.max_attempts:
        record.invalidated_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum OTP verification attempts exceeded. Please request a new code.",
        )

    if not verify_otp_hash(normalized_email, purpose, code.strip(), record.code_hash):
        record.attempts += 1
        if record.attempts >= record.max_attempts:
            record.invalidated_at = now
        db.commit()
        remaining = max(0, record.max_attempts - record.attempts)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid verification code. {remaining} attempt(s) remaining.",
        )

    record.verified_at = now
    db.flush()
    return record


def issue_otp(
    db: Session,
    phone_number: str,
    purpose: str,
    user_id: Optional[uuid.UUID] = None,
    target_email: Optional[str] = None,
) -> tuple[OtpRecord, Optional[str]]:
    """Create and send a hashed 6-digit SMS OTP, enforcing resend cooldown."""
    settings = get_settings()
    now = datetime.now(timezone.utc)

    latest = db.scalar(
        select(OtpRecord)
        .where(
            OtpRecord.phone_number == phone_number,
            OtpRecord.purpose == purpose,
            OtpRecord.invalidated_at.is_(None),
            OtpRecord.verified_at.is_(None),
        )
        .order_by(desc(OtpRecord.created_at))
        .limit(1)
    )

    if latest is not None:
        elapsed = (now - latest.last_sent_at).total_seconds()
        if elapsed < settings.otp_resend_cooldown_seconds:
            remaining = int(settings.otp_resend_cooldown_seconds - elapsed) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {remaining} seconds before requesting a new OTP.",
            )

    # Invalidate all prior pending OTPs for this phone and purpose
    db.execute(
        update(OtpRecord)
        .where(
            OtpRecord.phone_number == phone_number,
            OtpRecord.purpose == purpose,
            OtpRecord.invalidated_at.is_(None),
            OtpRecord.verified_at.is_(None),
        )
        .values(invalidated_at=now)
    )

    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    record = OtpRecord(
        user_id=user_id,
        phone_number=phone_number,
        target_email=target_email,
        purpose=purpose,
        code_hash=hash_otp(phone_number, purpose, raw_code),
        attempts=0,
        max_attempts=settings.otp_max_attempts,
        expires_at=now + timedelta(seconds=settings.otp_expire_seconds),
        last_sent_at=now,
    )
    db.add(record)
    db.flush()

    sms = get_sms_provider()
    try:
        sms.send_sms(
            phone_number,
            f"Your BRAVEBANK verification code is {raw_code}. It expires in 5 minutes. Do not share it.",
        )
    except Exception:
        db.rollback()
        raise

    return record, None


def verify_otp_code(
    db: Session,
    phone_number: str,
    purpose: str,
    code: str,
) -> OtpRecord:
    """Verify a 6-digit SMS OTP against expiry, attempt limit, and HMAC hash."""
    now = datetime.now(timezone.utc)
    record = db.scalar(
        select(OtpRecord)
        .where(
            OtpRecord.phone_number == phone_number,
            OtpRecord.purpose == purpose,
            OtpRecord.invalidated_at.is_(None),
            OtpRecord.verified_at.is_(None),
        )
        .order_by(desc(OtpRecord.created_at))
        .limit(1)
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active verification code found. Please request a new OTP.",
        )

    if record.expires_at <= now:
        record.invalidated_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new OTP.",
        )

    if record.attempts >= record.max_attempts:
        record.invalidated_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum OTP verification attempts exceeded. Please request a new OTP.",
        )

    if not verify_otp_hash(phone_number, purpose, code.strip(), record.code_hash):
        record.attempts += 1
        if record.attempts >= record.max_attempts:
            record.invalidated_at = now
        db.commit()
        remaining = max(0, record.max_attempts - record.attempts)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid verification code. {remaining} attempt(s) remaining.",
        )

    record.verified_at = now
    db.flush()
    return record
