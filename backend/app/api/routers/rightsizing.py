"""`GET /rightsizing` -- instance-class recommendations with their evidence
(spec 006, T050; FR-023, FR-002, S52).

**One endpoint, a GET, and nothing that acts.** FR-002 and acceptance scenario
3: no control exists to apply a recommendation, and the cheapest way to keep
that true is for no route to exist that could. The frontend renders what this
returns and nothing else; `test_no_remediation_execution.py` scans for the
alternative.

**Computed on request.** Same reasoning `forecasts.py` gives and tasks.md
T050a records: the calculation is deterministic arithmetic over collected
metrics, and a stored recommendation would only be a snapshot of what this
returns now.

Every role may read (FR-030's convention for this spec's surfaces): a
recommendation is something to discuss, not something to act on here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.errors import ERROR_RESPONSES
from app.core.db import tenant_session
from app.core.security import Principal, require_viewer
from app.governance.rightsizing import recommendations

router = APIRouter(tags=["rightsizing"])

ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]


class RightsizingRecommendationResponse(BaseModel):
    resource_id: str = Field(alias="resourceId")
    arn: str
    resource_type: str = Field(alias="resourceType")
    current_class: str = Field(alias="currentClass")
    recommended_class: str = Field(alias="recommendedClass")
    estimated_monthly_saving_usd: Decimal = Field(alias="estimatedMonthlySavingUsd")
    # The measurements and the thresholds they were judged against. Served
    # whole, because FR-023's requirement is that the evidence travels with the
    # recommendation, not that it exists somewhere.
    evidence: dict[str, Any]

    model_config = {"populate_by_name": True}


class RightsizingList(BaseModel):
    generated_at: datetime = Field(alias="generatedAt")
    recommendations: list[RightsizingRecommendationResponse]
    # Stated so a reader knows the saving's basis without opening the file.
    pricing_note: str = Field(alias="pricingNote")

    model_config = {"populate_by_name": True}


PRICING_NOTE = (
    "Savings are estimated from on-demand hourly prices for us-east-1 at 730 hours a month. "
    "They set the shape of a saving, not its invoice."
)


@router.get(
    "/rightsizing",
    operation_id="listRightsizingRecommendations",
    summary="Resources provisioned larger than their measured use, with evidence",
    response_model=RightsizingList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_rightsizing_recommendations(principal: ViewerPrincipal) -> RightsizingList:
    """FR-023. A resource that is high, variable, thin on history, unenriched,
    already smallest, or unknown to the class ladder is simply absent -- each
    of those is a reason a recommendation would be a guess, and the absence is
    the correct output, not an error."""
    with tenant_session(principal.tenant_id) as session:
        found = recommendations(session)
    return RightsizingList(
        generated_at=datetime.now(UTC),
        pricing_note=PRICING_NOTE,
        recommendations=[
            RightsizingRecommendationResponse(
                resource_id=str(r.resource_id),
                arn=r.arn,
                resource_type=r.resource_type,
                current_class=r.current_class,
                recommended_class=r.recommended_class,
                estimated_monthly_saving_usd=r.estimated_monthly_saving_usd,
                evidence=r.evidence,
            )
            for r in found
        ],
    )


__all__ = ["router"]
