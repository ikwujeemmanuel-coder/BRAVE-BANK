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


def get_schema_status(database_url: Optional[str] = None) -> dict[str, object]:
    """Inspect PostgreSQL connectivity, expected model tables/columns, and Alembic revision."""
    # Ensure all SQLAlchemy models are registered on Base.metadata
    import backend.app.models  # noqa: F401
    from sqlalchemy import inspect

    engine = get_engine(database_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = sorted(Base.metadata.tables.keys())
    missing_tables = [table for table in expected_tables if table not in existing_tables]

    missing_columns: dict[str, list[str]] = {}
    for table_name in expected_tables:
        if table_name in missing_tables:
            continue
        expected_cols = sorted(Base.metadata.tables[table_name].columns.keys())
        actual_cols = {col["name"] for col in inspector.get_columns(table_name)}
        absent = [col for col in expected_cols if col not in actual_cols]
        if absent:
            missing_columns[table_name] = absent

    alembic_revision: Optional[str] = None
    if "alembic_version" in existing_tables:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            if row is not None:
                alembic_revision = str(row[0])

    schema_ready = not missing_tables and not missing_columns
    return {
        "connected": True,
        "schema_ready": schema_ready,
        "expected_tables_count": len(expected_tables),
        "existing_tables_count": len(existing_tables & set(expected_tables)),
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "alembic_revision": alembic_revision,
    }


def format_schema_health_detail(schema_status: dict[str, object]) -> tuple[bool, str]:
    """Convert get_schema_status() output into a (healthy, detail_message) tuple."""
    missing_tables: list[str] = schema_status["missing_tables"]  # type: ignore[assignment]
    missing_columns: dict[str, list[str]] = schema_status["missing_columns"]  # type: ignore[assignment]
    if missing_tables:
        preview = ", ".join(missing_tables[:5])
        suffix = f" (+{len(missing_tables) - 5} more)" if len(missing_tables) > 5 else ""
        return (
            False,
            f"Database schema incomplete (missing tables: {preview}{suffix}). "
            "Run 'alembic -c backend/alembic.ini upgrade head' with DIRECT_URL configured.",
        )
    if missing_columns:
        cols_desc = ", ".join(
            f"{tbl}({', '.join(cols)})" for tbl, cols in sorted(missing_columns.items())
        )
        return (
            False,
            f"Database schema out of date (missing columns: {cols_desc}). "
            "Run 'alembic -c backend/alembic.ini upgrade head' with DIRECT_URL configured.",
        )
    return True, "connected"


def check_database_health(database_url: Optional[str] = None) -> tuple[bool, str]:
    """Verify PostgreSQL connectivity and required schema tables without silent fallback."""
    try:
        schema_status = get_schema_status(database_url)
        return format_schema_health_detail(schema_status)
    except DatabaseConfigurationError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive runtime check
        return False, f"PostgreSQL connection error: {exc}"
