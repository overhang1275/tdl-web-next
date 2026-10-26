from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DownloadFile, DownloadJob
from app.schemas import JobRead


def files_for_job(db: Session, job: DownloadJob) -> list[DownloadFile]:
    return list(
        db.scalars(
            select(DownloadFile)
            .where(DownloadFile.job_id == job.id)
            .order_by(DownloadFile.message_id)
        ).all()
    )


def job_read(db: Session, job: DownloadJob, queue_position: int | None = None) -> JobRead:
    files = files_for_job(db, job)
    downloaded = sum(item.size for item in files if item.status == "completed")
    expected: int | None
    if files and all(item.expected_size is not None for item in files):
        expected = sum(int(item.expected_size or 0) for item in files)
    else:
        expected = None
    progress: float | None = None
    if job.transfer_initialized and job.total_filtered_messages:
        progress = min(
            100.0,
            round(job.total_downloaded_files / job.total_filtered_messages * 100, 1),
        )
    speed = job.download_speed_bps if job.status.value == "running" else 0
    eta = job.download_eta_seconds
    if eta is None and expected is not None and speed > 0 and expected > downloaded:
        eta = max(1, round((expected - downloaded) / speed))
    return JobRead(
        id=job.id,
        chat_id=job.chat_id,
        chat_title=job.chat_title,
        hashtag=job.hashtag,
        media_type=job.media_type.value,
        search_text=job.search_text,
        date_from=job.date_from,
        date_to=job.date_to,
        skip_same=job.skip_same,
        refresh_export=job.refresh_export,
        export_only=job.export_only,
        output_subfolder=job.output_subfolder,
        status=job.status.value,
        stage=job.stage.value,
        total_filtered_messages=job.total_filtered_messages,
        total_downloaded_files=job.total_downloaded_files,
        total_failed_files=job.total_failed_files,
        transfer_initialized=job.transfer_initialized,
        downloaded_bytes=downloaded,
        total_expected_bytes=expected,
        speed_bps=speed,
        eta_seconds=eta,
        progress_percent=progress,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        queue_position=queue_position,
        deletion_requested=bool(getattr(job, "deletion_requested", False)),
        deletion_error=getattr(job, "deletion_error", None),
    )
