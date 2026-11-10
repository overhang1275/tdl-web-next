from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def check_schema() -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    try:
        with engine.connect() as connection:
            current = set(MigrationContext.configure(connection).get_current_heads())
    except SQLAlchemyError:
        raise RuntimeError("PostgreSQL is unavailable; check database connectivity and run alembic upgrade head.") from None
    if current != expected:
        raise RuntimeError("Database schema is incompatible; run alembic upgrade head before starting TDL.")


def init_db() -> None:
    check_schema()
    from app.services.runtime_settings import load_runtime

    with SessionLocal() as db:
        load_runtime(db)
    settings.ensure_directories()


def get_db():
    db = SessionLocal()
    try:
        from app.services.runtime_settings import load_runtime

        load_runtime(db)
        yield db
    finally:
        db.close()
