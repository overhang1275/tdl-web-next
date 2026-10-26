from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.schemas import SettingsUpdate, UserRead
from app.services.runtime_settings import load_runtime, operation, retry_move, save_settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
def read_settings(db: Session = Depends(get_db), _: UserRead = Depends(get_current_user)) -> dict:
    load_runtime(db)
    return {
        "operation": operation(db),
        "downloads_storage_root": str(settings.base_dir),
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


@router.put("/settings")
def update_settings(payload: SettingsUpdate, response: Response,
                    db: Session = Depends(get_db), _: UserRead = Depends(get_current_user)) -> dict:
    moving = save_settings(db, payload)
    response.status_code = 202 if moving else 200
    return read_settings(db, _)


@router.post("/settings/retry", status_code=202)
def retry_settings_move(db: Session = Depends(get_db),
                        _: UserRead = Depends(get_current_user)) -> dict:
    retry_move(db)
    return read_settings(db, _)
