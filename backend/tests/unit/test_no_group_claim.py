"""A token carrying no group claim at all is refused (FR-032a, edge case).

Distinct from "empty group list", and the distinction matters: an absent claim must
never be treated as an empty list that quietly matches a default. Both refuse, but for
reasons that are logged separately — if they were conflated, a misconfigured identity
provider that stopped emitting groups would look identical to a user with no groups, and
the operator would debug the wrong thing.
"""

from __future__ import annotations

import pytest

from app.api.errors import AppError
from app.core.security import GROUPS_CLAIM, get_principal, resolve_role


def test_absent_group_claim_is_refused() -> None:
    """The edge case: a valid identity with no group information at all."""
    with pytest.raises(AppError) as exc:
        resolve_role(None)
    assert exc.value.status_code == 403


def test_absent_claim_is_not_treated_as_an_empty_list() -> None:
    """Both refuse -- but they must be distinguishable in the logs.

    Conflating them would make a broken identity provider look like a user problem.
    """
    from app.core.security import _normalise_groups

    assert _normalise_groups(None) is None          # claim absent
    assert _normalise_groups([]) == []              # claim present, empty
    assert _normalise_groups("") == []              # flattened empty string


def test_no_default_role_exists_anywhere() -> None:
    """FR-032a: 'there is no default role.'

    Asserted structurally: the resolver has no fallback branch that yields a Role.
    """
    import inspect

    from app.core import security

    source = inspect.getsource(security.resolve_role)
    assert "return Role." not in source, (
        "resolve_role must never return a hardcoded Role -- that would be a default"
    )


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(["cloudpulse-admins"], id="list"),
        pytest.param("cloudpulse-admins", id="flattened-string"),
        pytest.param("[cloudpulse-admins]", id="bracketed-string"),
        pytest.param("cloudpulse-admins, cloudpulse-admins", id="comma-separated"),
    ],
)
def test_group_claim_shapes_are_normalised(raw: object) -> None:
    """Cognito emits a list; API Gateway may flatten it to a string.

    Both must resolve identically, or the same user gets different access depending on
    how the token happened to be serialised.
    """
    from app.core.config import Role
    from app.core.security import _normalise_groups

    assert resolve_role(_normalise_groups(raw)) is Role.ADMIN


def test_unparseable_claim_shape_is_refused() -> None:
    """A claim of an unexpected type must not become an accidental grant."""
    from app.core.security import _normalise_groups

    assert _normalise_groups(12345) is None
    with pytest.raises(AppError):
        resolve_role(_normalise_groups(12345))


def test_missing_subject_is_unauthorized_not_forbidden() -> None:
    """401 and 403 mean different things: 'who are you' vs 'not allowed'.

    Collapsing them makes a client retry-with-login when the real problem is
    permissions, or vice versa.
    """
    from starlette.requests import Request

    scope = {"type": "http", "headers": [], "state": {"claims": {GROUPS_CLAIM: ["cloudpulse-admins"]}}}
    request = Request(scope)
    request.state.claims = {GROUPS_CLAIM: ["cloudpulse-admins"]}   # no "sub"

    with pytest.raises(AppError) as exc:
        get_principal(request)
    assert exc.value.status_code == 401


def test_groups_claim_name_matches_cognito() -> None:
    """A typo here silently disables all authorisation."""
    assert GROUPS_CLAIM == "cognito:groups"
