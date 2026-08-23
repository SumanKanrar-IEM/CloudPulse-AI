#!/usr/bin/env python3
"""Fail on a structurally broken Step Functions state machine definition.

`terraform validate` and `terraform plan` treat a state machine's `definition` argument
as an opaque string -- they check that the surrounding HCL is well-formed, not that the
Amazon States Language (ASL) JSON inside it is. A missing `StartAt`, a `Next` pointing at
a state that doesn't exist, or a plain JSON syntax error all pass both commands cleanly
and only fail live, at `CreateStateMachine` or `UpdateStateMachine` time during `apply` --
the same class of blind spot `check_terraform_ascii.py` closes for a different resource
type (found live during spec 002's `/speckit-analyze`, T042a).

This is deliberately NOT a call to AWS's own `validate-state-machine-definition` API: CI
runs with no AWS credentials (FR-010's established pattern for every other gate here), and
adding a live API call to the credential-free PR gate would be a bigger, separate decision.
This catches the certain-failure class an offline structural check can reach; it does not
replace AWS's own deeper semantic validation, the same accepted-scope tradeoff
`check_terraform_ascii.py` makes for non-ASCII values.

Convention this depends on: an ASL definition lives in its own `*.asl.json` file,
referenced from Terraform via `file("./whatever.asl.json")`, never inlined as a heredoc --
that is what makes this check (and any future one) possible without parsing HCL.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _walk_states(states: dict[str, Any], path: str) -> list[str]:
    """Return structural problems in one `States` map -- recurses into Map/Parallel."""
    problems: list[str] = []
    if not states:
        problems.append(f"{path}: 'States' is empty")
        return problems

    for name, state in states.items():
        state_path = f"{path}.{name}"
        if not isinstance(state, dict):
            problems.append(f"{state_path}: state value is not an object")
            continue

        state_type = state.get("Type")
        if not state_type:
            problems.append(f"{state_path}: missing required 'Type'")
            continue

        is_terminal = state.get("End") is True or state_type == "Succeed" or state_type == "Fail"
        has_next = "Next" in state
        if not is_terminal and not has_next and state_type not in ("Choice",):
            problems.append(f"{state_path}: neither 'End: true' nor 'Next' -- a dead end")

        if has_next and state["Next"] not in states:
            problems.append(
                f"{state_path}: 'Next' points at '{state['Next']}', which is not a "
                f"sibling state in the same 'States' map"
            )

        if state_type == "Map":
            processor = state.get("ItemProcessor") or state.get("Iterator")
            if not processor:
                problems.append(f"{state_path}: Map state has no 'ItemProcessor'/'Iterator'")
            elif "States" in processor:
                problems.extend(_walk_states(processor["States"], f"{state_path}.ItemProcessor"))

        if state_type == "Parallel":
            for i, branch in enumerate(state.get("Branches", [])):
                if "States" in branch:
                    problems.extend(_walk_states(branch["States"], f"{state_path}.Branches[{i}]"))

    return problems


def _check_definition(data: dict[str, Any], rel: Path) -> list[str]:
    problems: list[str] = []

    start_at = data.get("StartAt")
    states = data.get("States")

    if not start_at:
        problems.append(f"{rel}: missing required top-level 'StartAt'")
    if not isinstance(states, dict):
        problems.append(f"{rel}: missing or non-object top-level 'States'")
    elif start_at and start_at not in states:
        problems.append(f"{rel}: 'StartAt' ('{start_at}') is not a key in 'States'")

    if isinstance(states, dict):
        problems.extend(f"{rel}:{p}" for p in _walk_states(states, ""))

    return problems


def main() -> int:
    violations: list[str] = []
    scanned = 0

    for path in sorted((ROOT / "infra").rglob("*.asl.json")):
        if ".terraform" in path.parts:
            continue
        scanned += 1
        rel = path.relative_to(ROOT)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            violations.append(f"{rel}: invalid JSON -- {exc}")
            continue
        if not isinstance(data, dict):
            violations.append(f"{rel}: top level must be a JSON object")
            continue
        violations.extend(_check_definition(data, rel))

    if scanned == 0:
        sys.stdout.write("stepfunctions-asl: OK (0 *.asl.json files found, nothing to check)\n")
        return 0

    if violations:
        sys.stderr.write(
            "Structurally broken Step Functions definition(s). terraform validate/plan "
            "would not have caught these -- they only fail live, at apply:\n\n"
        )
        for v in violations:
            sys.stderr.write(f"  {v}\n")
        return 1

    sys.stdout.write(f"stepfunctions-asl: OK ({scanned} file(s) scanned, 0 violations)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
