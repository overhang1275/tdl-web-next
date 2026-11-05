"""Back up PostgreSQL and local state; restore only into an empty maintenance target."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

spec = importlib.util.spec_from_file_location("configure_env", Path(__file__).with_name("configure-env.py"))
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)

KEY_FILES = {"JWT_PRIVATE_KEY_FILE": "jwt-private.pem", "JWT_PUBLIC_KEY_FILE": "jwt-public.pem"}
PG_PARAMETERS = {
    "sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY", "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
}


def database_url(values):
    url = make_url(values["DATABASE_URL"])
    if (url.get_backend_name() != "postgresql" or not url.database
            or not url.host or not url.username or not url.password):
        raise ValueError("DATABASE_URL debe especificar host, usuario, contraseña y base PostgreSQL")
    # Refuse ambient libpq defaults rather than inspect one server and transfer to another.
    if any(name.startswith("PG") and name != "PG_PASS" for name in os.environ):
        raise ValueError("Elimine variables PostgreSQL PG* heredadas; use solo DATABASE_URL")
    if any(key not in PG_PARAMETERS or not isinstance(value, str) for key, value in url.query.items()):
        raise ValueError("Parámetro PostgreSQL no admitido para respaldo")
    return url.set(drivername="postgresql+psycopg", port=url.port or 5432)


def require_idle(values: dict[str, str]) -> None:
    engine = create_engine(database_url(values))
    try:
        with engine.connect() as db:
            tables = inspect(db).get_table_names()
            if "runtime_settings" in tables and db.execute(text(
                "SELECT count(*) FROM runtime_settings WHERE operation_status IN ('queued','moving','failed')"
            )).scalar_one():
                raise RuntimeError("Hay un traslado de descargas pendiente. Resuélvelo antes de actualizar.")
            if "download_jobs" not in tables:
                return
            if db.execute(text("SELECT count(*) FROM download_jobs WHERE status IN ('pending','running')")).scalar_one():
                raise RuntimeError("Hay jobs pendientes o activos. Deja terminar la cola antes de actualizar.")
            columns = {column["name"] for column in inspect(db).get_columns("download_jobs")}
            if "deletion_requested" in columns and db.execute(text(
                "SELECT count(*) FROM download_jobs WHERE deletion_requested IS TRUE"
            )).scalar_one():
                raise RuntimeError("Hay borrados pendientes. Deja terminar la cola antes de actualizar.")
    finally:
        engine.dispose()


def pg_environment(values):
    url = database_url(values)
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "LANG") if name in os.environ}
    env.update(PGHOST=url.host, PGPORT=str(url.port),
               PGDATABASE=url.database, PGUSER=url.username, PGPASSWORD=url.password,
               PGCONNECT_TIMEOUT="10")
    for key, value in url.query.items():
        env[PG_PARAMETERS[key]] = value
    return env


def pg_run(tool, args, values):
    try:
        return subprocess.run([tool, *args], env=pg_environment(values),
                              capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        # Client stderr can contain credentials supplied by the remote endpoint.
        raise RuntimeError(f"Falló {tool}; operación incompleta. Revise el servicio PostgreSQL.") from None


def pg_versions(values, tool):
    engine = create_engine(database_url(values))
    try:
        with engine.connect() as db:
            server = int(db.execute(text("SHOW server_version_num")).scalar_one()) // 10000
    finally:
        engine.dispose()
    version = pg_run(tool, ["--version"], values).strip()
    match = re.search(r"PostgreSQL\) (\d+)", version)
    if not match or int(match[1]) != server:
        raise RuntimeError("Cliente PostgreSQL incompatible: instale la misma versión mayor del servidor")
    return server, version


def protected_copy(source, destination):
    with Path(source).open("rb") as src, destination.open("xb") as dst:
        destination.chmod(0o600)
        shutil.copyfileobj(src, dst)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_manifest(destination, manifest):
    with (destination / "manifest.json").open("w") as stream:
        (destination / "manifest.json").chmod(0o600)
        json.dump(manifest, stream, indent=2)


def backup(env_file: Path, destination_root: Path | None = None) -> Path:
    values = config.read_env(env_file)
    require_idle(values)
    base = destination_root or Path(values.get("BACKUPS_DIR", str(Path(values["DATA_DIR"]) / "backups")))
    destination = base / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"format_version": 1, "complete": False, "media_included": False, "sha256": {}}
    write_manifest(destination, manifest)
    try:
        server, client = pg_versions(values, "pg_dump")
        manifest.update(server_major=server, pg_dump_version=client)
        dump = destination / "database.dump"
        dump.touch(mode=0o600)
        pg_run("pg_dump", ["--format=custom", "--no-owner", "--no-privileges", "--file", str(dump)], values)
        protected_copy(env_file, destination / ".env")
        state = destination / "state.tar.gz"
        state.touch(mode=0o600)
        with tarfile.open(state, "w:gz") as archive:
            for name in ("TDL_SESSIONS_DIR", "EXPORTS_DIR", "LOGS_DIR"):
                path = Path(values[name])
                if path.exists():
                    archive.add(path, arcname=name)
            chats = Path(values["DATA_DIR"]) / "chats.json"
            if chats.exists():
                archive.add(chats, arcname="chats.json")
        for name in KEY_FILES:
            if values.get(name) and Path(values[name]).is_file():
                (destination / "keys").mkdir(mode=0o700, exist_ok=True)
                protected_copy(values[name], destination / "keys" / name)
        manifest["sha256"] = {str(path.relative_to(destination)): sha256(path)
                              for path in destination.rglob("*") if path.is_file() and path.name != "manifest.json"}
        manifest["complete"] = True
        write_manifest(destination, manifest)
    except Exception:
        manifest["complete"] = False
        write_manifest(destination, manifest)
        raise
    return destination


def validate_backup(directory):
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        hashes = manifest["sha256"]
        allowed = {"database.dump", ".env", "state.tar.gz", *(f"keys/{name}" for name in KEY_FILES)}
        if manifest["format_version"] != 1 or manifest["complete"] is not True:
            raise ValueError
        if not {"database.dump", ".env", "state.tar.gz"} <= hashes.keys() or hashes.keys() - allowed:
            raise ValueError
        for name, digest in hashes.items():
            path = directory / name
            if path.is_symlink() or path.parent.is_symlink() or sha256(path) != digest:
                raise ValueError
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("Respaldo incompleto o fallo de integridad del manifiesto") from None


def restore_database(env_file: Path, directory: Path, *, services_stopped: bool = False) -> None:
    if not services_stopped:
        raise RuntimeError("Confirme servicios detenidos con --services-stopped antes de restaurar")
    values = config.read_env(env_file)
    manifest = validate_backup(directory)
    server, _ = pg_versions(values, "pg_restore")
    if manifest.get("server_major") != server:
        raise RuntimeError("Versión PostgreSQL del respaldo incompatible con el destino")
    # Only canonical local destinations are allowed; paths in the backup are never trusted.
    key_dir = Path(values["DATA_DIR"]) / "keys"
    has_keys = any(f"keys/{name}" in manifest["sha256"] for name in KEY_FILES)
    if has_keys and (key_dir.is_symlink() or key_dir.parent.is_symlink()
                     or (key_dir.exists() and not key_dir.is_dir()) or not key_dir.parent.is_dir()):
        raise RuntimeError("Directorio de claves inseguro")
    keys = []
    for name, filename in KEY_FILES.items():
        if f"keys/{name}" not in manifest["sha256"]:
            continue
        source, target = directory / "keys" / name, key_dir / filename
        if target.is_symlink() or (target.exists() and (not target.is_file() or sha256(target) != sha256(source))):
            raise RuntimeError("Conflicto con claves existentes; no se sobrescriben")
        keys.append((source, target))
    engine = create_engine(database_url(values))
    try:
        with engine.connect() as db:
            if db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()")).scalar_one():
                raise RuntimeError("Hay conexiones activas al destino; detenga todos los servicios")
            if db.execute(text("""SELECT EXISTS (
                SELECT 1 FROM pg_namespace WHERE left(nspname, 3) <> 'pg_' AND nspname NOT IN ('public','information_schema')
                UNION ALL SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
                UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'
                UNION ALL SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'
            )""")).scalar_one():
                raise RuntimeError("El destino debe ser una base vacía; no se borrará ningún objeto")
    finally:
        engine.dispose()
    # An empty dbname uses PGDATABASE literally, never reparses names as conninfo.
    pg_run("pg_restore", ["--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges",
                          "--dbname", "", str(directory / "database.dump")], values)
    if keys:
        key_dir.mkdir(mode=0o700, exist_ok=True)
        key_dir.chmod(0o700)
        for source, target in keys:
            if not target.exists():
                protected_copy(source, target)
            target.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check-idle", "backup", "restore-database"])
    parser.add_argument("--env", type=Path, required=True, help="Configuración explícita de la base origen/destino")
    parser.add_argument("--destination-root", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--services-stopped", action="store_true", help="Confirma que API y workers están detenidos")
    args = parser.parse_args()
    if args.command == "restore-database" and args.backup is None:
        parser.error("--backup is required for restore-database")
    try:
        if args.command == "check-idle":
            require_idle(config.read_env(args.env))
        elif args.command == "backup":
            destination = backup(args.env, args.destination_root)
            print("Respaldo completo; medios no incluidos.", file=sys.stderr)
            print(destination)
        else:
            restore_database(args.env, args.backup, services_stopped=args.services_stopped)
    except Exception as error:
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        print("Operación fallida. Verifique configuración, mantenimiento, destino vacío e integridad del respaldo.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
