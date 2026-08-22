#!/usr/bin/env python3
"""Fail if a non-AWS AI runtime SDK enters any dependency manifest.

Enforces constitution Principle II (NON-NEGOTIABLE) and FR-013a. Principle II's
*Testable* clause demands an automated allowlist gate, not merely the absence of
SDKs -- a README assertion was judged insufficient for a NON-NEGOTIABLE principle.

Scope of the rule
-----------------
The deployed system's GenAI layer is Amazon Bedrock Agents, exclusively. No
third-party model host, inference SDK, or agent framework may become a runtime
dependency of the platform.

Claude Code and GitHub Copilot drive development and are *development-time* tools:
they are not installed by any manifest here, so this gate never sees them. The
boundary Principle II draws is absolute -- an authoring tool may be Anthropic's; a
running component may not be.

Exit codes: 0 clean, 1 violation found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Manifests that declare what ships or what CI installs.
MANIFESTS = (
    "backend/pyproject.toml",
    "frontend/package.json",
    "backend/requirements.txt",
    "backend/requirements-dev.txt",
)

# Distribution names that would put a non-AWS model runtime into the platform.
# Matched against dependency *names*, not arbitrary prose, so a doc comment
# explaining the rule does not trip it.
BANNED_PACKAGES: dict[str, str] = {
    "openai": "third-party model host",
    "anthropic": "third-party model host (Claude Code is development-time only; the platform calls Claude via Amazon Bedrock)",
    "cohere": "third-party model host",
    "mistralai": "third-party model host",
    "google-generativeai": "third-party model host",
    "google-genai": "third-party model host",
    "vertexai": "non-AWS model runtime",
    "replicate": "third-party model host",
    "together": "third-party model host",
    "groq": "third-party model host",
    "ollama": "non-AWS local model runtime",
    "huggingface-hub": "third-party model host",
    "transformers": "non-AWS local inference",
    "langchain": "non-AWS agent framework",
    "langchain-core": "non-AWS agent framework",
    "langchain-community": "non-AWS agent framework",
    "langgraph": "non-AWS agent framework",
    "llama-index": "non-AWS agent framework",
    "haystack-ai": "non-AWS agent framework",
    "crewai": "non-AWS agent framework",
    "autogen": "non-AWS agent framework",
    "semantic-kernel": "non-AWS agent framework",
    "@langchain/core": "non-AWS agent framework",
    "@anthropic-ai/sdk": "third-party model host",
}

# `name>=1.2,<2` / `"name": "^1.2.3"` -> name
DEP_NAME = re.compile(r'^\s*["\']?(?P<name>@?[A-Za-z0-9._/-]+)')


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _extract_python_deps(text: str) -> list[tuple[int, str]]:
    """Dependency names from pyproject dependency arrays."""
    found: list[tuple[int, str]] = []
    in_deps = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if re.match(r"^(dependencies|dev|test)\s*=\s*\[", stripped) or stripped.endswith("= ["):
            in_deps = True
            continue
        if in_deps:
            if stripped.startswith("]"):
                in_deps = False
                continue
            m = DEP_NAME.match(stripped)
            if m:
                found.append((lineno, _normalize(m.group("name").split("[")[0])))
    return found


def _extract_node_deps(text: str) -> list[tuple[int, str]]:
    """Dependency names from package.json dependency objects."""
    found: list[tuple[int, str]] = []
    in_deps = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if re.search(r'"(dependencies|devDependencies|peerDependencies)"\s*:\s*\{', stripped):
            in_deps = True
            continue
        if in_deps:
            if stripped.startswith("}"):
                in_deps = False
                continue
            m = re.match(r'^\s*"(?P<name>@?[A-Za-z0-9._/-]+)"\s*:', line)
            if m:
                found.append((lineno, _normalize(m.group("name"))))
    return found


def main() -> int:
    violations: list[str] = []
    scanned = 0

    for rel in MANIFESTS:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8")
        deps = _extract_node_deps(text) if path.suffix == ".json" else _extract_python_deps(text)

        for lineno, name in deps:
            if name in BANNED_PACKAGES:
                violations.append(
                    f"{rel}:{lineno}: '{name}' is a {BANNED_PACKAGES[name]}. "
                    f"Constitution Principle II permits Amazon Bedrock Agents only for the "
                    f"product GenAI layer (FR-013a)."
                )

    if violations:
        sys.stderr.write("Principle II violation -- non-AWS AI runtime in a dependency manifest:\n\n")
        for v in violations:
            sys.stderr.write(f"  {v}\n")
        sys.stderr.write(
            "\nIf the platform needs a model, call it through Amazon Bedrock. "
            "If this is a development-time tool, it does not belong in a runtime manifest.\n"
        )
        return 1

    sys.stdout.write(f"dependency-allowlist: OK ({scanned} manifest(s) scanned, 0 violations)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
