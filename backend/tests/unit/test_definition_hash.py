"""Content hashing for prompts and agent definitions (T010; FR-005, R-608)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.governance.definition_hash import AGENTS_ROOT, hash_definition, hash_text


def test_the_same_content_always_hashes_the_same() -> None:
    assert hash_text("be concise") == hash_text("be concise")


def test_changed_content_changes_the_hash() -> None:
    """The point of FR-005: an output's behaviour traces to a specific file
    version rather than being written off as model drift."""
    assert hash_text("be concise") != hash_text("be verbose")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("line one\nline two", "line one\r\nline two"),
        ("trailing space  \nnext", "trailing space\nnext"),
        ("body", "body\n\n"),
    ],
)
def test_formatting_differences_do_not_move_the_hash(a: str, b: str) -> None:
    """A file that differs only by how an editor saved it is not a behaviour
    change. A hash that moved on line endings would be noisy enough that people
    stopped trusting it — and a hash nobody trusts records nothing."""
    assert hash_text(a) == hash_text(b)


def test_a_definition_hash_covers_every_file_it_is_given(tmp_path: Path) -> None:
    """An agent's behaviour is its prompt *and* its definition. Hashing one and
    storing that would leave the other's changes untracked."""
    prompt = tmp_path / "prompt.md"
    definition = tmp_path / "definition.json"
    prompt.write_text("summarise", encoding="utf-8")
    definition.write_text('{"model": "x"}', encoding="utf-8")

    before = hash_definition(prompt, definition)
    definition.write_text('{"model": "y"}', encoding="utf-8")

    assert hash_definition(prompt, definition) != before


def test_file_order_is_part_of_the_hash(tmp_path: Path) -> None:
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("one", encoding="utf-8")
    b.write_text("two", encoding="utf-8")
    assert hash_definition(a, b) != hash_definition(b, a)


def test_hashing_nothing_is_refused() -> None:
    """An empty definition would hash to a stable value and look like a real
    version, which is worse than an error."""
    with pytest.raises(ValueError, match="at least one path"):
        hash_definition()


def test_the_agents_root_resolves_to_the_repository_tree() -> None:
    """Resolved from this module's location, not the working directory — a
    Lambda's cwd is not the repo root."""
    assert AGENTS_ROOT.name == "agents"
    assert (AGENTS_ROOT / "prompts").is_dir()


def test_a_hash_is_a_full_sha256_hex_digest() -> None:
    """`agent_run.definition_hash` is VARCHAR(64); a longer digest would be
    silently truncated by the database and stop being unique."""
    digest = hash_text("anything")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
