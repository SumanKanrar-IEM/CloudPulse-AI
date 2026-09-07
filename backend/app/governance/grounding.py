"""Deterministic grounding validation for agent output (spec 006, T007;
FR-001, FR-001a, FR-006, research.md R-607).

**Ordinary Python, never a second model call.** A validator that could itself
hallucinate would defeat its own purpose, and Principle IV's testable clause --
"every agent response passes a grounding validator that rejects ARNs and metrics
absent from the platform datastore" -- is only meaningful if the validator is
deterministic. It is also what lets SC-001 be proven in CI while the model
itself is unreachable (FR-007a).

**What is validated, per FR-001a.** Two classes, checked differently:

* **References** -- ARNs, resource ids, finding ids, project names -- are
  *declared* by the agent as structured data, so each is an exact lookup against
  what the platform holds. No prose parsing is involved.
* **Figures** -- platform-computed quantities -- are declared the same way and
  checked against the set the platform actually computed. The body is then swept
  for anything that *reads* as a platform figure (currency, percentage) but was
  not declared, because FR-001a treats a quantity presented as a platform figure
  that the platform never computed as unresolvable.

Ordinary prose numerals are deliberately exempt. "The last 7 days" and "the top
3 findings" are not platform figures, and flagging them would make grounding
reject correct digests routinely -- which R-607 names as the *unacceptable*
failure direction. Rejecting a good digest is bad; displaying a fabricated ARN
is worse, and the asymmetry is what these rules encode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.models.enums import GroundingReferenceKind

# The reference kinds the digest contract emits, mapped to the rejection kind an
# admin reads. `resource` splits on shape: an ARN rejects as an ARN, because
# "which ARN was fabricated" is the more useful diagnosis.
_KIND_TO_REJECTION: dict[str, GroundingReferenceKind] = {
    "finding": GroundingReferenceKind.FINDING_ID,
    "sda": GroundingReferenceKind.SDA,
    "account": GroundingReferenceKind.RESOURCE_ID,
    "resource": GroundingReferenceKind.RESOURCE_ID,
}

# Currency and percentages read as platform figures wherever they appear. A bare
# integer does not -- see the module docstring on FR-001a's exemption.
_PROSE_FIGURE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)|\b(\d[\d,]*\.\d+)\s?%|\b(\d[\d,]*)\s?%")


@dataclass(frozen=True)
class Reference:
    """One identifier an agent cited, declared rather than parsed from prose."""

    kind: str
    id: str
    label: str


@dataclass(frozen=True)
class Figure:
    """One platform-computed quantity an agent stated (FR-001a)."""

    label: str
    value: Decimal


@dataclass(frozen=True)
class Section:
    heading: str
    body: str
    references: list[Reference] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)


@dataclass(frozen=True)
class GroundingVerdict:
    """Pass, or the first thing that could not be resolved.

    One rejection is reported rather than all of them: it is enough to diagnose,
    and enumerating every fabricated identifier back to an admin turns a
    rejection record into a list of things that do not exist.
    """

    ok: bool
    rejected_reference: str | None = None
    reference_kind: GroundingReferenceKind | None = None


def _rejection_kind(reference: Reference) -> GroundingReferenceKind:
    if reference.kind == "resource" and reference.id.startswith("arn:"):
        return GroundingReferenceKind.ARN
    return _KIND_TO_REJECTION.get(reference.kind, GroundingReferenceKind.RESOURCE_ID)


def _normalise(value: Decimal) -> Decimal:
    """`1234.5` and `1234.50` are the same quantity.

    Comparing unnormalised would reject correct output on formatting alone,
    which is the failure direction R-607 rules out.
    """
    return value.normalize()


def _prose_figures(body: str) -> list[Decimal]:
    """Quantities in prose that read as platform figures."""
    found: list[Decimal] = []
    for match in _PROSE_FIGURE.finditer(body):
        raw = next((g for g in match.groups() if g), None)
        if raw is None:
            continue
        try:
            found.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:  # pragma: no cover - regex admits only decimals
            continue
    return found


def validate_output(
    sections: list[Section],
    *,
    known_references: dict[str, set[str]],
    known_figures: set[Decimal],
) -> GroundingVerdict:
    """FR-001: pass, or reject naming the first unresolvable reference.

    `known_references` maps a reference kind to the identifiers the platform
    holds for it; `known_figures` is every quantity the platform computed for
    this run. Both are supplied by the caller rather than queried here, so this
    stays pure and unit-testable with no database -- which is what makes it
    provable in CI while the model is unreachable.

    An empty `sections` list passes: FR-010's "nothing notable" digest has no
    sections, and that is a valid result rather than a validation failure.
    """
    normalised_known = {_normalise(f) for f in known_figures}

    for section in sections:
        for reference in section.references:
            if reference.id not in known_references.get(reference.kind, set()):
                return GroundingVerdict(
                    ok=False,
                    rejected_reference=reference.id,
                    reference_kind=_rejection_kind(reference),
                )

        declared = {_normalise(f.value) for f in section.figures}
        for figure in section.figures:
            if _normalise(figure.value) not in normalised_known:
                return GroundingVerdict(
                    ok=False,
                    rejected_reference=str(figure.value),
                    reference_kind=GroundingReferenceKind.FIGURE,
                )

        # FR-001a: a quantity presented as a platform figure but not declared
        # cannot have been checked, so it is unresolvable by definition.
        for prose_value in _prose_figures(section.body):
            if _normalise(prose_value) not in declared:
                return GroundingVerdict(
                    ok=False,
                    rejected_reference=str(prose_value),
                    reference_kind=GroundingReferenceKind.FIGURE,
                )

    return GroundingVerdict(ok=True)


__all__ = [
    "Figure",
    "GroundingVerdict",
    "Reference",
    "Section",
    "validate_output",
]
