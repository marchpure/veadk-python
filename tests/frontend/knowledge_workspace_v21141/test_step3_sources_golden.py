from collections import Counter
from pathlib import Path
import sqlite3
import json
import os
import sys
import time

from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
    SourcesGoldenError,
)
import pytest


def _application(tmp_path: Path) -> SourceGoldenApplication:
    return SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
    )


def _context(
    *,
    workspace_id: str = "workspace-a",
    principal_id: str = "user-1",
    role: str = "editor",
) -> AccessContext:
    return AccessContext(
        workspace_id=workspace_id,
        principal_id=principal_id,
        role=role,
    )


def test_connector_catalog_is_complete_typed_and_truthful(tmp_path: Path) -> None:
    catalog = _application(tmp_path).connector_catalog(_context())

    assert catalog.view == "connector_catalog"
    assert len(catalog.connectors) == 37
    assert Counter(item.category for item in catalog.connectors) == {
        "office": 10,
        "file": 8,
        "db": 11,
        "api": 5,
        "custom": 3,
    }
    assert len({item.connector_key for item in catalog.connectors}) == 37
    assert catalog.create_custom_action.connector_key == "create_custom"
    assert all(item.reason.code and item.reason.message for item in catalog.connectors)
    assert all(
        item.input_schema.additional_properties is False for item in catalog.connectors
    )
    assert all(item.permissions.read_scopes for item in catalog.connectors)

    by_key = {item.connector_key: item for item in catalog.connectors}
    assert by_key["csv"].capability_state == "available"
    assert by_key["sqlite"].capability_state == "available"
    assert by_key["local_file"].capability_state == "available"
    assert by_key["doc_txt"].capability_state == "available"
    assert by_key["oracle"].capability_state == "credential_blocked"
    assert by_key["postgresql"].capability_state == "credential_blocked"
    assert by_key["lark_doc"].capability_state == "credential_blocked"
    assert by_key["web_discovery"].capability_state == "credential_blocked"
    assert by_key["mcp_custom"].capability_state == "configurable"
    assert by_key["excel"].capability_state == "available"

    assert "host" not in by_key["csv"].input_schema.properties
    assert {"host", "port", "database"} <= set(
        by_key["postgresql"].input_schema.properties
    )
    assert {"endpoint", "paginationMode", "refreshSeconds"} <= set(
        by_key["rest_api"].input_schema.properties
    )
    assert {"transport", "endpoint", "toolAllowlist"} <= set(
        by_key["mcp_custom"].input_schema.properties
    )
    assert {"documentRef", "scopeRef"} <= set(
        by_key["lark_doc"].input_schema.properties
    )
    assert set(by_key["oracle"].credential_schema.properties) == {"secretRef"}

    serialized = catalog.model_dump(mode="json", by_alias=True)
    assert serialized["connectors"][0]["capabilityState"]
    assert "password" not in str(serialized).lower()
    assert "tokenValue" not in str(serialized)

    filtered = _application(tmp_path).connector_catalog(
        _context(), category="db", query="post"
    )
    assert [item.connector_key for item in filtered.connectors] == ["postgresql"]


def test_local_connection_validation_discovery_and_overview_survive_restart(
    tmp_path: Path,
) -> None:
    (tmp_path / "orders.csv").write_text(
        "order_id,amount\nA-1,12.50\nA-2,7.25\n",
        encoding="utf-8",
    )
    application = _application(tmp_path)
    result = application.create_connection(
        _context(),
        connector_key="csv",
        display_name="Orders",
        scope="personal",
        configuration={"sourceRef": "orders.csv"},
        secret_ref=None,
        idempotency_key="create-orders",
        trace_id="trace-create-orders",
    )

    assert result.connection.status == "ready"
    assert result.validation.status == "succeeded"
    assert result.discovery.status == "succeeded"
    assert result.discovery.resources[0].name == "orders.csv"
    assert [field.name for field in result.discovery.resources[0].fields] == [
        "order_id",
        "amount",
    ]

    reopened = _application(tmp_path)
    overview = reopened.data_overview(_context())
    assert overview.view == "data_overview"
    assert [connection.id for connection in overview.connections] == [
        result.connection.id
    ]
    assert overview.connections[0].discovered_resources[0].name == "orders.csv"
    assert (
        reopened.connection_detail(
            _context(), result.connection.id
        ).connection.display_name
        == "Orders"
    )


def test_external_adapter_contracts_validate_then_fail_closed(
    tmp_path: Path,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
        web_resolver=lambda host: (
            ["127.0.0.1"] if host == "private.example" else ["93.184.216.34"]
        ),
    )

    contracts = {
        key: application.adapter_contract(key)
        for key in (
            "oracle",
            "postgresql",
            "lark_doc",
            "rest_api",
            "web_discovery",
            "mcp_custom",
        )
    }
    assert contracts["oracle"].protocol == "oracle"
    assert contracts["postgresql"].protocol == "postgresql"
    assert contracts["lark_doc"].protocol == "lark_openapi"
    assert contracts["rest_api"].security_controls == [
        "secret_ref_only",
        "ssrf_dns_rebinding",
        "operation_allowlist",
        "bounded_pagination",
    ]
    assert contracts["mcp_custom"].operations == [
        "validate",
        "discover_tools",
        "read",
        "checkpoint",
        "close",
    ]

    blocked = application.create_connection(
        _context(),
        connector_key="postgresql",
        display_name="Warehouse",
        scope="team",
        configuration={
            "host": "db.example",
            "port": 5432,
            "database": "analytics",
            "query": "SELECT * FROM orders WHERE tenant_id = :tenant_id",
            "rowLimit": 100,
            "byteLimit": 100_000,
            "timeoutSeconds": 10,
        },
        secret_ref="secret://workspace-a/postgresql",
        idempotency_key="postgresql",
        trace_id="trace-postgresql",
    )
    assert blocked.connection.status == "credential_blocked"
    assert blocked.discovery.resources == []
    assert blocked.discovery.reason.code == "PROVIDER_EXECUTION_BLOCKED"
    serialized = blocked.model_dump_json(by_alias=True)
    assert "secret://workspace-a/postgresql" in serialized
    assert "password" not in serialized.lower()

    with pytest.raises(SourcesGoldenError, match="read-only"):
        application.create_connection(
            _context(),
            connector_key="oracle",
            display_name="Oracle",
            scope="personal",
            configuration={
                "host": "db.example",
                "port": 1521,
                "serviceName": "ORCL",
                "query": "DELETE FROM accounts",
            },
            secret_ref="secret://workspace-a/oracle",
            idempotency_key="bad-oracle",
            trace_id="trace-bad-oracle",
        )
    with pytest.raises(SourcesGoldenError, match="non-public"):
        application.create_connection(
            _context(),
            connector_key="rest_api",
            display_name="Unsafe API",
            scope="personal",
            configuration={
                "endpoint": "https://private.example/data",
                "paginationMode": "none",
                "refreshSeconds": 60,
            },
            secret_ref=None,
            idempotency_key="private-web",
            trace_id="trace-private-web",
        )
    with pytest.raises(SourcesGoldenError, match="secretRef"):
        application.create_connection(
            _context(),
            connector_key="web_discovery",
            display_name="Leaky API",
            scope="personal",
            configuration={
                "endpoint": "https://example.com/data",
                "apiKey": "must-not-persist",
            },
            secret_ref=None,
            idempotency_key="inline-secret",
            trace_id="trace-inline-secret",
        )


