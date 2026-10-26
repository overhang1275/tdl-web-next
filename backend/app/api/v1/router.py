from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1 import (
    admin,
    auth,
    chats,
    dashboard,
    health,
    jobs,
    search,
    settings,
    status,
    telegram,
    templates,
)
from app.services.runtime_settings import guard_storage_write

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(status.router)
api_router.include_router(dashboard.router)
api_router.include_router(chats.router, dependencies=[Depends(guard_storage_write)])
api_router.include_router(jobs.router, dependencies=[Depends(guard_storage_write)])
api_router.include_router(templates.router)
api_router.include_router(search.router)
api_router.include_router(settings.router)
api_router.include_router(admin.router, dependencies=[Depends(guard_storage_write)])
api_router.include_router(telegram.router)
