"""Content-hash a prompt or agent definition (spec 006, T010; FR-005, R-608).

Every stored agent output records the hash of what produced it, so a change in
behaviour traces to a change in a versioned file rather than being written off
as model drift. That is the whole of FR-005: "agent prompts and definitions MUST
be versioned in the repository, and every stored output MUST record which
version produced it."

Hashing content rather than reading a version string is deliberate. A version
string is a promise someone has to remember to keep; a content hash cannot
disagree with the file it came from.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# The repository's `agents/` tree, resolved from this file rather than from the
# working directory -- a Lambda's cwd is not the repo root.
AGENTS_ROOT = Path(__file__).resolve().parents[3] / "agents"


def hash_text(content: str) -> str:
    """SHA-256 of the content, normalised for line endings and trailing space.

    Normalising means a file that differs only by how an editor saved it does
    not read as a behaviour change -- which would make the hash noisy enough
    that people stopped trusting it.
    """
    normalised = "\n".join(line.rstrip() for line in content.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(normalised.strip().encode("utf-8")).hexdigest()


def hash_definition(*paths: Path) -> str:
    """One hash over several files, in the order given.

    An agent's behaviour is its prompt *and* its definition together, so a change
    to either must move the hash. Hashing them separately and storing only one
    would leave half the behaviour untracked.
    """
    if not paths:
        raise ValueError("at least one path is required to hash a definition")
    combined = "\n".join(f"{path.name}\n{path.read_text(encoding='utf-8')}" for path in paths)
    return hash_text(combined)


__all__ = ["AGENTS_ROOT", "hash_definition", "hash_text"]
