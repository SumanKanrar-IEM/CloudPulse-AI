#!/usr/bin/env python3
"""Fail if a cloud-provider SDK type leaks out of `backend/connectors/`.

Enforces FR-054 and constitution Principle V (Contract-First Modularity).

The rule
--------
Provider SDK imports (`boto3`, `botocore`, and provider-specific client modules)
are permitted **only** inside `backend/connectors/`, plus a small set of places
that legitimately talk to AWS for infrastructure reasons rather than for cloud
*discovery*: Lambda handlers, the Secrets Manager fetch in `app/core/db.py`, and
tests.

Everything else -- `app/api/`, `app/models/`, `app/scan/`, `app/workers/` -- must
consume the normalized resource model that spec 002 defines behind the connector
boundary.

Why this ships before the code it guards
----------------------------------------
Spec 001 reserves the connector package; spec 002 (backlog S11) writes the
protocol. If the first connector is written without this gate already green,
provider types leak into core code within days and Principle V's "new providers
ship without modifying core code" property is lost quietly. The gate has nothing
to catch until spec 002 lands -- it must still be green from the day it ships.

Exit codes: 0 clean, 1 violation found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

PROVIDER_MODULES = {"boto3", "botocore", "aiobotocore", "boto3.session", "mypy_boto3"}

# Paths where a provider import is legitimate, relative to backend/.
#
# The test for adding an entry here -- apply it before widening this list:
#
#   Does the import reach into a SCANNED cloud account (discovery, inventory,
#   enrichment)?              -> NOT allowed. It belongs behind the connector.
#   Does it operate the PLATFORM'S OWN infrastructure (fetching the platform
#   database credential, Lambda runtime plumbing)?  -> allowed.
#
# Widening this list reflexively is how a gate stops meaning anything. Each entry
# below names its reason, and a new one must too.
ALLOWED_PREFIXES = (
    "connectors/",              # the boundary itself -- FR-054
    "handlers/",                # Lambda entrypoints wire AWS runtime plumbing
    "app/core/db.py",           # Secrets Manager fetch for the platform's own DB (Principle III)
    "migrations/env.py",        # same fetch, same reason: Alembic needs the DB credential
                                # at migration time and must not read it from a file
    "app/scan/orchestrator.py", # starts/manages executions of the platform's OWN Step
                                # Functions state machine (spec 002, T045) -- operating
                                # the platform's own orchestration infrastructure, not
                                # reaching into a scanned account, same class of
                                # exception as the DB credential fetch above
    "tests/",                   # moto-based mocks, no real calls (FR-010)
)


def _is_allowed(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _provider_imports(tree: ast.AST) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in PROVIDER_MODULES:
                    hits.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in PROVIDER_MODULES:
                hits.append((node.lineno, node.module))
    return hits


def main() -> int:
    if not BACKEND.exists():
        sys.stdout.write("connector-boundary: OK (no backend/ yet)\n")
        return 0

    violations: list[str] = []
    checked = 0

    # Our source only. Build artefacts stage vendored third-party packages (boto3,
    # s3transfer, ...) which legitimately import botocore -- scanning them would report
    # every dependency as a boundary violation. CI never sees these directories; this
    # keeps the local run honest too.
    SKIP_ROOTS = (".venv/", "venv/", "build/", "dist/", "site-packages/", "__pycache__/")

    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if any(rel.startswith(r) or f"/{r}" in f"/{rel}" for r in SKIP_ROOTS):
            continue
        checked += 1
        if _is_allowed(rel):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # a syntax error is ruff's job to report, not ours
            sys.stderr.write(f"connector-boundary: skipping unparseable {rel}: {exc}\n")
            continue
        for lineno, module in _provider_imports(tree):
            violations.append(
                f"backend/{rel}:{lineno}: imports '{module}'. Provider SDK types must not "
                f"cross out of backend/connectors/ (FR-054). Consume the normalized "
                f"resource model instead."
            )

    if violations:
        sys.stderr.write("FR-054 violation -- provider SDK leaked outside the connector boundary:\n\n")
        for v in violations:
            sys.stderr.write(f"  {v}\n")
        return 1

    sys.stdout.write(f"connector-boundary: OK ({checked} file(s) checked, 0 violations)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
