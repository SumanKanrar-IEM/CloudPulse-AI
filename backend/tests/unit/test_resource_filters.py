"""tagStatus/ownerStatus are independent filter dimensions (FR-010, FR-013,
research.md R-403) -- `_parse_tag_status` is the pure-logic half that's
testable without a database; the actual DB-backed distinction between a
tag-compliance fact and an ownership-attribution fact is proven end-to-end
in tests/integration/test_resources_api.py."""

from __future__ import annotations

import pytest

from app.api.errors import AppError
from app.api.routers.resources import _parse_tag_status


def test_compliant_parses_with_no_rule_key() -> None:
    assert _parse_tag_status("compliant") == ("compliant", None)


def test_missing_prefix_parses_the_rule_key() -> None:
    assert _parse_tag_status("missing:owner") == ("missing", "owner")


def test_an_unrecognized_value_is_a_422_not_a_silent_no_match() -> None:
    with pytest.raises(AppError):
        _parse_tag_status("not-a-real-value")


def test_missing_with_no_rule_key_is_a_422() -> None:
    with pytest.raises(AppError):
        _parse_tag_status("missing:")
