"""`RuleDefinition`'s three independent checks, and the versioning contract the
`/rules` API's response shape commits to (FR-004, FR-005, FR-006).

Structural/schema-level only -- full behavioral proof that an edit creates a new
version under the same key, against a real database, is
tests/integration/test_rules_api.py's job (T004). This file tests what a `Rule`'s
`definition` can express and what the API's Pydantic models accept/reject, without a
database.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routers.rules import Rule, RuleCreate, RuleDefinition, RuleUpdate


def test_definition_expresses_required_allowed_values_and_format_independently() -> None:
    """FR-004: a rule can require a tag, constrain its values, and constrain its
    format, and any subset of the three -- not one all-or-nothing check."""
    required_only = RuleDefinition(required=True, allowed_values=None, format_pattern=None)
    assert required_only.required is True
    assert required_only.allowed_values is None
    assert required_only.format_pattern is None

    allowed_values_only = RuleDefinition(
        required=False, allowed_values=["dev", "staging", "prod"], format_pattern=None
    )
    assert allowed_values_only.allowed_values == ["dev", "staging", "prod"]

    format_only = RuleDefinition(
        required=False, allowed_values=None, format_pattern=r"^PROJ-\d{4}$"
    )
    assert format_only.format_pattern == r"^PROJ-\d{4}$"

    all_three = RuleDefinition(required=True, allowed_values=["a", "b"], format_pattern=r"^[ab]$")
    assert all_three.required and all_three.allowed_values and all_three.format_pattern


def test_definition_severity_defaults_to_medium() -> None:
    """spec.md Assumptions: severity is admin-chosen, defaulting to medium."""
    definition = RuleDefinition(required=True, allowed_values=None, format_pattern=None)
    assert definition.severity == "medium"


def test_definition_rejects_an_unrecognized_severity() -> None:
    with pytest.raises(ValidationError):
        RuleDefinition(
            required=True, allowed_values=None, format_pattern=None, severity="catastrophic"
        )


def test_rule_create_requires_key_and_definition() -> None:
    with pytest.raises(ValidationError):
        RuleCreate(definition={"required": True})  # type: ignore[call-arg]


def test_rule_create_rejects_unrecognized_fields() -> None:
    """Same `extra='forbid'` discipline AccountCreate established for spec 002."""
    with pytest.raises(ValidationError):
        RuleCreate.model_validate(
            {
                "key": "cost_center",
                "definition": {"required": True, "severity": "medium"},
                "notARealField": "x",
            }
        )


def test_rule_update_omits_key_entirely() -> None:
    """FR-006: an edit targets a key via the URL path, never the request body --
    RuleUpdate has no key field to accidentally rename one through."""
    assert "key" not in RuleUpdate.model_fields


def test_rule_response_shape_carries_version_and_key_as_the_stable_identity() -> None:
    """research.md R-301: `key` is stable across edits; `version` is what changes."""
    rule = Rule(
        id="00000000-0000-0000-0000-000000000001",
        key="owner",
        version=2,
        enabled=True,
        definition=RuleDefinition(required=True, allowed_values=None, format_pattern=None),
    )
    assert rule.key == "owner"
    assert rule.version == 2
