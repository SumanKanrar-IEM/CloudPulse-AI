"""Nothing in this platform applies a remediation (T026; spec 006, FR-002,
SC-005, constitution Principle IV).

**Asserted structurally, not by trying and failing.** A test that called an
apply endpoint and expected a 404 would prove only that one URL is absent. What
FR-002 actually claims is that *no such capability exists* -- so the assertions
below enumerate the real API surface and the real frontend source and fail if
anything remediation-executing appears in either.

This is a test that must keep passing as the platform grows, and its value is
entirely in catching the change nobody thought of. It is written to fail on a
plausible future addition rather than on today's known-empty state: a new route
whose path or operation id reads as applying a fix, a suggestion route that
accepts a state-changing method, or a button in the findings workbench wired to
one.

The suggester makes this load-bearing rather than theoretical. Before spec 006
no suggestion had an author who might imply it could be actioned; now one is
drafted by a model whose prompt is explicitly told the platform executes nothing
(`agents/prompts/suggester.md`). This test is what makes that instruction true
rather than merely stated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.main import openapi_document

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_FINDINGS = REPO_ROOT / "frontend" / "src" / "app" / "features" / "findings"

# Two tiers, because "apply" is not by itself evidence of anything -- the
# findings workbench legitimately has `applyFilters()`, and a test that flagged
# it would be turned off within a week, taking the real check with it.
#
# Unambiguous: no legitimate reading in this platform. Any call is a hit.
EXECUTING_VERBS = ("remediate", "autofix", "auto_fix")

# Contextual: ordinary words that only mean "act on a cloud account" when paired
# with what is being acted on. `applySuggestion` is a hit; `applyFilters` is not.
CONTEXTUAL_VERBS = ("apply", "execute", "enforce", "perform")
REMEDIATION_NOUNS = ("fix", "suggestion", "remediation", "recommendation", "change")

# Methods that change state. A suggestion route accepting any of these, other
# than the admin seed the platform already ships, would be a way to act on a
# finding rather than to read about one.
MUTATING_METHODS = frozenset({"post", "put", "patch", "delete"})

# The one deliberate exception, and the reason it is safe: spec 004's admin-only
# demo/QA seed writes suggestion *text*. It changes a row in this platform's own
# database and touches no cloud account.
SEED_OPERATION = "setFindingSuggestionSeed"


def _reads_as_executing(name: str) -> str | None:
    """The verb that makes this name read as acting on a cloud account, or None.

    An unambiguous verb stands alone. A contextual one counts only when the same
    name also says what is being acted on, which is what separates
    `applySuggestion` from `applyFilters`.
    """
    lowered = name.lower()
    for verb in EXECUTING_VERBS:
        if verb in lowered:
            return verb
    for verb in CONTEXTUAL_VERBS:
        if verb in lowered and any(noun in lowered for noun in REMEDIATION_NOUNS):
            return verb
    return None


def _operations() -> list[tuple[str, str, dict]]:
    document = openapi_document()
    return [
        (path, method, operation)
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
        if isinstance(operation, dict)
    ]


def test_no_route_reads_as_applying_a_fix() -> None:
    """FR-002. Checked against the generated contract, so a route added without
    a test of its own is still caught -- the document is built from the app's
    real router table, not from a list someone maintains."""
    offenders = [
        f"{method.upper()} {path} ({operation.get('operationId', '?')})"
        for path, method, operation in _operations()
        if _reads_as_executing(f"{path} {operation.get('operationId', '')}")
    ]

    assert offenders == [], (
        "an endpoint appears to apply or execute a remediation. Principle IV: agents "
        f"never execute changes against cloud accounts. Found: {offenders}"
    )


def test_the_only_mutating_suggestion_route_is_the_admin_seed() -> None:
    """The narrower claim, where a real apply endpoint would most naturally be
    added: on the suggestion resource itself."""
    mutating = [
        (path, method, operation.get("operationId"))
        for path, method, operation in _operations()
        if "suggestion" in path.lower() and method.lower() in MUTATING_METHODS
    ]

    assert [op for _, _, op in mutating] == [SEED_OPERATION], (
        "a state-changing suggestion route exists beyond spec 004's admin seed. "
        f"Found: {mutating}"
    )


def test_the_admin_seed_writes_text_and_touches_no_cloud_account() -> None:
    """The exception, pinned. If the seed ever grew a parameter that acted on a
    resource, the test above would still pass while FR-002 had been broken."""
    import inspect

    from app.api.routers import findings

    source = inspect.getsource(findings.set_finding_suggestion_seed)

    assert "boto3" not in source
    assert "connectors" not in source
    for verb in EXECUTING_VERBS:
        assert verb not in source.lower(), f"the admin seed mentions '{verb}'"
    assert _reads_as_executing(source) is None


def test_the_findings_workbench_has_no_apply_control() -> None:
    """SC-005. A suggestion is rendered as text a person acts on themselves;
    there is no control that would act on it for them."""
    sources = list(FRONTEND_FINDINGS.rglob("*.ts"))
    assert sources, f"expected findings components under {FRONTEND_FINDINGS}"

    offenders: list[str] = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        # Comments and prose legitimately discuss what the platform does not do
        # -- this file's own subject. Only code is checked.
        code = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
        # Every called identifier, judged whole: `applySuggestion` is a hit,
        # `applyFilters` is not, and neither decision rests on a bare substring.
        for identifier in set(re.findall(r"\b(\w+)\s*\(", code)):
            verb = _reads_as_executing(identifier)
            if verb is not None:
                offenders.append(f"{path.name}: {identifier}")

    assert offenders == [], (
        "the findings workbench appears to offer a control that applies a remediation "
        f"(SC-005). Found: {offenders}"
    )


def test_no_governance_module_can_write_to_a_cloud_account() -> None:
    """Principle IV's other half, at the layer where a suggestion would be
    acted on. `check_connector_boundary.py` already forbids a provider SDK
    outside `connectors/`; this asserts the narrower thing that matters here --
    that the suggestion path reaches no connector at all, so there is nothing
    for a future 'apply' to call through."""
    suggestions = (REPO_ROOT / "backend" / "app" / "governance" / "suggestions.py").read_text()
    suggester = (REPO_ROOT / "backend" / "app" / "governance" / "suggester.py").read_text()

    for name, source in (("suggestions.py", suggestions), ("suggester.py", suggester)):
        assert "connectors" not in source, f"{name} reaches the connector boundary"
        assert "boto3" not in source, f"{name} imports a cloud SDK"
