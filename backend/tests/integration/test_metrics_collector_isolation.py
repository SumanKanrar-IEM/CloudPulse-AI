"""One account's collection failure does not stop another's (spec 006, T042;
FR-019, S50).

The CloudWatch call is replaced at the connector seam -- the handler imports
`get_metric_data` by name, so patching it there is the whole boundary. The
first account's call raises; the second's answers. The second's measurements
must be in the store and the first must appear in `failed` with nothing
written for it, because a failed account is a collection failure and not a
resource with no measurement (see the handler's docstring).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import sessionmaker

import app.core.db as db_module
from app.core.db import tenant_session
from app.governance.metrics import query_id
from app.models.core import CloudAccount, Resource, ResourceMetric
from app.models.enums import AccountStatus, ConnectionMode, ResourceMetricKind
from handlers import metrics_collector_handler as handler_module

pytestmark = pytest.mark.integration


@pytest.fixture
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def seed(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> dict[str, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    # The handler bound `get_engine` by name at import; patch its copy too.
    monkeypatch.setattr(handler_module, "get_engine", lambda: clean_database)
    session = sessionmaker(bind=clean_database)()
    accounts = {}
    for alias, number in (("broken", "111111111111"), ("healthy", "222222222222")):
        account = CloudAccount(
            tenant_id=real_tenant_id,
            aws_account_id=number,
            alias=alias,
            connection_mode=ConnectionMode.LOCAL,
            scan_regions=["us-east-1"],
            status=AccountStatus.VERIFIED,
        )
        session.add(account)
        session.flush()
        session.add(
            Resource(
                tenant_id=real_tenant_id,
                cloud_account_id=account.id,
                arn=f"arn:aws:ec2:us-east-1:{number}:instance/i-{alias}",
                resource_type="AWS::EC2::Instance",
                service="ec2",
                region="us-east-1",
                tags={},
                detail={},
            )
        )
        accounts[alias] = account.id
    session.commit()
    session.close()
    return accounts


def test_one_failing_account_does_not_stop_the_next(
    real_tenant_id: uuid.UUID, seed: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get_metric_data(account: Any, region: str, queries: list[dict[str, Any]], **_: Any):  # type: ignore[no-untyped-def]
        if account.aws_account_id == "111111111111":
            raise RuntimeError("AccessDenied: cloudpulse-scanner is not assumable")
        return [{"Id": query_id(0, ResourceMetricKind.CPU), "Values": [7.0]}]

    monkeypatch.setattr(handler_module, "get_metric_data", fake_get_metric_data)

    result = handler_module.handler({"action": "trigger_daily"})

    assert result["failed"] == [str(seed["broken"])]
    assert result["collected"] == [str(seed["healthy"])]

    with tenant_session(real_tenant_id) as session:
        per_account = dict(
            session.raw.execute(
                session.scoped(
                    select(Resource.cloud_account_id, func.count(ResourceMetric.id)),
                    ResourceMetric,
                )
                .join(Resource, Resource.id == ResourceMetric.resource_id)
                .group_by(Resource.cloud_account_id)
            ).all()
        )

    # Four kinds for the healthy account's one instance (one measured, three
    # unavailable); nothing at all for the broken one.
    assert per_account == {seed["healthy"]: 4}
    assert seed["broken"] not in per_account
