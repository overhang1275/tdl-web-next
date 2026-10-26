from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.config import settings
from app.schemas import UserRead

router = APIRouter(tags=["settings"])


@router.get("/settings")
def read_settings(_: UserRead = Depends(get_current_user)) -> dict:
    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        },
        "paths": {
            "data_dir": str(settings.base_dir),
            "sessions_dir": str(settings.sessions_dir),
            "exports_dir": str(settings.exports_dir),
            "downloads_dir": str(settings.downloads_dir),
            "logs_dir": str(settings.logs_dir),
        },
        "limits": {
            "command_timeout_seconds": settings.command_timeout_seconds,
            "download_batch_size": settings.download_batch_size,
            "download_idle_timeout_seconds": settings.download_idle_timeout_seconds,
            "export_batch_size": settings.export_batch_size,
        },
        "tdl": {
            "binary": settings.tdl_binary,
            "namespace": settings.tdl_namespace,
        },
        "authentik": {
            "issuer": settings.authentik_issuer,
            "audience": settings.authentik_audience,
            "admin_group": settings.authentik_admin_group,
        },
        "can_start_services": settings.environment != "production",
    }
