"""Same-account mode reads with the platform's own roles (spec 002, T063; FR-002, FR-007).

Cross-account mode gets its read-only set from `cross_account_template.yaml`'s scanner
role. Same-account mode has no such role: registration verifies with the API role and
discovery runs as the scan worker, so both need the equivalent grants in Terraform.
Neither had them, and it went unseen until the VPC had egress (T143) -- these tests
parse the Terraform so the two lists cannot drift apart again.
"""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[3] / "infra" / "modules"
TEMPLATE = INFRA / "scan" / "cross_account_template.yaml"

# Read by other workers' own roles in same-account mode, not by discovery.
NOT_DISCOVERY = {"sts:GetCallerIdentity", "cloudtrail:LookupEvents"}


def _statement_actions(terraform: str, sid: str) -> set[str]:
    match = re.search(rf'sid\s*=\s*"{sid}".*?actions\s*=\s*\[(.*?)\]', terraform, re.DOTALL)
    assert match, f"statement {sid} not found"
    return set(re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', match.group(1)))


def _template_actions() -> set[str]:
    return set(re.findall(r"^\s+- ([a-z0-9-]+:[A-Za-z*]+)\s*$", TEMPLATE.read_text(), re.M))


def test_the_scan_worker_reads_what_the_scanner_role_reads() -> None:
    scan = (INFRA / "scan" / "main.tf").read_text()
    expected = _template_actions() - NOT_DISCOVERY - {"sts:AssumeRole"}
    assert _statement_actions(scan, "SameAccountReadOnlyScan") == expected


def test_the_same_account_grant_is_read_only() -> None:
    """FR-005: Describe/Get/List only, never a write."""
    scan = (INFRA / "scan" / "main.tf").read_text()
    for action in _statement_actions(scan, "SameAccountReadOnlyScan"):
        verb = action.split(":", 1)[1]
        assert verb.startswith(("Describe", "Get", "List")), action


def test_the_api_role_can_verify_in_both_modes() -> None:
    api = (INFRA / "api" / "main.tf").read_text()
    assert _statement_actions(api, "VerifySameAccountRead") == {"tag:GetResources"}
    assert _statement_actions(api, "AssumeScannerRole") == {"sts:AssumeRole"}
    assert _statement_actions(api, "StoreExternalIdSecrets") == {"secretsmanager:CreateSecret"}
    assert 'role/cloudpulse-scanner"' in api
