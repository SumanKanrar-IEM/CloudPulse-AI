"""Declarative base and the conventions every table follows.

These are enforced here rather than restated per model, so a table added by a later
spec inherits them by construction:

* **UUID primary key** defaulted server-side by ``gen_random_uuid()``.
* **Tenant scoping (FR-030)** -- every table except ``tenant`` and ``deployment``
  carries an indexed, non-null ``tenant_id``. ``deployment`` is the one deliberate
  exception: it records an act on the platform itself, not on a tenant's data.
* **Timestamps** -- ``created_at`` / ``updated_at``, server-defaulted.
* **No soft delete.** A record is live or genuinely gone; audit events are never
  removed at all (FR-029a).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Without this Alembic autogenerate produces
# database-assigned names that differ between environments, and FR-003's "unchanged
# definitions report no changes" guarantee quietly stops holding.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    """``id UUID PRIMARY KEY DEFAULT gen_random_uuid()``."""

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TenantScoped:
    """FR-030: a tenant-scoped table can never be read across tenant boundaries.

    The column and its index are declared here so no later spec can add a
    tenant-scoped table and forget either one. Enforcement at query time lives in
    ``app.core.db``; this is the schema half.
    """

    @property
    def __tenant_column__(self) -> str:
        return "tenant_id"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


__all__ = ["Base", "UUIDPrimaryKey", "Timestamps", "TenantScoped", "Index", "NAMING_CONVENTION"]