def test_markdown_csv_and_sqlite_build_persisted_golden_revisions(
    tmp_path: Path,
) -> None:
    (tmp_path / "policy.md").write_text(
        "# Returns\n\n Keep receipt. \nKeep receipt.\n",
        encoding="utf-8",
    )
    (tmp_path / "orders.csv").write_text(
        "order_id,amount,email\n A-1 ,12.50,a@example.com\n"
        "A-1,12.50,a@example.com\nB-2,7,\n",
        encoding="utf-8",
    )
    database = sqlite3.connect(tmp_path / "inventory.sqlite3")
    database.executescript(
        """
        CREATE TABLE inventory (sku TEXT NOT NULL, quantity INTEGER);
        INSERT INTO inventory VALUES ('SKU-1', 5), ('SKU-2', 0);
        """
    )
    database.close()

    application = _application(tmp_path)
    cases = [
        ("local_file", "policy.md", None, "knowledge"),
        ("csv", "orders.csv", None, "dataset"),
        ("sqlite", "inventory.sqlite3", "inventory", "dataset"),
    ]
    results = []
    for index, (connector_key, source_ref, resource_name, asset_kind) in enumerate(
        cases, 1
    ):
        connection = application.create_connection(
            _context(),
            connector_key=connector_key,
            display_name=source_ref,
            scope="personal",
            configuration={"sourceRef": source_ref},
            secret_ref=None,
            idempotency_key=f"connection-{index}",
            trace_id=f"trace-connection-{index}",
        ).connection
        resource_id = next(
            (
                resource.id
                for resource in connection.discovered_resources
                if resource_name is None or resource.name == resource_name
            ),
            None,
        )
        result = application.ingest(
            _context(),
            connection_id=connection.id,
            resource_id=resource_id,
            recipe_operations=["trim", "deduplicate"],
            idempotency_key=f"ingest-{index}",
            trace_id=f"trace-ingest-{index}",
        )
        results.append(result)

        assert result.status == "succeeded"
        assert result.source_revision.source_digest
        assert result.profile_run.status == "succeeded"
        assert result.cleaning_recipe.version == 1
        assert result.clean_run.status == "succeeded"
        assert result.golden_asset_revision.asset_kind == asset_kind
        assert result.golden_asset_revision.owner.workspace_id == "workspace-a"
        assert result.golden_asset_revision.permissions.can_read is True
        assert result.golden_asset_revision.lineage.source_revision_id == (
            result.source_revision.id
        )
        assert result.golden_asset_revision.trace_id == f"trace-ingest-{index}"
        assert application.golden_data(_context(), result.golden_asset_revision.id).rows

    reopened = _application(tmp_path)
    overview = reopened.data_overview(_context())
    assert len(overview.golden_assets) == 3
    csv_detail = reopened.golden_asset_detail(
        _context(), results[1].golden_asset_revision.asset_id
    )
    assert csv_detail.tabs == [
        "overview",
        "preview",
        "fields",
        "lineage",
        "quality",
        "usage",
    ]
    assert csv_detail.profile.sensitive_fields == ["email"]
    assert csv_detail.preview[0] == {
        "order_id": "A-1",
        "amount": 12.5,
        "email": "[REDACTED]",
    }
    assert (
        application.golden_data(_context(), results[1].golden_asset_revision.id).rows[
            0
        ]["email"]
        == "[REDACTED]"
    )
    assert csv_detail.overview.row_count == 2
    sqlite_detail = reopened.golden_asset_detail(
        _context(), results[2].golden_asset_revision.asset_id
    )
    assert [field.name for field in sqlite_detail.fields] == ["sku", "quantity"]
    assert sqlite_detail.preview[0]["quantity"] == 5


def test_excel_builds_persisted_profile_clean_and_golden_revision(
    tmp_path: Path,
) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "capacity"
    sheet.append(["service", "capacity", "owner_email"])
    sheet.append(["gateway", 12, "infra@example.com"])
    sheet.append(["scheduler", 7, None])
    workbook.save(tmp_path / "capacity.xlsx")
    workbook.close()

    application = _application(tmp_path)
    created = application.create_connection(
        _context(),
        connector_key="excel",
        display_name="Capacity workbook",
        scope="team",
        configuration={
            "sourceRef": "capacity.xlsx",
            "sheetAllowlist": ["capacity"],
        },
        secret_ref=None,
        idempotency_key="excel-create",
        trace_id="trace-excel-create",
    )
    assert [resource.name for resource in created.discovery.resources] == ["capacity"]

    result = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim", "redact"],
        idempotency_key="excel-ingest",
        trace_id="trace-excel-ingest",
    )
    detail = application.golden_asset_detail(
        _context(), result.golden_asset_revision.asset_id
    )

    assert result.source_revision.source_type == "excel"
    assert result.profile_run.row_count == 2
    assert [field.data_type for field in result.profile_run.fields] == [
        "string",
        "integer",
        "string",
    ]
    assert detail.preview[0] == {
        "capacity": 12,
        "owner_email": "[REDACTED]",
        "service": "gateway",
    }


