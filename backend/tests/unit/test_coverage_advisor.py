"""The coverage advisor's split: what can be accepted, and what may only be read
(T032; spec 006, FR-015, FR-015a, research.md R-603).

The rule this file exists to pin: **a gap is proposable only when accepting it
would actually take effect for that type.** Enabling an already-existing
enricher does, as configuration on the next scan. A resource type nobody has
written an enricher for does not, so it is advisory content and never an
acceptable proposal — an accept button that could not take effect misrepresents
what the platform can do, which the spec judges worse than not surfacing the gap
at all (FR-015a).

`detect_gaps` is pure, so all of this is provable with no database and no cloud
client. The registry of available enrichers is passed in rather than imported:
it lives in `connectors/aws.py` behind the connector boundary, and reaching
across that boundary to read it would put provider-adjacent detail in the
governance core.
"""

from __future__ import annotations

import uuid

from app.governance.coverage_advisor import (
    AdvisoryGap,
    InventoryType,
    ProposableGap,
    detect_gaps,
)
from app.models.enums import CoverageProposalKind

ACCOUNT = uuid.UUID("33333333-3333-3333-3333-333333333333")

# What this build actually ships, mirroring connectors/aws.py's registry shape.
KNOWN_ENRICHERS = {"enrich_ec2_instance", "enrich_s3_bucket", "enrich_sqs_queue"}

# Types already mapped in coverage_definitions.json.
COVERED = {"AWS::EC2::Instance", "AWS::S3::Bucket"}


def _seen(resource_type: str, count: int = 3) -> InventoryType:
    return InventoryType(
        resource_type=resource_type, evidence_account_id=ACCOUNT, resource_count=count
    )


# --- proposable: the gap closes as configuration (FR-015) --------------------


def test_a_type_with_an_existing_enricher_is_proposable() -> None:
    """The enrichment routine exists and is simply not mapped to this type yet.
    Accepting writes a mapping, and the next scan reads it — no deployment."""
    proposable, advisory = detect_gaps(
        [_seen("AWS::SQS::Queue")],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={"AWS::SQS::Queue": "enrich_sqs_queue"},
    )

    assert advisory == []
    assert len(proposable) == 1
    assert proposable[0].kind is CoverageProposalKind.ENABLE_EXISTING_ENRICHER
    assert proposable[0].proposed_change["enrichment_function"] == "enrich_sqs_queue"


def test_the_proposal_names_the_account_that_revealed_the_gap() -> None:
    """FR-017: evidence, not scope. Acceptance applies tenant-wide, and an admin
    should be able to see they are accepting that on one account's data."""
    proposable, _ = detect_gaps(
        [_seen("AWS::SQS::Queue")],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={"AWS::SQS::Queue": "enrich_sqs_queue"},
    )

    assert proposable[0].evidence_account_id == ACCOUNT


# --- advisory: the gap needs code (FR-015a) ---------------------------------


def test_a_type_with_no_enricher_is_advisory_never_proposable() -> None:
    """FR-015a, and the reason `CoverageProposalKind` has exactly two members.
    Nothing here can produce a third kind, so nothing can write this gap into
    `coverage_proposal`."""
    proposable, advisory = detect_gaps(
        [_seen("AWS::Kinesis::Stream")],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={},
    )

    assert proposable == []
    assert len(advisory) == 1
    assert advisory[0].resource_type == "AWS::Kinesis::Stream"
    assert "code change" in advisory[0].reason


def test_a_named_enricher_that_does_not_exist_is_advisory_not_proposable() -> None:
    """The dangerous case: the platform has a *name* for the routine but this
    build does not ship it. It looks closeable and is not.

    Without this branch, `enricher_for_type` would be trusted as proof of
    existence, and accepting the proposal would write a mapping to a function
    that resolves to None — enrichment silently doing nothing, which is exactly
    the failure `scan/coverage.py` raises loudly to avoid.
    """
    proposable, advisory = detect_gaps(
        [_seen("AWS::Redshift::Cluster")],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={"AWS::Redshift::Cluster": "enrich_redshift_cluster"},
    )

    assert proposable == []
    assert len(advisory) == 1
    assert "not present in this build" in advisory[0].reason
    # The reason names the routine, so a reader can tell this from "nobody has
    # written one" — different problems with different fixes.
    assert "enrich_redshift_cluster" in advisory[0].reason


def test_advisory_and_proposable_are_different_types() -> None:
    """A flag on one type would let a single careless `if` write an advisory gap
    into `coverage_proposal`. Two types make that a type error instead."""
    proposable, advisory = detect_gaps(
        [_seen("AWS::SQS::Queue"), _seen("AWS::Kinesis::Stream")],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={"AWS::SQS::Queue": "enrich_sqs_queue"},
    )

    assert all(isinstance(g, ProposableGap) for g in proposable)
    assert all(isinstance(g, AdvisoryGap) for g in advisory)
    assert not hasattr(advisory[0], "kind")


