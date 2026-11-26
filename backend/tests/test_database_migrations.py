"""Tests for Alembic PostgreSQL migrations, schema drift detection, and registration DB queries."""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.config import get_settings
from backend.app.database import Base, check_database_health, get_db, get_schema_status
from backend.app.main import create_app
from backend.app.models.user import User
from backend.tests.conftest import NORMALIZED_TEST_URL, test_engine


def _url_with_search_path(raw_url: str, schema_name: str) -> str:
    parsed = urlparse(raw_url)
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k != "options"]
    query_pairs.append(("options", f"-csearch_path={schema_name}"))
    return urlunparse(parsed._replace(query=urlencode(query_pairs)))


def test_alembic_requires_direct_url(monkeypatch):
    monkeypatch.setenv("DIRECT_URL", "")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert not settings.direct_url
        with pytest.raises(RuntimeError, match="DIRECT_URL is not configured"):
            cfg = Config("backend/alembic.ini")
            command.current(cfg)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_alembic_migrations_create_users_and_all_models_and_support_register_start(monkeypatch):
    schema_name = "alembic_verify_schema"
    with test_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema_name}"))

    scoped_url = _url_with_search_path(NORMALIZED_TEST_URL, schema_name)
    monkeypatch.setenv("DIRECT_URL", scoped_url)
    monkeypatch.setenv("DATABASE_URL", scoped_url)
    get_settings.cache_clear()

    scoped_engine = create_engine(scoped_url, pool_pre_ping=True, future=True)
    try:
        cfg = Config("backend/alembic.ini")
        command.upgrade(cfg, "head")

        # Verify Alembic reports no unmigrated model drift
        command.check(cfg)

        # Verify schema inspection and Alembic revision
        status_info = get_schema_status(scoped_url)
        assert status_info["connected"] is True
        assert status_info["schema_ready"] is True
        assert status_info["missing_tables"] == []
        assert status_info["missing_columns"] == {}
        assert status_info["alembic_revision"] == "c7a1f3e92b10"

        # Verify every SQLAlchemy model table and User columns/indexes exist
        inspector = inspect(scoped_engine)
        existing_tables = set(inspector.get_table_names())
        assert set(Base.metadata.tables.keys()).issubset(existing_tables)

        user_cols = {col["name"] for col in inspector.get_columns("users")}
        expected_user_cols = set(User.__table__.columns.keys())
        assert expected_user_cols == user_cols

        user_indexes = {idx["name"]: idx for idx in inspector.get_indexes("users")}
        assert user_indexes["ix_users_phone_number"]["unique"] is True
        assert user_indexes["ix_users_email"]["unique"] is True

        account_cols = {col["name"] for col in inspector.get_columns("accounts")}
        assert "demo_funded" in account_cols

        # Verify register_start executes against the Alembic-migrated PostgreSQL schema
        ScopedSession = sessionmaker(
            bind=scoped_engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        app = create_app()

        def override_scoped_db():
            db = ScopedSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_scoped_db
        with TestClient(app) as scoped_client:
            health = scoped_client.get("/api/health")
            assert health.status_code == 200, health.text
            assert health.json()["schema_ready"] is True
            assert health.json()["alembic_revision"] == "c7a1f3e92b10"

            res = scoped_client.post(
                "/api/auth/register/start",
                json={
                    "first_name": "Kemi",
                    "surname": "Adeyemi",
                    "phone_number": "08099998888",
                    "email": "kemi.adeyemi@example.com",
                    "password": "StrongPass#2026",
                    "confirm_password": "StrongPass#2026",
                },
            )
            assert res.status_code == 201, res.text
            assert res.json()["step"] == "verify_email"

        with ScopedSession() as check_db:
            persisted = check_db.scalar(
                select(User).where(User.phone_number == "+2348099998888")
            )
            assert persisted is not None
            assert persisted.email == "kemi.adeyemi@example.com"
    finally:
        scoped_engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()
        check_database_health()
        with test_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))


def test_health_check_detects_missing_tables_on_unmigrated_database(monkeypatch):
    empty_schema = "empty_unmigrated_schema"
    with test_engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {empty_schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {empty_schema}"))

    empty_url = _url_with_search_path(NORMALIZED_TEST_URL, empty_schema)
    try:
        # Point settings.database_url to an empty PostgreSQL schema with no tables
        monkeypatch.setenv("DATABASE_URL", empty_url)
        get_settings.cache_clear()

        ok, detail = check_database_health(empty_url)
        assert ok is False
        assert "missing tables" in detail
        assert "alembic -c backend/alembic.ini upgrade head" in detail

        app = create_app()
        with TestClient(app) as tc:
            health = tc.get("/api/health")
            assert health.status_code == 503
            body = health.json()
            assert body["status"] == "error"
            assert body["schema_ready"] is False
            assert "users" in body["missing_tables"]
            assert body["alembic_revision"] is None
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        check_database_health()
        with test_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {empty_schema} CASCADE"))
