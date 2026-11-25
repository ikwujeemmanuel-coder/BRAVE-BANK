"""Argon2id hashing for passwords/PINs and keyed HMAC hashing for OTPs/tokens."""

import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.app.config import get_settings

_password_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_pin_hasher = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=1)


def hash_password(plain_password: str) -> str:
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_pin(plain_pin: str) -> str:
    return _pin_hasher.hash(plain_pin)


def verify_pin(plain_pin: str, pin_hash: str) -> bool:
    try:
        return _pin_hasher.verify(pin_hash, plain_pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_otp(phone_number: str, purpose: str, code: str) -> str:
    settings = get_settings()
    payload = f"{phone_number}:{purpose}:{code}".encode("utf-8")
    return hmac.new(settings.secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_otp_hash(phone_number: str, purpose: str, code: str, expected_hash: str) -> bool:
    computed = hash_otp(phone_number, purpose, code)
    return hmac.compare_digest(computed, expected_hash)


def hash_token(raw_token: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
