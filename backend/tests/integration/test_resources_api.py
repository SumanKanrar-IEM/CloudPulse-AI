"""GET /resources and GET /resources/{id} (FR-010-FR-013, SC-005).

Runs against a real PostgreSQL container: filter combinations, the
tag-status-vs-attribution distinction (research.md R-403), and the
SDA-removed-mid-filter edge case are all real row state, not something a
mocked session should stand in for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.core.db as db_module
from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware
from app.api.routers import resources as resources_router
from app.models.core import CloudAccount, Finding, Resource
from app.models.core import ResourceOwner as ResourceOwnerRow
from app.models.core import Rule as RuleRow
from app.models.core import Sda as SdaRow
from app.models.enums import (
    AccountStatus,
    ConnectionMode,
    FindingSeverity,
    FindingStatus,
    OwnerConfidence,
)

pytestmark = pytest.mark.integration

ADMIN = ["cloudpulse-admins"]


class _ClaimStager:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.claims: dict[str, Any] | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] == "http":
            scope["state"] = dict(scope.get("state") or {})
            scope["state"]["claims"] = self.claims
        await self.app(scope, receive, send)


def _stage(stager: _ClaimStager, tenant_id: uuid.UUID, groups: list[str]) -> None:
    stager.claims = {
        "sub": "s",
        "email": "e@example.com",
        "cognito:groups": groups,
        "custom:tenant_id": str(tenant_id),
    }


@pytest.fixture
def real_tenant_id(clean_database: Engine, alembic_config: Any) -> uuid.UUID:
    command.upgrade(alembic_config, "head")
    with clean_database.connect() as conn:
        return uuid.UUID(str(conn.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()))


@pytest.fixture
def resources_app(
    clean_database: Engine, real_tenant_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, _ClaimStager, uuid.UUID]:
    monkeypatch.setattr(db_module, "get_engine", lambda: clean_database)
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(resources_router.router)
    stager = _ClaimStager(app)
    client = TestClient(stager, raise_server_exceptions=False)
    _stage(stager, real_tenant_id, ADMIN)
    return client, stager, real_tenant_id


@pytest.fixture
def seed(clean_database: Engine, real_tenant_id: uuid.UUID) -> dict[str, Any]:
    session: Session = sessionmaker(bind=clean_database)()
    account = CloudAccount(
        tenant_id=real_tenant_id,
        aws_account_id="123456789012",
        alias="test",
        connection_mode=ConnectionMode.LOCAL,
        scan_regions=["us-east-1"],
        status=AccountStatus.VERIFIED,
    )
    sda = SdaRow(
        tenant_id=real_tenant_id, name="Platform", owner_email="owner@example.com", tag_values={}
    )
    session.add(account)
    session.add(sda)
    session.flush()
    # Migration 0010 already seeds an "owner" rule at version 1 for every tenant
    # (spec 003) -- reuse it rather than inserting a colliding duplicate.
    owner_rule = (
        session.query(RuleRow).filter_by(tenant_id=real_tenant_id, key="owner", version=1).one()
    )

    # r1: compliant, attributed, in the SDA.
    r1 = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-1",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={"owner": "a@example.com"},
        sda_id=sda.id,
        detail={"state": "running"},
    )
    # r2: missing owner tag (open finding), unattributed, different service/region.
    r2 = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:s3:::bucket-2",
        resource_type="AWS::S3::Bucket",
        service="s3",
        region="us-west-2",
        tags={},
    )
    # r3: valid owner tag AND unattributed -- the exact R-403 divergence case.
    r3 = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-3",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={"owner": "c@example.com"},
    )
    # r4: soft-deleted -- excluded from listing, reachable by id.
    r4 = Resource(
        tenant_id=real_tenant_id,
        cloud_account_id=account.id,
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-4",
        resource_type="AWS::EC2::Instance",
        service="ec2",
        region="us-east-1",
        tags={},
        deleted_at=datetime.now(UTC),
    )
    session.add_all([r1, r2, r3, r4])
    session.flush()

    finding = Finding(
        tenant_id=real_tenant_id,
        resource_id=r2.id,
        rule_id=owner_rule.id,
        rule_version=1,
        severity=FindingSeverity.HIGH,
        status=FindingStatus.OPEN,
    )
    owner_r1 = ResourceOwnerRow(
        tenant_id=real_tenant_id,
        resource_id=r1.id,
        owner_email="a@example.com",
        confidence=OwnerConfidence.HIGH,
        evidence={"kind": "direct", "principal": "arn:aws:iam::123456789012:user/a"},
    )
    session.add(finding)
    session.add(owner_r1)
    session.commit()

    ids = {
        "account_id": str(account.id),
        "sda_id": str(sda.id),
        "r1": str(r1.id),
        "r2": str(r2.id),
        "r3": str(r3.id),
        "r4": str(r4.id),
    }
    session.close()
    return ids


def test_filters_narrow_to_exactly_the_matching_resources(resources_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    response = client.get("/resources", params={"service": "ec2", "region": "us-east-1"})
    assert response.status_code == 200, response.text
    ids = {r["id"] for r in response.json()["resources"]}
    assert ids == {seed["r1"], seed["r3"]}


def test_tag_status_missing_owner_matches_only_the_finding_resource(resources_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    response = client.get("/resources", params={"tagStatus": "missing:owner"})
    ids = {r["id"] for r in response.json()["resources"]}
    assert ids == {seed["r2"]}


def test_owner_status_unattributed_returns_exactly_the_unowned_resources(
    resources_app, seed
) -> None:  # type: ignore[no-untyped-def]
    """SC-005, research.md R-403: r3 has a valid owner *tag* but is
    unattributed -- proves this is a distinct fact from tag compliance, not
    the same thing under two names."""
    client, _, _ = resources_app
    response = client.get("/resources", params={"ownerStatus": "unattributed"})
    ids = {r["id"] for r in response.json()["resources"]}
    assert ids == {seed["r2"], seed["r3"]}
    assert seed["r1"] not in ids


def test_pagination_bounds_page_size(resources_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    response = client.get("/resources", params={"pageSize": 2})
    body = response.json()
    assert len(body["resources"]) == 2
    assert body["totalCount"] == 3  # r4 excluded (soft-deleted)
    assert body["page"] == 1


def test_soft_deleted_resource_excluded_from_listing_but_reachable_by_id(
    resources_app, seed
) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    listing = client.get("/resources")
    assert seed["r4"] not in {r["id"] for r in listing.json()["resources"]}

    detail = client.get(f"/resources/{seed['r4']}")
    assert detail.status_code == 200, detail.text


def test_resource_detail_returns_tags_owner_evidence_findings_and_enrichment(
    resources_app, seed
) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    response = client.get(f"/resources/{seed['r1']}")
    body = response.json()
    assert body["tags"] == {"owner": "a@example.com"}
    assert body["detail"] == {"state": "running"}
    assert body["owner"]["ownerEmail"] == "a@example.com"
    assert body["owner"]["evidence"]["principal"] == "arn:aws:iam::123456789012:user/a"
    assert body["findings"] == []


def test_resource_detail_shows_unattributed_explicitly_not_a_null_field(
    resources_app, seed
) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    response = client.get(f"/resources/{seed['r2']}")
    body = response.json()
    assert body["owner"] is None
    assert len(body["findings"]) == 1
    assert body["findings"][0]["ruleKey"] == "owner"


def test_a_nonexistent_resource_is_a_404(resources_app, seed) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = resources_app
    response = client.get(f"/resources/{uuid.uuid4()}")
    assert response.status_code == 404


def test_sda_filter_result_set_updates_when_the_sda_is_removed(
    resources_app, seed, clean_database
) -> None:  # type: ignore[no-untyped-def]
    """Edge Case: an sdaId filter's result set must not keep matching a
    removed SDA -- ON DELETE SET NULL is what tag compliance and ownership
    already relies on for this (FR-010b's immediate-revert semantics)."""
    client, _, _ = resources_app
    before = client.get("/resources", params={"sdaId": seed["sda_id"]})
    assert {r["id"] for r in before.json()["resources"]} == {seed["r1"]}

    session: Session = sessionmaker(bind=clean_database)()
    session.execute(text("DELETE FROM sda WHERE id = :id"), {"id": seed["sda_id"]})
    session.commit()
    session.close()

    after = client.get("/resources", params={"sdaId": seed["sda_id"]})
    assert after.json()["resources"] == []
    assert after.status_code == 200  # no error from referencing a removed sdaId
