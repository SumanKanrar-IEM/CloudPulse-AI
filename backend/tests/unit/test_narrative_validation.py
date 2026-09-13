"""A narrative beside a chart states only the chart's figures (T052; spec 006,
FR-024, SC-007, S53).

The existing validator (T007) already refuses an undeclared currency or
percentage. FR-024 is stricter, and the difference is the point of this file:
beside a chart, *every* number reads as one of its values, so FR-001a's
bare-integer exemption does not apply. "Spend is heading up over the next 30
days" is fine only because 30 is the horizon the calculation produced; "up
about 12%" is refused because no 12 came from anywhere.

Pure, like the validator. The chart's figures are supplied as `known_figures`
exactly as `GET /forecasts` would supply them.
"""

from __future__ import annotations

from decimal import Decimal

from app.governance.grounding import Figure, Section, validate_output

# What a forecast chart shows: projected 937.50, horizon 30 days, backtest
# error 4.2%, from 20 days of history.
CHART = {Decimal("937.50"), Decimal("30"), Decimal("4.2"), Decimal("20")}


def _narrative(body: str, *figures: str) -> list[Section]:
    return [
        Section(
            heading="Spend forecast",
            body=body,
            figures=[Figure(label=f"f{i}", value=Decimal(v)) for i, v in enumerate(figures)],
        )
    ]


def _validate(sections: list[Section]):  # type: ignore[no-untyped-def]
    return validate_output(sections, known_references={}, known_figures=CHART, exact_figures=True)


# --- acceptance scenario 1: matching figures pass -----------------------------------


def test_a_narrative_stating_only_the_chart_s_figures_passes() -> None:
    verdict = _validate(
        _narrative(
            "Spend is projected at $937.50 over the next 30 days, from 20 days of history. "
            "The backtest error was 4.2%.",
            "937.50",
            "30",
            "20",
            "4.2",
        )
    )
    assert verdict.ok


def test_formatting_differences_are_not_mismatches() -> None:
    """$937.5 and $937.50 are the same quantity. Rejecting on formatting would
    be the failure direction R-607 rules out."""
    assert _validate(_narrative("Projected: $937.5 over 30 days.", "937.50", "30")).ok


def test_iso_dates_are_not_figures() -> None:
    """The chart labels its axis with dates; the narrative may name them
    without 2026, 3 and 31 each needing to be a declared value."""
    assert _validate(
        _narrative("From 2026-03-01 to 2026-03-30, spend is projected at $937.50.", "937.50")
    ).ok


# --- acceptance scenario 2: any introduced figure is refused ------------------------------


def test_a_bare_number_the_calculation_did_not_produce_is_refused() -> None:
    """FR-001a would let "12" through as a count. FR-024 does not: beside a
    chart it reads as a value, and no 12 came from the calculation."""
    verdict = _validate(
        _narrative("Spend is projected at $937.50, up about 12 from last month.", "937.50")
    )
    assert not verdict.ok
    assert verdict.rejected_reference == "12"


def test_a_percentage_the_calculation_did_not_produce_is_refused() -> None:
    verdict = _validate(_narrative("Projected $937.50, roughly 15% higher.", "937.50"))
    assert not verdict.ok
    assert verdict.rejected_reference == "15"


def test_a_declared_figure_the_chart_does_not_show_is_refused() -> None:
    """Declaring a figure is not the same as it being real. The agent may
    declare only what it was handed, and 999 was not."""
    verdict = _validate(_narrative("Projected $999.", "999"))
    assert not verdict.ok
    assert verdict.rejected_reference == "999"


def test_a_figure_in_prose_but_not_declared_is_refused_even_if_the_chart_shows_it() -> None:
    """The chart shows 4.2%. Stating it without declaring it is still refused:
    the declaration is what lets the frontend tie prose to a chart value, and
    an undeclared match is a coincidence the reader cannot verify."""
    verdict = _validate(_narrative("Projected $937.50; error 4.2%.", "937.50"))
    assert not verdict.ok
    assert verdict.rejected_reference == "4.2"


def test_the_exemption_still_holds_outside_exact_mode() -> None:
    """The digest keeps FR-001a's rule. Turning exact mode on for narratives
    must not have turned it on for everyone."""
    verdict = validate_output(
        _narrative("Three findings are open, up 12 since yesterday."),
        known_references={},
        known_figures=set(),
        exact_figures=False,
    )
    assert verdict.ok


def test_an_empty_narrative_passes_and_states_nothing() -> None:
    """Contentless is "nothing to say", not a failure -- the same rule the
    digest applies to a nothing-notable day."""
    assert _validate([]).ok