def test_pdf_builds_persisted_profile_clean_and_golden_revision(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "runbook.pdf"
    _write_text_pdf(
        pdf_path,
        [
            "Infrastructure incident runbook",
            "Escalate gateway alerts after five minutes.",
        ],
    )

    application = _application(tmp_path)
    created = application.create_connection(
        _context(),
        connector_key="doc_txt",
        display_name="Incident runbook",
        scope="team",
        configuration={"sourceRef": "runbook.pdf"},
        secret_ref=None,
        idempotency_key="pdf-create",
        trace_id="trace-pdf-create",
    )
    result = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="pdf-ingest",
        trace_id="trace-pdf-ingest",
    )
    detail = application.golden_asset_detail(
        _context(), result.golden_asset_revision.asset_id
    )

    assert result.source_revision.source_type == "pdf"
    assert result.golden_asset_revision.asset_kind == "knowledge"
    assert result.profile_run.row_count == 2
    assert detail.preview == [
        {"page": 1, "text": "Infrastructure incident runbook"},
        {
            "page": 1,
            "text": "Escalate gateway alerts after five minutes.",
        },
    ]


def test_refresh_promotes_only_compatible_success_and_preserves_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "metrics.csv"
    source.write_text("name,value\nfirst,1\n", encoding="utf-8")
    application = _application(tmp_path)
    connection = application.create_connection(
        _context(),
        connector_key="csv",
        display_name="Metrics",
        scope="team",
        configuration={"sourceRef": "metrics.csv"},
        secret_ref=None,
        idempotency_key="metrics-connection",
        trace_id="trace-metrics-connection",
    ).connection
    first = application.ingest(
        _context(),
        connection_id=connection.id,
        resource_id=connection.discovered_resources[0].id,
        recipe_operations=["trim", "deduplicate"],
        idempotency_key="metrics-ingest",
        trace_id="trace-metrics-ingest",
    ).golden_asset_revision

    source.write_text("name,value\nsecond,2\n", encoding="utf-8")
    refreshed = application.refresh(
        _context(),
        asset_id=first.asset_id,
        idempotency_key="refresh-two",
        trace_id="trace-refresh-two",
    )
    assert refreshed.run.status == "succeeded"
    assert refreshed.run.previous_revision_id == first.id
    assert refreshed.run.promoted_revision_id == refreshed.golden_asset_revision.id
    assert refreshed.run.staging_ref.sha256 == (
        refreshed.golden_asset_revision.storage_ref.sha256
    )
    assert refreshed.golden_asset_revision.revision == 2
    assert refreshed.golden_asset_revision.id != first.id
    assert application.golden_revision(_context(), first.id).id == first.id
    assert (
        application.golden_asset_detail(_context(), first.asset_id).preview[0]["name"]
        == "second"
    )

    source.write_text("name,value,unit\nthird,3,kg\n", encoding="utf-8")
    drifted = application.refresh(
        _context(),
        asset_id=first.asset_id,
        idempotency_key="refresh-drift",
        trace_id="trace-refresh-drift",
    )
    assert drifted.run.status == "schema_drift"
    assert drifted.run.reason.code == "SCHEMA_DRIFT"
    assert drifted.golden_asset_revision is None
    assert drifted.last_good_revision.id == refreshed.golden_asset_revision.id

    source.write_bytes(b"\xff\xfe")
    failed = application.refresh(
        _context(),
        asset_id=first.asset_id,
        idempotency_key="refresh-failed",
        trace_id="trace-refresh-failed",
    )
    assert failed.run.status == "failed"
    assert failed.run.reason.code == "SOURCE_READ_FAILED"
    assert failed.last_good_revision.id == refreshed.golden_asset_revision.id

    retry = application.retry_refresh(
        _context(),
        failed_run_id=failed.run.id,
        idempotency_key="refresh-retry",
        trace_id="trace-refresh-retry",
    )
    assert retry.run.status == "failed"
    assert retry.run.retry_of == failed.run.id

    cancelled = application.cancel_refresh(
        _context(),
        asset_id=first.asset_id,
        idempotency_key="refresh-cancel",
        trace_id="trace-refresh-cancel",
    )
    assert cancelled.status == "cancelled"
    assert cancelled.previous_revision_id == refreshed.golden_asset_revision.id
    assert (
        application.golden_asset_detail(_context(), first.asset_id).asset.id
        == refreshed.golden_asset_revision.id
    )

    replay = application.refresh(
        _context(),
        asset_id=first.asset_id,
        idempotency_key="refresh-drift",
        trace_id="another-trace-is-ignored",
    )
    assert replay.run.id == drifted.run.id


def test_retry_refresh_authorizes_asset_before_exposing_run_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "personal-refresh.csv"
    source.write_text("name,value\nfirst,1\n", encoding="utf-8")
    application = _application(tmp_path)
    connection = application.create_connection(
        _context(),
        connector_key="csv",
        display_name="Personal refresh",
        scope="personal",
        configuration={"sourceRef": source.name},
        secret_ref=None,
        idempotency_key="personal-refresh-connection",
        trace_id="trace-personal-refresh-connection",
    ).connection
    ingested = application.ingest(
        _context(),
        connection_id=connection.id,
        resource_id=connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="personal-refresh-ingest",
        trace_id="trace-personal-refresh-ingest",
    )
    succeeded = application.refresh(
        _context(),
        asset_id=ingested.golden_asset_revision.asset_id,
        idempotency_key="personal-refresh-run",
        trace_id="trace-personal-refresh-run",
    )
    assert succeeded.run.status == "succeeded"

    with pytest.raises(SourcesGoldenError) as captured:
        application.retry_refresh(
            _context(principal_id="user-2"),
            failed_run_id=succeeded.run.id,
            idempotency_key="unauthorized-retry",
            trace_id="trace-unauthorized-retry",
        )

    assert captured.value.code == "PERMISSION_DENIED"


