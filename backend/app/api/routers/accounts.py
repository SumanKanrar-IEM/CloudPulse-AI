"""Account registration and the accounts admin surface (FR-006-FR-012).

Registration is roles-only (Principle III): an access key is not an accepted input at
all, not merely an unverified one (FR-001) -- `AccountCreate` simply has no field for
one, and `extra="forbid"` turns an attempt to submit one into a loud 422 rather than a
silently ignored field.

Registering, deactivating, and reactivating are admin-only (FR-011a); viewing is open
to all three roles (FR-010a) -- both reuse `app.core.security`'s existing
`require_admin`/`require_viewer` aliases unchanged. Triggering an on-demand scan
(T048, Phase 6) is operator-only and will deliberately NOT reuse
`app.core.security.require_operator`, which also admits admin -- research.md R-205
makes this spec's roles non-hierarchical, a distinction that only matters once that
route exists.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import ERROR_RESPONSES, AppError, ErrorCode, ErrorEnvelope, correlation_id_of
from app.core.audit import write_audit_event
from app.core.db import TenantSession, tenant_session
from app.core.logging import logger
from app.core.security import Principal, require_admin, require_viewer
from app.models.core import CloudAccount
from app.models.enums import AccountStatus, ConnectionMode
from app.scan.verification import VerificationError, verify_registration
from connectors.aws import get_local_account_id, store_external_id
from connectors.base import ConnectorAccount

router = APIRouter(prefix="/accounts", tags=["accounts"])

CROSS_ACCOUNT_TEMPLATE_URL = "/assets/cross-account-template.yaml"
DEFAULT_SCAN_REGION = "us-east-1"

AdminPrincipal = Annotated[Principal, Depends(require_admin)]
ViewerPrincipal = Annotated[Principal, Depends(require_viewer)]

_CONFLICT_RESPONSE = {
    "model": ErrorEnvelope,
    "description": "The request conflicts with the account's current state.",
}


# --- Schemas -------------------------------------------------------------------


class ExternalIdResponse(BaseModel):
    external_id: str = Field(alias="externalId")
    cloud_formation_template_url: str = Field(alias="cloudFormationTemplateUrl")

    model_config = {"populate_by_name": True}


class AccountCreate(BaseModel):
    """FR-006. `extra="forbid"` is FR-001's structural refusal of access-key input."""

    alias: str | None = None
    connection_mode: ConnectionMode = Field(alias="connectionMode")
    aws_account_id: str | None = Field(default=None, alias="awsAccountId")
    role_arn: str | None = Field(default=None, alias="roleArn")
    external_id: str | None = Field(default=None, alias="externalId")
    scan_regions: list[str] = Field(default_factory=list, alias="scanRegions")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class AccountUpdate(BaseModel):
    scan_regions: list[str] = Field(alias="scanRegions", min_length=1)

    model_config = {"populate_by_name": True, "extra": "forbid"}


class ScanSummary(BaseModel):
    status: str
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    resource_count: int | None = Field(default=None, alias="resourceCount")

    model_config = {"populate_by_name": True}


class Account(BaseModel):
    id: str
    alias: str | None = None
    connection_mode: str = Field(alias="connectionMode")
    aws_account_id: str = Field(alias="awsAccountId")
    role_arn: str | None = Field(default=None, alias="roleArn")
    scan_regions: list[str] = Field(alias="scanRegions")
    status: str
    last_scan: ScanSummary | None = Field(default=None, alias="lastScan")
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class AccountsList(BaseModel):
    accounts: list[Account]


# --- Helpers ---------------------------------------------------------------------


def _generate_external_id() -> str:
    """FR-003a: platform-generated, unique per account, high entropy.

    256 bits of randomness (32 bytes, URL-safe base64) -- collision-implausible, so no
    uniqueness check against existing values is needed.
    """
    return secrets.token_urlsafe(32)


def _to_account_model(row: CloudAccount) -> Account:
    return Account(
        id=str(row.id),
        alias=row.alias,
        connection_mode=row.connection_mode.value,
        aws_account_id=row.aws_account_id,
        role_arn=row.role_arn,
        scan_regions=list(row.scan_regions),
        status=row.status.value,
        created_at=row.created_at,
    )


