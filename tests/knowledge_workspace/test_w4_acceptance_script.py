from __future__ import annotations

import json

import pytest

from tools.knowledge_workspace_w4_acceptance import amain


@pytest.mark.asyncio
async def test_w4_acceptance_script_writes_template_lifecycle_evidence(tmp_path) -> None:
    result = await amain(tmp_path)

    assert result == 0
    summary = json.loads((tmp_path / "w4-acceptance-summary.json").read_text())
    assert summary["status"] == "CONTRACT_FIXTURE_PASS"
    assert set(summary["templates"]) == {"semantic", "dashboard", "sop"}
    assert summary["security_negative_checks"] == {
        "cookie": "ARTIFACT_UNSAFE",
        "external_url": "ARTIFACT_EXTERNAL_LINK",
        "fetch": "ARTIFACT_UNSAFE",
        "safe_inline_script": "allow-scripts",
    }
    for template_key in ("semantic", "dashboard", "sop"):
        detail = json.loads((tmp_path / f"{template_key}-lifecycle.json").read_text())
        assert detail["contract_fixture"] is True
        assert detail["template_config_redacted"] is True
        assert detail["zip"]["scripts_and_tests_present"] is True
        assert detail["zip"]["digests_differ"] is True
        assert detail["security"]["cross_tenant_denied"] is True
        assert detail["security"]["revoked_connection_denied"] is True
        assert detail["security"]["expired_lease_error"] == "LEASE_EXPIRED"
        assert "validate_skill" in detail["autoskill_commands"]
        assert {"run.started", "activity.started", "activity.completed", "assistant.delta", "assistant.final", "request.summary", "run.completed"}.issubset(
            detail["events"]["generate"]
        )
        assert all(item["html_valid"] for item in detail["artifacts"])
        assert all(item["sha256_verified"] for item in detail["artifacts"])
    assert len(summary["templates"]["dashboard"]["artifact_ids"]) == 3
