"""Scan scheduling: daily trigger construction, on-demand trigger role gating
(FR-026, FR-026a, research.md R-205).

Role-gating tests stay unit-level the same way test_account_registration.py's do:
`require_role(Role.OPERATOR)` refuses before any handler code runs, so no database
is needed to prove non-operator roles are refused. The daily-trigger query itself
(`start_due_daily_scans`) needs a real database and is covered by
test_concurrent_scans_isolated.py and the integration scan-diffing tests instead.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers.accounts import router

SOME_ACCOUNT_ID = str(uuid.uuid4())


class _ClaimStager:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.claims: dict[str, Any] | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


@pytest.fixture
def accounts_app() -> tuple[TestClient, _ClaimStager]:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    return client, stager


def _stage(stager: _ClaimStager, groups: list[str]) -> None:
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": groups,
        "custom:tenant_id": "11111111-1111-1111-1111-111111111111",
    }


# --- FR-026a: on-demand trigger is operator-only, non-hierarchically (R-205) -------


def test_admin_cannot_trigger_an_on_demand_scan(
    accounts_app: tuple[TestClient, _ClaimStager],
) -> None:
    """The cell a naive 'admin can do everything' implementation gets wrong
    (quickstart.md V9) -- admin's account-management grant does not carry
    operator's scan-trigger grant."""
    client, stager = accounts_app
    _stage(stager, ["cloudpulse-admins"])
    response = client.post(f"/accounts/{SOME_ACCOUNT_ID}/scans")
    assert response.status_code == 403


def test_viewer_cannot_trigger_an_on_demand_scan(
    accounts_app: tuple[TestClient, _ClaimStager],
) -> None:
    client, stager = accounts_app
    _stage(stager, ["cloudpulse-viewers"])
    response = client.post(f"/accounts/{SOME_ACCOUNT_ID}/scans")
    assert response.status_code == 403


def test_the_route_does_not_reuse_the_hierarchical_operator_alias() -> None:
    """Structural guard against regression: accounts.py must build its own
    `require_role(Role.OPERATOR)` dependency for this route, not
    `app.core.security.require_operator`, which also admits admin."""
    import inspect

    from app.api.routers import accounts as accounts_module

    source = inspect.getsource(accounts_module)
    assert "OperatorPrincipal" in source
    # The trigger_scan route must depend on OperatorPrincipal, not AdminPrincipal
    # or require_operator directly.
    trigger_fn_source = inspect.getsource(accounts_module.trigger_scan)
    assert "OperatorPrincipal" in trigger_fn_source
    assert "require_operator" not in trigger_fn_source


# --- FR-026: daily trigger construction --------------------------------------------


def test_build_execution_input_produces_one_unit_per_region() -> None:
    from app.models.core import CloudAccount, Scan
    from app.models.enums import AccountStatus, ConnectionMode, ScanTrigger
    from app.scan.orchestrator import _build_execution_input

    account = CloudAccount(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1", "eu-west-1", "ap-southeast-1"],
        status=AccountStatus.VERIFIED,
    )
    scan = Scan(
        id=uuid.uuid4(),
        tenant_id=account.tenant_id,
        cloud_account_id=account.id,
        trigger=ScanTrigger.SCHEDULED,
    )
    execution_input = _build_execution_input(scan, account)

    assert execution_input["scan_id"] == str(scan.id)
    assert execution_input["units"] == [
        {"region": "us-east-1"},
        {"region": "eu-west-1"},
        {"region": "ap-southeast-1"},
    ]


def test_start_scan_raises_when_a_scan_is_already_running() -> None:
    """FR-027, at the unit level: the guard raises before ever touching Step
    Functions -- proven by never mocking boto3 here and confirming no call happens."""
    from unittest.mock import MagicMock

    from app.models.core import CloudAccount, Scan
    from app.models.enums import AccountStatus, ConnectionMode, ScanStatus, ScanTrigger
    from app.scan.orchestrator import ScanAlreadyRunningError, start_scan

    account = CloudAccount(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    running_scan = Scan(
        id=uuid.uuid4(),
        tenant_id=account.tenant_id,
        cloud_account_id=account.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.RUNNING,
    )

    fake_session = MagicMock()
    fake_session.raw.execute.return_value.scalar_one_or_none.return_value = running_scan
    fake_session.scoped.side_effect = lambda stmt, model: stmt

    with patch("boto3.client") as mock_client:
        with pytest.raises(ScanAlreadyRunningError):
            start_scan(fake_session, account, trigger=ScanTrigger.MANUAL)
        mock_client.assert_not_called()
