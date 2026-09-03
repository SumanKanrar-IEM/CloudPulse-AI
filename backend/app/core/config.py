"""Application settings.

Constitution Principle III (NON-NEGOTIABLE) -- zero stored credentials. Every value
here comes from the environment or from AWS Secrets Manager at runtime. Nothing is
read from a committed file, and no field carries a usable default for a secret
(FR-007).

The database password is deliberately absent from this model. It is fetched by
`app/core/db.py` through the Lambda execution role, cached in the execution context,
and never passed through configuration.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """The two environments FR-002 permits. There is no staging or per-developer tier."""

    DEV = "dev"
    PROD = "prod"


class Role(StrEnum):
    """The three roles of FR-032.

    A caller resolves to exactly one of these, derived from directory group
    membership on every request. The platform never stores a role (FR-031a), so this
    enum is a claim vocabulary -- not a column.
    """

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Settings(BaseSettings):
    """Runtime configuration, sourced from the environment only."""

    model_config = SettingsConfigDict(
        env_prefix="CLOUDPULSE_",
        env_file=None,  # FR-007: never read a committed dotenv
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Field(description="dev or prod (FR-002)")
    aws_region: str = Field(min_length=1)

    # --- data store (FR-024). Reference only; the secret's *value* never lands here.
    db_host: str = Field(min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_secret_arn: str = Field(
        min_length=1,
        description="Secrets Manager ARN. Resolved at runtime via the execution role.",
    )

    # --- identity (FR-031, FR-034)
    #
    # Optional, not required: JWT validation happens entirely at the API Gateway
    # authorizer layer (Terraform), and no Python code currently reads either field --
    # they are declared for spec 002+ (e.g. admin operations against the user pool).
    # The migration and pre-token Lambdas share this Settings model but have no
    # Cognito configuration in their environment; making these required blocked
    # every non-API Lambda from resolving settings at all, including the deployment
    # recorder that specs T023/T108 depend on.
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None

    # --- observability (FR-045, FR-046a)
    log_level: str = Field(default="INFO")
    service_name: str = Field(default="cloudpulse-api")

    # --- build provenance, recorded on every deployment (FR-023)
    git_sha: str = Field(default="unknown")

    # --- cost ingestion (spec 005, FR-001) -- the tag key spend is grouped by,
    # matching spec 003's own seeded mandatory tag of the same name (the tag
    # SDA matching already keys project attribution on).
    project_tag_key: str = Field(default="project_id")

    @field_validator("db_secret_arn")
    @classmethod
    def _must_be_an_arn_not_a_secret(cls, v: str) -> str:
        """Reject anything that looks like a value rather than a reference.

        A literal password reaching this field would be a Principle III violation, so
        the shape is checked rather than trusted.
        """
        if not v.startswith("arn:aws:secretsmanager:"):
            raise ValueError(
                "db_secret_arn must be a Secrets Manager ARN, not a credential value "
                "(constitution Principle III, FR-007)"
            )
        return v

    @property
    def is_prod(self) -> bool:
        return self.environment is Environment.PROD


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings, resolved once per Lambda execution context."""
    # Values come from the environment; pydantic-settings resolves them.
    return Settings()
