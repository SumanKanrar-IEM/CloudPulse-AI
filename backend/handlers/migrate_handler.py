"""Migration Lambda (FR-016, research.md R-002).

**Why this exists at all.** FR-016 requires migrations to be applied before the new
service version serves traffic. Aurora sits in private subnets with no public endpoint,
and a GitHub-hosted runner is outside the VPC, so the pipeline cannot reach the database
directly. The alternatives were worse:

* expose Aurora publicly and run Alembic on the runner -- puts the governance store on
  the internet and needs a database password in a GitHub secret (Principle III);
* a self-hosted runner inside the VPC -- disproportionate infrastructure;
* migrate during the API's cold start -- makes every concurrent cold start race.

A Lambda in the same subnets reaches the cluster, reuses the same execution-role and
Secrets Manager path as the API (so no credential ever reaches the runner), and returns
a clean pass/fail the pipeline can gate on.

Invoked synchronously by ``deploy-dev.yml`` / ``deploy-prod.yml``; a non-zero result
fails the deployment before the API alias shifts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from app.core.logging import logger

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_COMMANDS = frozenset(
    {
        "upgrade",
        "current",
        "history",
        # Deployment recording shares this Lambda because it faces the same
        # constraint: the deployment table is in the private subnet and the CI runner
        # cannot reach it (R-002). A second Lambda would duplicate the VPC config, the
        # role and the package for two functions the pipeline always calls together.
        "record_start",
        "record_finish",
    }
)


def _config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return cfg


def _record(command: str, event: dict[str, Any]) -> dict[str, Any]:
    """Open or close a deployment record (FR-018, FR-023)."""
    from app.core import deployments

    try:
        if command == "record_start":
            deployment_id = deployments.record_start(
                environment=event["environment"],
                git_sha=event["git_sha"],
                triggered_by=event["triggered_by"],
                approved_by=event.get("approved_by"),
                approved_at=event.get("approved_at"),
            )
            return {"ok": True, "deployment_id": deployment_id}

        deployments.record_finish(
            deployment_id=event["deployment_id"],
            status=event["status"],
            migration_revision=event.get("migration_revision"),
        )
        return {"ok": True}
    except Exception as exc:
        logger.exception("deployment record failed", extra={"error_type": type(exc).__name__})
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Run one Alembic command.

    ``downgrade`` is deliberately absent from ALLOWED_COMMANDS. A rollback is a
    deliberate, human act -- revision 0003 is irreversible by design (FR-029), and an
    automated downgrade path would make undoing the audit-immutability controls a
    single API call.
    """
    requested = str(event.get("command", "upgrade"))
    revision = str(event.get("revision", "head"))

    if requested not in ALLOWED_COMMANDS:
        logger.error("rejected migration command", extra={"command": requested})
        return {
            "ok": False,
            "error": (
                f"command '{requested}' is not permitted. Allowed: "
                f"{sorted(ALLOWED_COMMANDS)}. Downgrades are deliberate manual acts."
            ),
        }

    if requested in {"record_start", "record_finish"}:
        return _record(requested, event)

    logger.info("running migration", extra={"command": requested, "revision": revision})

    try:
        if requested == "upgrade":
            command.upgrade(_config(), revision)
        elif requested == "current":
            command.current(_config())
        else:
            command.history(_config())
    except Exception as exc:
        # Return rather than raise: the pipeline reads the payload, and an exception
        # trace in a Lambda error response is harder to gate on than a flag.
        logger.exception("migration failed", extra={"error_type": type(exc).__name__})
        return {"ok": False, "command": requested, "error": f"{type(exc).__name__}: {exc}"}

    logger.info("migration complete", extra={"command": requested, "revision": revision})
    return {
        "ok": True,
        "command": requested,
        "revision": revision,
        "environment": os.environ.get("CLOUDPULSE_ENVIRONMENT", "unknown"),
    }


__all__ = ["handler", "ALLOWED_COMMANDS"]
