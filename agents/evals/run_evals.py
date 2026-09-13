#!/usr/bin/env python3
"""Run the agent eval cases against recorded model output (spec 006, T055;
FR-005, R-609).

Each case in `cases/` is one recorded model reply plus what the platform knew
at the time -- the references and figures it could verify against -- and the
verdict the deterministic pipeline must reach: `accept`, or `reject` naming
the reference. The runner parses the reply with the capability's own parser
and validates it with the capability's own validator call, so a case exercises
the same code a Lambda would, minus the model.

**Never calls Bedrock.** That is the whole of R-609: CI stays deterministic
and free, and a PR is never gated on a paid network call. The trade is that
these prove the *handling* of model output -- grounding, parsing, refusal --
not the model's quality, which a live eval would measure and this one
deliberately does not claim.

**A prompt change that breaks a case fails the PR.** The prompt files are
content-hashed onto every run row (R-608); this is the other half of that
bargain -- the hash makes a behaviour change traceable, and these cases make
the change visible before it ships. A case whose expectation is genuinely
obsolete is edited in the same PR as the prompt, with the reason in the case
file's `why`.

Exit codes: 0 every case reached its verdict, 1 otherwise.

Run from `backend/` so `app.*` imports resolve:

    python ../agents/evals/run_evals.py
"""

from __future__ import annotations

import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.governance.digest import parse_sections
from app.governance.grounding import Figure, GroundingVerdict, Section, validate_output
from app.governance.suggester import parse_draft

CASES_DIR = Path(__file__).resolve().parent / "cases"


def _narrator_sections(output_text: str) -> list[Section]:
    """The narrator prompt's output contract: one body, declared figures."""
    payload = json.loads(output_text)
    if not isinstance(payload, dict) or not str(payload.get("body", "")).strip():
        raise ValueError("narrative output must be an object with a non-empty 'body'")
    return [
        Section(
            heading="narrative",
            body=str(payload["body"]),
            figures=[
                Figure(label=str(f["label"]), value=Decimal(str(f["value"])))
                for f in payload.get("figures", [])
            ],
        )
    ]


def _validate(case: dict[str, Any]) -> GroundingVerdict | str:
    """Parse and validate as the capability would. A parse failure is returned
    as the error string: it is a legitimate outcome a case may expect."""
    capability = case["capability"]
    output = case["model_output"]
    known_references = {k: set(v) for k, v in case.get("known_references", {}).items()}
    known_figures = {Decimal(str(f)) for f in case.get("known_figures", [])}

    try:
        if capability == "digest":
            sections = parse_sections(output)
        elif capability == "suggester":
            sections = parse_draft(uuid.UUID(int=0), output).sections
        elif capability == "narrator":
            sections = _narrator_sections(output)
        else:
            raise ValueError(f"no parser for capability {capability!r}")
    except (ValueError, json.JSONDecodeError) as exc:
        return f"parse error: {exc}"

    return validate_output(
        sections,
        known_references=known_references,
        known_figures=known_figures,
        exact_figures=(capability == "narrator"),
    )


def _matches(expected: dict[str, Any], actual: GroundingVerdict | str) -> str | None:
    """None when the case reached its verdict; otherwise why not."""
    if expected["verdict"] == "parse_error":
        return None if isinstance(actual, str) else f"expected a parse error, got {actual}"
    if isinstance(actual, str):
        return f"expected {expected['verdict']}, got {actual}"
    if expected["verdict"] == "accept":
        return None if actual.ok else f"rejected {actual.rejected_reference!r}"
    if expected["verdict"] == "reject":
        if actual.ok:
            return "accepted, expected a rejection"
        want = expected.get("rejected_reference")
        if want is not None and actual.rejected_reference != want:
            return f"rejected {actual.rejected_reference!r}, expected {want!r}"
        return None
    return f"unknown verdict {expected['verdict']!r}"


def main() -> int:
    cases = sorted(CASES_DIR.glob("*.json"))
    if not cases:
        sys.stderr.write("agent-evals: no cases found\n")
        return 1

    failures = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        problem = _matches(case["expect"], _validate(case))
        status = "ok  " if problem is None else "FAIL"
        sys.stdout.write(f"{status} {path.stem}\n")
        if problem is not None:
            failures += 1
            sys.stdout.write(f"     {problem}\n     why: {case.get('why', '')}\n")

    sys.stdout.write(
        f"agent-evals: {len(cases) - failures}/{len(cases)} cases reached their verdict\n"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
