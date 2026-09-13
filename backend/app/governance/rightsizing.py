"""Instance-class recommendations for persistently under-used resources
(spec 006, T049; FR-023, FR-002, S52).

**A recommendation is a claim with its evidence attached, or it is not made.**
FR-023 says each one carries its supporting measurements and an estimated
saving, and that a resource whose utilization is high *or variable* is never
recommended down. Both halves are enforced here as arithmetic over the
metrics history `metrics.py` collected -- no model, no judgement call, and no
apply control anywhere downstream (FR-002).

**"Persistently low" is two rules, both data.** Over at least
`CLOUDPULSE_RIGHTSIZING_MIN_PERIODS` distinct days of CPU history:

* the mean is below `CLOUDPULSE_RIGHTSIZING_LOW_CPU_PERCENT`, and
* the peak is below twice that.

The second rule is what "or variable" means in practice. A resource that
averages 8% but spikes to 90% every night is not over-provisioned; it is
provisioned for the spike, and recommending it down would recommend an outage.
Mean alone cannot see that. Both thresholds are read from the environment at
point of use with conservative fallbacks (R-612).

**Class ladders and prices are data**, in `rightsizing_classes.json`. A
recommendation steps down exactly one rung of its family's ladder: the smallest
change that the evidence supports, and the one an operator can reason about.
The saving is (current hourly - recommended hourly) x 730, and the file says
what its prices are: structural, region-specific, refreshed by hand -- not a
quote. A class the file does not know gets no recommendation rather than a
guessed one.

**Computed on request.** `rightsizing_recommendation` rows are not written by
this phase; see tasks.md T050a for the same reasoning T047a records for
forecasts.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.db import TenantSession
from app.models.core import Resource as ResourceRow
from app.models.core import ResourceMetric as MetricRow
from app.models.enums import ResourceMetricKind

CLASSES_PATH = Path(__file__).with_name("rightsizing_classes.json")

_MIN_PERIODS_ENV = "CLOUDPULSE_RIGHTSIZING_MIN_PERIODS"
_LOW_CPU_ENV = "CLOUDPULSE_RIGHTSIZING_LOW_CPU_PERCENT"
_DEFAULT_MIN_PERIODS = 14
_DEFAULT_LOW_CPU = Decimal("20")

HOURS_PER_MONTH = Decimal(730)
_CENTS = Decimal("0.01")
_TENTH = Decimal("0.1")

# The `resource.detail` key holding the class, per type `metrics.py` measures.
CLASS_KEY: dict[str, str] = {
    "AWS::EC2::Instance": "instance_type",
    "AWS::RDS::DBInstance": "instance_class",
}


def minimum_periods() -> int:
    try:
        value = int(os.environ.get(_MIN_PERIODS_ENV, ""))
    except ValueError:
        return _DEFAULT_MIN_PERIODS
    return value if value > 0 else _DEFAULT_MIN_PERIODS


def low_cpu_percent() -> Decimal:
    try:
        value = Decimal(os.environ.get(_LOW_CPU_ENV, ""))
    except ArithmeticError:
        return _DEFAULT_LOW_CPU
    return value if 0 < value < 100 else _DEFAULT_LOW_CPU


@dataclass(frozen=True, slots=True)
class ClassLadders:
    ladders: dict[str, list[str]]
    hourly_usd: dict[str, Decimal]

    def step_down(self, current: str) -> str | None:
        for ladder in self.ladders.values():
            if current in ladder:
                index = ladder.index(current)
                return ladder[index - 1] if index > 0 else None
        return None


def load_class_ladders(path: Path = CLASSES_PATH) -> ClassLadders:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return ClassLadders(
        ladders={str(k): [str(c) for c in v] for k, v in raw["ladders"].items()},
        hourly_usd={str(k): Decimal(str(v)) for k, v in raw["hourly_usd"].items()},
    )


@dataclass(frozen=True, slots=True)
class CpuHistory:
    """What was measured, summarised the way the rules read it. Kept whole in
    the evidence rather than reduced to a verdict."""

    days: int
    mean_percent: Decimal
    peak_percent: Decimal
    first_day: date
    last_day: date


@dataclass(frozen=True, slots=True)
class Candidate:
    resource_id: uuid.UUID
    arn: str
    resource_type: str
    current_class: str | None
    history: CpuHistory | None


@dataclass(frozen=True, slots=True)
class Recommendation:
    resource_id: uuid.UUID
    arn: str
    resource_type: str
    current_class: str
    recommended_class: str
    estimated_monthly_saving_usd: Decimal
    evidence: dict[str, Any]


def _evidence(history: CpuHistory, *, low: Decimal) -> dict[str, Any]:
    """The measurements and the thresholds they were judged against. A reader
    can recompute the verdict from this alone, which is what makes it evidence
    rather than a summary."""
    return {
        "metric": "cpu",
        "periods": history.days,
        "period_first": history.first_day.isoformat(),
        "period_last": history.last_day.isoformat(),
        "mean_percent": str(history.mean_percent),
        "peak_percent": str(history.peak_percent),
        "low_threshold_percent": str(low),
        "peak_threshold_percent": str(low * 2),
    }


def recommend(
    candidate: Candidate,
    *,
    ladders: ClassLadders,
    minimum: int | None = None,
    low: Decimal | None = None,
) -> Recommendation | None:
    """FR-023 for one resource. None is the normal answer, and it is given for
    every reason a recommendation would be a guess: no class known, no history,
    too little history, not low enough, too variable, no smaller class, or no
    price to estimate a saving from."""
    minimum = minimum if minimum is not None else minimum_periods()
    low = low if low is not None else low_cpu_percent()
    history = candidate.history
    if candidate.current_class is None or history is None:
        return None
    if history.days < minimum:
        return None
    if history.mean_percent >= low:
        return None  # high
    if history.peak_percent >= low * 2:
        return None  # variable: provisioned for the spike, not the mean

    smaller = ladders.step_down(candidate.current_class)
    if smaller is None:
        return None
    current_price = ladders.hourly_usd.get(candidate.current_class)
    smaller_price = ladders.hourly_usd.get(smaller)
    if current_price is None or smaller_price is None:
        return None

    saving = ((current_price - smaller_price) * HOURS_PER_MONTH).quantize(
        _CENTS, rounding=ROUND_HALF_EVEN
    )
    return Recommendation(
        resource_id=candidate.resource_id,
        arn=candidate.arn,
        resource_type=candidate.resource_type,
        current_class=candidate.current_class,
        recommended_class=smaller,
        estimated_monthly_saving_usd=saving,
        evidence=_evidence(history, low=low),
    )


def candidates(session: TenantSession) -> list[Candidate]:
    """Every live resource of a measured type, with its CPU history summarised.

    Unavailable rows are excluded from the summary (FR-020): a NULL averaged
    as zero would manufacture exactly the low utilization this module is
    looking for.
    """
    summary = (
        select(
            MetricRow.resource_id,
            func.count(func.distinct(func.date(MetricRow.period_start))).label("days"),
            func.avg(MetricRow.value).label("mean"),
            func.max(MetricRow.value).label("peak"),
            func.min(func.date(MetricRow.period_start)).label("first"),
            func.max(func.date(MetricRow.period_start)).label("last"),
        )
        .where(MetricRow.tenant_id == session.tenant_id)
        .where(MetricRow.metric == ResourceMetricKind.CPU)
        .where(MetricRow.is_unavailable.is_(False))
        .group_by(MetricRow.resource_id)
        .subquery()
    )
    statement = (
        session.scoped(
            select(
                ResourceRow.id,
                ResourceRow.arn,
                ResourceRow.resource_type,
                ResourceRow.detail,
                summary.c.days,
                summary.c.mean,
                summary.c.peak,
                summary.c.first,
                summary.c.last,
            ),
            ResourceRow,
        )
        .outerjoin(summary, summary.c.resource_id == ResourceRow.id)
        .where(ResourceRow.deleted_at.is_(None))
        .where(ResourceRow.resource_type.in_(list(CLASS_KEY)))
        .order_by(ResourceRow.arn)
    )
    result: list[Candidate] = []
    for rid, arn, rtype, detail, days, mean, peak, first, last in session.raw.execute(statement):
        raw_class = (detail or {}).get(CLASS_KEY[rtype])
        history = (
            CpuHistory(
                days=int(days),
                mean_percent=Decimal(mean).quantize(_TENTH, rounding=ROUND_HALF_EVEN),
                peak_percent=Decimal(peak).quantize(_TENTH, rounding=ROUND_HALF_EVEN),
                first_day=first,
                last_day=last,
            )
            if days
            else None
        )
        result.append(
            Candidate(
                resource_id=rid,
                arn=arn,
                resource_type=rtype,
                current_class=str(raw_class) if raw_class else None,
                history=history,
            )
        )
    return result


def recommendations(session: TenantSession) -> list[Recommendation]:
    ladders = load_class_ladders()
    minimum = minimum_periods()
    low = low_cpu_percent()
    return [
        rec
        for candidate in candidates(session)
        if (rec := recommend(candidate, ladders=ladders, minimum=minimum, low=low)) is not None
    ]


__all__ = [
    "CLASS_KEY",
    "HOURS_PER_MONTH",
    "Candidate",
    "ClassLadders",
    "CpuHistory",
    "Recommendation",
    "candidates",
    "load_class_ladders",
    "low_cpu_percent",
    "minimum_periods",
    "recommend",
    "recommendations",
]
