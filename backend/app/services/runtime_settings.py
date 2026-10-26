from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, Request
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.config import settings
from app.database import get_db
from app.models import DownloadFile, DownloadJob, JobStatus, RuntimeSettings
from app.schemas import SettingsUpdate

FIELDS = ("downloads_dir", "command_timeout_seconds", "download_batch_size",
          "download_idle_timeout_seconds", "export_batch_size")
BUSY = {"queued", "moving", "failed"}


def current_values() -> dict:
    return {name: str(getattr(settings, name)) if name == "downloads_dir"
            else getattr(settings, name) for name in FIELDS}


def load_runtime(db: Session) -> None:
    row = db.get(RuntimeSettings, 1)
    if row:
        for name, value in json.loads(row.values_json).items():
            if name in FIELDS:
                setattr(settings, name, Path(value) if name == "downloads_dir" else value)


def operation(db: Session) -> dict:
    row = db.get(RuntimeSettings, 1)
    pending = json.loads(row.pending_json) if row and row.pending_json else {}
    return {"id": row.operation_id if row else None,
            "status": row.operation_status if row else "idle",
            "error": row.operation_error if row else None,
            "source": pending.get("source"), "destination": pending.get("destination")}


def _lock(db: Session) -> None:
    # Called before any mutation; serialize job creation and configuration changes in SQLite.
    db.rollback()
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    load_runtime(db)


def guard_storage_write(request: Request, db: Session = Depends(get_db)) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        _lock(db)
        row = db.get(RuntimeSettings, 1)
        if row and row.operation_status in BUSY:
            raise ApiError("storage_moving", "Hay un traslado pendiente. Revisa Configuración.", 409)


def _require_idle(db: Session) -> None:
    active = db.scalar(select(DownloadJob.id).where(or_(
        DownloadJob.status.in_([JobStatus.pending, JobStatus.running]),
        DownloadJob.deletion_requested.is_(True),
    )).limit(1))
    if active is not None:
        raise ApiError("queue_busy", "Espera a que terminen las descargas y los borrados antes de guardar.", 409)


def validate_destination(value: str, source: Path, *, owned_marker: str | None = None) -> Path:
    raw = Path(value)
    if not raw.is_absolute() or ".." in raw.parts or "\x00" in value:
        raise ApiError("invalid_directory", "Usa una ruta absoluta sin segmentos '..'.", 400)
    if any(path.is_symlink() for path in (raw, *raw.parents)):
        raise ApiError("invalid_directory", "No se permiten enlaces simbólicos en la ruta.", 400)
    target = raw.resolve()
    source = source.resolve()
    if target == source:
        return target
    if source in target.parents or target in source.parents:
        raise ApiError("invalid_directory", "La carpeta nueva no puede contener la anterior ni estar dentro de ella.", 400)
    protected = [settings.base_dir, settings.sessions_dir, settings.exports_dir, settings.logs_dir]
    for path in protected:
        path = path.resolve()
        if target == path or target in path.parents or (path != settings.base_dir.resolve() and path in target.parents):
            raise ApiError("invalid_directory", "Elige una carpeta exclusiva para las descargas.", 400)
    docker = Path("/.dockerenv").exists() or os.getenv("DEPLOYMENT_MODE") == "docker"
    if not docker and any(root == target or root in target.parents for root in
                          map(Path, ("/tmp", "/var/tmp", "/run", "/dev", "/proc", "/sys"))):
        raise ApiError("temporary_directory", "Usa almacenamiento persistente; no una carpeta temporal del sistema.", 400)
    if docker:
        roots = [settings.base_dir.resolve(), *[Path(p).resolve() for p in
                 os.getenv("DOWNLOADS_ALLOWED_ROOTS", "").split(os.pathsep) if p]]
        if not any(root in target.parents for root in roots):
            raise ApiError("unmounted_directory", "En Docker usa una subcarpeta del volumen de datos o de DOWNLOADS_ALLOWED_ROOTS.", 400)
    if target.exists():
        if not target.is_dir():
            raise ApiError("invalid_directory", "La ruta debe ser una carpeta.", 400)
        if owned_marker:
            marker = target / owned_marker
            if not marker.is_file() or marker.is_symlink():
                raise ApiError("destination_not_owned", "El destino no pertenece a este traslado.", 409)
        elif any(target.iterdir()):
            raise ApiError("destination_not_empty", "La carpeta de destino debe estar vacía.", 400)
    parent = next(p for p in (target, *target.parents) if p.exists())
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        raise ApiError("directory_not_writable", "La carpeta de destino no es escribible.", 400)
    return target


def _enqueue(db: Session, row: RuntimeSettings) -> None:
    from app.services.jobs import ensure_queue_available

    try:
        queue = ensure_queue_available()
        row.operation_status = "queued"
        row.operation_error = None
        db.commit()
        queue.enqueue("app.services.runtime_settings.run_settings_move", row.operation_id,
                      job_timeout=86400)
    except Exception as exc:
        row.operation_status = "failed"
        row.operation_error = "No se pudo encolar el traslado. Revisa Redis y reintenta."
        db.commit()
        raise ApiError("queue_unavailable", row.operation_error, 503) from exc


def save_settings(db: Session, payload: SettingsUpdate) -> bool:
    _lock(db)
    row = db.get(RuntimeSettings, 1)
    if row and row.operation_status in BUSY:
        raise ApiError("storage_moving", "Ya hay un traslado pendiente; reinténtalo antes de guardar.", 409)
    _require_idle(db)
    source = settings.downloads_dir.resolve()
    target = validate_destination(payload.downloads_dir, source)
    values = payload.model_dump(exclude={"confirm_move"})
    values["downloads_dir"] = str(target)
    if target != source and not payload.confirm_move:
        raise ApiError("confirmation_required", "Confirma el traslado de los archivos existentes.", 400)
    if row is None:
        row = RuntimeSettings(id=1, values_json=json.dumps(current_values()))
        db.add(row)
    if target == source:
        row.values_json = json.dumps(values)
        db.commit()
        load_runtime(db)
        return False
    row.operation_id = uuid4().hex
    row.pending_json = json.dumps({"source": str(source), "destination": str(target),
                                   "values": values, "committed": False})
    _enqueue(db, row)
    return True


