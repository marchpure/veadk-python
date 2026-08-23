from __future__ import annotations

import json
from pathlib import Path

import pytest


CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "fixtures/knowledge_workspace_v21141/e2e-skeleton.json"
)
CASES = json.loads(CONTRACT.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_commercial_e2e_skeleton_is_explicit(case: dict) -> None:
    """Collection stays green without representing unexecuted work as PASS."""
    assert case["status"] == "blocked"
    assert case["requires"]
    assert case["evidence"]
    assert case["evidence"][0].startswith("BLOCKED:")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_commercial_e2e_requires_external_evidence(case: dict) -> None:
    pytest.skip(
        f"{case['status'].upper()}: {case['evidence'][0]} "
        "(skeleton only; never counts as GA PASS)"
    )
