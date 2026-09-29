"""Dev teardown must survive real data; prod must never force-destroy (T146, FR-005a).

T145's teardown stopped at the versioned snapshots bucket because a live scan had
written to it. Parses the Terraform so the dev/prod split cannot regress.
"""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[3] / "infra" / "modules"


def _bucket_block(module: str, name: str) -> str:
    source = (INFRA / module / "main.tf").read_text()
    match = re.search(rf'resource "aws_s3_bucket" "{name}" \{{(.*?)\n\}}', source, re.DOTALL)
    assert match, f"{module}: aws_s3_bucket.{name} not found"
    return match.group(1)


def test_snapshots_force_destroy_in_dev_only() -> None:
    assert 'force_destroy = var.environment != "prod"' in _bucket_block("storage", "snapshots")


def test_frontend_origin_keeps_the_same_split() -> None:
    assert 'force_destroy = var.environment != "prod"' in _bucket_block("frontend", "origin")
