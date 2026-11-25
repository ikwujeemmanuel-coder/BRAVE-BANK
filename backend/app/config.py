"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for BraveBank."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="BRAVEBANK", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")

    secret_key: str = Field(
        default="dev-only-insecure-key-change-before-production",
        alias="SECRET_KEY",
    )
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    direct_url: Optional[str] = Field(default=None, alias="DIRECT_URL")
    test_database_url: Optional[str] = Field(default=None, alias="TEST_DATABASE_URL")

    email_provider: str = Field(default="mock", alias="EMAIL_PROVIDER")
    smtp_host: Optional[str] = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="no-reply@bravebank.ng", alias="SMTP_FROM")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")

    sms_provider: str = Field(default="mock", alias="SMS_PROVIDER")
    otp_expire_seconds: int = Field(default=300, alias="OTP_EXPIRE_SECONDS")
    otp_resend_cooldown_seconds: int = Field(default=60, alias="OTP_RESEND_COOLDOWN_SECONDS")
    otp_max_attempts: int = Field(default=5, alias="OTP_MAX_ATTEMPTS")

    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,https://bravebank-frontend.onrender.com",
        alias="ALLOWED_ORIGINS",
    )
    frontend_url: Optional[str] = Field(
        default="https://bravebank-frontend.onrender.com",
        alias="FRONTEND_URL",
    )
    render_external_url: Optional[str] = Field(default=None, alias="RENDER_EXTERNAL_URL")
    port: int = Field(default=3000, alias="PORT")

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be one of: development, test, production")
        return normalized

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "test"}

    @property
    def cors_origins(self) -> List[str]:
        origins: List[str] = []
        candidates = [origin.strip().rstrip("/") for origin in self.allowed_origins.split(",")]
        if self.frontend_url:
            candidates.append(self.frontend_url.strip().rstrip("/"))
        if self.render_external_url:
            candidates.append(self.render_external_url.strip().rstrip("/"))

        for origin in candidates:
            if not origin or origin == "*":
                continue
            if origin not in origins:
                origins.append(origin)
        return origins

    def validate_runtime(self) -> None:
        if self.app_env == "production" and (
            not self.secret_key
            or "change" in self.secret_key.lower()
            or len(self.secret_key) < 32
        ):
            raise RuntimeError(
                "SECRET_KEY must be set to a strong random string (>= 32 chars) in production."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    return settings
