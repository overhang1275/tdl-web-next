from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import ApiError
from app.database import get_db
from app.models import DownloadFile, DownloadJob, JobStatus
from app.schemas import (
    ConfirmRequest,
    JobCreate,
    JobFileRead,
    JobRead,
    LogRead,
    Page,
    UserRead,
)
from app.services.deletion import enqueue_delete
from app.services.files import (
    downloaded_file_path,
    job_download_root,
    job_file_entries,
)
from app.services.jobs import (
    DuplicateJobError,
    NoFailedFilesError,
    QueueUnavailableError,
    cancel_job,
    count_jobs_filtered,
    create_job,
    list_jobs_filtered,
    queue_position,
    retry_job,
)
from app.services.logs import job_events, job_log_path, read_job_log
from app.services.pagination import paginate_files
from app.services.progress import job_read

router = APIRouter(prefix="/jobs", tags=["jobs"])

UNSAFE_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "application/xml",
    "text/xml",
}


def get_job_or_404(db: Session, job_id: int) -> DownloadJob:
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise ApiError("job_not_found", "El job no existe.", 404)
    return job


@router.get("", response_model=Page[JobRead])
def list_jobs(
    status: list[JobStatus] | None = Query(default=None),
    chat_id: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> Page[JobRead]:
    total = count_jobs_filtered(db, status, chat_id or None, q or None)
    page_count = max(1, (total + per_page - 1) // per_page)
    page = min(page, page_count)
    jobs = list_jobs_filtered(
        db,
        statuses=status,
        chat_id=chat_id or None,
        q=q or None,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return Page[JobRead](
        items=[job_read(db, job) for job in jobs],
        page=page,
        per_page=per_page,
        total=total,
        page_count=page_count,
    )


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> JobRead:
    job = get_job_or_404(db, job_id)
    return job_read(db, job, queue_position(job))


@router.get("/{job_id}/files", response_model=Page[JobFileRead])
def list_job_files(
    job_id: int,
    q: str = "",
    kind: str = "",
    sort: str = "name",
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> Page[JobFileRead]:
    job = get_job_or_404(db, job_id)
    try:
        root = job_download_root(job.id, job.download_path)
    except (OSError, ValueError) as exc:
        raise ApiError("invalid_download_path", "Ruta de descargas inválida.", 409) from exc
    files = job_file_entries(db, job.id, root)
    pagination = paginate_files(files, q=q, kind=kind, sort=sort, page=page, per_page=per_page)
    return Page[JobFileRead](
        items=[JobFileRead(**item) for item in pagination["items"]],
        page=pagination["page"],
        per_page=pagination["per_page"],
        total=pagination["total"],
        page_count=pagination["page_count"],
    )


@router.get("/{job_id}/logs", response_model=LogRead)
def get_job_logs(
    job_id: int,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> LogRead:
    get_job_or_404(db, job_id)
    path = job_log_path(job_id)
    truncated = path.exists() and path.stat().st_size > 50_000
    return LogRead(content=read_job_log(job_id), truncated=truncated)


@router.get("/{job_id}/events")
def get_job_events(
    job_id: int,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> list[dict[str, str]]:
    get_job_or_404(db, job_id)
    return job_events(job_id)


@router.post("", response_model=JobRead, status_code=201)
def create_job_endpoint(
    payload: JobCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> JobRead:
    try:
        job = create_job(db, payload, idempotency_key=idempotency_key)
    except DuplicateJobError as exc:
        raise ApiError(
            "duplicate_job",
            "Ya existe un job activo con la misma configuración.",
            409,
            {"job_id": exc.job.id},
        ) from exc
    except QueueUnavailableError as exc:
        raise ApiError("queue_unavailable", str(exc), 503) from exc
    return job_read(db, job, queue_position(job))


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job_endpoint(
    job_id: int,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> JobRead:
    job = get_job_or_404(db, job_id)
    cancel_job(db, job)
    return job_read(db, job, queue_position(job))


@router.post("/{job_id}/retry", response_model=JobRead)
def retry_job_endpoint(
    job_id: int,
    mode: str = Query("pending", pattern="^(pending|failed)$"),
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> JobRead:
    job = get_job_or_404(db, job_id)
    try:
        job = retry_job(db, job, mode=mode)
    except NoFailedFilesError as exc:
        raise ApiError("no_failed_files", str(exc), 409) from exc
    except QueueUnavailableError as exc:
        raise ApiError("queue_unavailable", str(exc), 503) from exc
    return job_read(db, job, queue_position(job))


@router.delete("/{job_id}", response_model=JobRead, status_code=202)
def delete_job_endpoint(
    job_id: int,
    payload: ConfirmRequest,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> JobRead:
    if not payload.confirm:
        raise ApiError("confirmation_required", "Confirma la eliminación.", 400)
    job = get_job_or_404(db, job_id)
    try:
        enqueue_delete(db, job)
    except QueueUnavailableError as exc:
        raise ApiError("queue_unavailable", str(exc), 503) from exc
    return job_read(db, job, queue_position(job))


def _file_response(path: Path, download: bool) -> FileResponse:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    disposition = "attachment" if download or media_type in UNSAFE_TYPES else "inline"
    if media_type in UNSAFE_TYPES:
        media_type = "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name if disposition == "attachment" else None,
        content_disposition_type=disposition,
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _job_root(db: Session, job_id: int) -> Path:
    job = get_job_or_404(db, job_id)
    try:
        return job_download_root(job.id, job.download_path)
    except (OSError, ValueError) as exc:
        raise ApiError("invalid_download_path", "Ruta de descargas inválida.", 409) from exc


@router.get("/{job_id}/files/{file_id}/content")
def get_file_content(
    job_id: int,
    file_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> FileResponse:
    root = _job_root(db, job_id)
    record = db.get(DownloadFile, file_id)
    if record is None or record.job_id != job_id or not record.local_path:
        raise ApiError("file_not_found", "Archivo no encontrado.", 404)
    try:
        relative = Path(record.local_path).resolve().relative_to(root)
    except (OSError, ValueError) as exc:
        raise ApiError("file_not_found", "Archivo no encontrado.", 404) from exc
    try:
        path = downloaded_file_path(root, relative.as_posix())
    except (FileNotFoundError, ValueError) as exc:
        raise ApiError("file_not_found", "Archivo no encontrado.", 404) from exc
    return _file_response(path, download)


@router.get("/{job_id}/files/content")
def get_legacy_file_content(
    job_id: int,
    path: str,
    download: bool = False,
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
) -> FileResponse:
    root = _job_root(db, job_id)
    try:
        file_path = downloaded_file_path(root, path)
    except (FileNotFoundError, ValueError) as exc:
        raise ApiError("file_not_found", "Archivo no encontrado.", 404) from exc
    return _file_response(file_path, download)
