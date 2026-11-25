"""Authentication, registration, OTP verification, password, PIN, cookie sessions, and logout."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.banking import Account
from backend.app.models.services import SavingsAccount
from backend.app.models.user import Credential, LoginSession, TransactionPin, User
from backend.app.schemas.auth import (
    AuthTokenResponse,
    ChangePasswordRequest,
    ChangePinRequest,
    LinkEmailRequest,
    LoginRequest,
    OtpSendRequest,
    OtpVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshTokenRequest,
    RegisterEmailVerifyRequest,
    RegisterSetPinRequest,
    RegisterStartRequest,
    ResendEmailOtpRequest,
    ResetPinConfirmRequest,
    SessionOut,
    SetPinRequest,
    UserProfileResponse,
    VerifyEmailRequest,
)
from backend.app.security.dependencies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    enforce_rate_limit,
    get_client_ip,
    get_current_session_and_user,
    get_current_user,
)
from backend.app.security.hashing import (
    hash_password,
    hash_pin,
    hash_token,
    verify_password,
    verify_pin,
)
from backend.app.security.jwt import (
    create_access_token,
    create_refresh_token,
    create_registration_pin_token,
    decode_jwt_token,
    decode_registration_pin_token,
)
from backend.app.services.accounts import (
    generate_unique_account_number,
    generate_unique_savings_number,
)
from backend.app.services.audit import create_notification, log_audit
from backend.app.services.otp import (
    issue_email_otp,
    issue_otp,
    mask_email,
    verify_email_otp_code,
    verify_otp_code,
)
from backend.app.services.phone import normalize_nigerian_phone

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _build_profile(db: Session, user: User) -> UserProfileResponse:
    primary_account = db.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at).limit(1)
    )
    has_pin = db.scalar(select(TransactionPin.id).where(TransactionPin.user_id == user.id)) is not None
    return UserProfileResponse(
        id=user.id,
        first_name=user.first_name,
        surname=user.surname,
        phone_number=user.phone_number,
        email=user.email,
        phone_verified=user.phone_verified,
        email_verified=user.email_verified,
        has_transaction_pin=has_pin,
        account_number=primary_account.account_number if primary_account else None,
        created_at=user.created_at,
    )


def _is_https_request(request: Request) -> bool:
    settings = get_settings()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return (
        (not settings.is_development)
        or (request.url.scheme == "https")
        or (forwarded_proto == "https")
    )


def _append_partitioned_to_set_cookie_headers(response: Response) -> None:
    cookies = response.headers.getlist("set-cookie")
    if not cookies:
        return
    del response.headers["set-cookie"]
    for header_val in cookies:
        if "partitioned" not in header_val.lower():
            response.headers.append("set-cookie", f"{header_val}; Partitioned")
        else:
            response.headers.append("set-cookie", header_val)


def _set_session_cookies(
    response: Response,
    request: Request,
    access_token: str,
    refresh_token: str,
) -> None:
    settings = get_settings()
    is_https = _is_https_request(request)
    samesite_mode = "none" if is_https else "lax"
    csrf_token = secrets.token_urlsafe(32)

    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=is_https,
        samesite=samesite_mode,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_https,
        samesite=samesite_mode,
        max_age=settings.refresh_token_expire_days * 86400,
        path="/api/auth",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=is_https,
        samesite=samesite_mode,
        max_age=settings.refresh_token_expire_days * 86400,
        path="/",
    )
    if is_https:
        _append_partitioned_to_set_cookie_headers(response)


def _clear_session_cookies(response: Response, request: Request) -> None:
    is_https = _is_https_request(request)
    samesite_mode = "none" if is_https else "lax"
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/", secure=is_https, samesite=samesite_mode)
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth", secure=is_https, samesite=samesite_mode)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=is_https, samesite=samesite_mode)
    if is_https:
        _append_partitioned_to_set_cookie_headers(response)


def _issue_session_tokens(
    db: Session, user: User, request: Request, response: Response
) -> AuthTokenResponse:
    settings = get_settings()
    session_id = uuid.uuid4()
    refresh_token, expires_at = create_refresh_token(user.id, session_id)
    session = LoginSession(
        id=session_id,
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_token),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        ip_address=get_client_ip(request),
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()

    access_token = create_access_token(user.id, session_id)
    _set_session_cookies(response, request, access_token, refresh_token)
    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=_build_profile(db, user),
    )


def _is_registration_complete(db: Session, user: User) -> bool:
    has_pin = db.scalar(select(TransactionPin.id).where(TransactionPin.user_id == user.id)) is not None
    has_account = db.scalar(select(Account.id).where(Account.user_id == user.id)) is not None
    return has_pin and has_account and (user.email_verified or user.phone_verified)


@router.post(
    "/register/start",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_rate_limit("register_start", 12, 60))],
)
def register_start(payload: RegisterStartRequest, request: Request, db: Session = Depends(get_db)):
    """Step 1: Validate customer details & dispatch a 6-digit OTP strictly via Email."""
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    email_value = str(payload.email).strip().lower()
    existing_phone = db.scalar(select(User).where(User.phone_number == phone))
    existing_email = db.scalar(select(User).where(User.email == email_value))

    if existing_phone is not None and _is_registration_complete(db, existing_phone):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this Nigerian phone number already exists.",
        )

    if existing_email is not None and _is_registration_complete(db, existing_email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address is already registered to a BraveBank account.",
        )

    if existing_phone is not None and existing_email is not None and existing_phone.id != existing_email.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email address belongs to another pending registration.",
        )

    if existing_email is not None and existing_phone is None:
        # Pending user switched phone number before completing signup; update safely without duplicating
        user = existing_email
        user.phone_number = phone
    elif existing_phone is not None:
        user = existing_phone
    else:
        user = User(
            first_name=payload.first_name,
            surname=payload.surname,
            phone_number=phone,
            email=email_value,
            phone_verified=False,
            email_verified=False,
        )
        db.add(user)
        db.flush()

    if user.email != email_value:
        user.email = email_value
        user.email_verified = False

    user.first_name = payload.first_name
    user.surname = payload.surname

    if user.credential is None:
        db.add(Credential(user_id=user.id, password_hash=hash_password(payload.password)))
    else:
        user.credential.password_hash = hash_password(payload.password)
        user.credential.failed_login_attempts = 0
        user.credential.locked_until = None

    _, dev_otp = issue_email_otp(
        db,
        target_email=email_value,
        purpose="email_registration",
        phone_number=phone,
        user_id=user.id,
    )
    log_audit(
        db,
        action="user.registration_started",
        resource_type="user",
        user_id=user.id,
        resource_id=str(user.id),
        ip_address=get_client_ip(request),
        details={"email": email_value},
    )
    db.commit()

    settings = get_settings()
    response_body = {
        "step": "verify_email",
        "message": "Verification code sent to your email address.",
        "email": email_value,
        "masked_email": mask_email(email_value),
        "phone_number": phone,
        "otp_expires_in_seconds": settings.otp_expire_seconds,
        "resend_cooldown_seconds": settings.otp_resend_cooldown_seconds,
    }
    if dev_otp is not None:
        response_body["dev_otp"] = dev_otp
    return response_body


@router.post(
    "/register/resend-email-otp",
    dependencies=[Depends(enforce_rate_limit("register_resend_email_otp", 6, 60))],
)
def resend_registration_email_otp(payload: ResendEmailOtpRequest, db: Session = Depends(get_db)):
    email_value = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email_value))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending registration found for this email address.",
        )
    if _is_registration_complete(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account is already verified and active. Please login.",
        )

    _, dev_otp = issue_email_otp(
        db,
        target_email=email_value,
        purpose="email_registration",
        phone_number=user.phone_number,
        user_id=user.id,
    )
    db.commit()

    settings = get_settings()
    res = {
        "message": "A new 6-digit verification code has been sent to your email.",
        "email": email_value,
        "masked_email": mask_email(email_value),
        "otp_expires_in_seconds": settings.otp_expire_seconds,
        "resend_cooldown_seconds": settings.otp_resend_cooldown_seconds,
    }
    if dev_otp is not None:
        res["dev_otp"] = dev_otp
    return res


@router.post(
    "/register/verify-email",
    dependencies=[Depends(enforce_rate_limit("register_verify_email", 12, 60))],
)
def verify_registration_email(
    payload: RegisterEmailVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Step 2: Verify the 6-digit Email OTP. Marks ONLY email_verified=True (never phone_verified)."""
    email_value = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email_value))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending registration found for this email address.",
        )

    verify_email_otp_code(db, email_value, "email_registration", payload.code)

    # CRITICAL INVARIANT: Email verification marks ONLY email_verified = True.
    user.email_verified = True
    reg_token = create_registration_pin_token(user.id, email_value)
    log_audit(
        db,
        action="user.email_verified",
        resource_type="user",
        user_id=user.id,
        resource_id=str(user.id),
        ip_address=get_client_ip(request),
        details={"email": email_value},
    )
    db.commit()

    return {
        "step": "set_pin",
        "message": "Email verified successfully. Create your 4-digit transaction PIN.",
        "email": email_value,
        "masked_email": mask_email(email_value),
        "email_verified": user.email_verified,
        "phone_verified": user.phone_verified,
        "registration_token": reg_token,
    }


