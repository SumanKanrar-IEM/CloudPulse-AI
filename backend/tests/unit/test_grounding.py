"""The grounding validator (T006; spec 006, FR-001, FR-001a, FR-006, R-607).

Pure by construction, and that is the point twice over: Principle IV's testable
clause demands "every agent response passes a grounding validator that rejects
ARNs and metrics absent from the platform datastore", which is only meaningful
if the validator is deterministic — a validator that itself hallucinated would
defeat its own purpose. It is also what lets SC-001 be proven in CI while the
model is unreachable.

FR-001a's boundary is tested in **both** directions. Rejecting a real digest
because "the last 7 days" contains a numeral would make grounding useless in
practice; letting a fabricated dollar figure through would make it dishonest.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.governance.grounding import (
    Figure,
    Reference,
    Section,
    validate_output,
)
from app.models.enums import GroundingReferenceKind

ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc"


def _known() -> dict[str, set[str]]:
    """What the platform actually holds, as the caller supplies it."""
    return {
        "resource": {ARN, "res-1"},
        "finding": {"find-1"},
        "sda": {"platform"},
        "account": {"acct-1"},
    }


def _section(
    body: str = "Nothing unusual.",
    references: list[Reference] | None = None,
    figures: list[Figure] | None = None,
) -> Section:
    return Section(
        heading="Findings", body=body, references=references or [], figures=figures or []
    )


# --- references --------------------------------------------------------------------


def test_an_output_citing_only_real_references_passes() -> None:
    verdict = validate_output(
        [_section(references=[Reference("resource", ARN, "web server")])],
        known_references=_known(),
        known_figures=set(),
    )
    assert verdict.ok
    assert verdict.rejected_reference is None


def test_an_output_citing_an_absent_arn_is_rejected() -> None:
    verdict = validate_output(
        [_section(references=[Reference("resource", "arn:aws:ec2:::i-fake", "ghost")])],
        known_references=_known(),
        known_figures=set(),
    )
    assert not verdict.ok
    assert verdict.rejected_reference == "arn:aws:ec2:::i-fake"
    assert verdict.reference_kind is GroundingReferenceKind.ARN


def test_a_non_arn_resource_id_rejects_as_resource_id_not_arn() -> None:
    """The rejection's `reference_kind` is what an admin reads to diagnose, so it
    must describe what actually failed rather than defaulting to one value."""
    verdict = validate_output(
        [_section(references=[Reference("resource", "res-fake", "ghost")])],
        known_references=_known(),
        known_figures=set(),
    )
    assert verdict.reference_kind is GroundingReferenceKind.RESOURCE_ID


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("finding", GroundingReferenceKind.FINDING_ID),
        ("sda", GroundingReferenceKind.SDA),
    ],
)
def test_each_reference_kind_rejects_under_its_own_label(kind: str, expected: object) -> None:
    verdict = validate_output(
        [_section(references=[Reference(kind, "absent", "ghost")])],
        known_references=_known(),
        known_figures=set(),
    )
    assert not verdict.ok
    assert verdict.reference_kind is expected


def test_the_first_unresolvable_reference_is_the_one_reported() -> None:
    """Reporting one is enough to diagnose, and stopping there means a rejection
    never enumerates a list of fabricated identifiers back to an admin."""
    verdict = validate_output(
        [
            _section(references=[Reference("resource", "first-fake", "a")]),
            _section(references=[Reference("resource", "second-fake", "b")]),
        ],
        known_references=_known(),
        known_figures=set(),
    )
    assert verdict.rejected_reference == "first-fake"


# --- declared figures (FR-001a) ----------------------------------------------------


def test_a_declared_figure_the_platform_computed_passes() -> None:
    verdict = validate_output(
        [_section(figures=[Figure("month-to-date spend", Decimal("1234.50"))])],
        known_references=_known(),
        known_figures={Decimal("1234.50")},
    )
    assert verdict.ok


def test_a_declared_figure_the_platform_never_computed_is_rejected() -> None:
    verdict = validate_output(
        [_section(figures=[Figure("month-to-date spend", Decimal("9999.99"))])],
        known_references=_known(),
        known_figures={Decimal("1234.50")},
    )
    assert not verdict.ok
    assert verdict.reference_kind is GroundingReferenceKind.FIGURE
    assert verdict.rejected_reference == "9999.99"


def test_figure_comparison_ignores_trailing_zero_formatting() -> None:
    """`1234.5` and `1234.50` are the same quantity. Rejecting on formatting
    would make the validator fail on correct output, which R-607 names as the
    unacceptable failure direction."""
    verdict = validate_output(
        [_section(figures=[Figure("spend", Decimal("1234.5"))])],
        known_references=_known(),
        known_figures={Decimal("1234.50")},
    )
    assert verdict.ok


# --- prose numerals (FR-001a's exemption) ------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "Spend rose over the last 7 days.",
        "The top 3 findings are listed below.",
        "Reviewed 12 resources.",
    ],
)
def test_a_plain_prose_numeral_does_not_trigger_rejection(body: str) -> None:
    """FR-001a exempts numerals the platform does not compute. Flagging these
    would make grounding reject correct digests routinely."""
    verdict = validate_output([_section(body=body)], known_references=_known(), known_figures=set())
    assert verdict.ok


@pytest.mark.parametrize("body", ["Spend reached $4,200.00 this month.", "Coverage fell to 61.4%."])
def test_an_undeclared_platform_shaped_figure_in_prose_is_rejected(body: str) -> None:
    """FR-001a: a quantity presented as a platform figure but never computed is
    unresolvable. Currency and percentages read as platform figures; declaring
    them is what makes them checkable."""
    verdict = validate_output([_section(body=body)], known_references=_known(), known_figures=set())
    assert not verdict.ok
    assert verdict.reference_kind is GroundingReferenceKind.FIGURE


def test_a_prose_figure_that_was_declared_and_validated_passes() -> None:
    verdict = validate_output(
        [
            _section(
                body="Spend reached $4,200.00 this month.",
                figures=[Figure("spend", Decimal("4200.00"))],
            )
        ],
        known_references=_known(),
        known_figures={Decimal("4200.00")},
    )
    assert verdict.ok


def test_a_declared_figure_absent_from_the_prose_is_still_validated() -> None:
    """Declaring a figure is not a way to smuggle one past the store — every
    declared figure is checked whether or not it appears in the body."""
    verdict = validate_output(
        [_section(body="No figures here.", figures=[Figure("spend", Decimal("1.00"))])],
        known_references=_known(),
        known_figures=set(),
    )
    assert not verdict.ok


# --- shape -------------------------------------------------------------------------


def test_an_empty_output_passes_rather_than_erroring() -> None:
    """FR-010's "nothing notable" digest has no sections. That is a valid result,
    not a validation failure."""
    assert validate_output([], known_references=_known(), known_figures=set()).ok


def test_validation_is_deterministic_over_the_same_input() -> None:
    """R-607: the validator is ordinary code. Running it twice must give the same
    verdict, or Principle IV's testable clause means nothing."""
    sections = [_section(references=[Reference("resource", "absent", "x")])]
    first = validate_output(sections, known_references=_known(), known_figures=set())
    second = validate_output(sections, known_references=_known(), known_figures=set())
    assert (first.ok, first.rejected_reference, first.reference_kind) == (
        second.ok,
        second.rejected_reference,
        second.reference_kind,
    )
