from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from redis.exceptions import RedisError
from rq.job import Job
from sqlalchemy import select

from app.database import SessionLocal
from app.models import DownloadJob
from app.services.jobs import (
    ACTIVE_STATUSES,
    DeleteJobError,
    QueueUnavailableError,
    cancel_job,
    get_queue,
    wipe_delete_job,
)


def enqueue_delete(db, job: DownloadJob, delay: int = 0) -> str:
    token = uuid4().hex
    job.deletion_requested = True
    job.deletion_error = None
    job.deletion_rq_job_id = token
    db.commit()
    try:
        queue = get_queue()
        kwargs = {"job_id": token, "job_timeout": 300}
        if delay:
            queue.enqueue_in(
                timedelta(seconds=delay),
                "app.worker.delete_job",
                job.id,
                token,
                **kwargs,
            )
        else:
            queue.enqueue("app.worker.delete_job", job.id, token, **kwargs)
    except RedisError as exc:
        job.deletion_error = f"No se pudo encolar la eliminación: {exc}"
        db.commit()
        raise QueueUnavailableError(job.deletion_error) from exc
    return token


def run_delete(job_id: int, token: str | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        if token and job.deletion_rq_job_id and job.deletion_rq_job_id != token:
            return
        if job.status in ACTIVE_STATUSES:
            cancel_job(db, job)
            job.deletion_requested = True
            job.deletion_rq_job_id = None
            db.commit()
            enqueue_delete(db, job, delay=5)
            return
        try:
            wipe_delete_job(db, job)
        except DeleteJobError as exc:
            job.deletion_error = str(exc)
            job.deletion_rq_job_id = None
            db.commit()
    finally:
        db.close()


def reconcile_deletions() -> None:
    db = SessionLocal()
    try:
        jobs = list(
            db.scalars(
                select(DownloadJob).where(DownloadJob.deletion_requested.is_(True))
            ).all()
        )
        for job in jobs:
            if job.deletion_rq_job_id:
                try:
                    Job.fetch(job.deletion_rq_job_id, connection=get_queue().connection)
                    continue
                except Exception:
                    job.deletion_rq_job_id = None
                    db.commit()
            try:
                enqueue_delete(db, job)
            except QueueUnavailableError:
                return
    finally:
        db.close()
