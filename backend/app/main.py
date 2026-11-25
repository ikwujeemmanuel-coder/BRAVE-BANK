"""Main FastAPI application entry point for BRAVEBANK."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.database import DatabaseConfigurationError, get_session_factory
from backend.app.routers import accounts, auth, health, services, support, transactions, transfers
from backend.app.services.accounts import ensure_default_banks
from backend.app.services.email import EmailDeliveryError

logger = logging.getLogger("bravebank")

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            ensure_default_banks(db)
    except DatabaseConfigurationError as exc:
        logger.warning("Database not yet configured on startup: %s", exc)
    except Exception as exc:  # pragma: no cover - defensive startup log
        logger.warning("Startup bank directory seed skipped: %s", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="BraveBank — Simulated Nigerian Digital Banking Prototype API",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Requested-With"],
    )

    def _cors_headers(request: Request) -> dict[str, str]:
        origin = request.headers.get("origin")
        if origin and origin in settings.cors_origins:
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }
        return {}

    @app.exception_handler(DatabaseConfigurationError)
    async def database_config_exception_handler(
        request: Request, exc: DatabaseConfigurationError
    ):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
            headers=_cors_headers(request),
        )

    @app.exception_handler(EmailDeliveryError)
    async def email_delivery_exception_handler(request: Request, exc: EmailDeliveryError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
            headers=_cors_headers(request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled BraveBank API error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected server error occurred. Please try again."},
            headers=_cors_headers(request),
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(accounts.router)
    app.include_router(transfers.router)
    app.include_router(transactions.router)
    app.include_router(services.router)
    app.include_router(support.router)

    if (FRONTEND_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    if (FRONTEND_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
    if (FRONTEND_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def serve_manifest():
        return FileResponse(
            FRONTEND_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api"):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "API endpoint not found"},
            )
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
