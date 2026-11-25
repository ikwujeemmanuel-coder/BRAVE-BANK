"""Pydantic schemas for registration, OTP, authentication, PIN, and sessions."""

import re
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

SYMBOL_PATTERN = re.compile(r"[^A-Za-z0-9\s]")


def validate_password_strength(password: str) -> str:
    if len(password) < 7:
        raise ValueError("Password must be at least 7 characters long.")
    if not SYMBOL_PATTERN.search(password):
        raise ValueError("Password must contain at least one symbol (e.g. !@#$%^&*).")
    return password


class RegisterStartRequest(BaseModel):
    first_name: str = Field(min_length=2, max_length=80)
    surname: str = Field(min_length=2, max_length=80)
    phone_number: str = Field(min_length=10, max_length=20)
    email: EmailStr
    password: str = Field(min_length=7, max_length=128)
    confirm_password: str = Field(min_length=7, max_length=128)

    @field_validator("first_name", "surname")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Must be at least 2 characters.")
        return cleaned

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def validate_matches(self) -> "RegisterStartRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match.")
        return self


class ResendEmailOtpRequest(BaseModel):
    email: EmailStr


class RegisterEmailVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RegisterSetPinRequest(BaseModel):
    registration_token: str = Field(min_length=20)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    confirm_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")

    @model_validator(mode="after")
    def match(self) -> "RegisterSetPinRequest":
        if self.pin != self.confirm_pin:
            raise ValueError("Transaction PIN and confirmation PIN do not match.")
        return self


class OtpSendRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    purpose: str = Field(default="password_reset")


class OtpVerifyRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    purpose: str = Field(default="password_reset")


class LoginRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = Field(default=None, min_length=10)


class PasswordResetRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)


class PasswordResetConfirmRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=7, max_length=128)
    confirm_password: str = Field(min_length=7, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def match(self) -> "PasswordResetConfirmRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match.")
        return self


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=7, max_length=128)
    confirm_password: str = Field(min_length=7, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match.")
        return self


class SetPinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    confirm_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")

    @model_validator(mode="after")
    def match(self) -> "SetPinRequest":
        if self.pin != self.confirm_pin:
            raise ValueError("PIN and confirm PIN do not match.")
        return self


class ChangePinRequest(BaseModel):
    # Allow 4-digit PIN or preserved legacy 6-digit PIN when upgrading to 4 digits
    current_pin: str = Field(min_length=4, max_length=6, pattern=r"^(\d{4}|\d{6})$")
    new_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    confirm_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")

    @model_validator(mode="after")
    def match(self) -> "ChangePinRequest":
        if self.new_pin != self.confirm_pin:
            raise ValueError("New PIN and confirm PIN do not match.")
        return self


class ResetPinConfirmRequest(BaseModel):
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    confirm_pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")

    @model_validator(mode="after")
    def match(self) -> "ResetPinConfirmRequest":
        if self.new_pin != self.confirm_pin:
            raise ValueError("New PIN and confirm PIN do not match.")
        return self


class LinkEmailRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    first_name: str
    surname: str
    phone_number: str
    email: Optional[str]
    phone_verified: bool
    email_verified: bool
    has_transaction_pin: bool
    account_number: Optional[str] = None
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: Optional[str] = None
    user: UserProfileResponse


class SessionOut(BaseModel):
    id: uuid.UUID
    user_agent: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    expires_at: datetime
    is_current: bool
