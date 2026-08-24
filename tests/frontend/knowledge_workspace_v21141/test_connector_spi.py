from pathlib import Path

import pytest

from frontend.server.knowledge_assets.connectors import LocalFileConnector, connector_for
from frontend.server.knowledge_assets.ports import ConnectorConfig, ConnectorContext


def context() -> ConnectorContext:
    return ConnectorContext(
        tenant_id="tenant", caller_id="caller", workspace_id="workspace",
        trace_id="trace", idempotency_key="idem",
    )


def test_local_connector_reads_markdown_and_csv_with_typed_events(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (tmp_path / "rows.csv").write_text("name,value\nA,1\n", encoding="utf-8")
    connector = LocalFileConnector(root=tmp_path)
    for name in ("notes.md", "rows.csv"):
        config = ConnectorConfig(kind="markdown" if name.endswith("md") else "csv", endpoint=name)
        assert connector.test_connection(context(), config).status == "succeeded"
        introspection = connector.introspect(context(), config)
        assert introspection.status == "succeeded"
        assert introspection.details["schemaDigest"]


def test_local_connector_rejects_escape_unsupported_and_oversize(tmp_path: Path) -> None:
    (tmp_path / "bad.txt").write_text("no", encoding="utf-8")
    connector = LocalFileConnector(root=tmp_path, max_bytes=2)
    with pytest.raises(ValueError, match="escapes"):
        connector.test_connection(context(), ConnectorConfig(kind="markdown", endpoint="../secret.md"))
    with pytest.raises(ValueError, match="only Markdown"):
        connector.test_connection(context(), ConnectorConfig(kind="markdown", endpoint="bad.txt"))
    (tmp_path / "large.md").write_text("123", encoding="utf-8")
    with pytest.raises(ValueError, match="size limit"):
        connector.test_connection(context(), ConnectorConfig(kind="markdown", endpoint="large.md"))


def test_external_connector_is_explicitly_credential_blocked() -> None:
    adapter = connector_for("oracle")
    event = adapter.test_connection(
        context(), ConnectorConfig(kind="oracle", endpoint="oracle://db", options={"secretRef": "secret://db"})
    )
    assert event.status == "credential_blocked"
    assert event.details["kind"] == "oracle"


def test_external_connector_rejects_missing_secret_reference_without_inline_secret() -> None:
    adapter = connector_for("web_api")
    event = adapter.test_connection(
        context(), ConnectorConfig(kind="web_api", endpoint="https://example.invalid")
    )
    assert event.status == "credential_blocked"
    assert "secretRef" in event.details["reason"]