def test_workspace_isolation_and_revoke_hide_connection_and_asset(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.md").write_text("workspace secret\n", encoding="utf-8")
    application = _application(tmp_path)
    connection = application.create_connection(
        _context(),
        connector_key="local_file",
        display_name="Notes",
        scope="personal",
        configuration={"sourceRef": "notes.md"},
        secret_ref=None,
        idempotency_key="notes-connection",
        trace_id="trace-notes-connection",
    ).connection
    asset = application.ingest(
        _context(),
        connection_id=connection.id,
        resource_id=connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="notes-ingest",
        trace_id="trace-notes-ingest",
    ).golden_asset_revision

    with pytest.raises(SourcesGoldenError, match="authenticated workspace"):
        application.connection_detail(
            _context(workspace_id="workspace-b"), connection.id
        )
    with pytest.raises(SourcesGoldenError, match="authenticated workspace"):
        application.golden_asset_detail(
            _context(workspace_id="workspace-b"), asset.asset_id
        )
    with pytest.raises(SourcesGoldenError, match="permission"):
        application.revoke_connection(
            _context(role="viewer"),
            connection.id,
            reason="not allowed",
            trace_id="trace-denied",
        )

    application.revoke_connection(
        _context(),
        connection.id,
        reason="source permission removed",
        trace_id="trace-revoke",
    )
    assert application.data_overview(_context()).connections == []
    assert application.data_overview(_context()).golden_assets == []
    with pytest.raises(SourcesGoldenError, match="authenticated workspace"):
        application.golden_asset_detail(_context(), asset.asset_id)
    with pytest.raises(SourcesGoldenError, match="authenticated workspace"):
        application.source_revision(_context(), asset.lineage.source_revision_id)


def test_personal_sources_are_principal_isolated_and_team_sources_are_shared(
    tmp_path: Path,
) -> None:
    (tmp_path / "personal.md").write_text("private notes\n", encoding="utf-8")
    (tmp_path / "team.md").write_text("team notes\n", encoding="utf-8")
    application = _application(tmp_path)
    personal = application.create_connection(
        _context(),
        connector_key="local_file",
        display_name="Personal notes",
        scope="personal",
        configuration={"sourceRef": "personal.md"},
        secret_ref=None,
        idempotency_key="personal-connection",
        trace_id="trace-personal-connection",
    ).connection
    personal_result = application.ingest(
        _context(),
        connection_id=personal.id,
        resource_id=personal.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="personal-ingest",
        trace_id="trace-personal-ingest",
    )
    team = application.create_connection(
        _context(),
        connector_key="local_file",
        display_name="Team notes",
        scope="team",
        configuration={"sourceRef": "team.md"},
        secret_ref=None,
        idempotency_key="team-connection",
        trace_id="trace-team-connection",
    ).connection

    other = _context(principal_id="user-2")
    assert [item.id for item in application.data_overview(other).connections] == [
        team.id
    ]
    with pytest.raises(SourcesGoldenError, match="authenticated principal"):
        application.connection_detail(other, personal.id)
    with pytest.raises(SourcesGoldenError, match="authenticated principal"):
        application.golden_asset_detail(
            other, personal_result.golden_asset_revision.asset_id
        )
    with pytest.raises(SourcesGoldenError, match="authenticated principal"):
        application.source_revision(other, personal_result.source_revision.id)
    with pytest.raises(SourcesGoldenError, match="authenticated principal"):
        application.ingest(
            other,
            connection_id=personal.id,
            resource_id=personal.discovered_resources[0].id,
            recipe_operations=["trim"],
            idempotency_key="other-ingest",
            trace_id="trace-other-ingest",
        )


def test_add_data_and_bootstrap_bind_real_read_models(tmp_path: Path) -> None:
    application = _application(tmp_path)
    add_data = application.add_data(_context(), connector_key="postgresql")
    assert add_data.view == "add_data"
    assert add_data.selected_connector.connector_key == "postgresql"
    assert add_data.steps == ["configure", "authorize", "discover", "save"]
    assert add_data.blocked_reason.code == "CREDENTIAL_REQUIRED"
    assert (
        application.add_data(_context(role="viewer"), connector_key="csv").can_create
        is False
    )

    bootstrap = application.bootstrap_projection(_context())
    assert bootstrap["routes"] == [
        "data_overview",
        "add_data",
        "connector_catalog",
    ]
    assert len(bootstrap["workspaceData"]["connectorCatalog"]) == 37
    item = next(
        item
        for item in bootstrap["workspaceData"]["connectorCatalog"]
        if item["connectorKey"] == "postgresql"
    )
    assert item["category"] == "db"
    assert item["inputSchema"]["host"] == "string"
    assert item["credentialSchema"] == {"secretRef": "secret_ref"}
    assert item["capabilityState"] == "credential_blocked"
    assert item["reason"]["code"] == "CREDENTIAL_REQUIRED"
    assert bootstrap["connections"] == []


def test_remote_mcp_contract_is_credential_blocked_without_claiming_success(
    tmp_path: Path,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "remote-mcp.sqlite3",
        artifact_root=tmp_path / "remote-artifacts",
        source_root=tmp_path,
        web_resolver=lambda _host: ["93.184.216.34"],
    )
    result = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Remote MCP",
        scope="team",
        configuration={
            "transport": "streamable_http",
            "endpoint": "https://mcp.example/tools",
            "toolAllowlist": ["infrastructure.metrics"],
        },
        secret_ref="secret://workspace-a/remote-mcp",
        idempotency_key="remote-mcp",
        trace_id="trace-remote-mcp",
    )

    assert result.connection.status == "credential_blocked"
    assert result.validation.status == "credential_blocked"
    assert result.discovery.resources == []
    assert result.discovery.reason.code == "PROVIDER_EXECUTION_BLOCKED"


def test_input_revisions_are_distinct_and_each_revision_is_replayable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "versions.md"
    source.write_text("version one\n", encoding="utf-8")
    application = _application(tmp_path)
    connection = application.create_connection(
        _context(),
        connector_key="local_file",
        display_name="Versions",
        scope="personal",
        configuration={"sourceRef": "versions.md"},
        secret_ref=None,
        idempotency_key="versions-connection",
        trace_id="trace-versions-connection",
    ).connection
    first = application.ingest(
        _context(),
        connection_id=connection.id,
        resource_id=connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="versions-one",
        trace_id="trace-versions-one",
    )
    source.write_text("version two\n", encoding="utf-8")
    second = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="versions-two",
        trace_id="trace-versions-two",
    )

    assert second.run.status == "succeeded"
    assert second.golden_asset_revision.lineage.source_revision_id != (
        first.source_revision.id
    )
    assert second.golden_asset_revision.storage_ref.sha256 != (
        first.golden_asset_revision.storage_ref.sha256
    )
    first_replay = application.golden_revision(
        _context(), first.golden_asset_revision.id
    )
    assert application.golden_data(_context(), first_replay.id).rows == [
        {"text": "version one"}
    ]
    second_replay = application.golden_revision(
        _context(), second.golden_asset_revision.id
    )
    assert application.golden_data(_context(), second_replay.id).rows == [
        {"text": "version two"}
    ]


