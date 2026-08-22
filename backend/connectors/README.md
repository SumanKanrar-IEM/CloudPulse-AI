# `connectors/` — reserved package

**This package is deliberately empty. Spec 001 does not define its contents.**

Backlog story **S11** — the provider-agnostic connector interface and the normalized resource
model — belongs to **spec 002 (account-onboarding-and-discovery)**. Spec 001 reserves the package
and fixes the boundary rule; spec 002 writes the protocol.

## The boundary rule (FR-054, constitution Principle V)

> No cloud-provider SDK type may cross **out** of this package.

`boto3` / `botocore` types, raw AWS API response shapes, and provider-specific identifiers stay
behind this line. Core code (`app/api/`, `app/workers/`, `app/scan/`, `app/models/`) consumes the
normalized model only.

This is enforced, not merely requested:

- the **`connector-boundary`** job in `.github/workflows/ci.yml` fails any pull request that
  imports a provider SDK outside this package (FR-054, SC-016);
- `backend/pyproject.toml` carries a local ruff banned-api mirror of the same rule.

## Why the rule exists before the code does

Five specs build on this foundation. If the first connector is written without the boundary
already enforced, provider types leak into core code within days and the "new provider ships
without modifying core code" property in Principle V is lost quietly. Landing the gate while the
package is still empty costs nothing and makes the leak impossible.

The gate has nothing to catch until spec 002 lands. It must still be green from the day it ships.
