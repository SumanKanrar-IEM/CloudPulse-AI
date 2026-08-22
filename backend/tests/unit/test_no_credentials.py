"""No credential, secret, or long-lived key is committed (FR-013, SC-012).

A local mirror of the CI secret-scanning job, so a leak is caught by `make check`
before it reaches a pull request. Constitution Principle III is NON-NEGOTIABLE, and
the cheapest place to enforce it is before the commit.

Deliberately pattern-based rather than entropy-based: entropy scanners are noisy on
Terraform ARNs and generated lockfiles, and a noisy gate gets ignored.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Patterns that indicate a real credential rather than a reference to one.
CREDENTIAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "AWS secret access key assignment": re.compile(
        r"aws_secret_access_key\s*[=:]\s*['\"][A-Za-z0-9/+=]{40}['\"]", re.IGNORECASE
    ),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    "hardcoded password assignment": re.compile(
        r"\b(?:password|passwd|pwd)\s*[=:]\s*['\"](?!\s*$)(?![{$<])[^'\"\n]{8,}['\"]",
        re.IGNORECASE,
    ),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
}

SCAN_SUFFIXES = {".py", ".ts", ".js", ".tf", ".tfvars", ".yml", ".yaml", ".json", ".sh", ".toml"}

# Files whose purpose is to define, test, or allowlist credential patterns.
# See the rule in _files_to_scan before adding to this set.
SCANNER_OWN_FIXTURES = {
    "test_no_credentials.py",   # defines the patterns it searches for
    "test_log_redaction.py",    # asserts secret-shaped values ARE redacted (FR-046)
    ".gitleaks.toml",           # its allowlist must name what it allows
}

SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".terraform",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
    # The fixtures exist precisely to contain a fake credential (T020).
    "ci-fixtures",
}


def _files_to_scan(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # Some files necessarily contain credential-SHAPED strings because their
        # purpose is to detect or redact credentials. The rule for this list, to be
        # applied before adding to it:
        #
        #   Does the file exist to DEFINE, TEST, or ALLOWLIST credential patterns?
        #     -> excluded. Its fixtures are inert published examples.
        #   Does it merely happen to contain something that looks like a secret?
        #     -> NOT excluded. That is the finding.
        #
        # Every entry is a specific filename, never a directory glob: a broad
        # exclusion is how a credential scanner quietly stops working.
        if path.name in SCANNER_OWN_FIXTURES:
            continue
        out.append(path)
    return out


@pytest.mark.parametrize("label", sorted(CREDENTIAL_PATTERNS))
def test_no_committed_credentials(repo_root: Path, label: str) -> None:
    """SC-012: a repo-wide scan finds zero credentials or long-lived keys."""
    pattern = CREDENTIAL_PATTERNS[label]
    hits: list[str] = []
    for path in _files_to_scan(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(repo_root)}:{lineno}")
    assert not hits, f"{label} found (FR-013, Principle III): {hits}"


def test_scanner_actually_matches_a_known_credential_shape() -> None:
    """Guard against the scan silently passing because a pattern stopped matching.

    A credential scanner that matches nothing looks identical to a clean repository,
    which is the failure mode worth defending against.
    """
    sample = "AKIAIOSFODNN7EXAMPLE"  # AWS's own published example key
    assert CREDENTIAL_PATTERNS["AWS access key id"].search(sample)


def test_terraform_definitions_hold_no_secrets(repo_root: Path) -> None:
    """FR-007: environment definitions must contain no credentials of any kind."""
    infra = repo_root / "infra"
    if not infra.exists():
        pytest.skip("infra/ not present")
    offenders: list[str] = []
    for path in infra.rglob("*.tf*"):
        if ".terraform" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in CREDENTIAL_PATTERNS.items():
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(repo_root)}:{lineno} ({label})")
    assert not offenders, f"FR-007 violation -- secret in environment definitions: {offenders}"
