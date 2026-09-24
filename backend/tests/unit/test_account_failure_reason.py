"""A role gone bad after registration marks the account failed, with a reason an
admin can act on (US1 scenario 6, US2 scenario 3, FR-012, T062).

moto's STS mock never refuses AssumeRole (T013's note: it hands out credentials for
a role that was never deployed), so the refusal is injected at the AssumeRole
boundary with a real botocore `ClientError`, the same fallback
`test_external_id_generation.py` uses. The status transition itself is plain
attribute logic and needs no database; the constraint and the API are proven
against real Postgres in `tests/integration/test_account_failure_reason.py`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.models.core import CloudAccount
from app.models.enums import AccountStatus
from app.scan.orchestrator import record_role_outcome
from app.scan.verification import role_failure_reason
from connectors.aws import AwsConnector, RoleAssumptionError
from connectors.base import ConnectorAccount

ROLE_ARN = "arn:aws:iam::222222222222:role/cloudpulse-scanner"


def test_a_role_that_can_no_longer_be_assumed_surfaces_as_a_typed_error() -> None:
    account = ConnectorAccount(
        aws_account_id="222222222222",
        connection_mode="assume_role",
        role_arn=ROLE_ARN,
        external_id="the-registered-value",
    )
    sts = MagicMock()
    sts.assume_role.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not authorized"}}, "AssumeRole"
    )

    with patch("boto3.client", return_value=sts), pytest.raises(RoleAssumptionError) as caught:
        AwsConnector().discover(account, "us-east-1")

    assert caught.value.code == "AccessDenied"


def test_the_reason_names_the_role_the_account_the_error_and_the_fix() -> None:
    reason = role_failure_reason(
        role_arn=ROLE_ARN, aws_account_id="222222222222", code="AccessDenied"
    )
    assert ROLE_ARN in reason
    assert "222222222222" in reason
    assert "AccessDenied" in reason
    assert "Re-deploy the CloudPulse cross-account template" in reason
    assert "trigger a scan" in reason


def _account(status: AccountStatus, reason: str | None = None) -> CloudAccount:
    return CloudAccount(status=status, failure_reason=reason)


def test_a_failed_role_check_marks_a_verified_account_failed_with_its_reason() -> None:
    account = _account(AccountStatus.VERIFIED)
    record_role_outcome(account, "fix it")
    assert account.status is AccountStatus.FAILED
    assert account.failure_reason == "fix it"


def test_a_successful_role_check_restores_a_failed_account_and_clears_the_reason() -> None:
    account = _account(AccountStatus.FAILED, "fix it")
    record_role_outcome(account, None)
    assert account.status is AccountStatus.VERIFIED
    assert account.failure_reason is None


def test_a_successful_role_check_leaves_a_verified_account_alone() -> None:
    account = _account(AccountStatus.VERIFIED)
    record_role_outcome(account, None)
    assert account.status is AccountStatus.VERIFIED
    assert account.failure_reason is None


@pytest.mark.parametrize("reason", ["fix it", None])
def test_a_deactivated_account_stays_disabled_whatever_the_outcome(reason: str | None) -> None:
    """FR-009b: a scan finishing after deactivation must not undo it."""
    account = _account(AccountStatus.DISABLED)
    record_role_outcome(account, reason)
    assert account.status is AccountStatus.DISABLED
    assert account.failure_reason is None
