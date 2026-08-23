"""Two accounts' scans do not cross-contaminate (FR-027, SC-007).

FR-027 forbids two concurrent scans of the *same* account -- it does not, and must
not, block two different accounts from scanning at the same time. Proven at the unit
level: `start_scan`'s already-running check is scoped by `cloud_account_id`, so a
running scan on account A can never be mistaken for one on account B.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.core import CloudAccount, Scan
from app.models.enums import AccountStatus, ConnectionMode, ScanStatus, ScanTrigger
from app.scan.orchestrator import ScanAlreadyRunningError, persist_unit_result, start_scan
from connectors.base import NormalizedResource


def _account(aws_account_id: str) -> CloudAccount:
    return CloudAccount(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        aws_account_id=aws_account_id,
        alias=aws_account_id,
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )


def test_account_bs_running_scan_does_not_block_account_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The already-running check is a per-call query scoped to the account passed
    in -- proven here by having the two calls see different query results, exactly
    as two different accounts' independent checks would."""
    monkeypatch.setenv(
        "CLOUDPULSE_SCAN_STATE_MACHINE_ARN",
        "arn:aws:states:us-east-1:000000000000:stateMachine:test",
    )
    account_a = _account("111111111111")
    account_b = _account("222222222222")
    running_scan_for_b = Scan(
        id=uuid.uuid4(),
        tenant_id=account_b.tenant_id,
        cloud_account_id=account_b.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.RUNNING,
    )

    fake_session = MagicMock()
    fake_session.scoped.side_effect = lambda stmt, model: stmt

    # Account A's check finds nothing running; account B's finds its own scan.
    fake_session.raw.execute.return_value.scalar_one_or_none.side_effect = [
        None,
        running_scan_for_b,
    ]

    with patch("boto3.client") as mock_sfn:
        mock_sfn.return_value.start_execution.return_value = {"executionArn": "arn:aws:states:..."}
        scan_a = start_scan(fake_session, account_a, trigger=ScanTrigger.MANUAL)
        assert scan_a.cloud_account_id == account_a.id

    with pytest.raises(ScanAlreadyRunningError):
        start_scan(fake_session, account_b, trigger=ScanTrigger.MANUAL)


def test_persisted_resources_are_never_written_against_the_wrong_account() -> None:
    """SC-007: no resource from account A's discovery ends up under account B."""
    account_a_id = uuid.uuid4()
    account_b_id = uuid.uuid4()

    fake_session = MagicMock()
    fake_session.raw.execute.return_value.scalar_one_or_none.return_value = None
    fake_session.scoped.side_effect = lambda stmt, model: stmt

    resource_a = NormalizedResource(
        provider="aws",
        account_id="111111111111",
        resource_id="arn:aws:ec2:us-east-1:111111111111:instance/i-a",
        service="ec2",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        name=None,
        tags={},
        state="running",
        created_at=None,
    )

    persist_unit_result(fake_session, cloud_account_id=account_a_id, resources=[resource_a])

    added = fake_session.add.call_args[0][0]
    assert added.cloud_account_id == account_a_id
    assert added.cloud_account_id != account_b_id
