"""The agent access path is read-only and holds no credential (FR-056, SC-017).

Spec 006 will build Bedrock action groups against this. These tests pin the constraints
now, while the surface is small enough to reason about — retrofitting "agents cannot
mutate" onto a built agent layer is far harder than asserting it before one exists.
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from app.api.errors import AppError
from app.core import agent_access
from app.core.agent_access import (
    AGENT_CLAIM, READ_ONLY_METHODS, AgentPrincipal,
    build_agent_principal, enforce_agent_read_only,
)
from app.core.config import Role
from app.core.security import Principal

TENANT = uuid.uuid4()


class _FakeRequest:
    def __init__(self, method: str) -> None:
        self.method = method
        self.url = type("U", (), {"path": "/whatever"})()


def _agent() -> AgentPrincipal:
    return AgentPrincipal(agent_id="digest-agent", tenant_id=TENANT)


@pytest.mark.parametrize("method", sorted(READ_ONLY_METHODS))
def test_agents_may_read(method: str) -> None:
    enforce_agent_read_only(_FakeRequest(method), _agent())  # does not raise


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post", "TRACE"])
def test_agents_may_not_mutate(method: str) -> None:
    """FR-056 / Principle IV: agents observe and recommend, never execute."""
    with pytest.raises(AppError) as exc:
        enforce_agent_read_only(_FakeRequest(method), _agent())
    assert exc.value.status_code == 403


def test_an_unknown_method_is_refused() -> None:
    """Fail closed: a method not on the read-only list is refused, not allowed."""
    with pytest.raises(AppError):
        enforce_agent_read_only(_FakeRequest("FUTUREVERB"), _agent())


def test_agents_are_always_viewer_role() -> None:
    """Hardcoded, not derived -- an agent must never obtain a mutating role."""
    assert _agent().role is Role.VIEWER


def test_agent_role_cannot_be_overridden_by_claims() -> None:
    """Even a token claiming admin yields viewer."""
    principal = build_agent_principal(
        {AGENT_CLAIM: "a1", "custom:tenant_id": str(TENANT), "custom:role": "admin"}
    )
    assert principal.role is Role.VIEWER


def test_tenant_comes_from_the_token_not_a_parameter() -> None:
    """An agent that could name its own tenant would defeat FR-030 entirely."""
    principal = build_agent_principal({AGENT_CLAIM: "a1", "custom:tenant_id": str(TENANT)})
    assert principal.tenant_id == TENANT

    with pytest.raises(AppError):
        build_agent_principal({AGENT_CLAIM: "a1"})               # no tenant
    with pytest.raises(AppError):
        build_agent_principal({AGENT_CLAIM: "a1", "custom:tenant_id": "not-a-uuid"})


def test_a_missing_agent_id_is_unauthorized() -> None:
    with pytest.raises(AppError) as exc:
        build_agent_principal({"custom:tenant_id": str(TENANT)})
    assert exc.value.status_code == 401


def test_human_principals_are_unaffected() -> None:
    """The guard must not restrict ordinary users -- a control that blocks everything
    is as useless as one that blocks nothing."""
    human = Principal(subject="u1", email="a@b.c", role=Role.ADMIN, tenant_id=TENANT)
    enforce_agent_read_only(_FakeRequest("POST"), human)  # does not raise


def test_the_module_holds_no_cloud_credential_path() -> None:
    """FR-056: an agent must hold no cloud credential.

    Asserted structurally: nothing in this module reaches for boto3, a secret, or a
    session. The connector-boundary gate covers the import; this covers intent.
    """
    source = inspect.getsource(agent_access)
    for forbidden in ("boto3", "get_secret_value", "assume_role", "AccessKey"):
        assert forbidden not in source, f"agent access path references {forbidden!r}"


def test_agents_are_identifiable() -> None:
    """A route that must refuse agents specifically needs to be able to tell."""
    assert _agent().is_agent is True
    assert not hasattr(Principal(subject="u", email="", role=Role.VIEWER, tenant_id=TENANT), "agent_id")
