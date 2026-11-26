"""Health check endpoint verifying FastAPI and PostgreSQL status."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from backend.app.config import get_settings
from backend.app.database import (
    DatabaseConfigurationError,
    format_schema_health_detail,
    get_schema_status,
)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check():
    settings = get_settings()
    db_ok = False
    db_detail = "PostgreSQL connection error"
    schema_ready = False
    alembic_revision = None
    missing_tables: list[str] = []

    try:
        schema_status = get_schema_status()
        db_ok, db_detail = format_schema_health_detail(schema_status)
        schema_ready = bool(schema_status["schema_ready"])
        alembic_revision = schema_status["alembic_revision"]
        missing_tables = list(schema_status["missing_tables"])  # type: ignore[arg-type]
    except DatabaseConfigurationError as exc:
        db_detail = str(exc)
    except Exception as exc:  # pragma: no cover - defensive runtime check
        db_detail = f"PostgreSQL connection error: {exc}"

    payload: dict[str, object] = {
        "status": "ok" if db_ok else "error",
        "service": settings.app_name,
        "environment": settings.app_env,
        "database": db_detail,
        "schema_ready": schema_ready,
        "alembic_revision": alembic_revision,
        "primary_currency": "NGN",
    }
    if missing_tables:
        payload["missing_tables"] = missing_tables

    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
