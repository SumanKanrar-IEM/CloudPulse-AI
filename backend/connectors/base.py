"""The provider-agnostic connector protocol and normalized resource model (FR-014).

Spec 1's FR-054 reserved this package and fixed the boundary rule: no cloud-provider
SDK type may cross **out** of `connectors/`. This module is the interface side of
that boundary -- everything in `app/` and `handlers/` (outside `connectors/` and
`migrations/`) consumes `NormalizedResource` and `Connector` only, never a boto3
response shape directly.

A second provider (e.g. GCP, Azure) implements `Connector` in a second file here;
no code that consumes `NormalizedResource` needs to change (Principle V's own test,
FR-014).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ConnectorAccount:
    """The minimal identity a connector needs to reach one account.

    Deliberately not `app.models.core.CloudAccount`: importing the ORM model here
    would couple the connector boundary to the persistence layer, and a second
    provider's connector should need nothing about how CloudPulse stores accounts.

    ``external_id`` is the resolved secret *value*, held only in memory for the life
    of one unit of work (research.md R-206) -- never the Secrets Manager reference
    itself, and never persisted or logged (Principle III).
    """

    aws_account_id: str
    connection_mode: str  # "local" | "assume_role" -- kept as str for the same reason
    role_arn: str | None = None
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedResource:
    """The FR-013 shape. A 1:1 mapping onto `resource`'s columns.

    ``resource_id`` is the provider-native unique identifier (FR-015) -- an ARN for
    AWS, mapped onto `resource.arn` by the persistence layer. ``detail`` carries
    FR-019's service-specific enrichment payload; empty until a connector's
    ``enrich()`` populates it.
    """

    provider: str
    account_id: str
    resource_id: str
    service: str
    resource_type: str
    region: str
    name: str | None
    tags: dict[str, str]
    state: str | None
    created_at: datetime | None
    detail: dict[str, Any] = field(default_factory=dict)


class Connector(Protocol):
    """Provider-agnostic discovery and enrichment (FR-014, Principle V)."""

    def discover(self, account: ConnectorAccount, region: str) -> Iterable[NormalizedResource]:
        """Enumerate resources in one region via generic discovery surfaces (R-201).

        Must find resources regardless of whether they carry tags (FR-017), and must
        not rely on a fixed, hand-maintained per-service list (FR-016).
        """
        ...

    def enrich(self, resource: NormalizedResource) -> NormalizedResource:
        """Return `resource` with `detail` populated via a targeted describe (R-202).

        Returns a new, fully-populated `NormalizedResource` rather than mutating the
        input -- the dataclass is frozen, and callers should not need to know that.
        """
        ...


__all__ = ["ConnectorAccount", "NormalizedResource", "Connector"]
