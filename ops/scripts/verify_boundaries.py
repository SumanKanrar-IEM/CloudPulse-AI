#!/usr/bin/env python3
"""Verify the architectural boundaries hold in the built system (T125).

Checks FR-013a and FR-054 to FR-057 -- the requirements added during analyze remediation
that constrain what specs 002-006 may do. They are worth re-checking as a set because
each one is a *negative* property (no leak, no credential, no undocumented delegation),
and negative properties rot silently.

Exit codes: 0 all hold, 1 one or more failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "specs" / "001-platform-foundation"


def _contains(path: Path, *needles: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return all(n in text for n in needles)


def _script_passes(name: str) -> bool:
    return subprocess.run(
        [sys.executable, str(ROOT / "ops" / "scripts" / name)],
        capture_output=True,
    ).returncode == 0


CHECKS: list[tuple[str, str, object]] = [
    (
        "FR-013a",
        "CI dependency-allowlist gate passes (no non-AWS AI runtime)",
        lambda: _script_passes("check_dependencies.py"),
    ),
    (
        "FR-054",
        "no provider SDK leaks outside backend/connectors/",
        lambda: _script_passes("check_connector_boundary.py"),
    ),
    (
        "FR-054",
        "connector package reserved, boundary rule stated, protocol delegated to spec 002",
        lambda: _contains(ROOT / "backend/connectors/README.md", "FR-054", "spec 002", "S11"),
    ),
    (
        "FR-055",
        "finding lifecycle and SDA semantics explicitly delegated to spec 003",
        lambda: _contains(SPEC / "spec.md", "FR-055")
        and _contains(SPEC / "data-model.md", "FR-055", "spec 3"),
    ),
    (
        "FR-056",
        "agent access path exists and is read-only by construction",
        lambda: _contains(
            ROOT / "backend/app/core/agent_access.py", "READ_ONLY_METHODS", "AgentPrincipal"
        ),
    ),
    (
        "FR-056",
        "agent access path references no credential mechanism",
        lambda: not any(
            token in (ROOT / "backend/app/core/agent_access.py").read_text()
            for token in ("boto3", "get_secret_value", "assume_role", "AccessKey")
        ),
    ),
    (
        "FR-056",
        "agents scaffold states the constraint spec 006 must build against",
        lambda: _contains(ROOT / "agents/README.md", "FR-056", "read-only"),
    ),
    (
        "FR-057",
        "breaking-change procedure documented before it is needed",
        lambda: _contains(
            ROOT / "ops/runbooks/contract-changes.md", "add-new", "FR-048c"
        ),
    ),
]


def main() -> int:
    failures = 0
    for requirement, description, check in CHECKS:
        try:
            ok = bool(check())  # type: ignore[operator]
        except Exception as exc:
            ok = False
            description = f"{description}  [{type(exc).__name__}: {exc}]"
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  {status}  {requirement:8} {description}")

    print()
    if failures:
        print(f"{failures} boundary check(s) failed.", file=sys.stderr)
        return 1
    print(f"All {len(CHECKS)} boundary checks hold (T125).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