def retry_move(db: Session) -> None:
    _lock(db)
    row = db.get(RuntimeSettings, 1)
    if not row or not row.pending_json or row.operation_status not in BUSY:
        raise ApiError("no_pending_move", "No hay un traslado pendiente.", 409)
    _require_idle(db)
    _enqueue(db, row)


def _digest(path: Path) -> bytes:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def _flush_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _flush_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _flush_tree(target: Path) -> None:
    for directory in sorted((p for p in target.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
        _flush_directory(directory)
    for directory in (target, *target.parents):
        _flush_directory(directory)


def _copy_file(source: Path, target: Path, temporary_dir: Path) -> None:
    if target.is_symlink():
        raise ValueError("No se permiten enlaces simbólicos en el destino.")
    if target.exists():
        if target.is_file() and _digest(source) == _digest(target):
            _flush_file(target)
            return
        raise ValueError(f"Un archivo distinto ocupa el destino: {target.name}")
    with tempfile.NamedTemporaryFile(dir=temporary_dir, prefix="part-", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copy2(source, temporary)
        _flush_file(temporary)
        if _digest(source) != _digest(temporary):
            raise OSError("La verificación de la copia falló.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_tree(source: Path, target: Path, marker: str) -> None:
    if source.is_symlink():
        raise ValueError("La carpeta de origen no puede ser un enlace simbólico.")
    items = sorted(source.rglob("*")) if source.exists() else []
    staging = target / f"{marker}-staging"
    if staging.is_symlink() or any(item.relative_to(source).parts[0] in {marker, staging.name} for item in items):
        raise ValueError("Un archivo ocupa el área reservada para el traslado.")
    staging.mkdir(exist_ok=True)
    # Only this operation's reserved staging area can contain orphaned partial copies.
    for partial in staging.iterdir():
        if partial.is_symlink() or not partial.is_file():
            raise ValueError("Contenido inesperado en el área temporal del traslado.")
        partial.unlink()
    for item in items:
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ValueError("La carpeta contiene enlaces o archivos especiales; retíralos antes de trasladar.")
        destination = target / item.relative_to(source)
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            raise ValueError("Enlace simbólico en el destino.")
        if item.is_dir():
            destination.mkdir(exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_file(item, destination, staging)
    staging.rmdir()
    expected = {str(item.relative_to(source)) for item in items}
    actual = {str(item.relative_to(target)) for item in target.rglob("*")
              if str(item.relative_to(target)) != marker}
    if expected != actual:
        raise ValueError("El contenido del destino no coincide con el origen.")
    _flush_tree(target)


def _replace_root(value: str | None, source: Path, target: Path) -> str | None:
    if not value:
        return value
    try:
        return str(target / Path(value).relative_to(source))
    except ValueError:
        return value


def run_settings_move(operation_id: str) -> None:
    import fcntl

    from app import database

    database.engine.dispose()
    # Single host, shared data volume: prevent duplicate retries from copying concurrently.
    settings.base_dir.mkdir(parents=True, exist_ok=True)
    with (settings.base_dir / ".settings-move.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with database.SessionLocal() as db:
            row = db.get(RuntimeSettings, 1)
            if not row or row.operation_id != operation_id or row.operation_status == "completed":
                return
            pending = json.loads(row.pending_json)
            source, target = Path(pending["source"]), Path(pending["destination"])
            marker = f".tdl-relocation-{operation_id}"
            try:
                _require_idle(db)
                row.operation_status = "moving"
                row.operation_error = None
                db.commit()
                load_runtime(db)
                if not pending["committed"]:
                    owned = (target / marker).is_file()
                    validate_destination(str(target), source, owned_marker=marker if owned else None)
                    target.mkdir(parents=True, exist_ok=True)
                    (target / marker).touch(exist_ok=True)
                    _flush_file(target / marker)
                    _copy_tree(source, target, marker)
                    for job in db.scalars(select(DownloadJob)):
                        job.download_path = _replace_root(job.download_path, source, target)
                    for item in db.scalars(select(DownloadFile)):
                        for field in ("destination_root", "output_dir", "local_path"):
                            setattr(item, field, _replace_root(getattr(item, field), source, target))
                    row.values_json = json.dumps(pending["values"])
                    pending["committed"] = True
                    row.pending_json = json.dumps(pending)
                    db.commit()
                    load_runtime(db)
                # The new files and DB paths are durable before removing any old file.
                if source.exists():
                    children = sorted(source.rglob("*"), key=lambda p: len(p.parts), reverse=True)
                    for child in children:
                        if child.is_symlink():
                            raise ValueError("El origen cambió durante el traslado.")
                        if child.is_dir():
                            child.rmdir()
                        else:
                            copied = target / child.relative_to(source)
                            if not copied.is_file() or _digest(child) != _digest(copied):
                                raise ValueError("El origen cambió; se conserva el archivo sin eliminar.")
                            child.unlink()
                    _flush_directory(source)
                (target / marker).unlink(missing_ok=True)
                _flush_directory(target)
                row.operation_status = "completed"
                row.operation_error = None
                db.commit()
            except Exception as exc:
                db.rollback()
                row = db.get(RuntimeSettings, 1)
                row.operation_status = "failed"
                row.operation_error = str(exc)[:1000]
                db.commit()
