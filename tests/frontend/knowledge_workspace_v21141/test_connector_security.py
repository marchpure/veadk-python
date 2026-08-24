from __future__ import annotations

import pytest

from frontend.server.knowledge_assets.connectors import validate_external_config
from frontend.server.knowledge_assets.ports import ConnectorConfig
from frontend.server.knowledge_assets.security import (
    validate_mcp_tool,
    validate_read_only_sql,
    validate_web_endpoint,
)


def test_web_connector_rejects_private_and_dns_rebinding_targets() -> None:
    with pytest.raises(ValueError, match="non-public"):
        validate_web_endpoint("https://127.0.0.1/data", resolver=lambda _: ["127.0.0.1"])
    with pytest.raises(ValueError, match="non-public"):
        validate_web_endpoint(
            "https://public.example/data",
            resolver=lambda _: ["93.184.216.34", "169.254.169.254"],
        )


def test_connector_config_rejects_inline_credentials() -> None:
    with pytest.raises(ValueError, match="secretRef"):
        validate_external_config(
            ConnectorConfig(
                kind="web_api",
                endpoint="https://example.com",
                options={"apiKey": "do-not-store"},
            )
        )


def test_database_policy_is_read_only_and_parameterized() -> None:
    validate_read_only_sql(
        "SELECT * FROM accounts WHERE owner = :owner",
        parameters={"owner": "alice"},
    )
    with pytest.raises(ValueError, match="read-only"):
        validate_read_only_sql("UPDATE accounts SET name = :name", parameters={"name": "x"})
    with pytest.raises(ValueError, match="parameters"):
        validate_read_only_sql("SELECT * FROM accounts WHERE owner = :owner", parameters={})


def test_mcp_policy_enforces_allowlist_and_output_budget() -> None:
    validate_mcp_tool("workday.lookup", allowlist={"workday.lookup"}, output_bytes=100)
    with pytest.raises(ValueError, match="allowlist"):
        validate_mcp_tool("shell.exec", allowlist={"workday.lookup"}, output_bytes=100)
    with pytest.raises(ValueError, match="budget"):
        validate_mcp_tool("workday.lookup", allowlist={"workday.lookup"}, output_bytes=2_000_000)
