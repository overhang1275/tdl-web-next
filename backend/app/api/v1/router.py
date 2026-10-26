from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, health, status

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(status.router)
