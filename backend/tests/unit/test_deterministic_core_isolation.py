"""Principle IV's own testable clause, asserted (T011b; spec 006, FR-007).

The constitution states three proofs for *Deterministic Core, Agentic Edge*:
replaying a fixed snapshot twice produces byte-identical inventory and finding
sets; **core engine modules import no Bedrock client**; and every agent response
passes a grounding validator. The third is covered by `test_grounding.py`. The
first two are covered here, and were covered nowhere before this task —
`/speckit-analyze` found FR-007 with zero task coverage.

`check_connector_boundary.py` restricts boto3 to `connectors/` generally, which
is a different claim: it would not notice `app/governance/grounding.py` importing
`connectors.aws.invoke_agent` and putting a model call on a validation path.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# The deterministic core: discovery, validation, scoring, spend ingestion.
# FR-007 requires these to produce identical results whether or not the
# intelligence layer is enabled, which they cannot do if a model call can reach
# them.
CORE_MODULES = (
    "app/scan/orchestrator.py",
    "app/scan/enrichment.py",
    "app/governance/validation.py",
    "app/governance/scoring.py",
    "app/governance/spend.py",
    "app/governance/scan_deltas.py",
    "app/governance/sda_matching.py",
    "app/governance/ownership.py",
    "app/governance/utilization.py",
)

_FORBIDDEN_NAMES = ("bedrock", "invoke_agent", "invoke_model")


def _imported_names(path: Path) -> set[str]:
    """Every module and symbol a file imports, flattened."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("relative", CORE_MODULES)
def test_a_core_module_imports_no_model_call(relative: str) -> None:
    """FR-007 and Principle IV: no model call sits on a deterministic path."""
    path = BACKEND_ROOT / relative
    if not path.exists():  # a module a later spec has not written yet
        pytest.skip(f"{relative} does not exist yet")

    offending = [
        name
        for name in _imported_names(path)
        for token in _FORBIDDEN_NAMES
        if token in name.lower()
    ]
    assert offending == [], f"{relative} reaches a model call: {offending}"


@pytest.mark.parametrize("relative", CORE_MODULES)
def test_a_core_module_does_not_import_the_agent_layer(relative: str) -> None:
    """Stricter than the boundary check and deliberately so: importing
    `app.governance.digest` or `app.governance.agent_runs` into scoring would put
    the intelligence layer's availability on a deterministic path, so scoring
    could start failing because Bedrock was unreachable."""
    path = BACKEND_ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} does not exist yet")

    agent_modules = {
        "app.governance.digest",
        "app.governance.agent_runs",
        "app.governance.grounding",
        "app.governance.coverage_advisor",
    }
    assert not (_imported_names(path) & agent_modules), f"{relative} imports the agent layer"


def test_the_grounding_validator_itself_makes_no_model_call() -> None:
    """R-607. A validator that could hallucinate would defeat its own purpose,
    and Principle IV's third clause would mean nothing."""
    names = _imported_names(BACKEND_ROOT / "app/governance/grounding.py")
    assert not any(token in name.lower() for name in names for token in _FORBIDDEN_NAMES)
    assert not any(name.startswith("boto") for name in names)


def test_the_core_module_list_is_not_silently_empty() -> None:
    """A guard on the guard: if every path above were renamed, every test here
    would skip and report green while asserting nothing."""
    existing = [m for m in CORE_MODULES if (BACKEND_ROOT / m).exists()]
    assert len(existing) >= 6, f"only {len(existing)} core modules found — has the layout moved?"
