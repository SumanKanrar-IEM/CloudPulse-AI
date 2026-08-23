"""The connector protocol shape (FR-014).

Confirms `connectors/aws.py` still passes the `connector-boundary` CI gate as an empty
stub (T034 fills it in Phase 5), and that `Connector`/`NormalizedResource` carry the
FR-013/FR-014 shape a second provider would need to implement.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from connectors.base import Connector, ConnectorAccount, NormalizedResource

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_normalized_resource_has_the_fr013_fields() -> None:
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:ec2:us-east-1:123456789012:instance/i-abc123",
        service="ec2",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        name="my-instance",
        tags={"env": "dev"},
        state="running",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert resource.detail == {}
    assert resource.resource_id.startswith("arn:aws:")


def test_normalized_resource_is_immutable() -> None:
    """A connector returns a new record rather than mutating a shared one."""
    resource = NormalizedResource(
        provider="aws",
        account_id="123456789012",
        resource_id="arn:aws:s3:::my-bucket",
        service="s3",
        resource_type="AWS::S3::Bucket",
        region="us-east-1",
        name="my-bucket",
        tags={},
        state=None,
        created_at=None,
    )
    try:
        resource.state = "changed"  # type: ignore[misc]
        raised = False
    except AttributeError:
        raised = True
    assert raised, "NormalizedResource must be frozen"


def test_connector_account_never_carries_a_long_lived_credential() -> None:
    """Principle III: only a role reference and an in-memory external-id value."""
    account = ConnectorAccount(
        aws_account_id="123456789012",
        connection_mode="assume_role",
        role_arn="arn:aws:iam::123456789012:role/cloudpulse-scanner",
        external_id="unit-test-external-id",
    )
    for field_name in ("access_key", "secret_key", "access_key_id", "secret_access_key"):
        assert not hasattr(account, field_name)


def test_connector_protocol_declares_discover_and_enrich() -> None:
    assert hasattr(Connector, "discover")
    assert hasattr(Connector, "enrich")


def test_aws_connector_module_is_still_an_empty_stub() -> None:
    """T034 (Phase 5) fills this in. Until then it must stay a boundary-safe stub."""
    aws_py = REPO_ROOT / "backend" / "connectors" / "aws.py"
    tree = ast.parse(aws_py.read_text(encoding="utf-8"))
    defs = [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.ClassDef)]
    assert defs == [], "aws.py should still be an empty stub in Phase 2"


def test_connector_boundary_gate_passes_with_the_current_stub() -> None:
    """`ops/scripts/check_connector_boundary.py` must stay green (playbook §0.5)."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "ops" / "scripts" / "check_connector_boundary.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
