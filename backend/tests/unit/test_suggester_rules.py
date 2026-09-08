"""The suggester's rules, proved without a database (T021; spec 006, FR-011,
FR-013, FR-014, Clarification 2026-09-05).

What is testable here is everything that does not need a store: what a
suggestion is allowed to cite, and what the parser accepts. The rules that are
genuinely about rows -- FR-013's refusal to overwrite an admin-seeded
suggestion, FR-014's skipping of a closed finding, and FR-004a's retention of
validated items past the cap -- are enforced by a query and a conflict clause,
so `test_suggester_pipeline.py` proves those against a real PostgreSQL. Asserting
them against a stub session here would prove only that the stub agreed with the
test.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.governance.grounding import validate_output
from app.governance.suggester import (
    SuggestionTarget,
    known_references_for,
    parse_draft,
)

FINDING_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
RESOURCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
ARN = "arn:aws:s3:::bucket-1"
OTHER_ARN = "arn:aws:s3:::someone-elses-bucket"


def _target(**overrides: object) -> SuggestionTarget:
    fields: dict[str, object] = {
        "finding_id": FINDING_ID,
        "resource_id": RESOURCE_ID,
        "resource_arn": ARN,
        "resource_type": "AWS::S3::Bucket",
        "rule_key": "owner",
        "severity": "high",
    }
    fields.update(overrides)
    return SuggestionTarget(**fields)  # type: ignore[arg-type]


def _draft(suggestion: str, blast_radius: str, references: list[dict[str, str]]) -> str:
    return json.dumps(
        {"suggestion": suggestion, "blastRadius": blast_radius, "references": references}
    )


# --- what one suggestion may cite (FR-011) -----------------------------------


def test_the_vocabulary_is_scoped_to_this_findings_own_resource() -> None:
    """Clarification 2026-09-05: per individual finding, specific to that
    finding's own resource. A tenant-wide vocabulary would let a suggestion cite
    a real ARN belonging to some other finding and still validate -- grounded,
    and still not a suggestion about the thing it claims to be about."""
    references = known_references_for(_target())

    assert references["finding"] == {str(FINDING_ID)}
    assert references["resource"] == {ARN, str(RESOURCE_ID)}


def test_a_suggestion_naming_another_findings_resource_is_rejected() -> None:
    """The property the scoping above exists to enforce, asserted end to end
    through the validator rather than by inspecting the dictionary."""
    draft = parse_draft(
        FINDING_ID,
        _draft(
            "Add an owner tag to the bucket.",
            "Tagging is metadata-only and changes no access.",
            [{"kind": "resource", "id": OTHER_ARN, "label": "a bucket"}],
        ),
    )

    verdict = validate_output(
        draft.sections, known_references=known_references_for(_target()), known_figures=set()
    )

    assert verdict.ok is False
    assert verdict.rejected_reference == OTHER_ARN


def test_a_suggestion_naming_its_own_resource_passes() -> None:
    """R-607's direction: a correct suggestion must be accepted. A validator
    that only ever refuses would satisfy every rejection test above and be
    useless."""
    draft = parse_draft(
        FINDING_ID,
        _draft(
            "Add an owner tag to the bucket.",
            "Tagging is metadata-only and changes no access.",
            [{"kind": "resource", "id": ARN, "label": "a bucket"}],
        ),
    )

    verdict = validate_output(
        draft.sections, known_references=known_references_for(_target()), known_figures=set()
    )

    assert verdict.ok is True


def test_a_finding_with_no_resource_still_gets_a_vocabulary() -> None:
    """A budget-overrun finding attaches to a project, not a resource (spec 005,
    R-508). It must not produce a `resource` key holding nothing -- an empty set
    would read as "no resource is citable" and is correct, but a missing key and
    a KeyError are not the same thing."""
    references = known_references_for(_target(resource_id=None, resource_arn=None))

    assert references == {"finding": {str(FINDING_ID)}}


def test_an_arn_less_finding_still_cites_by_resource_id() -> None:
    """The half-populated case: a resource row exists but carries no ARN. The
    id is still a real identifier and must stay citable, rather than the branch
    raising because the ARN was the one it keyed on."""
    references = known_references_for(_target(resource_arn=None))

    assert references["resource"] == {str(RESOURCE_ID)}


# --- the output contract, fail-closed ----------------------------------------


def test_both_halves_are_required() -> None:
    """FR-011 asks for a fix *and* a blast-radius note. An empty note is not a
    suggestion with nothing to warn about; it is one that skipped the half a
    reader leans on hardest before acting."""
    with pytest.raises(ValueError, match="blast-radius"):
        parse_draft(FINDING_ID, _draft("Add an owner tag.", "   ", []))

    with pytest.raises(ValueError, match="blast-radius"):
        parse_draft(FINDING_ID, _draft("", "Metadata only.", []))


def test_a_missing_field_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="malformed suggestion"):
        parse_draft(FINDING_ID, json.dumps({"suggestion": "Add a tag."}))


def test_malformed_json_is_refused() -> None:
    """Fail-closed. A best-effort read would drop the broken part silently, and
    a fabricated ARN inside it would then never reach the validator at all."""
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_draft(FINDING_ID, "here is my suggestion: add a tag")


def test_a_malformed_reference_is_refused_not_skipped() -> None:
    """Dropping an unparseable reference would let the model evade validation by
    emitting a broken one -- the citation disappears, and the prose that relied
    on it is stored unchallenged."""
    with pytest.raises(ValueError, match="malformed reference"):
        parse_draft(
            FINDING_ID,
            json.dumps(
                {
                    "suggestion": "Add a tag.",
                    "blastRadius": "Metadata only.",
                    "references": [{"label": "no kind or id here"}],
                }
            ),
        )


def test_references_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="references must be a list"):
        parse_draft(
            FINDING_ID,
            json.dumps(
                {"suggestion": "Add a tag.", "blastRadius": "Metadata only.", "references": {}}
            ),
        )


# --- both halves are validated together --------------------------------------


def test_a_fabricated_arn_in_the_blast_radius_note_is_caught() -> None:
    """The fix and the note are validated as one body, deliberately. Validating
    only the fix would let a fabricated resource appear in the note -- the half
    a reader consults precisely because they are about to change something."""
    draft = parse_draft(
        FINDING_ID,
        _draft(
            "Add an owner tag to the bucket.",
            f"This bucket is read by {OTHER_ARN}, which would lose access.",
            [{"kind": "resource", "id": OTHER_ARN, "label": "a consumer"}],
        ),
    )

    verdict = validate_output(
        draft.sections, known_references=known_references_for(_target()), known_figures=set()
    )

    assert verdict.ok is False
    assert OTHER_ARN in draft.sections[0].body


def test_the_stored_halves_stay_separate_even_though_they_validate_together() -> None:
    """Joined for validation, separate on the row. FR-012's interface has to show
    a fix and a blast-radius note as distinct things, so concatenating them for
    storage would make the display re-split prose the model wrote."""
    draft = parse_draft(FINDING_ID, _draft("Add an owner tag.", "Metadata only.", []))

    assert draft.suggestion_text == "Add an owner tag."
    assert draft.blast_radius_note == "Metadata only."
    assert draft.sections[0].body == "Add an owner tag.\n\nMetadata only."


def test_no_figures_are_declared_so_a_number_in_prose_is_unresolvable() -> None:
    """A suggestion has no platform-computed quantities behind it, so
    `known_figures` is empty and FR-001a's prose sweep rejects any currency or
    percentage the model volunteers. "$400 a month in savings" is exactly the
    kind of confident invention this catches."""
    draft = parse_draft(
        FINDING_ID,
        _draft("Delete the volume to save $400.00 a month.", "The volume is unattached.", []),
    )

    verdict = validate_output(
        draft.sections, known_references=known_references_for(_target()), known_figures=set()
    )

    assert verdict.ok is False
    assert verdict.rejected_reference == "400.00"
