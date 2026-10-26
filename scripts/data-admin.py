"""Check idle jobs or back up local state before a Docker cutover."""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location("configure_env", Path(__file__).with_name("configure-env.py"))
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def database_path(values: dict[str, str]) -> Path:
    url = values["DATABASE_URL"]
    if not url.startswith("sqlite:///"):
        raise ValueError("Only the existing SQLite database is supported")
    return Path(url.removeprefix("sqlite:///"))


def require_idle(values: dict[str, str]) -> None:
    path = database_path(values)
    if not path.exists():
        return
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE name='download_jobs'").fetchone():
            return
        if db.execute("SELECT count(*) FROM download_jobs WHERE status IN ('pending','running')").fetchone()[0]:
            raise RuntimeError("Hay jobs pendientes o activos. Deja terminar la cola antes de actualizar.")


def backup(env_file: Path) -> Path:
    values = config.read_env(env_file)
    require_idle(values)
    destination = Path(values["DATA_DIR"]) / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True, mode=0o700)
    source = database_path(values)
    if source.exists():
        with sqlite3.connect(str(source)) as db, sqlite3.connect(str(destination / "database.sqlite3")) as target:
            db.backup(target)
    shutil.copy2(env_file, destination / ".env")
    with tarfile.open(destination / "state.tar.gz", "w:gz") as archive:
        for name in ("TDL_SESSIONS_DIR", "EXPORTS_DIR", "LOGS_DIR"):
            path = Path(values[name])
            if path.exists():
                archive.add(path, arcname=name)
        chats = Path(values["DATA_DIR"]) / "chats.json"
        if chats.exists():
            archive.add(chats, arcname="chats.json")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check-idle", "backup"])
    parser.add_argument("--env", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check-idle":
        require_idle(config.read_env(args.env))
    else:
        print(backup(args.env))