def _duplicate_check(session: TenantSession, aws_account_id: str) -> CloudAccount | None:
    """FR-009: refuse a second registration regardless of connection mode or status
    (including a currently-deactivated existing record)."""
    stmt = session.scoped(select(CloudAccount), CloudAccount).where(
        CloudAccount.aws_account_id == aws_account_id
    )
    return session.raw.execute(stmt).scalars().first()


def _audit(
    session: TenantSession,
    *,
    principal: Principal,
    action: str,
    target_id: str | None,
    correlation_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> None:
    write_audit_event(
        session,
        action=action,
        target_type="cloud_account",
        actor_label=principal.email or principal.subject,
        target_id=target_id,
        correlation_id=correlation_id,
        payload=payload,
    )


def _get_or_404(session: TenantSession, account_id: uuid.UUID) -> CloudAccount:
    stmt = session.scoped(select(CloudAccount), CloudAccount).where(CloudAccount.id == account_id)
    account: CloudAccount | None = session.raw.execute(stmt).scalar_one_or_none()
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)
    return account


# --- Routes ------------------------------------------------------------------


@router.post(
    "/external-id",
    operation_id="generateExternalId",
    summary="Get a fresh platform-generated ExternalId ahead of cross-account registration",
    response_model=ExternalIdResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_200_OK,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def generate_external_id(principal: AdminPrincipal) -> dict[str, Any]:
    """T016a. Admin only, deliberately stateless -- see module and openapi.yaml docs."""
    return ExternalIdResponse(
        external_id=_generate_external_id(),
        cloud_formation_template_url=CROSS_ACCOUNT_TEMPLATE_URL,
    ).model_dump(by_alias=True)


@router.get(
    "",
    operation_id="listAccounts",
    summary="List every registered account",
    response_model=AccountsList,
    response_model_by_alias=True,
    responses={401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]},
)
async def list_accounts(principal: ViewerPrincipal) -> AccountsList:
    """FR-010/FR-010a. All three roles may view."""
    with tenant_session(principal.tenant_id) as session:
        rows = (
            session.raw.execute(session.scoped(select(CloudAccount), CloudAccount)).scalars().all()
        )
        return AccountsList(accounts=[_to_account_model(r) for r in rows])


@router.post(
    "",
    operation_id="registerAccount",
    summary="Register a new AWS account",
    response_model=Account,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        409: _CONFLICT_RESPONSE,
        422: ERROR_RESPONSES[422],
    },
)
async def register_account(
    body: AccountCreate,
    request: Request,
    principal: AdminPrincipal,
) -> Account:
    """FR-006/FR-007/FR-011a. Verifies before accepting; refuses a duplicate (FR-009)."""
    correlation_id = correlation_id_of(request)

    if body.connection_mode is ConnectionMode.ASSUME_ROLE:
        if not body.role_arn or not body.aws_account_id or not body.external_id:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                status_code=422,
                message="assume_role registration requires awsAccountId, roleArn, and externalId.",
            )
        aws_account_id = body.aws_account_id
    else:
        aws_account_id = get_local_account_id()

    regions = body.scan_regions or [DEFAULT_SCAN_REGION]

    # `raise` inside a `with tenant_session(...)` block triggers its rollback (the
    # context manager's own exception handling), which would silently undo an audit
    # write made in the same block -- so the audit write and the raise are kept in
    # separate transactions, the write committing before the raise ever happens.
    duplicate_id: str | None = None
    with tenant_session(principal.tenant_id) as session:
        existing = _duplicate_check(session, aws_account_id)
        if existing is not None:
            duplicate_id = str(existing.id)
            _audit(
                session,
                principal=principal,
                action="account.register.refused",
                target_id=duplicate_id,
                correlation_id=correlation_id,
                payload={"reason": "duplicate", "aws_account_id": aws_account_id},
            )
    if duplicate_id is not None:
        raise AppError(
            ErrorCode.CONFLICT,
            status_code=status.HTTP_409_CONFLICT,
            message=(
                "This AWS account is already registered. Reactivate the existing "
                "record instead of registering again."
            ),
        )

    # Verification happens outside any open DB transaction -- it is a network call
    # that can legitimately take seconds, and holding a row lock across it serves
    # nothing here (the duplicate check above already closed the race for this tenant).
    connector_account = ConnectorAccount(
        aws_account_id=aws_account_id,
        connection_mode=body.connection_mode.value,
        role_arn=body.role_arn,
        external_id=body.external_id,
    )
    try:
        verify_registration(connector_account, regions[0])
    except VerificationError as exc:
        with tenant_session(principal.tenant_id) as session:
            _audit(
                session,
                principal=principal,
                action="account.register.refused",
                target_id=None,
                correlation_id=correlation_id,
                payload={"reason": f"verification_failed:{exc.kind}"},
            )
        logger.warning("account verification failed", extra={"kind": exc.kind})
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            status_code=422,
            message=(
                "The role could not be assumed."
                if exc.kind == "role_not_assumable"
                else "The role was assumed but grants no usable read access."
            ),
        ) from None

    external_id_ref: str | None = None
    if body.connection_mode is ConnectionMode.ASSUME_ROLE:
        assert body.external_id is not None  # narrowed above
        external_id_ref = store_external_id(
            tenant_id=str(principal.tenant_id),
            cloud_account_id=str(uuid.uuid4()),
            external_id=body.external_id,
        )

    with tenant_session(principal.tenant_id) as session:
        account = CloudAccount(
            aws_account_id=aws_account_id,
            alias=body.alias or aws_account_id,
            connection_mode=body.connection_mode,
            role_arn=body.role_arn,
            external_id_ref=external_id_ref,
            scan_regions=regions,
            status=AccountStatus.VERIFIED,
        )
        session.add(account)
        session.flush()
        _audit(
            session,
            principal=principal,
            action="account.register.succeeded",
            target_id=str(account.id),
            correlation_id=correlation_id,
            payload={"connection_mode": body.connection_mode.value},
        )
        return _to_account_model(account)


