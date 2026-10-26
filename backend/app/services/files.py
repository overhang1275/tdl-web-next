from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DownloadFile
from app.services.paths import safe_child


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def human_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remaining_seconds}s"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h {remaining_minutes}m"


def file_kind(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    if not media_type:
        return "file"
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("video/"):
        return "video"
    if media_type.startswith("audio/"):
        return "audio"
    if media_type == "application/pdf":
        return "pdf"
    if media_type.startswith("text/"):
        return "text"
    return "file"


def list_downloaded_files(root: Path) -> list[dict[str, str | int | bool]]:
    if not root.exists():
        return []
    files: list[dict[str, str | int | bool]] = []
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            size = path.stat().st_size
            modified_at = int(path.stat().st_mtime)
            kind = file_kind(path)
            files.append(
                {
                    "name": path.name,
                    "relative_path": relative,
                    "size": size,
                    "human_size": human_size(size),
                    "modified_at": modified_at,
                    "modified_label": datetime.fromtimestamp(modified_at).strftime("%Y-%m-%d %H:%M"),
                    "kind": kind,
                    "can_preview": kind in {"image", "video", "audio", "pdf", "text"},
                }
            )
    return sorted(files, key=lambda item: str(item["relative_path"]).lower())


def job_file_entries(db: Session, job_id: int, root: Path) -> list[dict]:
    files = list_downloaded_files(root)
    records = list(
        db.scalars(select(DownloadFile).where(DownloadFile.job_id == job_id)).all()
    )
    by_relative: dict[str, DownloadFile] = {}
    for record in records:
        if not record.local_path:
            continue
        try:
            relative = Path(record.local_path).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        by_relative[relative] = record
    for item in files:
        record = by_relative.get(str(item["relative_path"]))
        item["file_id"] = record.id if record else None
        item["message_id"] = record.message_id if record else None
        item["status"] = record.status if record else None
        item["attempts"] = record.attempts if record else 0
        item["last_error"] = record.last_error if record else None
        if record:
            content = f"/api/v1/jobs/{job_id}/files/{record.id}/content"
        else:
            content = (
                f"/api/v1/jobs/{job_id}/files/content"
                f"?path={quote(str(item['relative_path']))}"
            )
        item["content_url"] = content
        item["download_url"] = f"{content}{'&' if '?' in content else '?'}download=true"
    return files


def job_download_root(job_id: int, download_path: str | None) -> Path:
    if download_path:
        return safe_child(settings.downloads_dir, *Path(download_path).resolve().relative_to(settings.downloads_dir.resolve()).parts)
    return safe_child(settings.downloads_dir, str(job_id))


def downloaded_file_path(root: Path, relative_path: str) -> Path:
    path = safe_child(root, relative_path)
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    return path


def scan_tree(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                files += 1
                total += item.stat().st_size
            except OSError:
                continue
    return files, total


def count_downloaded_files(path: Path) -> int:
    return scan_tree(path)[0]


def scan_download_progress(path: Path) -> tuple[int, int]:
    return scan_tree(path)


def directory_size(path: Path) -> int:
    return scan_tree(path)[1]
