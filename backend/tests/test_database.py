from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import DownloadFile, DownloadJob, JobStatus


def test_test_database_requires_explicit_disposable_target(monkeypatch):
    import conftest

    def forbidden_engine(*args, **kwargs):
        pytest.fail("Invalid test targets must not open a connection or clean anything")

    monkeypatch.setattr(conftest, "create_engine", forbidden_engine)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://production/tdl")
    for target in (None, "", "sqlite:///:memory:", "not-a-url"):
        if target is None:
            monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        else:
            monkeypatch.setenv("TEST_DATABASE_URL", target)
        with pytest.raises(ValueError, match="TEST_DATABASE_URL"):
            with conftest.isolated_test_engine():
                pytest.fail("Invalid target accepted")


def test_database_roundtrip(db_session, test_engine):
    assert db_session.bind.dialect.name == "postgresql"
    schema = db_session.scalar(text("SELECT current_schema()"))
    assert schema.startswith("tdl_test_")
    job = DownloadJob(chat_id="roundtrip", output_subfolder="download")
    db_session.add(job)
    db_session.flush()
    with Session(test_engine) as other:
        assert other.scalar(select(DownloadJob).where(DownloadJob.chat_id == "roundtrip")) is None
    db_session.commit()
    with Session(test_engine) as other:
        assert other.get(DownloadJob, job.id).chat_id == "roundtrip"


def test_database_schemas_are_independent_and_cleanup_is_scoped(test_engine):
    from conftest import isolated_test_engine

    with test_engine.begin() as connection:
        outer_schema = connection.scalar(text("SELECT current_schema()"))
        connection.execute(text("CREATE TABLE isolation_marker (id INTEGER)"))
        connection.execute(text("INSERT INTO isolation_marker VALUES (7)"))
    with isolated_test_engine() as other:
        with other.connect() as connection:
            inner_schema = connection.scalar(text("SELECT current_schema()"))
            assert inner_schema != outer_schema
            assert connection.scalar(text("SELECT to_regclass('isolation_marker')")) is None
    with test_engine.connect() as connection:
        assert connection.scalar(text("SELECT id FROM isolation_marker")) == 7
        assert connection.scalar(
            text("SELECT count(*) FROM pg_namespace WHERE nspname = :schema"),
            {"schema": inner_schema},
        ) == 0


def migration_config(connection):
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def test_migrations_from_empty_and_second_upgrade_are_safe():
    from alembic import command
    from conftest import isolated_test_engine

    with isolated_test_engine(migrate=False) as engine:
        with engine.begin() as connection:
            assert inspect(connection).get_table_names() == []
            config = migration_config(connection)
            command.upgrade(config, "head")
            connection.execute(text("INSERT INTO runtime_settings (id, values_json, operation_status) VALUES (7, '{}', 'idle')"))
            command.upgrade(config, "head")
            assert connection.scalar(text("SELECT id FROM runtime_settings")) == 7
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002_identity"
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version", "download_jobs", "download_files", "download_templates", "runtime_settings",
                "users", "external_identities", "auth_sessions", "audit_events",
            }
            command.check(config)
            command.downgrade(config, "base")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            assert inspect(connection).get_enums() == []
            command.upgrade(config, "head")
            command.check(config)


@pytest.mark.parametrize("revision", [None, "0001_application", "old_revision", "future_revision"])
def test_startup_rejects_old_schema(monkeypatch, revision):
    from conftest import isolated_test_engine

    from app import database

    with isolated_test_engine(migrate=False) as engine:
        monkeypatch.setattr(database, "engine", engine)
        if revision:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
                connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision})
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            database.init_db()
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == ({"alembic_version"} if revision else set())


def test_startup_accepts_migrated_schema_without_ddl(monkeypatch, test_engine, tmp_path):
    from sqlalchemy import event

    from app import database
    from app.config import settings

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(test_engine))
    for name in ("base_dir", "sessions_dir", "exports_dir", "downloads_dir", "logs_dir"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    statements = []
    event.listen(test_engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
    database.init_db()
    database.init_db()
    assert settings.downloads_dir.is_dir()
    assert not any(sql.lstrip().upper().startswith(("CREATE", "ALTER", "DROP")) for sql in statements)


def test_bytes_exceed_32_bits(db_session, test_engine):
    job = DownloadJob(chat_id="large", output_subfolder="download", download_observed_bytes=5_000_000_000, download_speed_bps=3_000_000_000)
    job.files.append(DownloadFile(chat_id="large", message_id="1", file_name="large.bin", message_json="{}", destination_root="/tmp", output_dir="/tmp/large", expected_size=5_000_000_000, size=5_000_000_000))
    db_session.add(job)
    db_session.commit()
    with Session(test_engine) as fresh:
        file = fresh.scalar(select(DownloadFile))
        assert file.size == 5_000_000_000
        assert file.expected_size == 5_000_000_000
        stored = fresh.get(DownloadJob, job.id)
        assert stored.download_observed_bytes == 5_000_000_000
        assert stored.download_speed_bps == 3_000_000_000
        assert fresh.scalar(select(func.sum(DownloadFile.size))) == 5_000_000_000
        assert stored.created_at.tzinfo is not None
        assert stored.created_at.utcoffset() == UTC.utcoffset(datetime.now(UTC))


def test_active_dedupe_is_partial(db_session):
    db_session.add_all([
        DownloadJob(chat_id="same", output_subfolder="download", dedupe_key="same", status=JobStatus.completed),
        DownloadJob(chat_id="same", output_subfolder="download", dedupe_key="same", status=JobStatus.completed),
        DownloadJob(chat_id="same", output_subfolder="download", dedupe_key="same", status=JobStatus.pending),
    ])
    db_session.commit()
    db_session.add(DownloadJob(chat_id="same", output_subfolder="download", dedupe_key="same", status=JobStatus.running))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(DownloadJob)) == 3


def test_rq_worker_rejects_unmigrated_schema(monkeypatch):
    from conftest import isolated_test_engine

    from app import database, rq_worker

    with isolated_test_engine(migrate=False) as engine:
        monkeypatch.setattr(database, "engine", engine)
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            rq_worker.main()


@pytest.mark.parametrize(("age_seconds", "expected_status"), [(1, JobStatus.pending), (60, JobStatus.failed)])
def test_queue_reconciliation_compares_persisted_utc_times(db_session, monkeypatch, age_seconds, expected_status):
    from rq.exceptions import NoSuchJobError

    from app.services import jobs

    job = DownloadJob(chat_id="queue-gap", output_subfolder="download", rq_job_id="not-enqueued", rq_enqueued_at=datetime.now(UTC) - timedelta(seconds=age_seconds))
    db_session.add(job)
    db_session.commit()
    db_session.expire_all()
    monkeypatch.setattr(jobs.Redis, "from_url", lambda *a, **kw: SimpleNamespace(ping=lambda: True))

    def missing(*args, **kwargs):
        raise NoSuchJobError("missing")

    monkeypatch.setattr(jobs.Job, "fetch", missing)
    jobs.sync_pending_jobs_with_queue(db_session)
    db_session.expire_all()
    assert db_session.get(DownloadJob, job.id).status == expected_status
