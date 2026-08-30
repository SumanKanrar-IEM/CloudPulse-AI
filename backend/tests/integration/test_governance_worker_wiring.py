"""End-to-end governance pipeline wiring (spec 003, T030, research.md R-303).

`finalize_scan` enqueues one message per finalized scan to both new SQS
queues, and both worker handlers correctly process that message end-to-end
against a real database.

Follows research.md R-210's precedent for this codebase: real LocalStack SQS
proves the *enqueue* reaches a real SQS-compatible API with the correct
message shape -- not a full LocalStack Lambda deployment (R-210 already found
that impractical for `scan_worker_handler.py`'s real deployment package; the
same reasoning applies here, so it isn't repeated). The worker handler
*functions* are instead invoked directly, in-process, against a real
Testcontainers Postgres -- the "Lambda-level tests" fallback R-210 already
established -- with `app.core.db.get_engine` monkeypatched onto the test
container (bypassing Secrets Manager, which no test container provides) and
`connectors.aws.sweep_cloudtrail_events`/`sweep_write_events` monkeypatched
(R-307: moto has zero CloudTrail `lookup_events` coverage to route that leg
through instead) -- this file proves direct attribution only; the fallback
chain (P2, T038/T039) has its own dedicated test file.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from alembic import command
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
import handlers.compliance_validation_worker_handler as compliance_handler_module
import handlers.ownership_attribution_worker_handler as ownership_handler_module
from app.models.core import CloudAccount, Finding, Resource, ResourceOwner, Scan
from app.models.core import Rule as RuleRow
from app.models.core import Sda as SdaRow
from app.models.enums import AccountStatus, ConnectionMode, ScanStatus, ScanTrigger
from app.scan.orchestrator import finalize_scan

pytestmark = pytest.mark.integration

try:
    from testcontainers.community.localstack import LocalStackContainer
except ImportError:  # pragma: no cover
    from testcontainers.localstack import LocalStackContainer  # type: ignore[no-redef]


@pytest.fixture(scope="module")
def localstack_endpoint() -> Iterator[str]:
    try:
        with LocalStackContainer(image="localstack/localstack:3.8") as container:
            yield container.get_url()
    except Exception as exc:  # Docker unavailable in this environment
        pytest.skip(f"Docker/LocalStack unavailable: {exc}")


@pytest.fixture
def sqs_client(localstack_endpoint: str) -> Any:
    return boto3.client(
        "sqs",
        endpoint_url=localstack_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def queue_urls(
    sqs_client: Any, monkeypatch: pytest.MonkeyPatch, localstack_endpoint: str
) -> dict[str, str]:
    """Creates the two real (LocalStack) queues, points `finalize_scan`'s
    enqueue at them via the same env vars Terraform wires in production, and
    redirects every `boto3.client("sqs", ...)` call in this test's process to
    LocalStack -- production code never sets `endpoint_url` itself."""
    compliance_url = sqs_client.create_queue(QueueName="compliance-validation")["QueueUrl"]
    ownership_url = sqs_client.create_queue(QueueName="ownership-attribution")["QueueUrl"]
    monkeypatch.setenv("CLOUDPULSE_COMPLIANCE_VALIDATION_QUEUE_URL", compliance_url)
    monkeypatch.setenv("CLOUDPULSE_OWNERSHIP_ATTRIBUTION_QUEUE_URL", ownership_url)

    real_client: Any = boto3.client

    def _patched_client(service_name: str, *args: Any, **kwargs: Any) -> Any:
        if service_name == "sqs":
            kwargs.setdefault("endpoint_url", localstack_endpoint)
            kwargs.setdefault("region_name", "us-east-1")
            kwargs.setdefault("aws_access_key_id", "test")
            kwargs.setdefault("aws_secret_access_key", "test")
        return real_client(service_name, *args, **kwargs)

    monkeypatch.setattr(boto3, "client", _patched_client)
    return {"compliance": compliance_url, "ownership": ownership_url}


@pytest.fixture(autouse=True)
def _noop_governance_enqueue() -> Iterator[None]:
    """Overrides conftest's default no-op (same name, nearer scope wins in
    pytest) -- this file exists specifically to prove the real enqueue call
    reaches real queues."""
    yield


class _RawSession:
    def __init__(self, session: Session, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def raw(self) -> Session:
        return self._session

    @property
    def tenant_id(self) -> uuid.UUID:  # type: ignore[override]
        return self._tenant_id

    def scoped(self, statement: Any, model: Any) -> Any:
        return statement.where(model.tenant_id == self._tenant_id)

    def add(self, instance: Any) -> None:
        instance.tenant_id = self._tenant_id
        self._session.add(instance)

    def flush(self) -> None:
        self._session.flush()


@pytest.fixture
def db(
    clean_database: Engine, alembic_config: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Session]:
    command.upgrade(alembic_config, "head")
    db_module.get_engine.cache_clear()
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    session = sessionmaker(bind=clean_database, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant_id(db: Session) -> uuid.UUID:
    tid = uuid.UUID(str(db.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))
    db.execute(update(RuleRow).values(enabled=False))
    db.flush()
    return tid


@pytest.fixture
def account(db: Session, tenant_id: uuid.UUID) -> CloudAccount:
    account = CloudAccount(
        tenant_id=tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    db.add(account)
    db.flush()
    return account


def test_a_finalized_scan_enqueues_and_both_workers_process_it(
    db: Session,
    tenant_id: uuid.UUID,
    account: CloudAccount,
    queue_urls: dict[str, str],
    sqs_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RawSession(db, tenant_id)

    # A rule this resource will violate (missing "team") -- proves T016 ran.
    rule = RuleRow(
        tenant_id=tenant_id, key="team", version=1, definition={"required": True}, enabled=True
    )
    db.add(rule)
    sda = SdaRow(
        tenant_id=tenant_id,
        name="Platform",
        owner_email="owner@example.com",
        tag_values={"tier": "core"},
    )
    db.add(sda)
    resource = Resource(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-wiring",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={"tier": "core"},  # matches the SDA, missing the required "team" tag
    )
    db.add(resource)
    scan = Scan(
        tenant_id=tenant_id,
        cloud_account_id=account.id,
        trigger=ScanTrigger.MANUAL,
        status=ScanStatus.RUNNING,
    )
    db.add(scan)
    db.flush()
    db.commit()

    # --- finalize_scan enqueues to both real (LocalStack) queues -----------------
    final_status = finalize_scan(session, scan, [{"status": "succeeded", "region": "us-east-1"}])  # type: ignore[arg-type]
    assert final_status == ScanStatus.SUCCEEDED

    compliance_messages = sqs_client.receive_message(
        QueueUrl=queue_urls["compliance"], WaitTimeSeconds=2
    ).get("Messages", [])
    ownership_messages = sqs_client.receive_message(
        QueueUrl=queue_urls["ownership"], WaitTimeSeconds=2
    ).get("Messages", [])
    assert len(compliance_messages) == 1
    assert len(ownership_messages) == 1
    for raw in (compliance_messages[0], ownership_messages[0]):
        body = json.loads(raw["Body"])
        assert body["scan_id"] == str(scan.id)
        assert body["tenant_id"] == str(tenant_id)
        assert body["cloud_account_id"] == str(account.id)

    # --- the compliance-validation worker processes its message end-to-end -------
    compliance_event = {"Records": [{"body": compliance_messages[0]["Body"]}]}
    compliance_handler_module.handler(compliance_event)

    db.expire_all()
    reloaded = db.execute(select(Resource).where(Resource.id == resource.id)).scalar_one()
    assert reloaded.sda_id == sda.id  # T011 ran
    findings = db.execute(select(Finding).where(Finding.resource_id == resource.id)).scalars().all()
    assert len(findings) == 1  # T016 ran
    assert findings[0].status.value == "open"

    # --- the ownership-attribution worker processes its message end-to-end -------
    fake_events = {
        "i-wiring": {
            "principal": "arn:aws:iam::123456789012:user/alice",
            "is_human": True,
            "event_name": "RunInstances",
            "event_time": datetime(2026, 3, 1, tzinfo=UTC),
            "event_id": "evt-wiring",
            "is_write": True,
        }
    }
    monkeypatch.setattr(
        ownership_handler_module, "sweep_cloudtrail_events", lambda *a, **k: fake_events
    )
    monkeypatch.setattr(ownership_handler_module, "sweep_write_events", lambda *a, **k: {})
    ownership_event = {"Records": [{"body": ownership_messages[0]["Body"]}]}
    ownership_handler_module.handler(ownership_event)

    owner = db.execute(
        select(ResourceOwner).where(ResourceOwner.resource_id == resource.id)
    ).scalar_one()  # T023/T024 ran
    assert owner.owner_email == "arn:aws:iam::123456789012:user/alice"
    assert owner.evidence["cloudtrail_event_id"] == "evt-wiring"
