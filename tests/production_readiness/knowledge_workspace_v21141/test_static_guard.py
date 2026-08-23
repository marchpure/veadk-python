from pathlib import Path

from static_guard import (
    RUNTIME_PATTERNS,
    STEP_1_ALLOWED_PREFIXES,
    is_first_party_production_source,
    production_policy_findings,
    scan,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_current_production_tree_passes_step_1_static_guard() -> None:
    result = scan(REPO_ROOT)
    assert result["status"] == "pass", result["findings"]
    assert result["frozen_production_copies"] <= 1
    assert result["new_first_party_production_files"] == 0
    assert result["new_first_party_production_gross_loc"] == 0
    assert result["new_first_party_production_net_loc"] == 0
    assert result["oversized_new_source_files"] == []
    assert result["mandatory_split_review_files"] == []
    assert all(item["line_growth"] <= 0 for item in result["shared_hotspots"])
    assert result["changed_files"] >= 1


def test_step_1_scope_excludes_production_implementation() -> None:
    assert not any(
        prefix.startswith(("frontend/src/", "frontend/server/", "veadk/"))
        for prefix in STEP_1_ALLOWED_PREFIXES
    )


def test_step_1_guard_rejects_production_sources_and_runtime_artifacts() -> None:
    assert is_first_party_production_source("frontend/src/knowledge/new.ts")
    assert is_first_party_production_source(
        "frontend/server/knowledge_assets/routes.py"
    )
    assert is_first_party_production_source("veadk/knowledge/service.py")
    assert {"*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp"} <= RUNTIME_PATTERNS


def test_production_policy_guard_rejects_every_forbidden_dependency() -> None:
    samples = {
        "iframe": "<iframe src='/embedded' />",
        "fixture": "fetch('/tests/fixtures/knowledge.json')",
        "local-storage": "localStorage.setItem('knowledge', state)",
        "mock-provider": "const provider = new MockProvider()",
        "static-success": "const result = staticSuccess(payload)",
        "fake-sse": "return fakeSse(events)",
    }
    for expected, source in samples.items():
        assert production_policy_findings(
            "frontend/src/knowledge-workspace/example.tsx", source
        ) == [f"production-{expected}:frontend/src/knowledge-workspace/example.tsx"]
