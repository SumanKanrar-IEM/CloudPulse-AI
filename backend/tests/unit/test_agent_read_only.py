"""The action-group principal is read-only and credential-free (T012; spec 006,
FR-002, FR-003, and spec 001's FR-056).

Asserted against spec 001's `app/core/agent_access.py` rather than against a
re-implementation. That module's own docstring gives the reason: "a rule stated
once in a constitution and re-implemented by each later spec is a rule that
eventually gets implemented wrong." Spec 006's job is to build on it, and these
tests are how spec 006 shows it did not quietly build beside it.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.errors import AppError
from app.core.agent_access import (
    AGENT_CLAIM,
    READ_ONLY_METHODS,
    AgentPrincipal,
    build_agent_principal,
    enforce_agent_read_only,
)
from app.core.config import Role
from app.core.security import Principal

TENANT = uuid.uuid4()


class _Request:
    """The two attributes `enforce_agent_read_only` reads."""

    def __init__(self, method: str) -> None:
        self.method = method
        self.url = type("U", (), {"path": "/insights/digest"})()


def _agent() -> AgentPrincipal:
    return AgentPrincipal(agent_id="digest", tenant_id=TENANT)


@pytest.mark.parametrize("method", sorted(READ_ONLY_METHODS))
def test_an_agent_may_use_every_read_only_method(method: str) -> None:
    enforce_agent_read_only(_Request(method), _agent())  # no raise


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_an_agent_is_refused_every_mutating_method(method: str) -> None:
    """FR-002: agents must not execute, schedule, or trigger any change."""
    with pytest.raises(AppError):
        enforce_agent_read_only(_Request(method), _agent())


def test_an_unknown_method_is_refused_rather_than_allowed() -> None:
    """Fail-closed. A method this platform has never heard of must not be
    permitted by omission — including one a later HTTP revision adds."""
    with pytest.raises(AppError):
        enforce_agent_read_only(_Request("QUERY"), _agent())


def test_an_agent_is_always_viewer_whatever_its_claims_say() -> None:
    """The role is hardcoded, not derived. An agent that could obtain a mutating
    role by presenting a group claim would defeat FR-002 through the front
    door."""
    assert _agent().role is Role.VIEWER


def test_the_agent_principal_carries_no_credential() -> None:
    """FR-003: agents hold no cloud credential. Asserted structurally — there is
    no attribute on the principal that could carry one."""
    principal = _agent()
    attributes = {a.lower() for a in dir(principal) if not a.startswith("__")}
    assert not any(
        token in attribute
        for attribute in attributes
        for token in ("secret", "credential", "access_key", "token", "password")
    )


def test_a_human_principal_is_untouched_by_the_agent_guard() -> None:
    """The guard must not become a general method filter — an operator's POST is
    not an agent's POST."""
    human = Principal(subject="user", email="u@example.com", role=Role.OPERATOR, tenant_id=TENANT)
    enforce_agent_read_only(_Request("POST"), human)  # no raise


def test_the_tenant_comes_from_the_token_never_from_a_parameter() -> None:
    """An agent that could name its own tenant would defeat FR-030 entirely."""
    claims: dict[str, Any] = {AGENT_CLAIM: "digest", "custom:tenant_id": str(TENANT)}
    assert build_agent_principal(claims).tenant_id == TENANT


@pytest.mark.parametrize(
    "claims",
    [
        {"custom:tenant_id": str(TENANT)},  # no agent id
        {AGENT_CLAIM: "digest"},  # no tenant
        {AGENT_CLAIM: "digest", "custom:tenant_id": "not-a-uuid"},
    ],
)
def test_an_incomplete_or_malformed_claim_set_is_refused(claims: dict[str, Any]) -> None:
    with pytest.raises(AppError):
        build_agent_principal(claims)


def test_an_agent_is_identifiable_as_one() -> None:
    """Routes that must refuse agents specifically need a marker, not a guess
    from the subject string."""
    assert _agent().is_agent is True