@router.post(
    "/register/set-pin",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthTokenResponse,
    dependencies=[Depends(enforce_rate_limit("register_set_pin", 10, 60))],
)
def complete_registration_set_pin(
    payload: RegisterSetPinRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Step 3 & 4: Persist Argon2id 4-digit PIN, create BraveBank NGN account, and issue session."""
    claims = decode_registration_pin_token(payload.registration_token)
    user_id = uuid.UUID(claims["sub"])
    token_email = str(claims["email"]).strip().lower()

    user = db.get(User, user_id)
    if user is None or (user.email or "").lower() != token_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid registration setup session.",
        )
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email must be verified before setting a transaction PIN.",
        )

    if _is_registration_complete(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration is already complete. Please login.",
        )

    existing_pin = db.scalar(select(TransactionPin).where(TransactionPin.user_id == user.id))
    if existing_pin is None:
        db.add(TransactionPin(user_id=user.id, pin_hash=hash_pin(payload.pin)))

    existing_account = db.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at).limit(1)
    )
    if existing_account is None:
        account_number = generate_unique_account_number(db)
        db.add(
            Account(
                user_id=user.id,
                account_number=account_number,
                account_name=f"{user.first_name} {user.surname}".upper(),
                currency="NGN",
                available_balance=Decimal("0.00"),
                ledger_balance=Decimal("0.00"),
                status="active",
            )
        )
    else:
        account_number = existing_account.account_number

    existing_savings = db.scalar(select(SavingsAccount).where(SavingsAccount.user_id == user.id))
    if existing_savings is None:
        db.add(
            SavingsAccount(
                user_id=user.id,
                account_number=generate_unique_savings_number(db),
                balance=Decimal("0.00"),
                annual_interest_rate=Decimal("12.50"),
                accrued_interest=Decimal("0.00"),
            )
        )

    create_notification(
        db,
        user.id,
        "account",
        "Welcome to BRAVEBANK",
        f"Your BraveBank NGN account {account_number} is active and ready. Banking Without Limits!",
    )
    tokens = _issue_session_tokens(db, user, request, response)
    log_audit(
        db,
        action="user.registered",
        resource_type="user",
        user_id=user.id,
        resource_id=str(user.id),
        ip_address=get_client_ip(request),
        details={"account_number": account_number, "email_verified": user.email_verified},
    )
    db.commit()
    return tokens


@router.post(
    "/register/resume",
    dependencies=[Depends(enforce_rate_limit("register_resume", 10, 60))],
)
def resume_pending_registration(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate an incomplete registrant's password to resume Email OTP or PIN setup cleanly."""
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    user = db.scalar(select(User).where(User.phone_number == phone))
    if user is None or user.credential is None or not verify_password(
        payload.password, user.credential.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone number or password.",
        )

    if _is_registration_complete(db, user):
        return {"step": "login", "message": "Account setup is already complete."}

    if not user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email address on file for this pending registration. Please start registration again.",
        )

    if not user.email_verified:
        dev_otp = None
        try:
            _, dev_otp = issue_email_otp(
                db,
                target_email=user.email,
                purpose="email_registration",
                phone_number=user.phone_number,
                user_id=user.id,
            )
            db.commit()
        except HTTPException as exc:
            if exc.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
                raise
        settings = get_settings()
        res = {
            "step": "verify_email",
            "email": user.email,
            "masked_email": mask_email(user.email),
            "phone_number": user.phone_number,
            "otp_expires_in_seconds": settings.otp_expire_seconds,
            "resend_cooldown_seconds": settings.otp_resend_cooldown_seconds,
        }
        if dev_otp is not None:
            res["dev_otp"] = dev_otp
        return res

    reg_token = create_registration_pin_token(user.id, user.email)
    return {
        "step": "set_pin",
        "email": user.email,
        "masked_email": mask_email(user.email),
        "registration_token": reg_token,
    }