# --- what is not a gap at all ------------------------------------------------


def test_a_covered_type_is_neither() -> None:
    """Already mapped. Proposing it would be noise, and accepting would rewrite
    a mapping that is already correct."""
    proposable, advisory = detect_gaps(
        [_seen("AWS::EC2::Instance"), _seen("AWS::S3::Bucket")],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={"AWS::EC2::Instance": "enrich_ec2_instance"},
    )

    assert proposable == []
    assert advisory == []


def test_an_empty_inventory_produces_nothing() -> None:
    """A tenant with no resources has no gaps — not one gap per known type. The
    advisor reports on what a tenant actually has (FR-015: "present in a
    tenant's inventory")."""
    proposable, advisory = detect_gaps(
        [], covered_types=COVERED, known_enrichers=KNOWN_ENRICHERS, enricher_for_type={}
    )

    assert proposable == []
    assert advisory == []


# --- the mixed case, which is the realistic one ------------------------------


def test_a_mixed_inventory_splits_correctly() -> None:
    """Covered, proposable and advisory in one pass. Each pairwise test above
    passes under several wrong implementations; this one does not."""
    proposable, advisory = detect_gaps(
        [
            _seen("AWS::EC2::Instance"),
            _seen("AWS::SQS::Queue"),
            _seen("AWS::Kinesis::Stream"),
            _seen("AWS::Redshift::Cluster"),
        ],
        covered_types=COVERED,
        known_enrichers=KNOWN_ENRICHERS,
        enricher_for_type={
            "AWS::SQS::Queue": "enrich_sqs_queue",
            "AWS::Redshift::Cluster": "enrich_redshift_cluster",
        },
    )

    assert [g.resource_type for g in proposable] == ["AWS::SQS::Queue"]
    assert sorted(g.resource_type for g in advisory) == [
        "AWS::Kinesis::Stream",
        "AWS::Redshift::Cluster",
    ]


def test_detection_is_deterministic_for_the_same_inventory() -> None:
    """FR-015's proposals feed an admin decision queue. The same inventory
    producing a different split between runs would make that queue unreadable."""
    inventory = [_seen("AWS::SQS::Queue"), _seen("AWS::Kinesis::Stream")]
    args = {
        "covered_types": COVERED,
        "known_enrichers": KNOWN_ENRICHERS,
        "enricher_for_type": {"AWS::SQS::Queue": "enrich_sqs_queue"},
    }

    first = detect_gaps(inventory, **args)  # type: ignore[arg-type]
    second = detect_gaps(inventory, **args)  # type: ignore[arg-type]

    assert first == second


# --- FR-017: the scan path reads accepted overrides as configuration ----------


def test_an_accepted_override_resolves_to_its_enricher_on_the_next_scan(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The whole of FR-017's "no code deployment": the override is a mapping
    merged over the shipped file at read time, and `resolve_enrichment_function`
    finds it the same way it finds a shipped entry."""
    from app.scan.coverage import load_coverage_definitions, resolve_enrichment_function

    shipped = tmp_path / "coverage_definitions.json"
    shipped.write_text('{"AWS::S3::Bucket": {"enrichment_function": "enrich_s3", "fields": []}}')

    def enrich_s3(*_: object) -> dict[str, object]:
        return {}

    def enrich_cache(*_: object) -> dict[str, object]:
        return {"engine": "redis"}

    registry = {"enrich_s3": enrich_s3, "enrich_cache": enrich_cache}
    definitions = load_coverage_definitions(
        shipped, overrides={"AWS::ElastiCache::CacheCluster": "enrich_cache"}
    )

    assert (
        resolve_enrichment_function("AWS::ElastiCache::CacheCluster", definitions, registry)
        is enrich_cache
    )
    # And the shipped entry is untouched by the merge.
    assert resolve_enrichment_function("AWS::S3::Bucket", definitions, registry) is enrich_s3


def test_the_shipped_file_wins_over_an_override_for_a_covered_type(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """An override for a type already covered is a proposal the advisor should
    never have raised. The shipped definition has a reviewer attached; the
    override does not get to replace it."""
    from app.scan.coverage import load_coverage_definitions

    shipped = tmp_path / "coverage_definitions.json"
    shipped.write_text('{"AWS::S3::Bucket": {"enrichment_function": "enrich_s3", "fields": []}}')

    definitions = load_coverage_definitions(
        shipped, overrides={"AWS::S3::Bucket": "something_else"}
    )

    assert definitions["AWS::S3::Bucket"].enrichment_function == "enrich_s3"
