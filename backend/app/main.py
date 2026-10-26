from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install as install_error_handlers
from app.api.v1.router import api_router
from app.config import settings
from app.database import init_db
from app.security import install as install_security
from app.services.status import status_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    settings.apply_umask()
    init_db()
    status_service.invalidate()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.enable_docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.enable_docs else None,
)

install_security(app)
install_error_handlers(app)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "docs": "/api/docs" if settings.enable_docs else "disabled",
    }
