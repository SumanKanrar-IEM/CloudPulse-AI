"""The teardown guard refuses prod BEFORE touching anything (FR-005a, R-010).

Three layers protect prod (research.md R-010):

    1. ``aws_rds_cluster.deletion_protection``  -- refuses at the cluster, last
    2. ``lifecycle { prevent_destroy }``        -- fails partway through a plan
    3. this script's guard                      -- refuses before terraform runs

Only the third can satisfy the spec's "teardown aimed at prod" edge case, which
requires refusal *before anything is touched* rather than a partial destroy that stops
at the protected resource. That ordering is what these tests pin down -- not merely
that the script exits non-zero, but that it exits non-zero having invoked nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_REL = Path("ops/teardown.sh")


@pytest.fixture
def script(repo_root: Path) -> Path:
    path = repo_root / SCRIPT_REL
    if not path.exists():
        pytest.skip(f"{SCRIPT_REL} not present")
    return path


def _run(
    script: Path, *args: str, cwd: Path, tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the guard with `terraform` and `aws` replaced by recording shims.

    Emptying PATH would also remove `dirname` and `tr`, which the script legitimately
    uses -- that tests the harness, not the guard. Instead a shim directory is placed
    FIRST on PATH: each shim appends its own name to a marker file and exits 0. If the
    marker file exists afterwards, the guard reached a real invocation before refusing.

    Returns the completed process and the marker path, so a test can assert on both
    the exit code and on what was (not) invoked.
    """
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir(exist_ok=True)
    marker = tmp_path / "invoked.log"

    for tool in ("terraform", "aws"):
        shim = shim_dir / tool
        shim.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{marker}"\nexit 0\n')
        shim.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}:{env.get('PATH', '')}"
    env.pop("AWS_PROFILE", None)
    env.pop("AWS_ACCESS_KEY_ID", None)
    env.pop("AWS_ROLE_ARN", None)

    proc = subprocess.run(
        ["/bin/bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    return proc, marker


def test_script_is_executable(script: Path) -> None:
    assert os.access(script, os.X_OK), "ops/teardown.sh must be executable"


@pytest.mark.parametrize("target", ["prod", "PROD", "Prod", "production", "PRODUCTION"])
def test_prod_is_refused_in_any_casing(
    script: Path, repo_root: Path, tmp_path: Path, target: str
) -> None:
    """Case-insensitive. `PROD` typed in a hurry must refuse exactly like `prod`."""
    result, marker = _run(script, target, cwd=repo_root, tmp_path=tmp_path)
    assert result.returncode != 0, f"'{target}' was NOT refused"
    assert "REFUSED" in result.stderr


@pytest.mark.parametrize("target", ["prod", "PROD", "production"])
def test_refusal_happens_before_any_tool_is_invoked(
    script: Path, repo_root: Path, tmp_path: Path, target: str
) -> None:
    """The edge case requires refusal before anything is touched.

    With PATH emptied, reaching a real invocation would surface a
    'command not found' error. Its absence is the evidence.
    """
    result, marker = _run(script, target, cwd=repo_root, tmp_path=tmp_path)
    assert result.returncode != 0
    assert not marker.exists(), (
        f"guard invoked {marker.read_text().strip()!r} before refusing -- FR-005a "
        f"requires refusal BEFORE anything is touched"
    )
    assert "nothing has been touched" in (result.stdout + result.stderr).lower()


def test_refusal_explains_why_not_just_that(script: Path, repo_root: Path, tmp_path: Path) -> None:
    """A refusal a reader cannot act on gets worked around rather than respected."""
    stderr = _run(script, "prod", cwd=repo_root, tmp_path=tmp_path)[0].stderr.lower()
    assert "fr-005a" in stderr
    assert "audit" in stderr or "cannot be rebuilt" in stderr
    assert "deletion protection" in stderr


def test_missing_argument_is_refused(script: Path, repo_root: Path, tmp_path: Path) -> None:
    result, marker = _run(script, cwd=repo_root, tmp_path=tmp_path)
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()


def test_unknown_environment_is_refused(script: Path, repo_root: Path, tmp_path: Path) -> None:
    """FR-002 permits exactly two environments; anything else is a typo."""
    result, marker = _run(script, "staging", cwd=repo_root, tmp_path=tmp_path)
    assert result.returncode != 0
    assert "REFUSED" in result.stderr


def test_dev_is_not_blocked_by_the_prod_guard(
    script: Path, repo_root: Path, tmp_path: Path
) -> None:
    """The inverse half: a guard that refuses everything is as useless as none.

    `dev` must fail on the *credentials* check, not the protected-environment check.
    """
    result, marker = _run(script, "dev", cwd=repo_root, tmp_path=tmp_path)
    assert result.returncode != 0
    assert "protected environment" not in result.stderr
    assert "credentials" in result.stderr.lower()


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_has_no_bash4_only_syntax(script: Path) -> None:
    """macOS ships bash 3.2. A guard that errors on a syntax it cannot parse fails
    OPEN, which is strictly worse than having no guard at all."""
    result = subprocess.run(
        ["/bin/bash", "-n", str(script)], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, f"syntax error under the system bash: {result.stderr}"

    # Check code, not comments -- the script deliberately *mentions* ${1,,} in the
    # comment explaining why it is avoided.
    code = [line for line in script.read_text().splitlines() if not line.lstrip().startswith("#")]
    offenders = [line.strip() for line in code if "${1,," in line or "${TARGET,," in line]
    assert not offenders, f"bash 4+ case expansion is not portable: {offenders}"
