"""Integration fixtures — a real PostgreSQL, not an emulation.

research.md R-007: LocalStack's free tier covers neither Cognito nor RDS, so the
strategy is split by dependency rather than forced through one tool. For the database
that is not a compromise — FR-026 requires migrations to apply cleanly to a *populated*
store, and only a real engine proves that. Emulation would let a PostgreSQL-specific
trigger, partial index, or native enum pass here and fail in production.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]

try:
    # Moved in newer testcontainers; keep the legacy path as a fallback so the suite
    # runs on either version rather than skipping silently.
    from testcontainers.community.postgres import (
        PostgresContainer,  # type: ignore[import-not-found]
    )
except ImportError:  # pragma: no cover
    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore[no-redef]
    except ImportError:
        PostgresContainer = None  # type: ignore[assignment,misc]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A throwaway PostgreSQL 16, matching the Aurora engine version in infra."""
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    try:
        with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
            yield pg.get_connection_url()
    except Exception as exc:  # Docker unavailable in this environment
        pytest.skip(f"Docker unavailable: {exc}")


@pytest.fixture
def engine(postgres_url: str) -> Iterator[Engine]:
    eng = create_engine(postgres_url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def clean_database(engine: Engine) -> Iterator[Engine]:
    """A database with no schema, so each test starts from truly nothing."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    yield engine


@pytest.fixture
def alembic_config(postgres_url: str):  # type: ignore[no-untyped-def]
    """Alembic pointed at the container.

    DATABASE_URL is set in the environment rather than written to alembic.ini —
    Principle III forbids a credential in a committed file, and the test must exercise
    the same code path production uses.
    """
    from alembic.config import Config

    os.environ["DATABASE_URL"] = postgres_url
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return cfg


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def _noop_governance_enqueue(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """T026 (spec 003, research.md R-303) added an SQS enqueue call to
    `finalize_scan` -- a no-op here by default so every finalize_scan-calling
    test that predates this spec keeps testing what it already tests (scan
    status transitions, diffing, history), not SQS wiring.

    `test_governance_worker_wiring.py` (T030) overrides this fixture -- same
    name, nearer scope wins in pytest -- to exercise the real enqueue call
    against moto-mocked SQS queues instead.
    """
    monkeypatch.setattr("app.scan.orchestrator._enqueue_governance_messages", lambda scan: None)
    yield
