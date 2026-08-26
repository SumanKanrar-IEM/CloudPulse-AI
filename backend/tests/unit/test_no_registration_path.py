"""There is no way to register, set a password, or assign a role (FR-031, FR-031a).

These are absence tests. They are unusual to write and easy to skip, but the properties
they protect are exactly the kind that get eroded by a reasonable-looking pull request:
"add a users admin screen" sounds like a feature, and it would make the platform a
second source of truth for authorisation.

The contract is the surface a client sees, so the contract is what gets asserted.
"""

from __future__ import annotations

import pytest

from app.api.main import openapi_document
from app.models.core import AppUser

FORBIDDEN_OPERATION_FRAGMENTS = (
    "register",
    "signup",
    "sign_up",
    "createuser",
    "create_user",
    "setpassword",
    "set_password",
    "changepassword",
    "resetpassword",
    "assignrole",
    "assign_role",
    "setrole",
    "set_role",
    "grantrole",
)


@pytest.fixture(scope="module")
def contract() -> dict:
    return openapi_document()


EXEMPT_PATH_PREFIXES = (
    # Spec 002's `POST /accounts` (operationId `registerAccount`) legitimately matches
    # the "register" fragment -- it is an admin-gated action registering a *cloud
    # account* (a governance object CloudPulse scans), not a self-service path for a
    # *person* to create their own identity. FR-031 is about the latter; identity still
    # comes exclusively from the directory (FR-031a), unchanged by this endpoint.
    "/accounts",
    # Spec 003's `POST /sdas` (operationId `registerSda`) is the same class of
    # exemption for the same reason: an admin-gated action registering a governance
    # object (a Service Delivery Area), never a person's identity. spec.md's own User
    # Story 2 and FR-007 use the word "register" for exactly this action -- renaming
    # the endpoint to dodge this fragment match would obscure the API's own vocabulary
    # to satisfy a check whose actual concern (self-service user registration) this
    # endpoint was never close to.
    "/sdas",
)


def test_no_registration_or_password_operation_exists(contract: dict) -> None:
    """FR-031: no self-service USER registration path, and no platform-held passwords."""
    operations = [
        (path, method, op.get("operationId", ""))
        for path, methods in contract["paths"].items()
        for method, op in methods.items()
        if isinstance(op, dict)
    ]

    offenders = [
        f"{method.upper()} {path} ({op_id})"
        for path, method, op_id in operations
        if not path.startswith(EXEMPT_PATH_PREFIXES)
        and any(f in (op_id + path).lower().replace("-", "") for f in FORBIDDEN_OPERATION_FRAGMENTS)
    ]
    assert not offenders, f"FR-031 violation -- registration/password surface: {offenders}"


def test_no_operation_can_assign_a_role(contract: dict) -> None:
    """FR-031a: the directory is the SOLE authority.

    SC-013 requires that 'the platform exposes no endpoint or screen through which any
    role can be assigned'. This is that assertion.
    """
    for path, methods in contract["paths"].items():
        for method, op in methods.items():
            if not isinstance(op, dict) or method.lower() in {"get", "head", "options"}:
                continue
            body = op.get("requestBody", {})
            rendered = str(body).lower()
            assert "role" not in rendered, (
                f"{method.upper()} {path} accepts a role in its request body -- "
                f"FR-031a forbids assigning a role through this platform"
            )


def test_role_appears_only_as_a_read_only_output(contract: dict) -> None:
    """`role` may be reported, never accepted."""
    current_user = contract["components"]["schemas"].get("CurrentUser")
    assert current_user is not None
    assert "role" in current_user["properties"], "/me must report the resolved role"


def test_app_user_model_stores_no_role_or_password() -> None:
    """The schema half of the same property."""
    columns = set(AppUser.__table__.c.keys())
    for forbidden in ("role", "roles", "password", "password_hash", "is_admin", "permissions"):
        assert forbidden not in columns, f"app_user.{forbidden} violates FR-031/FR-031a"


def test_health_is_the_only_public_operation(contract: dict) -> None:
    """FR-033a: no default-permit. Everything except /health requires a resolved role."""
    public = [
        (path, method)
        for path, methods in contract["paths"].items()
        for method, op in methods.items()
        if isinstance(op, dict) and op.get("security") == []
    ]
    assert public == [("/health", "get")], f"unexpected public operations: {public}"


def test_a_security_scheme_is_actually_declared(contract: dict) -> None:
    """A global requirement referencing an undefined scheme enforces nothing."""
    schemes = contract["components"].get("securitySchemes", {})
    assert "cognitoJwt" in schemes
    assert contract.get("security") == [{"cognitoJwt": []}]
