from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session


@contextmanager
def isolated_test_engine(*, migrate=True):
    raw_url = os.environ.get("TEST_DATABASE_URL", "")
    try:
        url = make_url(raw_url)
        if url.get_backend_name() != "postgresql" or not url.database:
            raise ValueError
    except (ArgumentError, ValueError):
        raise ValueError("TEST_DATABASE_URL must explicitly name a disposable PostgreSQL database") from None

    url = url.set(drivername="postgresql+psycopg")
    schema = f"tdl_test_{uuid4().hex}"
    control = create_engine(url, pool_pre_ping=True)
    engine = None
    created = False
    try:
        with control.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        engine = create_engine(
            url, connect_args={"options": f"-csearch_path={schema}"}, pool_pre_ping=True
        )
        if migrate:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with control.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            control.dispose()


@pytest.fixture
def test_engine():
    with isolated_test_engine() as engine:
        yield engine


@pytest.fixture
def db_session(test_engine):
    with Session(test_engine, expire_on_commit=False) as session:
        yield session