def test_main_and_w2_consumer_contract_uses_pinned_authorized_revision(
    tmp_path: Path,
) -> None:
    contract_path = (
        Path(__file__).parents[2]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "step3-w1-ui-consumer-contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    (tmp_path / "metrics.csv").write_text(
        "service,latency_ms\ngateway,42\n", encoding="utf-8"
    )
    application = _application(tmp_path)
    connection = application.create_connection(
        _context(),
        connector_key="csv",
        display_name="Service metrics",
        scope="team",
        configuration={"sourceRef": "metrics.csv"},
        secret_ref=None,
        idempotency_key="consumer-create",
        trace_id="trace-consumer-create",
    ).connection
    ingested = application.ingest(
        _context(),
        connection_id=connection.id,
        resource_id=connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="consumer-ingest",
        trace_id="trace-consumer-ingest",
    )
    revision_id = ingested.golden_asset_revision.id
    projections = {
        "bootstrap": application.bootstrap_projection(_context()),
        "data_overview": application.data_overview(_context()).model_dump(
            mode="json", by_alias=True
        ),
        "add_data": application.add_data(_context(), connector_key="csv").model_dump(
            mode="json", by_alias=True
        ),
        "connection_detail": application.connection_detail(
            _context(), connection.id
        ).model_dump(mode="json", by_alias=True),
        "golden_asset_detail": application.golden_asset_detail(
            _context(), ingested.golden_asset_revision.asset_id
        ).model_dump(mode="json", by_alias=True),
        "golden_data": application.golden_data(_context(), revision_id).model_dump(
            mode="json", by_alias=True
        ),
        "w2_resource_binding": application.golden_resource_binding(
            _context(), revision_id
        ).model_dump(mode="json", by_alias=True),
    }

    for projection, required_paths in contract["requiredFields"].items():
        assert all(_has_path(projections[projection], path) for path in required_paths)
    binding = projections["w2_resource_binding"]
    assert binding["kind"] == "golden_asset"
    assert binding["objectId"] == ingested.golden_asset_revision.asset_id
    assert binding["revision"] == revision_id
    assert binding["providerRevision"] == ingested.source_revision.id
    assert binding["contentDigest"] == ingested.source_revision.source_digest
    assert binding["permissions"]["workspaceId"] == "workspace-a"
    assert projections["golden_data"]["rows"] == [
        {"latency_ms": 42, "service": "gateway"}
    ]


def test_local_file_security_and_idempotency_are_enforced(tmp_path: Path) -> None:
    (tmp_path / "safe.csv").write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "binary.csv").write_bytes(b"id\n\x00\n")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.csv"
    outside.write_text("id\n9\n", encoding="utf-8")
    (tmp_path / "linked.csv").symlink_to(outside)
    application = _application(tmp_path)

    first = application.create_connection(
        _context(),
        connector_key="csv",
        display_name="Safe",
        scope="personal",
        configuration={"sourceRef": "safe.csv"},
        secret_ref=None,
        idempotency_key="same-create",
        trace_id="trace-one",
    )
    replay = application.create_connection(
        _context(),
        connector_key="csv",
        display_name="Ignored",
        scope="personal",
        configuration={"sourceRef": "safe.csv"},
        secret_ref=None,
        idempotency_key="same-create",
        trace_id="trace-two",
    )
    assert replay.replayed is True
    assert replay.connection.id == first.connection.id
    assert replay.connection.display_name == "Safe"
    ingested = application.ingest(
        _context(),
        connection_id=first.connection.id,
        resource_id=first.connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="same-ingest",
        trace_id="trace-ingest-one",
    )
    ingest_replay = application.ingest(
        _context(),
        connection_id=first.connection.id,
        resource_id=first.connection.discovered_resources[0].id,
        recipe_operations=["redact"],
        idempotency_key="same-ingest",
        trace_id="trace-ingest-two",
    )
    assert ingest_replay.replayed is True
    assert ingest_replay.golden_asset_revision.id == ingested.golden_asset_revision.id

    for name, message in [
        ("../" + outside.name, "escapes"),
        ("linked.csv", "symlinks"),
        ("binary.csv", "binary"),
    ]:
        with pytest.raises((SourcesGoldenError, ValueError), match=message):
            application.create_connection(
                _context(),
                connector_key="csv",
                display_name=name,
                scope="personal",
                configuration={"sourceRef": name},
                secret_ref=None,
                idempotency_key=f"unsafe-{name}",
                trace_id=f"trace-{name}",
            )


def test_unknown_fields_and_invalid_roles_fail_closed(tmp_path: Path) -> None:
    application = _application(tmp_path)
    with pytest.raises(SourcesGoldenError, match="Fields are not valid"):
        application.create_connection(
            _context(),
            connector_key="csv",
            display_name="Wrong form",
            scope="personal",
            configuration={"sourceRef": "rows.csv", "host": "db.internal"},
            secret_ref=None,
            idempotency_key="wrong-form",
            trace_id="trace-wrong-form",
        )
    with pytest.raises(SourcesGoldenError, match="permission"):
        application.create_connection(
            _context(role="viewer"),
            connector_key="csv",
            display_name="Denied",
            scope="personal",
            configuration={"sourceRef": "rows.csv"},
            secret_ref=None,
            idempotency_key="denied",
            trace_id="trace-denied",
        )


def test_fixture_stdio_mcp_calls_feed_source_and_golden_revisions(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "habitat-readings.json"
    data_path.write_text(
        json.dumps(
            [
                {"station": "wetland-a", "temperature": 18.2},
                {"station": "forest-b", "temperature": 16.7},
            ]
        ),
        encoding="utf-8",
    )
    server = (
        Path(__file__).parents[2]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "mcp_habitat_server.py"
    ).resolve()
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
        secret_resolver=lambda ref: (
            "resolved-only-in-child" if ref == "secret://workspace-a/mcp-test" else None
        ),
    )
    created = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Habitat MCP",
        scope="team",
        configuration={
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(server)],
            "env": {
                "MCP_FIXTURE_DATA_PATH": str(data_path),
                "MCP_SECRET_TOKEN": "secret://workspace-a/mcp-test",
            },
            "cwd": str(tmp_path),
            "startupTimeoutSeconds": 2,
            "callTimeoutSeconds": 2,
            "toolAllowlist": ["habitat.readings"],
            "outputBytes": 1_000_000,
        },
        secret_ref=None,
        idempotency_key="mcp-create",
        trace_id="trace-mcp-create",
    )
    assert created.connection.status == "ready"
    assert [item.name for item in created.discovery.resources] == ["habitat.readings"]

    first = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        tool_arguments={"region": "all"},
        idempotency_key="mcp-ingest-one",
        trace_id="trace-mcp-call-one",
    )
    assert first.source_revision.source_type == "mcp"
    assert first.golden_asset_revision.asset_kind == "dataset"
    first_detail = application.golden_asset_detail(
        _context(), first.golden_asset_revision.asset_id
    )
    assert first_detail.preview[0]["station"] == "wetland-a"
    assert first_detail.preview[0]["secretEcho"] == "[REDACTED]"

    data_path.write_text(
        json.dumps(
            [
                {"station": "wetland-a", "temperature": 19.1},
                {"station": "forest-b", "temperature": 16.7},
            ]
        ),
        encoding="utf-8",
    )
    second = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="mcp-refresh-two",
        trace_id="trace-mcp-call-two",
    )
    assert second.run.status == "succeeded"
    assert second.golden_asset_revision.revision == 2
    assert second.golden_asset_revision.storage_ref.sha256 != (
        first.golden_asset_revision.storage_ref.sha256
    )
    assert second.golden_asset_revision.lineage.source_revision_id != (
        first.source_revision.id
    )

    traces = application.mcp_process_traces(_context(), created.connection.id)
    assert (
        sum(
            exchange.method == "tools/call"
            for trace in traces
            for exchange in trace.exchanges
        )
        == 2
    )
    assert all(trace.pid != os.getpid() and trace.pid > 0 for trace in traces)
    assert all(
        {
            "initialize",
            "notifications/initialized",
            "tools/list",
            "shutdown",
        }
        <= {exchange.method for exchange in trace.exchanges}
        for trace in traces
    )
    serialized = json.dumps(
        [trace.model_dump(mode="json", by_alias=True) for trace in traces]
    )
    assert "resolved-only-in-child" not in serialized
    assert "MCP_SECRET_TOKEN" not in serialized
    assert all(
        b"resolved-only-in-child" not in path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )


