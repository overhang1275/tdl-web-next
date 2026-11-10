from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import check_schema

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    try:
        check_schema()
    except RuntimeError:
        return JSONResponse({"detail": "Database is not ready"}, status_code=503)
    return {"status": "ok"}
