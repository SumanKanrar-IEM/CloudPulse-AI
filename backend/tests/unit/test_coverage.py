"""Coverage-as-data loading and dispatch (FR-021, FR-022, research.md R-203).

Not an explicit tasks.md task, but production code added alongside T007 needs its own
unit test per constitution Principle VI ("each story's definition of done includes
tests covering its acceptance criteria").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scan.coverage import (
    DEFAULT_DEFINITIONS_PATH,
    load_coverage_definitions,
    resolve_enrichment_function,
)

P1_TYPES = {
    "AWS::EC2::Instance",
    "AWS::EC2::Volume",
    "AWS::EC2::EIP",
    "AWS::S3::Bucket",
    "AWS::RDS::DBInstance",
    "AWS::Lambda::Function",
}


def test_default_file_seeds_the_six_p1_types() -> None:
    """FR-019: EC2, EBS, EIP, S3, RDS, Lambda."""
    definitions = load_coverage_definitions()
    assert set(definitions) == P1_TYPES
    for resource_type, definition in definitions.items():
        assert definition.resource_type == resource_type
        assert definition.enrichment_function
        assert len(definition.fields) > 0


def test_extending_coverage_is_a_pure_data_change(tmp_path: Path) -> None:
    """FR-021: a new resource type ships as a data change, no code touched.

    Proven the way SC-005's own acceptance criterion asks for: add one entry at
    runtime and confirm it is immediately usable.
    """
    seeded = json.loads(DEFAULT_DEFINITIONS_PATH.read_text(encoding="utf-8"))
    seeded["AWS::EKS::Cluster"] = {
        "enrichment_function": "enrich_eks_cluster",
        "fields": ["version", "status"],
    }
    extended_file = tmp_path / "coverage_definitions.json"
    extended_file.write_text(json.dumps(seeded), encoding="utf-8")

    definitions = load_coverage_definitions(extended_file)
    assert "AWS::EKS::Cluster" in definitions
    assert definitions["AWS::EKS::Cluster"].enrichment_function == "enrich_eks_cluster"


def test_malformed_entry_fails_loudly_at_load_time(tmp_path: Path) -> None:
    bad_file = tmp_path / "coverage_definitions.json"
    bad_file.write_text(json.dumps({"AWS::EC2::Instance": {"fields": ["x"]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="enrichment_function"):
        load_coverage_definitions(bad_file)


def test_resolve_enrichment_function_dispatches_by_name() -> None:
    definitions = load_coverage_definitions()
    calls: list[str] = []

    def _enrich_ec2_instance(resource: object) -> dict[str, object]:
        calls.append("called")
        return {}

    registry = {"enrich_ec2_instance": _enrich_ec2_instance}
    fn = resolve_enrichment_function("AWS::EC2::Instance", definitions, registry)
    assert fn is not None
    fn(object())
    assert calls == ["called"]


def test_resolve_enrichment_function_returns_none_for_uncovered_type() -> None:
    definitions = load_coverage_definitions()
    fn = resolve_enrichment_function("AWS::EKS::Cluster", definitions, {})
    assert fn is None


def test_resolve_enrichment_function_returns_none_when_registry_lacks_the_name() -> None:
    """A definition can name a function the registry hasn't shipped yet without crashing."""
    definitions = load_coverage_definitions()
    fn = resolve_enrichment_function("AWS::EC2::Instance", definitions, {})
    assert fn is None
