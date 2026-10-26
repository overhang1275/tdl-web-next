from __future__ import annotations

import shutil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DownloadJob, DownloadTemplate, JobStatus
from app.services.chat_cache import delete_chats_cache
from app.services.jobs import cancel_job, get_queue


def _remove_contents(path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def reset_application_state(db: Session, keep_session: bool = True) -> dict:
    jobs = list(db.scalars(select(DownloadJob)).all())
    cancelled = 0
    for job in jobs:
        if job.status in {JobStatus.pending, JobStatus.running}:
            cancel_job(db, job)
            cancelled += 1
    try:
        get_queue().empty()
        redis_cleared = True
    except Exception:
        redis_cleared = False
    deleted_jobs = db.scalar(select(func.count()).select_from(DownloadJob)) or 0
    deleted_templates = db.scalar(select(func.count()).select_from(DownloadTemplate)) or 0
    db.query(DownloadJob).delete(synchronize_session=False)
    db.query(DownloadTemplate).delete(synchronize_session=False)
    db.commit()
    _remove_contents(settings.exports_dir)
    _remove_contents(settings.downloads_dir)
    _remove_contents(settings.logs_dir)
    delete_chats_cache()
    if not keep_session:
        _remove_contents(settings.sessions_dir)
    settings.ensure_directories()
    return {
        "cancelled_jobs": cancelled,
        "deleted_jobs": deleted_jobs,
        "deleted_templates": deleted_templates,
        "redis_cleared": redis_cleared,
        "kept_session": keep_session,
    }