@router.post(
    "/otp/send",
    dependencies=[Depends(enforce_rate_limit("otp_send", 5, 60))],
)
def send_otp(payload: OtpSendRequest, db: Session = Depends(get_db)):
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    user = db.scalar(select(User).where(User.phone_number == phone))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    _, dev_otp = issue_otp(db, phone, payload.purpose, user_id=user.id)
    db.commit()

    response = {
        "message": "Verification code dispatched.",
        "phone_number": phone,
        "otp_expires_in_seconds": get_settings().otp_expire_seconds,
    }
    if dev_otp is not None:
        response["dev_otp"] = dev_otp
    return response


@router.post(
    "/otp/verify",
    response_model=AuthTokenResponse,
    dependencies=[Depends(enforce_rate_limit("otp_verify", 10, 60))],
)
def verify_phone_otp(
    payload: OtpVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    verify_otp_code(db, phone, payload.purpose, payload.code)

    user = db.scalar(select(User).where(User.phone_number == phone))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    user.phone_verified = True
    tokens = _issue_session_tokens(db, user, request, response)
    log_audit(
        db,
        action="user.phone_verified",
        resource_type="user",
        user_id=user.id,
        resource_id=str(user.id),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return tokens


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    dependencies=[Depends(enforce_rate_limit("login", 25, 60))],
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    user = db.scalar(select(User).where(User.phone_number == phone))
    if user is None or user.credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone number or password.",
        )

    now = datetime.now(timezone.utc)
    if user.credential.locked_until and user.credential.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account login is temporarily locked due to repeated invalid attempts.",
        )

    if not verify_password(payload.password, user.credential.password_hash):
        user.credential.failed_login_attempts += 1
        if user.credential.failed_login_attempts >= 5:
            user.credential.locked_until = now + timedelta(minutes=15)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone number or password.",
        )

    if not (user.email_verified or user.phone_verified):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification pending. Complete email OTP verification first.",
        )

    if user.transaction_pin is None or not user.accounts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration setup incomplete. Set your 4-digit transaction PIN first.",
        )

    user.credential.failed_login_attempts = 0
    user.credential.locked_until = None
    tokens = _issue_session_tokens(db, user, request, response)
    log_audit(
        db,
        action="user.login",
        resource_type="session",
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return tokens


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh_access_token(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = Body(default=None),
    db: Session = Depends(get_db),
):
    raw_refresh = (payload.refresh_token if payload and payload.refresh_token else None) or request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing.",
        )

    decoded = decode_jwt_token(raw_refresh, expected_type="refresh")
    session_id = uuid.UUID(decoded["sid"])
    user_id = uuid.UUID(decoded["sub"])

    session = db.get(LoginSession, session_id)
    now = datetime.now(timezone.utc)
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or session.expires_at <= now
        or session.refresh_token_hash != hash_token(raw_refresh)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or revoked.",
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable.")

    session.revoked_at = now
    tokens = _issue_session_tokens(db, user, request, response)
    db.commit()
    return tokens


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    pair: tuple[LoginSession, User] = Depends(get_current_session_and_user),
    db: Session = Depends(get_db),
):
    session, user = pair
    session.revoked_at = datetime.now(timezone.utc)
    log_audit(db, action="user.logout", resource_type="session", user_id=user.id, resource_id=str(session.id))
    db.commit()
    _clear_session_cookies(response, request)
    return {"message": "Signed out successfully."}


