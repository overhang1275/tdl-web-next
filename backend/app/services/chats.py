from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import DownloadJob
from app.schemas import ChatProfileRead, ChatRead
from app.services.chat_cache import read_chats_cache
from app.services.files import count_downloaded_files, directory_size, human_size
from app.services.jobs import list_jobs_for_chat
from app.services.paths import chat_path_key, safe_child
from app.services.progress import job_read


def _chat_read(chat: dict, fallback_id: str = "") -> ChatRead:
    return ChatRead(
        id=str(chat.get("id") or fallback_id),
        title=str(chat.get("title") or chat.get("visible_name") or "Sin nombre"),
        username=str(chat.get("username") or ""),
        type=str(chat.get("type") or ""),
        topics_count=len(chat.get("topics") or []),
    )


def chat_profile_data(db: Session, chat_id: str) -> ChatProfileRead:
    jobs: list[DownloadJob] = list_jobs_for_chat(db, chat_id)
    chat_title = jobs[0].chat_title if jobs and jobs[0].chat_title else ""
    cached, _ = read_chats_cache()
    chat = None
    for candidate in cached:
        if str(candidate.get("id")) == chat_id:
            chat = candidate
            chat_title = (
                candidate.get("title") or candidate.get("visible_name") or chat_title
            )
            break
    export_exists = False
    export_updated_at = None
    try:
        export_path = safe_child(settings.exports_dir, chat_path_key(chat_id), "export.json")
        export_exists = export_path.exists()
        if export_exists:
            export_updated_at = datetime.fromtimestamp(export_path.stat().st_mtime)
    except ValueError:
        pass
    try:
        downloads_root = safe_child(settings.downloads_dir, chat_path_key(chat_id))
    except ValueError:
        downloads_root = Path(settings.downloads_dir) / "__invalid__"
    return ChatProfileRead(
        chat=_chat_read(chat, chat_id) if chat else None,
        chat_id=chat_id,
        chat_title=chat_title or chat_id,
        jobs=[job_read(db, job) for job in jobs],
        export_exists=export_exists,
        export_updated_at=export_updated_at,
        downloaded_files=count_downloaded_files(downloads_root),
        downloaded_size=human_size(directory_size(downloads_root)),
        download_root=str(downloads_root),
    )
