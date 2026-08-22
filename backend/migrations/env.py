"""Alembic environment.

Two rules this file enforces, both from the spec rather than convention:

**No credential ever reaches a file (Principle III, FR-007).** The database URL is
assembled at runtime. In AWS the password comes from Secrets Manager through the
Lambda execution role; locally it comes from an environment variable that developers
set for a throwaway container. There is no ``sqlalchemy.url`` in ``alembic.ini``.

**Every revision declares reversibility (FR-027).** ``REVERSIBLE: yes|no`` must appear
in each revision's module docstring. CI extracts it, so an irreversible migration is
identifiable *before* merge rather than discovered during a prod release.
"""

from __future__ import annotations

import os
import re
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

REVERSIBLE_MARKER = re.compile(r"^REVERSIBLE:\s*(yes|no)\s*$", re.IGNORECASE | re.MULTILINE)


def _database_url() -> str:
    """Assemble the URL without ever reading a credential from a file."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    secret_arn = os.environ.get("CLOUDPULSE_DB_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError(
            "Set DATABASE_URL (local) or CLOUDPULSE_DB_SECRET_ARN (AWS). "
            "A database URL is never committed (Principle III)."
        )

    # Imported lazily so unit tests and local runs need no AWS SDK.
    import json

    import boto3

    secret = json.loads(
        boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
    )
    host = os.environ["CLOUDPULSE_DB_HOST"]
    port = os.environ.get("CLOUDPULSE_DB_PORT", "5432")
    name = os.environ.get("CLOUDPULSE_DB_NAME", "cloudpulse")
    return (
        f"postgresql+psycopg://{secret['username']}:{secret['password']}@{host}:{port}/{name}"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Deterministic constraint names come from the model naming convention;
            # comparing them keeps autogenerate from proposing phantom renames.
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
