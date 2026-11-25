"""FastAPI authentication, HttpOnly cookie + CSRF validation, session checks, and rate limiter."""

import hmac
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Deque, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.user import LoginSession, User
from backend.app.security.jwt import decode_jwt_token

bearer_scheme = HTTPBearer(auto_error=False)
ACCESS_COOKIE_NAME = "bb_access_token"
REFRESH_COOKIE_NAME = "bb_refresh_token"
CSRF_COOKIE_NAME = "bb_csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter for auth and OTP endpoints."""

    def __init__(self) -> None:
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, max_calls: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_calls:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please wait and try again.",
                )
            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(prefix: str, max_calls: int, window_seconds: int):
    def _dependency(request: Request) -> None:
        settings = get_settings()
        if settings.app_env == "test":
            return
        client_ip = get_client_ip(request)
        rate_limiter.check(f"{prefix}:{client_ip}", max_calls, window_seconds)

    return _dependency


def get_current_session_and_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> tuple[LoginSession, User]:
    raw_token: Optional[str] = None
    using_cookie = False

    if credentials and credentials.scheme.lower() == "bearer":
        raw_token = credentials.credentials
    else:
        cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
        if cookie_token:
            raw_token = cookie_token
            using_cookie = True

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if using_cookie and request.method.upper() not in SAFE_METHODS:
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME) or ""
        csrf_header = request.headers.get("x-csrf-token") or ""
        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed. Refresh and try again.",
            )

    payload = decode_jwt_token(raw_token, expected_type="access")
    try:
        user_id = uuid.UUID(payload["sub"])
        session_id = uuid.UUID(payload["sid"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token",
        ) from exc

    session = db.get(LoginSession, session_id)
    now = datetime.now(timezone.utc)
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or session.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked. Please sign in again.",
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive or unavailable",
        )

    return session, user


def get_current_user(
    pair: tuple[LoginSession, User] = Depends(get_current_session_and_user),
) -> User:
    return pair[1]
