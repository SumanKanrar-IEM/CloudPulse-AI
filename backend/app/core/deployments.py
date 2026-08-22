"""Recording deployments (FR-018, FR-021, FR-023).

**Why this runs in a Lambda rather than on the CI runner.** The `deployment` table lives
in the same private Aurora cluster as everything else, and a GitHub-hosted runner cannot
reach it — the identical constraint that produced the migration Lambda (research.md
R-002). Putting a database credential in a GitHub secret to avoid the hop would violate
Principle III, so the pipeline invokes a Lambda that is already inside the VPC.

FR-021 defines "known, serviceable state" as three conditions, all of which this module
is responsible for the third of: the recorded status must be `failed` rather than left
`running`. A deployment stuck in `running` forever is indistinguishable from one still
in progress, which makes the record useless exactly when it matters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.audit import write_audit_event
from app.core.db import tenant_session
from app.core.logging import logger
from app.models.core import Deployment
from app.models.enums import DeploymentEnvironment, DeploymentStatus


class DeploymentRecordError(RuntimeError):
    """The deployment record could not be written or is invalid."""


def _tenant_id() -> uuid.UUID:
    from sqlalchemy import text

    from app.core.db import get_engine

    with get_engine().connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant ORDER BY created_at LIMIT 1")).scalar_one()))


def record_start(
    *,
    environment: str,
    git_sha: str,
    triggered_by: str,
    approved_by: str | None = None,
    approved_at: str | None = None,
) -> str:
    """Open a deployment record (FR-023).

    For prod, `approved_by` and `approved_at` are mandatory — not by convention but by
    a database CHECK constraint (FR-017, FR-018). The insert fails if they are absent,
    so a prod deployment literally cannot be recorded without a named approver.
    """
    env = DeploymentEnvironment(environment)

    if env is DeploymentEnvironment.PROD and not (approved_by and approved_at):
        raise DeploymentRecordError(
            "a prod deployment requires a recorded approver (FR-017, FR-018). "
            "The database will refuse the insert regardless; this check produces a "
            "clearer failure in the pipeline log."
        )

    # Spec Assumptions: with a single maintainer every prod approval is a
    # self-approval. Permitted, but recorded as such so the merge history stays honest
    # about what kind of gate it was.
    self_approved = bool(approved_by) and approved_by == triggered_by

    tenant = _tenant_id()
    with tenant_session(tenant) as session:
        deployment = Deployment(
            environment=env,
            git_sha=git_sha,
            triggered_by=triggered_by,
            approved_by=approved_by,
            approved_at=datetime.fromisoformat(approved_at) if approved_at else None,
            self_approved=self_approved,
            status=DeploymentStatus.RUNNING,
        )
        # deployment is the one table that is NOT tenant-scoped -- it records an act on
        # the platform, not on a tenant's data. .raw is the sanctioned path for it.
        session.raw.add(deployment)
        session.flush()
        deployment_id = str(deployment.id)

        if env is DeploymentEnvironment.PROD:
            write_audit_event(
                session,
                action="deploy.approve",
                target_type="deployment",
                target_id=deployment_id,
                actor_label=approved_by or triggered_by,
                payload={
                    "environment": env.value,
                    "git_sha": git_sha,
                    "triggered_by": triggered_by,
                    "self_approved": self_approved,
                },
            )

    logger.info(
        "deployment started",
        extra={
            "deployment_id": deployment_id,
            "environment": env.value,
            "git_sha": git_sha,
            "self_approved": self_approved,
        },
    )
    return deployment_id


def record_finish(
    *, deployment_id: str, status: str, migration_revision: str | None = None
) -> None:
    """Close a deployment record (FR-021, FR-023).

    Must be called on failure as well as success. Leaving a row in `running` is the
    third FR-021 condition unmet — the environment may be serviceable, but the record
    does not say so.
    """
    final = DeploymentStatus(status)
    if final is DeploymentStatus.RUNNING:
        raise DeploymentRecordError("record_finish requires a terminal status")

    tenant = _tenant_id()
    with tenant_session(tenant) as session:
        deployment = session.raw.execute(
            select(Deployment).where(Deployment.id == uuid.UUID(deployment_id))
        ).scalar_one_or_none()

        if deployment is None:
            raise DeploymentRecordError(f"no deployment {deployment_id}")

        if deployment.status is not DeploymentStatus.RUNNING:
            # Terminal states are immutable. Re-finishing would rewrite history.
            raise DeploymentRecordError(
                f"deployment {deployment_id} is already {deployment.status.value}"
            )

        deployment.status = final
        deployment.finished_at = datetime.now(UTC)
        if migration_revision:
            deployment.migration_revision = migration_revision
        session.flush()

    logger.info(
        "deployment finished", extra={"deployment_id": deployment_id, "status": final.value}
    )


def latest(environment: str) -> dict[str, Any] | None:
    """The most recent deployment for an environment, for pipeline diagnostics."""
    tenant = _tenant_id()
    with tenant_session(tenant) as session:
        row = session.raw.execute(
            select(Deployment)
            .where(Deployment.environment == DeploymentEnvironment(environment))
            .order_by(Deployment.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "git_sha": row.git_sha,
            "status": row.status.value,
            "approved_by": row.approved_by,
            "self_approved": row.self_approved,
        }


__all__ = ["record_start", "record_finish", "latest", "DeploymentRecordError"]
