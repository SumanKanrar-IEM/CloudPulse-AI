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
import unicodedata
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
#
# The body is NFKC-normalised before this runs, which is load-bearing rather than
# tidiness: without it a fullwidth dollar sign or percent sign is invisible to an
# ASCII pattern while reading identically to a human, so a fabricated figure passes
# unchecked. Normalising folds those to their ASCII forms first.
#
# Currency symbols beyond `$` are matched for the same reason -- recognising only
# `$` means "€9999" is never swept at all.
_CURRENCY = r"[$\u20ac\u00a3\u00a5]|\b(?:USD|EUR|GBP|JPY)\b"

# A deliberately strict number grammar: either well-formed thousands grouping or
# no grouping at all. `4,2,0,0.00` matches neither, and is treated as an
# unparseable figure rather than silently normalised onto a declared 4200.00.
_NUMBER = r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?"

# Anything currency- or percent-shaped, captured loosely so a token that *looks*
# like a figure but parses badly still gets flagged (fail-closed, R-607).
# The sign is captured separately because it can sit either side of the currency
# symbol: "-$500" and "$-500" read the same to a person, and dropping the minus
# would let a stated saving validate against a declared cost of the same
# magnitude -- the reader and the validator seeing opposite facts.
_FIGURE_TOKEN = re.compile(
    rf"(?P<sign_before>-)?\s?(?:{_CURRENCY})\s?(?P<amount>[-\d][\d,.\u066b\u066c]*)"
    rf"|(?P<pct>-?[\d][\d,.]*)\s?%"
    rf"|(?P<amount_after>-?[\d][\d,.]*)\s?(?:USD|EUR|GBP|JPY)\b"
)
_STRICT_NUMBER = re.compile(rf"^(?:{_NUMBER})$")

# Exact-figure mode (FR-024): every number in prose, not only currency- and
# percent-shaped ones. ISO dates are removed first -- "2026-03-01" is a date the
# chart labels an axis with, not three figures the calculation produced.
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_BARE_NUMBER = re.compile(rf"(?<![\w.])(?P<number>{_NUMBER})(?![\w.])")


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


def _prose_figures(body: str) -> list[Decimal | str]:
    """Quantities in prose that read as platform figures.

    Returns a `Decimal` for anything well-formed and the raw token for anything
    that reads as a figure but does not parse. Both must be declared; the raw
    form is kept so a rejection names what was actually written rather than a
    number the validator invented while trying to parse it.

    Fail-closed by design (R-607): a token shaped like money or a percentage
    that cannot be parsed is treated as unresolvable, not skipped. Skipping is
    how `$4,2,0,0.00` would slip through by normalising onto a declared 4200.00.
    """
    normalised = unicodedata.normalize("NFKC", body)
    found: list[Decimal | str] = []
    for match in _FIGURE_TOKEN.finditer(normalised):
        raw = match.group("amount") or match.group("pct") or match.group("amount_after")
        if raw is None:  # pragma: no cover - every branch captures a group
            continue
        raw = raw.rstrip(".,")
        if match.group("sign_before") and not raw.startswith("-"):
            raw = f"-{raw}"
        if not _STRICT_NUMBER.match(raw):
            found.append(raw)
            continue
        try:
            found.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:  # pragma: no cover - grammar admits only decimals
            found.append(raw)
    return found


def _bare_numbers(body: str) -> list[Decimal]:
    """Every number in prose, for exact-figure mode. Dates are stripped first;
    the currency/percent tokens are found by `_prose_figures` and are matched
    here too, which is harmless -- a declared figure passes both sweeps."""
    normalised = _ISO_DATE.sub(" ", unicodedata.normalize("NFKC", body))
    found: list[Decimal] = []
    for match in _BARE_NUMBER.finditer(normalised):
        try:
            found.append(Decimal(match.group("number").replace(",", "")))
        except InvalidOperation:  # pragma: no cover - grammar admits only decimals
            continue
    return found


def validate_output(
    sections: list[Section],
    *,
    known_references: dict[str, set[str]],
    known_figures: set[Decimal],
    exact_figures: bool = False,
) -> GroundingVerdict:
    """FR-001: pass, or reject naming the first unresolvable reference.

    `known_references` maps a reference kind to the identifiers the platform
    holds for it; `known_figures` is every quantity the platform computed for
    this run. Both are supplied by the caller rather than queried here, so this
    stays pure and unit-testable with no database -- which is what makes it
    provable in CI while the model is unreachable.

    `exact_figures` is FR-024's mode for narratives beside a chart. FR-001a
    exempts bare integers ("3 findings" is a count, not a platform figure);
    FR-024 does not -- "a narrative MUST NOT introduce any figure the
    deterministic calculation did not produce", and beside a chart every
    number reads as one of its values. In this mode every number in the prose
    must be declared, ISO dates excepted.

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
            if isinstance(prose_value, str) or _normalise(prose_value) not in declared:
                return GroundingVerdict(
                    ok=False,
                    rejected_reference=str(prose_value),
                    reference_kind=GroundingReferenceKind.FIGURE,
                )

        if exact_figures:
            for number in _bare_numbers(section.body):
                if _normalise(number) not in declared:
                    return GroundingVerdict(
                        ok=False,
                        rejected_reference=str(number),
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