def test_official_sdk_stdio_mcp_cross_implementation_and_dynamic_revisions(
    tmp_path: Path,
) -> None:
    from importlib.metadata import version

    assert version("mcp") == "1.26.0"
    data_path = tmp_path / "infrastructure-metrics.json"
    data_path.write_text(
        json.dumps(
            [
                {
                    "service": "search",
                    "cpuPercent": 41.2,
                    "dataAsOf": "2026-08-25T08:00:00Z",
                },
                {
                    "service": "indexer",
                    "cpuPercent": 63.1,
                    "dataAsOf": "2026-08-25T08:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    server = (
        Path(__file__).parents[2]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "mcp_sdk_infrastructure_server.py"
    ).resolve()
    application = SourceGoldenApplication(
        database_path=tmp_path / "official-sdk.sqlite3",
        artifact_root=tmp_path / "official-artifacts",
        source_root=tmp_path,
    )
    command = {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(server)],
        "env": {"MCP_FIXTURE_DATA_PATH": str(data_path)},
        "cwd": str(tmp_path),
        "startupTimeoutSeconds": 5,
        "callTimeoutSeconds": 5,
        "toolAllowlist": ["infrastructure.metrics"],
        "outputBytes": 1_000_000,
    }
    created = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Infrastructure metrics",
        scope="team",
        configuration=command,
        secret_ref=None,
        idempotency_key="official-sdk-create",
        trace_id="trace-official-initialize",
    )
    tool = created.discovery.resources[0]
    assert tool.name == "infrastructure.metrics"
    assert tool.input_schema["type"] == "object"
    assert tool.output_schema["type"] == "object"
    first = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=tool.id,
        recipe_operations=["trim"],
        tool_arguments={"service": "all"},
        idempotency_key="official-sdk-call-one",
        trace_id="trace-official-call-one",
    )
    first_detail = application.golden_asset_detail(
        _context(), first.golden_asset_revision.asset_id
    )
    assert first_detail.preview[0]["cpuPercent"] == 41.2
    assert first_detail.preview[0]["dataAsOf"] == "2026-08-25T08:00:00Z"

    data_path.write_text(
        json.dumps(
            [
                {
                    "service": "search",
                    "cpuPercent": 52.8,
                    "dataAsOf": "2026-08-25T08:05:00Z",
                },
                {
                    "service": "indexer",
                    "cpuPercent": 63.1,
                    "dataAsOf": "2026-08-25T08:05:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    second = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="official-sdk-call-two",
        trace_id="trace-official-call-two",
    )
    second_detail = application.golden_asset_detail(
        _context(), first.golden_asset_revision.asset_id
    )
    assert second.run.status == "succeeded"
    assert second_detail.preview[0]["cpuPercent"] == 52.8
    assert second_detail.preview[0]["dataAsOf"] == "2026-08-25T08:05:00Z"
    assert first.source_revision.id != (
        second.golden_asset_revision.lineage.source_revision_id
    )
    assert first.source_revision.source_digest != (
        application.source_revision(
            _context(),
            second.golden_asset_revision.lineage.source_revision_id,
        ).source_digest
    )
    assert first.golden_asset_revision.id != second.golden_asset_revision.id
    assert first.golden_asset_revision.storage_ref.sha256 != (
        second.golden_asset_revision.storage_ref.sha256
    )
    assert first.golden_asset_revision.freshness_at != (
        second.golden_asset_revision.freshness_at
    )
    assert first.golden_asset_revision.data_as_of == "2026-08-25T08:00:00Z"
    assert second.golden_asset_revision.data_as_of == "2026-08-25T08:05:00Z"

    traces = application.mcp_process_traces(_context(), created.connection.id)
    assert len(traces) == 3
    assert all(
        trace.server_name == "repository-infrastructure-metrics" for trace in traces
    )
    assert all(trace.protocol_version == "2025-11-25" for trace in traces)
    assert all(trace.exit_code == 0 for trace in traces)
    assert all(trace.process_reaped is True for trace in traces)
    assert all(trace.shell is False for trace in traces)
    assert all(trace.shutdown_mode == "stdio_eof" for trace in traces)
    assert all(trace.pid != os.getpid() for trace in traces)
    assert [trace.correlation_id for trace in traces] == [
        "trace-official-initialize",
        "trace-official-call-one",
        "trace-official-call-two",
    ]
    assert (
        sum(
            exchange.method == "tools/call"
            for trace in traces
            for exchange in trace.exchanges
        )
        == 2
    )
    assert all(not _pid_is_alive(trace.pid) for trace in traces)
    assert first.golden_asset_revision.lineage.adapter_run_id == traces[1].id
    assert first.golden_asset_revision.lineage.correlation_id == (
        "trace-official-call-one"
    )
    assert first.golden_asset_revision.lineage.content_digest == (
        first.source_revision.source_digest
    )
    second_source = application.source_revision(
        _context(),
        second.golden_asset_revision.lineage.source_revision_id,
    )
    assert second.golden_asset_revision.lineage.adapter_run_id == traces[2].id
    assert second.golden_asset_revision.lineage.content_digest == (
        second_source.source_digest
    )

    data_path.write_text(
        json.dumps(
            [
                {
                    "service": "search",
                    "cpuPercent": 52.8,
                    "queueDepth": 3,
                    "dataAsOf": "2026-08-25T08:10:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    drifted = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="official-sdk-schema-drift",
        trace_id="trace-official-schema-drift",
    )
    assert drifted.run.status == "schema_drift"
    assert drifted.golden_asset_revision is None
    assert drifted.last_good_revision.id == second.golden_asset_revision.id


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("hang_initialize", "MCP_TIMEOUT"),
        ("exit_initialize", "MCP_PROCESS_EXITED"),
        ("invalid_initialize", "MCP_INVALID_MESSAGE"),
        ("oversize_stderr", "MCP_OUTPUT_LIMIT"),
        ("outside_allowlist", "MCP_TOOL_NOT_ALLOWED"),
        ("hang_after_shutdown", "MCP_TIMEOUT"),
    ],
)
def test_stdio_mcp_startup_failures_are_typed_and_persisted(
    tmp_path: Path, mode: str, expected_code: str
) -> None:
    application, config = _mcp_failure_application(tmp_path, mode)
    with pytest.raises(SourcesGoldenError) as captured:
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name=f"Failure {mode}",
            scope="personal",
            configuration=config,
            secret_ref=None,
            idempotency_key=f"create-{mode}",
            trace_id=f"trace-{mode}",
        )
    assert captured.value.code == expected_code
    traces = application.mcp_process_traces_for_workspace(_context())
    assert traces[-1].status in {"failed", "timed_out"}
    assert traces[-1].exit_code != 0
    assert traces[-1].process_reaped is True
    assert not _pid_is_alive(traces[-1].pid)


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("hang_tool", "MCP_TIMEOUT"),
        ("tool_error", "MCP_TOOL_FAILED"),
        ("oversize_tool", "MCP_OUTPUT_LIMIT"),
    ],
)
def test_stdio_mcp_tool_failures_do_not_create_revisions(
    tmp_path: Path, mode: str, expected_code: str
) -> None:
    application, config = _mcp_failure_application(tmp_path, mode)
    connection = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name=f"Failure {mode}",
        scope="personal",
        configuration=config,
        secret_ref=None,
        idempotency_key=f"create-{mode}",
        trace_id=f"trace-create-{mode}",
    ).connection
    with pytest.raises(SourcesGoldenError) as captured:
        application.ingest(
            _context(),
            connection_id=connection.id,
            resource_id=connection.discovered_resources[0].id,
            recipe_operations=["trim"],
            tool_arguments={},
            idempotency_key=f"ingest-{mode}",
            trace_id=f"trace-call-{mode}",
        )
    assert captured.value.code == expected_code
    assert application.data_overview(_context()).golden_assets == []
    assert "resolved-only-in-child" not in str(captured.value)
    trace = application.mcp_process_traces(_context(), connection.id)[-1]
    assert trace.process_reaped is True
    assert not _pid_is_alive(trace.pid)


