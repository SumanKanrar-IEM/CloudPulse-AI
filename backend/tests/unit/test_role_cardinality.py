"""Exactly one role, or refuse (FR-032, FR-032a).

The two cases these tests exist for are **zero mapped groups** and **more than one**.
Both must be *refused*, not resolved.

That is worth stating plainly because the wrong implementation looks completely normal:
picking the first group, or the highest-ranked one, produces a working system that
passes every functional test. It is a privilege-escalation bug that is invisible except
from the security angle — which is exactly why FR-032a spells out the refusal rather
than leaving it to judgement.
"""

from __future__ import annotations

import pytest

from app.api.errors import AppError, ErrorCode
from app.core.config import Role
from app.core.security import DEFAULT_GROUP_ROLE_MAP, resolve_role
from handlers.pre_token_handler import DEFAULT_GROUP_ROLE_MAP as LAMBDA_MAP
from handlers.pre_token_handler import resolve_single_role


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        (["cloudpulse-admins"], Role.ADMIN),
        (["cloudpulse-operators"], Role.OPERATOR),
        (["cloudpulse-viewers"], Role.VIEWER),
        # An unmapped group alongside exactly one mapped group is still unambiguous.
        (["cloudpulse-admins", "some-unrelated-directory-group"], Role.ADMIN),
    ],
)
def test_exactly_one_mapped_group_resolves(groups: list[str], expected: Role) -> None:
    assert resolve_role(groups) is expected


@pytest.mark.parametrize(
    "groups",
    [
        pytest.param([], id="empty-list"),
        pytest.param(["not-a-cloudpulse-group"], id="unmapped-only"),
        pytest.param(["a", "b", "c"], id="several-unmapped"),
    ],
)
def test_zero_mapped_groups_is_refused(groups: list[str]) -> None:
    """No default role. FR-032a: 'a person whose identity maps to no group MUST
    receive no access at all'."""
    with pytest.raises(AppError) as exc:
        resolve_role(groups)
    assert exc.value.code is ErrorCode.FORBIDDEN
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "groups",
    [
        pytest.param(["cloudpulse-admins", "cloudpulse-viewers"], id="admin+viewer"),
        pytest.param(["cloudpulse-operators", "cloudpulse-viewers"], id="operator+viewer"),
        pytest.param(
            ["cloudpulse-admins", "cloudpulse-operators", "cloudpulse-viewers"],
            id="all-three",
        ),
    ],
)
def test_multiple_mapped_groups_is_refused_not_resolved(groups: list[str]) -> None:
    """FR-032a: refused 'rather than silently granted the higher or lower of the two'.

    This is the assertion that matters most in this file.
    """
    with pytest.raises(AppError) as exc:
        resolve_role(groups)
    assert exc.value.status_code == 403


def test_multi_group_refusal_does_not_pick_the_highest() -> None:
    """Belt and braces: an admin+viewer identity must not come back as admin."""
    with pytest.raises(AppError):
        resolve_role(["cloudpulse-admins", "cloudpulse-viewers"])


def test_multi_group_refusal_does_not_pick_the_lowest() -> None:
    """...nor silently downgrade, which would look like a safe default and is not."""
    with pytest.raises(AppError):
        resolve_role(["cloudpulse-viewers", "cloudpulse-admins"])


def test_duplicate_of_the_same_group_still_resolves() -> None:
    """Two entries mapping to ONE role is not ambiguous -- it is one role listed twice."""
    assert resolve_role(["cloudpulse-admins", "cloudpulse-admins"]) is Role.ADMIN


def test_the_refusal_reveals_nothing_about_why() -> None:
    """An unauthenticated probe should not learn its group membership from the error."""
    with pytest.raises(AppError) as exc:
        resolve_role(["cloudpulse-admins", "cloudpulse-viewers"])
    message = str(exc.value).lower()
    for leak in ("group", "admin", "viewer", "two", "multiple"):
        assert leak not in message, f"refusal message leaked {leak!r}"


# --- The two layers must agree (research.md R-004) -------------------------

@pytest.mark.parametrize(
    "groups",
    [
        [], ["cloudpulse-admins"], ["cloudpulse-admins", "cloudpulse-viewers"],
        ["unmapped"], None,
    ],
)
def test_both_layers_agree_on_every_case(groups: list[str] | None) -> None:
    """The pre-token Lambda and the API must never disagree.

    If the Lambda stamped a role the API then refused, sign-in would appear to succeed
    and every request would fail -- a confusing failure mode. If the API accepted where
    the Lambda declined, the second layer would be pointless.
    """
    lambda_role = resolve_single_role(groups, LAMBDA_MAP)

    try:
        api_role: str | None = resolve_role(groups).value
    except AppError:
        api_role = None

    assert lambda_role == api_role, (
        f"layers disagree for {groups!r}: lambda={lambda_role}, api={api_role}"
    )


def test_both_layers_use_the_same_group_names() -> None:
    """A typo in one map would silently disable a role on one layer only."""
    assert set(DEFAULT_GROUP_ROLE_MAP) == set(LAMBDA_MAP)
    assert {r.value for r in DEFAULT_GROUP_ROLE_MAP.values()} == set(LAMBDA_MAP.values())


def test_exactly_three_roles_are_mapped() -> None:
    """FR-032 defines exactly three."""
    assert len(DEFAULT_GROUP_ROLE_MAP) == 3
    assert set(DEFAULT_GROUP_ROLE_MAP.values()) == {Role.ADMIN, Role.OPERATOR, Role.VIEWER}
