from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import DownloadJob


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