def test_stdio_mcp_rejects_inline_sensitive_environment_before_spawn(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")
    config["env"]["MCP_SECRET_TOKEN"] = "plaintext-super-secret"

    with pytest.raises(SourcesGoldenError) as captured:
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name="Unsafe environment",
            scope="personal",
            configuration=config,
            secret_ref=None,
            idempotency_key="unsafe-environment",
            trace_id="trace-unsafe-environment",
        )

    assert captured.value.code == "MCP_CONFIGURATION_INVALID"
    assert "plaintext-super-secret" not in str(captured.value)
    assert application.mcp_process_traces_for_workspace(_context()) == []
    assert (
        b"plaintext-super-secret"
        not in (tmp_path / "sources-golden-normal.sqlite3").read_bytes()
    )


def test_secret_references_are_workspace_bound_and_tool_secrets_are_rejected(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")

    with pytest.raises(SourcesGoldenError) as cross_workspace:
        application.create_connection(
            _context(),
            connector_key="postgresql",
            display_name="Cross-workspace secret",
            scope="team",
            configuration={
                "host": "db.example",
                "port": 5432,
                "database": "analytics",
            },
            secret_ref="secret://workspace-b/postgresql",
            idempotency_key="cross-workspace-secret",
            trace_id="trace-cross-workspace-secret",
        )
    assert cross_workspace.value.code == "INVALID_SECRET_REFERENCE"

    connection = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="MCP argument security",
        scope="personal",
        configuration=config,
        secret_ref=None,
        idempotency_key="mcp-argument-security",
        trace_id="trace-mcp-argument-security",
    ).connection
    with pytest.raises(SourcesGoldenError) as inline_tool_secret:
        application.ingest(
            _context(),
            connection_id=connection.id,
            resource_id=connection.discovered_resources[0].id,
            recipe_operations=["trim"],
            tool_arguments={"apiToken": "plaintext-super-secret"},
            idempotency_key="inline-tool-secret",
            trace_id="trace-inline-tool-secret",
        )
    assert inline_tool_secret.value.code == "INLINE_SECRET_REJECTED"
    assert "plaintext-super-secret" not in str(inline_tool_secret.value)
    assert (
        b"plaintext-super-secret"
        not in (tmp_path / "sources-golden-normal.sqlite3").read_bytes()
    )


def test_stdio_mcp_accepts_server_notifications_before_responses(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(
        tmp_path, "notification_before_tools"
    )

    created = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Notification-compatible MCP",
        scope="personal",
        configuration=config,
        secret_ref=None,
        idempotency_key="notification-compatible",
        trace_id="trace-notification-compatible",
    )

    assert created.connection.status == "ready"
    assert [resource.name for resource in created.discovery.resources] == [
        "habitat.readings"
    ]
    trace = application.mcp_process_traces(_context(), created.connection.id)[0]
    assert trace.process_reaped is True
    assert not _pid_is_alive(trace.pid)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"cwd": ".."}, "MCP_CONFIGURATION_INVALID"),
        (
            {"args": ["--token=plaintext-super-secret"]},
            "MCP_CONFIGURATION_INVALID",
        ),
        (
            {"args": ["--token", "plaintext-super-secret"]},
            "MCP_CONFIGURATION_INVALID",
        ),
    ],
)
def test_stdio_mcp_rejects_unsafe_process_configuration_before_spawn(
    tmp_path: Path,
    mutation: dict[str, object],
    expected_code: str,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")
    config.update(mutation)

    with pytest.raises(SourcesGoldenError) as captured:
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name="Unsafe MCP",
            scope="personal",
            configuration=config,
            secret_ref=None,
            idempotency_key="unsafe-process-configuration",
            trace_id="trace-unsafe-process-configuration",
        )

    assert captured.value.code == expected_code
    assert "plaintext-super-secret" not in str(captured.value)
    assert application.mcp_process_traces_for_workspace(_context()) == []


