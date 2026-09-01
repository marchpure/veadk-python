from __future__ import annotations

import ast
from pathlib import Path

import pytest

from frontend.server.knowledge_workspace.autoskill import AutoSkillConfig
from frontend.server.knowledge_workspace.connection import (
    ConnectionServiceConfig,
    ConnectionServiceGateway,
)

ROOT = Path(__file__).parents[2]


def test_native_production_modules_exclude_legacy_transport_and_state_bridge() -> None:
    autoskill = (ROOT / "frontend/server/knowledge_workspace/autoskill.py").read_text()
    connection = (
        ROOT / "frontend/server/knowledge_workspace/connection.py"
    ).read_text()

    assert "/openapi/autoskill/v1" not in autoskill
    assert '"Last-Event-ID"' not in autoskill
    assert "mcp_config.yaml" not in connection
    assert "_state_with_mcp" not in connection


def test_staging_harness_accepts_only_https_urls() -> None:
    source = (ROOT / "tools/kac2_w3_staging_harness.py").read_text()
    ast.parse(source)
    assert "--autoskill-url" in source
    assert "--connection-url" in source
    assert "KNOWLEDGE_AUTOSKILL_API_KEY" in source
    assert "KAC2_CONNECTION_PRINCIPAL_AUTHORIZATION" in source


def test_production_rejects_loopback_autoskill_and_connection_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_AUTOSKILL_ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="HTTPS"):
        from frontend.server.knowledge_workspace.autoskill import AutoSkillClient

        AutoSkillClient(AutoSkillConfig(base_url="http://127.0.0.1:8000"))
    with pytest.raises(ValueError, match="HTTPS"):
        ConnectionServiceGateway(
            ConnectionServiceConfig(
                "http://127.0.0.1:9000",
                "secret",
                runtime_public_url="http://127.0.0.1:9000",
            )
        )
