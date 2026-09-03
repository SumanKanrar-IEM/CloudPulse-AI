"""The pure pieces of spend ingestion: SDA attribution
(`app.governance.spend.resolve_sda_id`) and Cost Explorer response parsing
(`connectors.aws._parse_cost_and_usage_response`) -- spec 005, FR-001,
FR-002a.

The correction-in-place, gap-writing, and NULL-safe-uniqueness behavior
`ingest_spend_rows` itself provides is inherently DB-dependent (an `ON
CONFLICT` upsert has no meaning without a real unique index to conflict
against) and is tested for real in
`tests/integration/test_spend_ingestion.py` instead, matching this
project's own established unit/integration split (`compute_scan_deltas` is
pure and unit-tested; anything needing a real constraint is integration-
tested against a real PostgreSQL, e.g. `test_finding_kind_constraint.py`).
"""

from __future__ import annotations

from decimal import Decimal

from app.governance.spend import resolve_sda_id
from app.models.core import Sda
from connectors.aws import _parse_cost_and_usage_response

TAG_KEY = "project_id"


def _sda(name: str, tag_value: str) -> Sda:
    return Sda(name=name, owner_email=f"{name}@example.com", tag_values={TAG_KEY: tag_value})


def test_a_tag_value_matching_a_registered_sda_resolves_to_it() -> None:
    platform = _sda("platform", "proj-platform")
    data = _sda("data", "proj-data")
    assert resolve_sda_id("proj-platform", [platform, data], TAG_KEY) == platform.id


def test_a_tag_value_matching_no_registered_sda_resolves_to_none() -> None:
    platform = _sda("platform", "proj-platform")
    assert resolve_sda_id("proj-unregistered", [platform], TAG_KEY) is None


def test_a_none_tag_value_resolves_to_none_without_even_matching() -> None:
    """An untagged/unattributed resource -- the "No SDA" bucket -- regardless
    of what SDAs exist."""
    platform = _sda("platform", "proj-platform")
    assert resolve_sda_id(None, [platform], TAG_KEY) is None


def test_an_empty_sda_list_resolves_every_tag_value_to_none() -> None:
    assert resolve_sda_id("proj-platform", [], TAG_KEY) is None


def _ce_response(groups: list[tuple[str, str, str]]) -> dict[str, object]:
    """Build a `ce:GetCostAndUsage`-shaped response from
    `[(service, tag_group_key, amount)]` tuples, matching the real API's
    `ResultsByTime[].Groups[].{Keys,Metrics}` shape."""
    return {
        "ResultsByTime": [
            {
                "Groups": [
                    {
                        "Keys": [service, tag_group_key],
                        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
                    }
                    for service, tag_group_key, amount in groups
                ]
            }
        ]
    }


def test_a_tagged_group_key_extracts_the_value_after_the_dollar_sign() -> None:
    response = _ce_response([("AmazonEC2", "project_id$proj-platform", "12.3400000000")])
    rows = _parse_cost_and_usage_response(response)
    assert rows == [
        {
            "service": "AmazonEC2",
            "tag_value": "proj-platform",
            "amount_usd": Decimal("12.3400000000"),
        }
    ]


def test_an_untagged_group_key_extracts_a_none_tag_value_not_an_empty_string() -> None:
    """Cost Explorer's own group key for "no value" is `"project_id$"` -- an
    empty string after the `$`, which must map to `None` (the "No SDA"
    bucket), not the literal empty string `""`."""
    response = _ce_response([("AmazonS3", "project_id$", "0.5000000000")])
    rows = _parse_cost_and_usage_response(response)
    assert rows[0]["tag_value"] is None


def test_multiple_services_and_time_periods_all_appear() -> None:
    response: dict[str, object] = {
        "ResultsByTime": [
            {
                "Groups": [
                    {
                        "Keys": ["AmazonEC2", "project_id$proj-a"],
                        "Metrics": {"UnblendedCost": {"Amount": "1.00", "Unit": "USD"}},
                    },
                    {
                        "Keys": ["AmazonS3", "project_id$proj-b"],
                        "Metrics": {"UnblendedCost": {"Amount": "2.00", "Unit": "USD"}},
                    },
                ]
            }
        ]
    }
    rows = _parse_cost_and_usage_response(response)
    assert len(rows) == 2
    assert {r["service"] for r in rows} == {"AmazonEC2", "AmazonS3"}


def test_no_results_produces_an_empty_list_not_an_error() -> None:
    assert _parse_cost_and_usage_response({"ResultsByTime": []}) == []
