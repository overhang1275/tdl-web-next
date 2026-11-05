from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401
from app.config import settings
from app.database import Base

config = context.config
target_metadata = Base.metadata


def run_migrations(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Migrations require PostgreSQL")
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
    else:
        engine = create_engine(settings.database_url, poolclass=pool.NullPool)
        try:
            with engine.connect() as connection:
                run_migrations(connection)
        finally:
            engine.dispose()
