from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from test_deploy import load

from app.models import DownloadTemplate, RuntimeSettings


@pytest.fixture
def admin_env(tmp_path, admin_databases):
    env = tmp_path / "app.env"
    data = tmp_path / "data"
    data.mkdir()
    entries = {"DATABASE_URL": admin_databases[0], "DATA_DIR": str(data)}
    for name in ("TDL_SESSIONS_DIR", "EXPORTS_DIR", "LOGS_DIR", "DOWNLOADS_DIR"):
        path = data / name.lower()
        path.mkdir()
        (path / "marker").write_text(name)
        entries[name] = str(path)
    env.write_text("".join(f"{key}={value}\n" for key, value in entries.items()))
    return env


def migrate(url):
    engine = create_engine(url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine


def target_env(admin_env, admin_databases):
    target = admin_env.with_name("target.env")
    target.write_text(admin_env.read_text().replace(admin_databases[0], admin_databases[1]))
    return target


def test_postgres_backup_restore_roundtrip(admin_env, admin_databases, tmp_path, monkeypatch, capsys):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    with Session(engine) as session:
        row = DownloadTemplate(name="custom", output_subfolder="my-folder")
        session.add_all([row, RuntimeSettings(id=1, values_json='{"DOWNLOADS_DIR":"/custom/media"}', operation_status="idle")])
        session.commit()
        original_id = row.id
    engine.dispose()
    calls = []
    environments = []
    monkeypatch.setenv("UNRELATED_SECRET", "unrelated-private-value")
    run = subprocess.run

    def record(args, **kwargs):
        calls.append(args)
        environments.append(kwargs["env"])
        return run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    assert (snapshot / "database.dump").read_bytes().startswith(b"PGDMP")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert manifest["format_version"] == 1
    assert manifest["complete"] is True
    assert manifest["media_included"] is False
    with tarfile.open(snapshot / "state.tar.gz") as archive:
        assert "TDL_SESSIONS_DIR/marker" in archive.getnames()
        assert not any("DOWNLOADS_DIR" in name for name in archive.getnames())
    for path in [snapshot, *snapshot.rglob("*")]:
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    admin.restore_database(target_env(admin_env, admin_databases), snapshot, services_stopped=True)
    target = create_engine(admin_databases[1])
    with Session(target) as session:
        row = session.get(DownloadTemplate, original_id)
        assert (row.name, row.output_subfolder) == ("custom", "my-folder")
        assert session.get(RuntimeSettings, 1).values_json == '{"DOWNLOADS_DIR":"/custom/media"}'
        next_row = DownloadTemplate(name="new")
        session.add(next_row)
        session.commit()
        assert next_row.id > original_id
    target.dispose()
    captured = capsys.readouterr()
    secret = "tdl_test"
    assert secret not in captured.out + captured.err + repr(calls)
    assert all("--clean" not in args for args in calls)
    assert all(env["PGPASSWORD"] == "tdl_test" and "UNRELATED_SECRET" not in env for env in environments)


def test_restore_refuses_nonempty_database(admin_env, admin_databases, tmp_path):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    with pytest.raises(RuntimeError, match="vac"):
        admin.restore_database(admin_env, snapshot, services_stopped=True)


def test_restore_requires_stopped_services(admin_env, admin_databases, tmp_path):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    target = target_env(admin_env, admin_databases)
    with pytest.raises(RuntimeError, match="deten"):
        admin.restore_database(target, snapshot)
    target_engine = create_engine(admin_databases[1])
    with target_engine.connect():
        with pytest.raises(RuntimeError, match="conex"):
            admin.restore_database(target, snapshot, services_stopped=True)
    target_engine.dispose()


def test_dump_failure_does_not_report_success(admin_env, admin_databases, tmp_path):
    engine = migrate(admin_databases[0])
    engine.dispose()
    tools = tmp_path / "tools"
    tools.mkdir()
    fake = tools / "pg_dump"
    fake.write_text('#!/bin/sh\ncase "$1" in --version) echo "pg_dump (PostgreSQL) 16.15"; exit 0;; esac\necho "$PGPASSWORD" >&2\nexit 1\n')
    fake.chmod(0o700)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/data-admin.py"), "backup", "--env", str(admin_env), "--destination-root", str(tmp_path / "backups")], env={**os.environ, "PATH": f"{tools}:{os.environ['PATH']}"}, capture_output=True, text=True)
    assert result.returncode != 0
    assert not result.stdout.strip()
    assert "tdl_test" not in result.stderr
    snapshots = list((tmp_path / "backups").iterdir())
    assert len(snapshots) == 1
    assert json.loads((snapshots[0] / "manifest.json").read_text())["complete"] is False


@pytest.mark.parametrize("table,columns,row,message", [
    ("download_jobs", "status text, deletion_requested boolean", "'running',false", "activos"),
    ("download_jobs", "status text, deletion_requested boolean", "'completed',true", "borrados"),
    ("runtime_settings", "operation_status text", "'moving'", "traslado"),
])
def test_backup_requires_idle(admin_env, admin_databases, tmp_path, table, columns, row, message):
    admin = load("data-admin")
    engine = create_engine(admin_databases[0])
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {table} ({columns})"))
        connection.execute(text(f"INSERT INTO {table} VALUES ({row})"))
    engine.dispose()
    with pytest.raises(RuntimeError, match=message):
        admin.backup(admin_env, tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_manifest_tampering_is_rejected_before_restore(admin_env, admin_databases, tmp_path):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    with (snapshot / "database.dump").open("ab") as stream:
        stream.write(b"corrupted")
    with pytest.raises(RuntimeError, match="integridad"):
        admin.restore_database(target_env(admin_env, admin_databases), snapshot, services_stopped=True)


@pytest.mark.parametrize("existing_identical", [False, True])
def test_optional_keys_have_controlled_restore_paths(admin_env, admin_databases, tmp_path, existing_identical):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    before = admin.backup(admin_env, tmp_path / "backups")
    assert not (before / "keys").exists()
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    private.write_text("private-secret")
    public.write_text("public-key")
    with admin_env.open("a") as stream:
        stream.write(f"JWT_PRIVATE_KEY_FILE={private}\nJWT_PUBLIC_KEY_FILE={public}\n")
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    assert (snapshot / "keys/JWT_PRIVATE_KEY_FILE").read_text() == "private-secret"
    target = target_env(admin_env, admin_databases)
    # Source paths in .env and arbitrary manifest metadata are never restore destinations.
    manifest_file = snapshot / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["key_destinations"] = {"JWT_PRIVATE_KEY_FILE": str(private)}
    manifest_file.write_text(json.dumps(manifest))
    if existing_identical:
        keys = tmp_path / "data/keys"
        keys.mkdir()
        (keys / "jwt-private.pem").write_text("private-secret")
        (keys / "jwt-public.pem").write_text("public-key")
    admin.restore_database(target, snapshot, services_stopped=True)
    assert private.read_text() == "private-secret"
    assert (tmp_path / "data/keys/jwt-private.pem").read_text() == "private-secret"
    assert stat.S_IMODE((tmp_path / "data/keys/jwt-private.pem").stat().st_mode) == 0o600


@pytest.mark.parametrize("conflict", ["different_key", "symlink", "file_directory"])
def test_restore_preflights_key_conflicts_before_database(admin_env, admin_databases, tmp_path, conflict):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    private = tmp_path / "private.pem"
    private.write_text("original")
    with admin_env.open("a") as stream:
        stream.write(f"JWT_PRIVATE_KEY_FILE={private}\n")
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    keys = tmp_path / "data/keys"
    if conflict == "file_directory":
        keys.write_text("unrelated")
    else:
        keys.mkdir()
        target = keys / "jwt-private.pem"
        if conflict == "symlink":
            target.symlink_to(private)
        else:
            target.write_text("different")
    with pytest.raises(RuntimeError, match="claves"):
        admin.restore_database(target_env(admin_env, admin_databases), snapshot, services_stopped=True)
    target = create_engine(admin_databases[1])
    with target.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one() == 0
    target.dispose()
    assert private.read_text() == "original"


def test_restore_failure_is_atomic_and_reports_no_success(admin_env, admin_databases, tmp_path):
    import hashlib

    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    with Session(engine) as session:
        session.add(DownloadTemplate(name="large", search_text="x" * 200))
        session.commit()
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    dump = snapshot / "database.dump"
    dump.write_bytes(dump.read_bytes()[:-80])
    manifest_file = snapshot / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["sha256"]["database.dump"] = hashlib.sha256(dump.read_bytes()).hexdigest()
    manifest_file.write_text(json.dumps(manifest))
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/data-admin.py"), "restore-database", "--env", str(target_env(admin_env, admin_databases)), "--backup", str(snapshot), "--services-stopped"], capture_output=True, text=True)
    assert result.returncode != 0
    assert not result.stdout.strip()
    assert "tdl_test" not in result.stderr
    target = create_engine(admin_databases[1])
    with target.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one() == 0
    target.dispose()


def test_restore_refuses_manifest_paths_outside_backup(admin_env, admin_databases, tmp_path):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("keep")
    manifest_file = snapshot / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["sha256"][str(unrelated)] = "ignored"
    manifest_file.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="integridad"):
        admin.restore_database(target_env(admin_env, admin_databases), snapshot, services_stopped=True)
    assert unrelated.read_text() == "keep"


def test_restore_detects_other_role_connections_with_limited_credentials(admin_env, admin_databases, tmp_path):
    from uuid import uuid4

    from sqlalchemy.engine import make_url

    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    role = "tdl_backup_role_" + uuid4().hex
    control = create_engine(admin_databases[1], isolation_level="AUTOCOMMIT")
    with control.connect() as connection:
        connection.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'disposable-role-password'"))
    target = target_env(admin_env, admin_databases)
    target_url = make_url(admin_databases[1]).set(username=role, password="disposable-role-password")
    target.write_text(target.read_text().replace(admin_databases[1], target_url.render_as_string(hide_password=False)))
    try:
        with control.connect():
            with pytest.raises(RuntimeError, match="conex"):
                admin.restore_database(target, snapshot, services_stopped=True)
    finally:
        with control.connect() as connection:
            connection.execute(text(f"DROP ROLE {role}"))
        control.dispose()


@pytest.mark.parametrize("admin_databases", ["equals"], indirect=True)
def test_restore_treats_validated_database_name_as_literal(admin_env, admin_databases, tmp_path):
    admin = load("data-admin")
    engine = migrate(admin_databases[0])
    engine.dispose()
    snapshot = admin.backup(admin_env, tmp_path / "backups")
    admin.restore_database(target_env(admin_env, admin_databases), snapshot, services_stopped=True)
    target = create_engine(admin_databases[1])
    with target.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1
        assert connection.execute(text("SELECT current_database()")).scalar_one().endswith("=literal")
    target.dispose()
