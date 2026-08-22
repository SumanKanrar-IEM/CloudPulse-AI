#!/usr/bin/env python3
"""Fail if a Terraform attribute VALUE contains a non-ASCII character.

Several AWS APIs reject non-ASCII outright -- `CreateSecurityGroup` returns
`InvalidParameterValue: Character sets beyond ASCII are not supported` for a
`GroupDescription` containing so much as an em-dash.

`terraform validate` does not catch this, and neither does `terraform plan`: the value
is syntactically fine and only the live API rejects it. So it surfaces mid-apply, after
some resources have already been created -- which is the worst time to find it.

Comments are exempt: they never leave the repository. Only values do.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# attribute = "value"  -- the form that becomes an API parameter.
ASSIGNMENT = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(.*)"\s*$')


def main() -> int:
    violations: list[str] = []
    scanned = 0

    for path in sorted((ROOT / "infra").rglob("*.tf")):
        if ".terraform" in path.parts:
            continue
        scanned += 1
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            match = ASSIGNMENT.match(line)
            if not match:
                continue
            value = match.group(2)
            offenders = sorted({c for c in value if ord(c) > 127})
            if offenders:
                rel = path.relative_to(ROOT)
                violations.append(
                    f"{rel}:{lineno}: {match.group(1)} contains {offenders!r}\n"
                    f"      {value[:80]}"
                )

    if violations:
        sys.stderr.write(
            "Non-ASCII in Terraform attribute values. Several AWS APIs reject these "
            "outright, and the failure only appears mid-apply:\n\n"
        )
        for v in violations:
            sys.stderr.write(f"  {v}\n")
        sys.stderr.write("\nUse plain ASCII in values. Comments may use anything.\n")
        return 1

    sys.stdout.write(f"terraform-ascii: OK ({scanned} file(s) scanned, 0 violations)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
