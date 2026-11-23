"""Alembic's entry point: runs migrations against the database the app is configured for.

Three ways in:
- `alembic upgrade head` (online): connect using DIRECT_DATABASE_URL, else DATABASE_URL.
- `alembic upgrade head --sql` (offline): print the SQL instead of running it.
- tests: they pass an open connection in `config.attributes["connection"]`, so migrations run
  on the test database inside the tests' own control, and logging is left untouched.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata
passed_connection: Connection | None = config.attributes.get("connection")

if config.config_file_name is not None and passed_connection is None:
    fileConfig(config.config_file_name)


def migration_url() -> str:
    # A pooled (transaction-mode) URL can't hold the session a migration needs.
    settings = get_settings()
    return settings.direct_database_url or settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_on(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if passed_connection is not None:
        run_on(passed_connection)
        return
    # NullPool: a migration run is one short-lived process; there is nothing to pool.
    engine = create_engine(migration_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_on(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
