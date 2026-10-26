from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DownloadJob, JobStatus
from app.services.chat_cache import read_chats_cache
from app.services.files import directory_size, human_size
from app.services.progress import job_read


def dashboard_data(db: Session) -> dict:
    active = (
        db.scalar(
            select(func.count())
            .select_from(DownloadJob)
            .where(DownloadJob.status.in_([JobStatus.pending, JobStatus.running]))
        )
        or 0
    )
    failed = (
        db.scalar(
            select(func.count())
            .select_from(DownloadJob)
            .where(DownloadJob.status == JobStatus.failed)
        )
        or 0
    )
    downloaded = (
        db.scalar(select(func.coalesce(func.sum(DownloadJob.total_downloaded_files), 0)))
        or 0
    )
    latest = list(
        db.scalars(
            select(DownloadJob)
            .where(DownloadJob.status == JobStatus.failed)
            .order_by(DownloadJob.finished_at.desc().nullslast(), DownloadJob.created_at.desc())
            .limit(5)
        ).all()
    )
    chats, cached_at = read_chats_cache()
    counts = {"channels": 0, "groups": 0, "private": 0, "total": len(chats), "cached_at": cached_at}
    for chat in chats:
        value = str(chat.get("type") or "").lower()
        if "channel" in value:
            counts["channels"] += 1
        elif "group" in value:
            counts["groups"] += 1
        elif "private" in value or "user" in value:
            counts["private"] += 1
    return {
        "active_jobs": active,
        "failed_jobs": failed,
        "downloaded_files": downloaded,
        "disk_usage": human_size(directory_size(settings.downloads_dir)),
        "latest_errors": [job_read(db, job) for job in latest],
        "chat_counts": counts,
    }
