"""Health check endpoint verifying FastAPI and PostgreSQL status."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from backend.app.config import get_settings
from backend.app.database import check_database_health

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check():
    settings = get_settings()
    db_ok, db_detail = check_database_health()
    payload = {
        "status": "ok" if db_ok else "error",
        "service": settings.app_name,
        "environment": settings.app_env,
        "database": db_detail,
        "primary_currency": "NGN",
    }
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