@router.get("/me", response_model=UserProfileResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _build_profile(db, current_user)


@router.post(
    "/password/reset-request",
    dependencies=[Depends(enforce_rate_limit("pw_reset", 5, 60))],
)
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    user = db.scalar(select(User).where(User.phone_number == phone))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    _, dev_otp = issue_otp(db, phone, "password_reset", user_id=user.id)
    db.commit()

    res = {"message": "Password reset OTP sent."}
    if dev_otp is not None:
        res["dev_otp"] = dev_otp
    return res


@router.post("/password/reset-confirm")
def confirm_password_reset(payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)):
    try:
        phone = normalize_nigerian_phone(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    verify_otp_code(db, phone, "password_reset", payload.otp_code)
    user = db.scalar(select(User).where(User.phone_number == phone))
    if user is None or user.credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    now = datetime.now(timezone.utc)
    user.credential.password_hash = hash_password(payload.new_password)
    user.credential.failed_login_attempts = 0
    user.credential.locked_until = None
    db.execute(
        update(LoginSession)
        .where(LoginSession.user_id == user.id, LoginSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    log_audit(db, action="user.password_reset", resource_type="user", user_id=user.id)
    db.commit()
    return {"message": "Password reset successfully. Please sign in with your new password."}


@router.post("/password/change")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.credential is None or not verify_password(
        payload.current_password, current_user.credential.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    current_user.credential.password_hash = hash_password(payload.new_password)
    create_notification(
        db,
        current_user.id,
        "security",
        "Password Changed",
        "Your BraveBank login password was updated.",
    )
    log_audit(db, action="user.password_changed", resource_type="user", user_id=current_user.id)
    db.commit()
    return {"message": "Password updated successfully."}


@router.post("/pin/set")
def set_transaction_pin(
    payload: SetPinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(TransactionPin).where(TransactionPin.user_id == current_user.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transaction PIN is already configured. Use change PIN instead.",
        )

    pin_row = TransactionPin(user_id=current_user.id, pin_hash=hash_pin(payload.pin))
    db.add(pin_row)
    create_notification(
        db,
        current_user.id,
        "security",
        "Transaction PIN Set",
        "Your 4-digit transaction PIN is now active.",
    )
    log_audit(db, action="user.pin_set", resource_type="transaction_pin", user_id=current_user.id)
    db.commit()
    return {"message": "4-digit transaction PIN set successfully."}


@router.post("/pin/change")
def change_transaction_pin(
    payload: ChangePinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pin_row = db.scalar(select(TransactionPin).where(TransactionPin.user_id == current_user.id))
    if pin_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transaction PIN set yet.",
        )

    if not verify_pin(payload.current_pin, pin_row.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current transaction PIN is incorrect.",
        )

    pin_row.pin_hash = hash_pin(payload.new_pin)
    pin_row.failed_attempts = 0
    pin_row.locked_until = None
    create_notification(
        db,
        current_user.id,
        "security",
        "Transaction PIN Updated",
        "Your 4-digit transaction PIN was updated.",
    )
    log_audit(db, action="user.pin_changed", resource_type="transaction_pin", user_id=current_user.id)
    db.commit()
    return {"message": "4-digit transaction PIN updated successfully."}


@router.post(
    "/pin/reset-request",
    dependencies=[Depends(enforce_rate_limit("pin_reset", 5, 60))],
)
def request_pin_reset(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _, dev_otp = issue_otp(db, current_user.phone_number, "pin_reset", user_id=current_user.id)
    db.commit()
    res = {"message": "PIN reset verification code sent to your registered phone."}
    if dev_otp is not None:
        res["dev_otp"] = dev_otp
    return res


@router.post("/pin/reset-confirm")
def confirm_pin_reset(
    payload: ResetPinConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_otp_code(db, current_user.phone_number, "pin_reset", payload.otp_code)
    pin_row = db.scalar(select(TransactionPin).where(TransactionPin.user_id == current_user.id))
    if pin_row is None:
        pin_row = TransactionPin(user_id=current_user.id, pin_hash=hash_pin(payload.new_pin))
        db.add(pin_row)
    else:
        pin_row.pin_hash = hash_pin(payload.new_pin)
        pin_row.failed_attempts = 0
        pin_row.locked_until = None

    create_notification(
        db,
        current_user.id,
        "security",
        "Transaction PIN Reset",
        "Your 4-digit transaction PIN has been reset via OTP verification.",
    )
    log_audit(db, action="user.pin_reset", resource_type="transaction_pin", user_id=current_user.id)
    db.commit()
    return {"message": "4-digit transaction PIN reset successfully."}


@router.post("/email/link")
def link_email(
    payload: LinkEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email_norm = str(payload.email).strip().lower()
    other = db.scalar(select(User).where(User.email == email_norm, User.id != current_user.id))
    if other is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email address is already linked to another customer.",
        )

    current_user.email = email_norm
    current_user.email_verified = False
    _, dev_otp = issue_email_otp(
        db,
        target_email=email_norm,
        purpose="email_verification",
        phone_number=current_user.phone_number,
        user_id=current_user.id,
    )
    db.commit()
    res = {"message": "Verification code sent to your email address.", "email": email_norm}
    if dev_otp is not None:
        res["dev_otp"] = dev_otp
    return res


@router.post("/email/verify")
def verify_linked_email(
    payload: VerifyEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No email linked.")
    verify_email_otp_code(db, current_user.email, "email_verification", payload.otp_code)
    current_user.email_verified = True
    create_notification(
        db,
        current_user.id,
        "account",
        "Email Verified",
        f"Your email address {current_user.email} has been verified.",
    )
    db.commit()
    return {"message": "Email verified successfully.", "email": current_user.email}


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    pair: tuple[LoginSession, User] = Depends(get_current_session_and_user),
    db: Session = Depends(get_db),
):
    current_session, user = pair
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(LoginSession)
        .where(
            LoginSession.user_id == user.id,
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > now,
        )
        .order_by(desc(LoginSession.created_at))
    ).all()

    return [
        SessionOut(
            id=row.id,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            created_at=row.created_at,
            expires_at=row.expires_at,
            is_current=row.id == current_session.id,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = db.get(LoginSession, session_id)
    if target is None or target.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    target.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Session revoked."}
