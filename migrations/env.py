"""Ambiente Alembic — usa Base.metadata dos modelos ORM e ASO_DATABASE_URL."""

from __future__ import annotations

import os

from sqlalchemy import create_engine

from alembic import context
from aso.db.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("ASO_DATABASE_URL", "sqlite:///aso.db")


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_url())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
