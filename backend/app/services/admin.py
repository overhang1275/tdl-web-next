from __future__ import annotations

import shutil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DownloadJob, DownloadTemplate, JobStatus
from app.services.chat_cache import delete_chats_cache
from app.services.jobs import cancel_job, get_queue
from app.services.runtime_settings import require_storage_available


def _remove_contents(path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        cleared = True
        for item in path.iterdir():
            try:
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                cleared = False
        return cleared
    except OSError:
        return False


def reset_application_state(db: Session, keep_session: bool = True) -> dict:
    require_storage_available(db)
    jobs = list(db.scalars(select(DownloadJob)).all())
    cancelled = 0
    for job in jobs:
        if job.status in {JobStatus.pending, JobStatus.running}:
            cancel_job(db, job)
            cancelled += 1
    require_storage_available(db)
    try:
        get_queue().empty()
        redis_cleared = True
    except Exception:
        redis_cleared = False
    deleted_jobs = db.scalar(select(func.count()).select_from(DownloadJob)) or 0
    deleted_templates = db.scalar(select(func.count()).select_from(DownloadTemplate)) or 0
    db.query(DownloadJob).delete(synchronize_session=False)
    db.query(DownloadTemplate).delete(synchronize_session=False)
    cleanup = [_remove_contents(settings.exports_dir),
               _remove_contents(settings.downloads_dir),
               _remove_contents(settings.logs_dir)]
    try:
        delete_chats_cache()
    except OSError:
        cleanup.append(False)
    if not keep_session:
        cleanup.append(_remove_contents(settings.sessions_dir))
    try:
        settings.ensure_directories()
    except OSError:
        cleanup.append(False)
    db.commit()
    return {
        "cancelled_jobs": cancelled,
        "deleted_jobs": deleted_jobs,
        "deleted_templates": deleted_templates,
        "redis_cleared": redis_cleared,
        "filesystem_cleared": all(cleanup),
        "kept_session": keep_session,
    }
