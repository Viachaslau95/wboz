from __future__ import annotations

import os
import re
from collections.abc import Iterable
from logging.config import fileConfig
from pathlib import Path

from alembic.operations.ops import MigrationScript
from alembic.runtime.migration import MigrationContext
from sqlalchemy import engine_from_config, pool

from alembic import context
from app.db import models  # noqa: F401
from app.db.base import Base
from app.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

VERSIONS_DIR = Path(__file__).resolve().parent / "versions"


def _build_alembic_database_url() -> str:
    database_url = settings.database_url_sync
    if not database_url:
        database_url = config.get_main_option("sqlalchemy.url")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for Alembic")
    return database_url


def get_next_migration_number(versions_dir: Path = VERSIONS_DIR) -> str:
    migration_re = re.compile(r"^(\d{4})_.*\.py$")
    max_num = 0

    if versions_dir.exists():
        for filename in os.listdir(versions_dir):
            match = migration_re.match(filename)
            if match:
                max_num = max(max_num, int(match.group(1)))

    return f"{max_num + 1:04d}"


def process_revision_directives(
    _: MigrationContext,
    __: str | Iterable[str | None] | Iterable[str],
    directives: list[MigrationScript],
) -> None:
    if not directives:
        return

    script = directives[0]
    if hasattr(script, "message") and script.message:
        script.message = f"{get_next_migration_number()}_{script.message}"


config.set_main_option("sqlalchemy.url", _build_alembic_database_url())


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
