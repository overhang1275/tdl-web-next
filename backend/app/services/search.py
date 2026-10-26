from __future__ import annotations

from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import DownloadFile, DownloadJob
from app.services.chat_cache import read_chats_cache
from app.services.files import file_kind, human_size


def global_search(db: Session, query: str, limit: int = 8) -> dict[str, list[dict]]:
    q = query.strip().lower()
    if not q:
        return {"chats": [], "jobs": [], "files": []}
    return {
        "chats": search_chats(q, limit),
        "jobs": search_jobs(db, q, limit),
        "files": search_files(db, q, limit),
    }


def search_chats(q: str, limit: int) -> list[dict]:
    chats, _ = read_chats_cache()
    results = []
    for chat in chats:
        haystack = " ".join(
            str(chat.get(key) or "")
            for key in ("id", "title", "visible_name", "username", "type")
        ).lower()
        if q in haystack:
            title = chat.get("title") or chat.get("visible_name") or "Sin nombre"
            results.append(
                {
                    "id": chat.get("id"),
                    "title": title,
                    "subtitle": (
                        f"@{chat.get('username')}"
                        if chat.get("username")
                        else str(chat.get("type") or "chat")
                    ),
                    "url": f"/chats/{chat.get('id')}",
                }
            )
        if len(results) >= limit:
            break
    return results


def search_jobs(db: Session, q: str, limit: int) -> list[dict]:
    like = f"%{q}%"
    jobs = list(
        db.scalars(
            select(DownloadJob)
            .where(
                or_(
                    DownloadJob.chat_id.ilike(like),
                    DownloadJob.chat_title.ilike(like),
                    DownloadJob.hashtag.ilike(like),
                    DownloadJob.search_text.ilike(like),
                    DownloadJob.output_subfolder.ilike(like),
                    DownloadJob.error_message.ilike(like),
                )
            )
            .order_by(DownloadJob.created_at.desc())
            .limit(limit)
        ).all()
    )
    return [
        {
            "id": job.id,
            "title": f"Job #{job.id} · {job.chat_title or job.chat_id}",
            "subtitle": (
                f"{job.status.value} · {job.media_type.value} · "
                f"{job.total_downloaded_files} archivos"
            ),
            "url": f"/downloads/{job.id}",
        }
        for job in jobs
    ]


def search_files(db: Session, q: str, limit: int) -> list[dict]:
    like = f"%{q}%"
    rows = db.execute(
        select(DownloadFile, DownloadJob)
        .join(DownloadJob, DownloadJob.id == DownloadFile.job_id)
        .where(
            or_(
                DownloadFile.file_name.ilike(like),
                DownloadFile.last_error.ilike(like),
                DownloadFile.status.ilike(like),
            )
        )
        .order_by(DownloadFile.id.desc())
        .limit(limit)
    ).all()
    results = []
    for record, job in rows:
        kind = file_kind(Path(record.file_name))
        results.append(
            {
                "id": record.id,
                "title": record.file_name,
                "subtitle": (
                    f"{job.chat_title or job.chat_id} · "
                    f"{human_size(record.size)} · {kind}"
                ),
                "url": f"/downloads/{job.id}?file={record.id}",
                "download_url": (
                    f"/api/v1/jobs/{job.id}/files/{record.id}/content?download=true"
                ),
            }
        )
    return results
