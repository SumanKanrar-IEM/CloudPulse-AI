"""Every agent definition's declared paths match its handler's allowlist
(spec 006, T035; FR-003, FR-056, R-602).

Each action-group handler carries a comment saying its `ALLOWED_PATHS` must
match the definition JSON. Three handlers now say it, and a comment is not a
check. The two lists drifting apart fails in one of two ways, and the quiet one
is the dangerous one:

* a path in the JSON but not the handler is refused with a 404 the agent reads
  as "no such operation" -- confusing, but safe;
* a path in the handler but not the JSON is a **reachable operation nobody
  declared**, which is the fail-closed property `_platform_api.call` exists to
  provide, silently widened.

So this asserts equality rather than containment in either direction.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.governance.definition_hash import AGENTS_ROOT

CAPABILITIES = ("digest", "suggester", "advisor")


def _declared_paths(capability: str) -> set[str]:
    definition = json.loads(
        (AGENTS_ROOT / "definitions" / f"{capability}.json").read_text(encoding="utf-8")
    )
    return {
        path
        for group in definition["actionGroups"]
        for path in group["apiSchema"]["paths"]
    }


def _handler_paths(capability: str) -> set[str]:
    """Import the handler the way its Lambda package does.

    `agents/action-groups/` is flat on the deployed function -- the CI build
    copies every file beside the handler -- so `import _platform_api` resolves
    only with that directory on the path. Adding it here reproduces the deployed
    import shape rather than reaching around it.
    """
    directory = AGENTS_ROOT / "action-groups"
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    name = f"{capability}_tools"
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.ALLOWED_PATHS)


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_the_handler_allows_exactly_what_the_definition_declares(capability: str) -> None:
    assert _handler_paths(capability) == _declared_paths(capability)


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_every_declared_operation_is_a_get(capability: str) -> None:
    """FR-056. The read-only guarantee is enforced three times over -- by the
    API's agent principal, by `_platform_api.call`'s method check, and by there
    being no non-GET operation to invoke. This asserts the third."""
    definition = json.loads(
        (AGENTS_ROOT / "definitions" / f"{capability}.json").read_text(encoding="utf-8")
    )
    methods = {
        method
        for group in definition["actionGroups"]
        for operations in group["apiSchema"]["paths"].values()
        for method in operations
    }
    assert methods == {"get"}


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_the_prompt_file_the_definition_names_exists(capability: str) -> None:
    """A missing prompt is not a startup error anywhere: the definition is read
    by infra at deploy time, and the hash is computed from paths the caller
    supplies. A typo here would ship an agent with no instruction."""
    definition = json.loads(
        (AGENTS_ROOT / "definitions" / f"{capability}.json").read_text(encoding="utf-8")
    )
    prompt = Path(AGENTS_ROOT).parent / definition["promptFile"]
    assert prompt.is_file()
