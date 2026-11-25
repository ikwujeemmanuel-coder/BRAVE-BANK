"""PostgreSQL SQLAlchemy engine, session management, and configuration validation."""

from collections.abc import Generator
from typing import Optional

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all BraveBank SQLAlchemy models."""


class DatabaseConfigurationError(RuntimeError):
    """Raised when PostgreSQL DATABASE_URL is missing or invalid."""


def normalize_postgres_url(raw_url: Optional[str]) -> str:
    """Validate and normalize a PostgreSQL connection URL for psycopg v3."""
    if not raw_url or not raw_url.strip():
        raise DatabaseConfigurationError(
            "DATABASE_URL is not configured. BraveBank requires a PostgreSQL database "
            "(for example, Neon PostgreSQL). SQLite is strictly prohibited."
        )

    url = raw_url.strip()
    lower = url.lower()

    if lower.startswith("sqlite"):
        raise DatabaseConfigurationError(
            "SQLite is strictly prohibited. Configure DATABASE_URL with a PostgreSQL connection string."
        )

    if lower.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif lower.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    elif not lower.startswith("postgresql+psycopg://"):
        raise DatabaseConfigurationError(
            "Unsupported database scheme in DATABASE_URL. Only PostgreSQL (postgresql://) is permitted."
        )

    return url


_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None
_configured_url: Optional[str] = None


def get_engine(database_url: Optional[str] = None) -> Engine:
    """Return a cached SQLAlchemy PostgreSQL engine."""
    global _engine, _session_factory, _configured_url

    settings = get_settings()
    target_url = normalize_postgres_url(database_url or settings.database_url)

    if _engine is None or _configured_url != target_url:
        _engine = create_engine(
            target_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
        _session_factory = sessionmaker(
            bind=_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        _configured_url = target_url

    return _engine


def get_session_factory(database_url: Optional[str] = None) -> sessionmaker[Session]:
    """Return the SQLAlchemy sessionmaker bound to PostgreSQL."""
    get_engine(database_url)
    assert _session_factory is not None
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency providing a PostgreSQL session per request."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> tuple[bool, str]:
    """Verify PostgreSQL connectivity without silent fallback."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "connected"
    except DatabaseConfigurationError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive runtime check
        return False, f"PostgreSQL connection error: {exc}"