@router.patch(
    "/{account_id}",
    operation_id="updateAccountRegions",
    summary="Edit an account's scan-region list",
    response_model=Account,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def update_account_regions(
    account_id: uuid.UUID,
    body: AccountUpdate,
    request: Request,
    principal: AdminPrincipal,
) -> Account:
    """FR-008/FR-011a. Admin only. Takes effect from the next scan onward."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        account = _get_or_404(session, account_id)
        account.scan_regions = body.scan_regions
        session.flush()
        _audit(
            session,
            principal=principal,
            action="account.regions.updated",
            target_id=str(account.id),
            correlation_id=correlation_id,
            payload={"scan_regions": body.scan_regions},
        )
        return _to_account_model(account)


@router.post(
    "/{account_id}/deactivate",
    operation_id="deactivateAccount",
    summary="Stop scanning an account without deleting its history",
    response_model=Account,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
    },
)
async def deactivate_account(
    account_id: uuid.UUID,
    request: Request,
    principal: AdminPrincipal,
) -> Account:
    """FR-009a/FR-011a. A scan already running is unaffected (FR-009b) -- this only
    changes `cloud_account.status`, which the next scheduler pass reads, not the
    in-flight execution."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        account = _get_or_404(session, account_id)
        account.status = AccountStatus.DISABLED
        session.flush()
        _audit(
            session,
            principal=principal,
            action="account.deactivated",
            target_id=str(account.id),
            correlation_id=correlation_id,
        )
        return _to_account_model(account)


@router.post(
    "/{account_id}/reactivate",
    operation_id="reactivateAccount",
    summary="Resume scanning a deactivated account",
    response_model=Account,
    response_model_by_alias=True,
    responses={
        401: ERROR_RESPONSES[401],
        403: ERROR_RESPONSES[403],
        404: ERROR_RESPONSES[404],
        409: _CONFLICT_RESPONSE,
    },
)
async def reactivate_account(
    account_id: uuid.UUID,
    request: Request,
    principal: AdminPrincipal,
) -> Account:
    """FR-009c/FR-011a. No re-registration, no re-verification -- a stale role is
    caught by the same scan-failure handling that covers any active account
    (Edge Cases), on the next scan attempt."""
    correlation_id = correlation_id_of(request)
    with tenant_session(principal.tenant_id) as session:
        account = _get_or_404(session, account_id)
        if account.status is not AccountStatus.DISABLED:
            raise AppError(
                ErrorCode.CONFLICT,
                status_code=status.HTTP_409_CONFLICT,
                message="The account is not currently deactivated.",
            )
        account.status = AccountStatus.VERIFIED
        session.flush()
        _audit(
            session,
            principal=principal,
            action="account.reactivated",
            target_id=str(account.id),
            correlation_id=correlation_id,
        )
        return _to_account_model(account)


__all__ = ["router"]
