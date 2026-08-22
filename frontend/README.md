# `frontend/` — Angular 18 SPA

Standalone components with signals, Angular Material, hosted on S3 behind CloudFront.

## Layout and ownership

| Path | Owner | Contents |
|---|---|---|
| `src/app/shared/` | spec 001 | shell, layout, navigation |
| `src/app/core/` | spec 001 | auth service, route guards, interceptors |
| `src/app/api/` | **generated** | never hand-edit — see its README |
| `src/app/features/` | **specs 002–005** | feature routes |
| `e2e/` | spec 001 (extended by 004) | Playwright + axe-core |

## The accessibility baseline (FR-047a) — inherited by every screen

- semantic markup with correct roles and labels;
- every interactive control reachable and operable by **keyboard alone**;
- a **visible focus indicator**, set once in `styles.scss` so a component library that
  suppresses the default outline cannot silently remove it.

`@angular-eslint`'s template rules gate the static half and fail the PR. **FR-047b is
explicit that this proves only part of it** — keyboard operability and focus visibility
remain a reviewer's responsibility. Passing lint is not evidence the baseline is met.

## The generated client

`src/app/api/` comes from `backend/openapi.generated.yaml`. CI regenerates it and fails
the PR on any diff. To change the client, change the Pydantic models — the chain is
one-directional by design.

The generator is a Java tool. CI runners have a JRE; locally:

```bash
brew install openjdk && export JAVA_HOME=/opt/homebrew/opt/openjdk
```

## Guards are usability, not security

`authGuard` and `roleGuard` decide what to *render*. They run in code the user controls,
so they can never decide what is *permitted* — the API enforces authorisation on every
request independently. Treating a client-side guard as a security control is the classic
mistake this note exists to prevent.

```bash
npm ci && npm run lint && npm run build
```