def test_stdio_mcp_missing_command_fails_before_trace_persistence(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")
    config["command"] = str(tmp_path / "missing-mcp-executable")

    with pytest.raises(SourcesGoldenError) as captured:
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name="Missing MCP",
            scope="personal",
            configuration=config,
            secret_ref=None,
            idempotency_key="missing-mcp",
            trace_id="trace-missing-mcp",
        )

    assert captured.value.code == "MCP_PROCESS_START_FAILED"
    assert application.mcp_process_traces_for_workspace(_context()) == []


def test_stdio_mcp_missing_command_after_discovery_is_a_stable_ingest_error(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")
    executable = tmp_path / "ephemeral-python"
    executable.symlink_to(sys.executable)
    config["command"] = str(executable)
    connection = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Ephemeral MCP",
        scope="personal",
        configuration=config,
        secret_ref=None,
        idempotency_key="ephemeral-mcp",
        trace_id="trace-ephemeral-discovery",
    ).connection
    executable.unlink()

    with pytest.raises(SourcesGoldenError) as captured:
        application.ingest(
            _context(),
            connection_id=connection.id,
            resource_id=connection.discovered_resources[0].id,
            recipe_operations=["trim"],
            tool_arguments={},
            idempotency_key="ephemeral-ingest",
            trace_id="trace-ephemeral-ingest",
        )

    assert captured.value.code == "MCP_PROCESS_START_FAILED"
    assert application.data_overview(_context()).golden_assets == []
    assert len(application.mcp_process_traces(_context(), connection.id)) == 1


def test_stdio_mcp_missing_command_on_refresh_preserves_last_good(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")
    executable = tmp_path / "refresh-python"
    executable.symlink_to(sys.executable)
    config["command"] = str(executable)
    connection = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Refresh MCP",
        scope="personal",
        configuration=config,
        secret_ref=None,
        idempotency_key="refresh-mcp",
        trace_id="trace-refresh-discovery",
    ).connection
    first = application.ingest(
        _context(),
        connection_id=connection.id,
        resource_id=connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        tool_arguments={},
        idempotency_key="refresh-mcp-first",
        trace_id="trace-refresh-first",
    )
    executable.unlink()

    failed = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="refresh-mcp-missing-command",
        trace_id="trace-refresh-missing-command",
    )

    assert failed.run.status == "failed"
    assert failed.run.reason.code == "MCP_PROCESS_START_FAILED"
    assert failed.run.reason.retryable is True
    assert failed.last_good_revision.id == first.golden_asset_revision.id
    assert failed.golden_asset_revision is None
    assert len(application.mcp_process_traces(_context(), connection.id)) == 2


def test_remote_mcp_rejects_private_endpoint(tmp_path: Path) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "private-remote-mcp.sqlite3",
        artifact_root=tmp_path / "private-remote-artifacts",
        source_root=tmp_path,
        web_resolver=lambda _host: ["127.0.0.1"],
    )

    with pytest.raises(SourcesGoldenError, match="non-public"):
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name="Private remote MCP",
            scope="team",
            configuration={
                "transport": "streamable_http",
                "endpoint": "https://mcp.internal/tools",
                "toolAllowlist": ["infrastructure.metrics"],
            },
            secret_ref="secret://workspace-a/remote-mcp",
            idempotency_key="private-remote-mcp",
            trace_id="trace-private-remote-mcp",
        )


def test_connection_input_is_rejected_before_mcp_process_start(
    tmp_path: Path,
) -> None:
    application, config = _mcp_failure_application(tmp_path, "normal")

    with pytest.raises(SourcesGoldenError) as captured:
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name=" ",
            scope="invalid",
            configuration=config,
            secret_ref=None,
            idempotency_key="invalid-instance-fields",
            trace_id="trace-invalid-instance-fields",
        )

    assert captured.value.code == "INVALID_CONNECTION"
    assert application.mcp_process_traces_for_workspace(_context()) == []


def _mcp_failure_application(
    tmp_path: Path, mode: str
) -> tuple[SourceGoldenApplication, dict[str, object]]:
    data_path = tmp_path / "habitat-readings.json"
    data_path.write_text("[]", encoding="utf-8")
    server = (
        Path(__file__).parents[2]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "mcp_habitat_server.py"
    ).resolve()
    application = SourceGoldenApplication(
        database_path=tmp_path / f"sources-golden-{mode}.sqlite3",
        artifact_root=tmp_path / f"artifacts-{mode}",
        source_root=tmp_path,
        secret_resolver=lambda ref: (
            "resolved-only-in-child" if ref == "secret://workspace-a/mcp-test" else None
        ),
    )
    return application, {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(server)],
        "env": {
            "MCP_FIXTURE_DATA_PATH": str(data_path),
            "MCP_FIXTURE_MODE": mode,
            "MCP_SECRET_TOKEN": "secret://workspace-a/mcp-test",
        },
        "cwd": str(tmp_path),
        "startupTimeoutSeconds": 0.05 if mode == "hang_initialize" else 2,
        "callTimeoutSeconds": (
            0.05 if mode in {"hang_tool", "hang_after_shutdown"} else 2
        ),
        "toolAllowlist": (
            ["other.tool"] if mode == "outside_allowlist" else ["habitat.readings"]
        ),
        "outputBytes": (
            1_024 if mode in {"oversize_stderr", "oversize_tool"} else 1_000_000
        ),
    }


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    time.sleep(0.01)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _has_path(value: object, path: str) -> bool:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _write_text_pdf(path: Path, lines: list[str]) -> None:
    escaped = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        for line in lines
    ]
    drawing = ["BT", "/F1 12 Tf", "72 760 Td"]
    for index, line in enumerate(escaped):
        if index:
            drawing.append("0 -20 Td")
        drawing.append(f"({line}) Tj")
    drawing.append("ET")
    stream = ("\n".join(drawing) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"endstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, body in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{object_number} 0 obj\n".encode("ascii"))
        document.extend(body)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(document)
