"""Database engine, session, and tenant scoping.

Three requirements shape this module:

**Principle III / FR-007 -- no stored credential.** The password is fetched from
Secrets Manager through the Lambda execution role and cached in the execution context.
It is never a setting, never in source, never in Terraform state (the cluster uses
``manage_master_user_password``, so AWS owns it end to end).

**research.md R-003 -- NullPool.** Lambda freezes its execution context between
invocations. SQLAlchemy's default pool would hold connections across that freeze and
strand them, and the failure mode -- intermittent exhaustion under load -- surfaces at
the worst possible moment. NullPool opens and closes per session; RDS Proxy does the
pooling on the far side of the boundary.

**FR-030 -- tenant scoping.** ``TenantSession`` refuses to query a tenant-scoped model
without a tenant filter. Enforcement is at the query layer rather than the schema, and
is deliberately fail-closed: forgetting the filter raises rather than returning another
tenant's rows.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, TypeVar

from sqlalchemy import Engine, Select, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.models.base import TenantScoped

T = TypeVar("T")


class TenantScopeError(RuntimeError):
    """A tenant-scoped model was queried without a tenant filter (FR-030)."""


@lru_cache(maxsize=1)
def _resolve_credentials(secret_arn: str) -> tuple[str, str]:
    """Fetch the master credential from Secrets Manager.

    Cached for the life of the execution context: one call per cold start, not one per
    request. boto3 is imported lazily so unit tests need no AWS SDK at import time.
    """
    import boto3

    payload = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    secret: dict[str, Any] = json.loads(payload["SecretString"])
    return secret["username"], secret["password"]


def build_database_url(settings: Settings | None = None) -> str:
    """Assemble the connection URL. The password exists only in memory."""
    settings = settings or get_settings()
    username, password = _resolve_credentials(settings.db_secret_arn)
    return (
        f"postgresql+psycopg://{username}:{password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Engine for the current execution context.

    ``NullPool`` is not a performance compromise here -- it is the correct choice for
    Lambda, where a pooled connection outlives the context that owns it (R-003).
    """
    settings = get_settings()
    return create_engine(
        build_database_url(settings),
        poolclass=NullPool,
        pool_pre_ping=True,
        echo=False,
        connect_args={"application_name": settings.service_name},
    )


class TenantSession:
    """A session bound to exactly one tenant (FR-030).

    Wraps ``Session`` rather than subclassing it, so the only way to run a query is
    through methods that apply the tenant filter. A subclass would leave
    ``session.query`` and ``session.execute`` reachable unfiltered, which is precisely
    the gap FR-030 closes.
    """

    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> uuid.UUID:
        return self._tenant_id

    @property
    def raw(self) -> Session:
        """The underlying session.

        For the deliberate exceptions only -- ``deployment``, which is not
        tenant-scoped, and migrations. Reaching for this to bypass a tenant filter is
        an FR-030 violation, and a reviewer should treat it as one.
        """
        return self._session

    def scoped(self, statement: Select[Any], model: type[Any]) -> Select[Any]:
        """Apply the tenant filter, or refuse.

        Fail-closed by design: a model that *should* be tenant-scoped but is not raises
        rather than silently returning every tenant's rows.
        """
        if not issubclass(model, TenantScoped):
            raise TenantScopeError(
                f"{model.__name__} is not tenant-scoped. If it holds tenant data it must "
                f"inherit TenantScoped (FR-030); if it genuinely does not -- like "
                f"Deployment -- use .raw and say why."
            )
        return statement.where(model.tenant_id == self._tenant_id)

    def add(self, instance: Any) -> None:
        """Add an instance, stamping the tenant so a caller cannot forget it."""
        if isinstance(instance, TenantScoped):
            existing = getattr(instance, "tenant_id", None)
            if existing is not None and existing != self._tenant_id:
                raise TenantScopeError(
                    f"refusing to write a row for tenant {existing} through a session "
                    f"scoped to {self._tenant_id} (FR-030)"
                )
            instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: uuid.UUID) -> Iterator[TenantSession]:
    """Open a tenant-scoped session, committing on success and rolling back on error."""
    session = _session_factory()()
    try:
        yield TenantSession(session, tenant_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "TenantSession",
    "TenantScopeError",
    "tenant_session",
    "get_engine",
    "build_database_url",
]
