"""Pytest fixtures wired exclusively to an isolated PostgreSQL test database."""

import os
from pathlib import Path
from typing import Generator

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=False)

TEST_DB_URL = os.getenv("TEST_DATABASE_URL") or (
    "postgresql+psycopg://bravebank:bravebank@127.0.0.1:5432/bravebank_test"
)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["SMS_PROVIDER"] = "mock"
os.environ["EMAIL_PROVIDER"] = "mock"

from backend.app.config import get_settings  # noqa: E402
from backend.app.database import Base, get_db, normalize_postgres_url  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.security.dependencies import rate_limiter  # noqa: E402
from backend.app.services.accounts import ensure_default_banks  # noqa: E402

get_settings.cache_clear()
NORMALIZED_TEST_URL = normalize_postgres_url(TEST_DB_URL)
test_engine = create_engine(NORMALIZED_TEST_URL, pool_pre_ping=True, future=True)
TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_schema() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def clean_tables() -> Generator[None, None, None]:
    rate_limiter.reset()
    with test_engine.begin() as conn:
        table_names = [table.name for table in reversed(Base.metadata.sorted_tables)]
        if table_names:
            conn.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    with TestingSessionLocal() as db:
        ensure_default_banks(db)
    yield


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


def register_and_verify_user(
    client: TestClient,
    phone_number: str = "08012345678",
    first_name: str = "Chinedu",
    surname: str = "Okafor",
    password: str = "StrongPass#123",
    pin: str = "2468",
    email: str | None = None,
    clear_cookies: bool = True,
) -> dict:
    digits = "".join(ch for ch in phone_number if ch.isdigit())
    resolved_email = email if email is not None else f"user.{digits}@bravebank.ng"

    start_res = client.post(
        "/api/auth/register/start",
        json={
            "first_name": first_name,
            "surname": surname,
            "phone_number": phone_number,
            "email": resolved_email,
            "password": password,
            "confirm_password": password,
        },
    )
    assert start_res.status_code == 201, start_res.text
    start_data = start_res.json()

    verify_res = client.post(
        "/api/auth/register/verify-email",
        json={
            "email": start_data["email"],
            "code": start_data["dev_otp"],
        },
    )
    assert verify_res.status_code == 200, verify_res.text
    verify_data = verify_res.json()
    assert verify_data["email_verified"] is True
    assert verify_data["phone_verified"] is False

    pin_res = client.post(
        "/api/auth/register/set-pin",
        json={
            "registration_token": verify_data["registration_token"],
            "pin": pin,
            "confirm_pin": pin,
        },
    )
    assert pin_res.status_code == 201, pin_res.text
    auth_data = pin_res.json()

    headers = {"Authorization": f"Bearer {auth_data['access_token']}"}
    csrf_token = client.cookies.get("bb_csrf_token")
    if clear_cookies:
        client.cookies.clear()

    return {
        "user": auth_data["user"],
        "access_token": auth_data["access_token"],
        "refresh_token": auth_data["refresh_token"],
        "csrf_token": csrf_token,
        "headers": headers,
        "account_number": auth_data["user"]["account_number"],
        "pin": pin,
    }
