from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TypedDict, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import JsonValue

from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    GoldenContextReference,
    SourceGoldenApplication,
    SourcesGoldenError,
    provider_adapters,
)
from frontend.server.knowledge_assets.sources_golden.connector_adapter import (
    ConnectorAdapter,
    ConnectorAdapterError,
    ConnectorExecutionPolicy,
    ConnectorRequest,
)
from frontend.server.knowledge_assets.sources_golden.connector_registry import (
    SqlConnectorAdapter,
)
from frontend.server.knowledge_assets.sources_golden.database_adapter import (
    SqlDatabaseAdapter,
)
from frontend.server.knowledge_assets.sources_golden.http_transport import (
    SecureHttpTransport,
)
from frontend.server.knowledge_assets.sources_golden.models import DiscoveredResource


def _context() -> AccessContext:
    return AccessContext(
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        role="editor",
    )


def _application(root: Path) -> SourceGoldenApplication:
    return SourceGoldenApplication(
        database_path=root / "sources-golden.sqlite3",
        artifact_root=root / "artifacts",
        source_root=root / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
    )


def _unused_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


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


def test_all_37_catalog_entries_have_a_formal_callable_adapter(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    catalog_keys = {
        definition.connector_key
        for definition in application.connector_catalog(_context()).connectors
    }

    adapters = application.connector_adapters()

    assert len(adapters) == 37
    assert set(adapters) == catalog_keys
    for connector_key, adapter in adapters.items():
        assert isinstance(adapter, ConnectorAdapter), connector_key
        assert connector_key in adapter.connector_keys
        for stage in (
            "validate",
            "authenticate",
            "authorize",
            "discover",
            "introspect",
            "sample",
            "read",
            "ingest",
            "profile",
            "clean",
            "golden",
            "refresh",
            "checkpoint",
            "close",
        ):
            assert callable(getattr(adapter, stage)), (connector_key, stage)


def test_all_37_adapters_reject_invalid_configuration_with_typed_errors(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)

    for connector_key, adapter in application.connector_adapters().items():
        request = ConnectorRequest(
            connector_key=connector_key,
            workspace_id=_context().workspace_id,
            principal_id=_context().principal_id,
            configuration={},
            secret_ref=None,
            trace_id=f"trace-invalid-{connector_key}",
        )
        with pytest.raises(ConnectorAdapterError) as failure:
            adapter.validate(request)
        assert failure.value.stage == "validate", connector_key
        assert failure.value.code, connector_key


def test_uniform_execution_policy_enforces_retry_timeout_and_cancellation() -> None:
    attempts = 0
    retry_policy = ConnectorExecutionPolicy(
        timeout_seconds=5,
        max_pages=3,
        max_attempts=2,
        freshness_seconds=60,
    )

    def transient_operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectorAdapterError(
                "TRANSIENT",
                "retry",
                stage="read",
                retryable=True,
            )
        return "succeeded"

    assert retry_policy.run("read", transient_operation) == "succeeded"
    assert attempts == 2
    assert retry_policy.max_pages == 3
    assert retry_policy.freshness_seconds == 60

    cancelled = ConnectorExecutionPolicy(
        timeout_seconds=5,
        cancelled=lambda: True,
    )
    with pytest.raises(ConnectorAdapterError) as cancellation:
        cancelled.run("discover", lambda: "must not run")
    assert cancellation.value.code == "CONNECTOR_CANCELLED"
    assert cancellation.value.stage == "discover"
    assert cancelled.run("close", lambda: "closed") == "closed"

    timed_out = ConnectorExecutionPolicy(timeout_seconds=0.001)
    time.sleep(0.002)
    with pytest.raises(ConnectorAdapterError) as timeout:
        timed_out.run("read", lambda: "must not run")
    assert timeout.value.code == "CONNECTOR_TIMEOUT"
    assert timeout.value.stage == "read"


def test_all_adapters_validate_bounded_retry_policy(tmp_path: Path) -> None:
    application = _application(tmp_path)
    for connector_key, adapter in application.connector_adapters().items():
        request = ConnectorRequest(
            connector_key=connector_key,
            workspace_id=_context().workspace_id,
            principal_id=_context().principal_id,
            configuration={"maxAttempts": 6},
            secret_ref=None,
            trace_id=f"trace-retry-limit-{connector_key}",
        )
        with pytest.raises(ConnectorAdapterError) as failure:
            adapter.validate(request)
        assert failure.value.code == "INVALID_CONFIGURATION", connector_key
        assert failure.value.stage == "validate", connector_key


def test_application_cancellation_fails_before_connection_is_persisted(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "cancel.csv").write_text("id\n1\n", encoding="utf-8")
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError) as failure:
        application.create_connection(
            _context(),
            connector_key="csv",
            display_name="Cancelled",
            scope="personal",
            configuration={"sourceRef": "cancel.csv"},
            secret_ref=None,
            idempotency_key="cancel-create",
            trace_id="trace-cancel-create",
            cancelled=lambda: True,
        )

    assert failure.value.code == "CONNECTOR_CANCELLED"
    assert application.data_overview(_context()).connections == []


def test_connection_creation_runs_the_registered_adapter_control_plane(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "orders.json").write_text(
        json.dumps([{"order_id": "A-1", "amount": 12}]),
        encoding="utf-8",
    )
    application = _application(tmp_path)

    created = application.create_connection(
        _context(),
        connector_key="json",
        display_name="Orders",
        scope="team",
        configuration={"sourceRef": "orders.json"},
        secret_ref=None,
        idempotency_key="registered-control-plane",
        trace_id="trace-registered-control-plane",
    )

    operations = application.connector_operations(_context(), created.connection.id)
    assert [operation.operation for operation in operations] == [
        "validate",
        "authenticate",
        "authorize",
        "discover",
        "introspect",
        "close",
    ]
    assert all(operation.status == "succeeded" for operation in operations)


def test_ingest_runs_the_registered_adapter_data_plane_and_checkpoint(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "orders.json").write_text(
        json.dumps([{"order_id": "A-1", "amount": 12}]),
        encoding="utf-8",
    )
    application = _application(tmp_path)
    created = application.create_connection(
        _context(),
        connector_key="json",
        display_name="Orders",
        scope="team",
        configuration={"sourceRef": "orders.json"},
        secret_ref=None,
        idempotency_key="data-plane-create",
        trace_id="trace-data-plane-create",
    )

    result = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="data-plane-ingest",
        trace_id="trace-data-plane-ingest",
    )

    trace = application.connector_trace(
        _context(),
        created.connection.id,
        "trace-data-plane-ingest",
    )
    assert [operation.operation for operation in trace.operations] == [
        "authenticate",
        "authorize",
        "sample",
        "read",
        "ingest",
        "profile",
        "clean",
        "golden",
        "checkpoint",
        "close",
    ]
    assert trace.operations[-2].checkpoint == result.source_revision.checkpoint
    assert all(operation.status == "succeeded" for operation in trace.operations)


def test_refresh_runs_the_registered_adapter_and_persists_its_checkpoint(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "orders.json"
    source.write_text(
        json.dumps([{"order_id": "A-1", "amount": 12}]),
        encoding="utf-8",
    )
    application = _application(tmp_path)
    created = application.create_connection(
        _context(),
        connector_key="json",
        display_name="Orders",
        scope="team",
        configuration={"sourceRef": "orders.json"},
        secret_ref=None,
        idempotency_key="refresh-adapter-create",
        trace_id="trace-refresh-adapter-create",
    )
    first = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="refresh-adapter-ingest",
        trace_id="trace-refresh-adapter-ingest",
    )
    source.write_text(
        json.dumps([{"order_id": "A-1", "amount": 14}]),
        encoding="utf-8",
    )

    refreshed = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="refresh-adapter-run",
        trace_id="trace-refresh-adapter-run",
    )
    assert refreshed.golden_asset_revision is not None

    trace = application.connector_trace(
        _context(),
        created.connection.id,
        "trace-refresh-adapter-run",
    )
    assert [operation.operation for operation in trace.operations] == [
        "authenticate",
        "authorize",
        "refresh",
        "read",
        "profile",
        "clean",
        "golden",
        "checkpoint",
        "close",
    ]
    source_revision = application.source_revision(
        _context(),
        refreshed.golden_asset_revision.lineage.source_revision_id,
    )
    assert trace.operations[-2].checkpoint == source_revision.checkpoint
    assert refreshed.golden_asset_revision.revision == 2
    assert all(operation.status == "succeeded" for operation in trace.operations)


def test_public_connection_views_never_expose_secret_or_process_configuration(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "orders.json").write_text("[]", encoding="utf-8")
    application = _application(tmp_path)

    created = application.create_connection(
        _context(),
        connector_key="json",
        display_name="Orders",
        scope="team",
        configuration={"sourceRef": "orders.json"},
        secret_ref=None,
        idempotency_key="safe-public-view",
        trace_id="trace-safe-public-view",
    )

    public_models = [
        created.connection,
        application.data_overview(_context()).connections[0],
        application.connection_detail(_context(), created.connection.id).connection,
    ]
    for model in public_models:
        serialized = model.model_dump(mode="json", by_alias=True)
        assert "configuration" not in serialized
        assert "secretRef" not in serialized
    persisted = application.repository.connection(
        _context().workspace_id, created.connection.id
    )
    assert persisted is not None
    assert persisted.configuration == {"sourceRef": "orders.json"}


@pytest.mark.parametrize(
    "profile",
    [
        {
            "transport": "stdio",
            "command": sys.executable,
            "toolAllowlist": ["inventory.read"],
        },
        {
            "transport": "streamable_http",
            "toolAllowlist": ["inventory.read"],
        },
        {
            "transport": "sse",
            "endpoint": "https://mcp.example.test/sse",
            "toolAllowlist": [],
        },
    ],
)
def test_server_mcp_profiles_fail_fast_when_transport_configuration_is_incomplete(
    tmp_path: Path,
    profile: dict[str, object],
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        mcp_profiles={"invalid": profile},
    )

    with pytest.raises(SourcesGoldenError) as failure:
        application.mcp_profile_configuration("invalid", [])

    assert failure.value.code == "MCP_PROFILE_INVALID"


@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
def test_server_remote_mcp_profiles_are_valid_without_stdio_execution_fields(
    tmp_path: Path,
    transport: str,
) -> None:
    profile = {
        "transport": transport,
        "endpoint": "https://mcp.example.test/protocol",
        "toolAllowlist": ["inventory.read"],
        "startupTimeoutSeconds": 5,
        "callTimeoutSeconds": 10,
        "maxPages": 3,
        "outputBytes": 50_000,
    }
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        mcp_profiles={"remote": profile},
    )

    assert application.mcp_profile_configuration("remote", []) == profile
    assert application.mcp_profile_catalog() == [
        {
            "profileId": "remote",
            "label": "remote",
            "transport": transport,
            "toolAllowlist": ["inventory.read"],
        }
    ]


def test_local_adapter_validation_failure_is_typed_at_the_spi_boundary(
    tmp_path: Path,
) -> None:
    adapter = _application(tmp_path).connector_adapters()["json"]
    request = ConnectorRequest(
        connector_key="json",
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration={"sourceRef": "missing.json"},
        secret_ref=None,
        trace_id="trace-missing-json",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.validate(request)

    assert failure.value.code == "SOURCE_VALIDATION_FAILED"
    assert failure.value.stage == "validate"


def test_openapi_adapter_validation_failure_is_typed_at_the_spi_boundary(
    tmp_path: Path,
) -> None:
    adapter = _application(tmp_path).connector_adapters()["openapi_spec"]
    request = ConnectorRequest(
        connector_key="openapi_spec",
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration={
            "specRef": "missing.yaml",
            "operationAllowlist": ["listItems"],
        },
        secret_ref=None,
        trace_id="trace-missing-openapi",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.validate(request)

    assert failure.value.code == "OPENAPI_CONFIGURATION_INVALID"
    assert failure.value.stage == "validate"


def test_http_adapter_discovery_failure_is_typed_and_secret_safe(
    tmp_path: Path,
) -> None:
    secret = "runtime-http-secret"
    application = SourceGoldenApplication(
        database_path=tmp_path / "http-errors.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
        secret_resolver=lambda _ref: secret,
        web_resolver=lambda _host: ["93.184.216.34"],
        http_transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        ),
    )
    adapter = application.connector_adapters()["rest_api"]
    request = ConnectorRequest(
        connector_key="rest_api",
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration={
            "endpoint": "https://public.example/data",
            "operationAllowlist": ["read"],
        },
        secret_ref="secret://workspace-step3b/http",
        trace_id="trace-http-error",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == "HTTP_DISCOVERY_FAILED"
    assert failure.value.stage == "discover"
    assert secret not in failure.value.message


def test_database_adapter_discovery_requires_typed_authentication(
    tmp_path: Path,
) -> None:
    adapter = _application(tmp_path).connector_adapters()["postgresql"]
    request = ConnectorRequest(
        connector_key="postgresql",
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration=_valid_external_configuration("postgresql"),
        secret_ref=None,
        trace_id="trace-postgresql-no-secret",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == "EXTERNAL_CREDENTIAL_REQUIRED"
    assert failure.value.stage == "authenticate"


@pytest.mark.parametrize("connector_key", ["postgresql", "mysql"])
def test_database_adapters_reject_private_endpoint_without_allowlist(
    tmp_path: Path,
    connector_key: str,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["127.0.0.1"],
        secret_resolver=lambda _ref: json.dumps(
            {"username": "reader", "password": "runtime-password"}
        ),
    )
    adapter = application.connector_adapters()[connector_key]
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration={
            "host": "database.example",
            "port": 5432 if connector_key == "postgresql" else 3306,
            "database": "knowledge",
            "schemaAllowlist": ["public"],
            "tableAllowlist": ["orders"],
        },
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}-private-endpoint",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == "DATABASE_ENDPOINT_FORBIDDEN"
    assert failure.value.stage == "discover"


@pytest.mark.parametrize("connector_key", ["postgresql", "mysql"])
def test_database_adapters_reject_dns_rebinding_during_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connector_key: str,
) -> None:
    resolutions = iter([["93.184.216.34"], ["93.184.216.35"]])
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: next(resolutions),
        secret_resolver=lambda _ref: json.dumps(
            {"username": "reader", "password": "runtime-password"}
        ),
    )
    adapter = cast(SqlConnectorAdapter, application.connector_adapters()[connector_key])
    database_adapter: SqlDatabaseAdapter = adapter._adapter

    class Connection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        database_adapter,
        "_connection",
        lambda _connector_key, _options, _configuration: Connection(),
    )
    monkeypatch.setattr(
        database_adapter,
        "_discover_resources",
        lambda *_args, **_kwargs: [
            DiscoveredResource(
                id="public.orders",
                name="orders",
                schema_name="public",
                resource_type="table",
            )
        ],
    )
    request = ConnectorRequest(
        connector_key=connector_key,
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration={
            "host": "database.example",
            "port": 5432 if connector_key == "postgresql" else 3306,
            "database": "knowledge",
            "schemaAllowlist": ["public"],
            "tableAllowlist": ["orders"],
        },
        secret_ref=f"secret://workspace-step3b/{connector_key}",
        trace_id=f"trace-{connector_key}-rebinding",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.discover(request)

    assert failure.value.code == "DATABASE_DNS_REBINDING"
    assert failure.value.stage == "discover"


def _valid_external_configuration(connector_key: str) -> dict[str, JsonValue]:
    database: dict[str, JsonValue] = {
        "host": "database.example",
        "port": 443,
        "database": "analytics",
        "schemaAllowlist": ["reporting"],
        "tableAllowlist": ["orders"],
        "pageSize": 50,
        "rowLimit": 100,
        "byteLimit": 100_000,
        "timeoutSeconds": 5,
    }
    configurations: dict[str, dict[str, JsonValue]] = {
        "postgresql": database,
        "mysql": database,
        "oracle": {
            **{key: value for key, value in database.items() if key != "database"},
            "serviceName": "ORCL",
        },
        "sqlserver": database,
        "clickhouse": database,
        "doris": database,
        "starrocks": database,
        "snowflake": {
            "account": "organization-account",
            "warehouse": "reporting",
            "database": "analytics",
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
            "pageSize": 50,
            "rowLimit": 100,
            "byteLimit": 100_000,
            "timeoutSeconds": 5,
        },
        "bigquery": {
            "projectId": "project",
            "datasetId": "reporting",
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
            "pageSize": 50,
            "rowLimit": 100,
            "byteLimit": 100_000,
            "timeoutSeconds": 5,
        },
        "hive": database,
        "s3": {
            "bucket": "knowledge",
            "objectPrefix": "safe/",
            "region": "us-east-1",
            "maxObjects": 100,
            "maxObjectBytes": 100_000,
            "timeoutSeconds": 5,
        },
        "oss": {
            "bucket": "knowledge",
            "objectPrefix": "safe/",
            "endpoint": "https://oss.example",
            "region": "cn-test",
            "maxObjects": 100,
            "maxObjectBytes": 100_000,
            "timeoutSeconds": 5,
        },
        "kafka": {
            "bootstrapServers": ["broker.example:9093"],
            "topics": ["inventory"],
            "consumerGroup": "knowledge",
            "maxMessages": 100,
            "maxMessageBytes": 100_000,
            "timeoutSeconds": 5,
        },
    }
    lark_fields: dict[str, dict[str, JsonValue]] = {
        "lark_doc": {"documentRef": "doc-token"},
        "lark_wiki": {"wikiRef": "space-token"},
        "lark_drive": {"folderRef": "folder-token"},
        "lark_meeting": {
            "calendarRef": "calendar-token",
            "dateFrom": "2026-08-01",
            "dateTo": "2026-08-25",
        },
        "lark_minutes": {"minutesRef": "minutes-token"},
        "lark_group": {"chatRef": "group-chat", "timeRange": "P7D"},
        "lark_chat": {"chatRef": "direct-chat", "timeRange": "P7D"},
        "lark_sheet": {"sheetRef": "spreadsheet-token"},
        "lark_base": {"appRef": "app-token", "tableRef": "table-token"},
        "lark_mail": {"folder": "INBOX"},
    }
    for key, fields in lark_fields.items():
        configurations[key] = {
            **fields,
            "scopeRef": f"scope-{key}",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 50,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        }
    return configurations[connector_key]


def test_external_adapters_validate_offline_and_report_typed_secret_blockers(
    tmp_path: Path,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
    )
    external = {
        "lark_doc",
        "lark_wiki",
        "lark_drive",
        "lark_meeting",
        "lark_minutes",
        "lark_group",
        "lark_chat",
        "lark_sheet",
        "lark_base",
        "lark_mail",
        "s3",
        "oss",
        "oracle",
        "sqlserver",
        "clickhouse",
        "doris",
        "starrocks",
        "snowflake",
        "bigquery",
        "hive",
        "kafka",
    }

    for connector_key in sorted(external):
        adapter = application.connector_adapters()[connector_key]
        request = ConnectorRequest(
            connector_key=connector_key,
            workspace_id=_context().workspace_id,
            principal_id=_context().principal_id,
            configuration=_valid_external_configuration(connector_key),
            secret_ref=None,
            trace_id=f"trace-{connector_key}",
        )
        assert adapter.validate(request).status == "succeeded", connector_key
        with pytest.raises(ConnectorAdapterError) as missing:
            adapter.authenticate(request)
        assert missing.value.code == "EXTERNAL_CREDENTIAL_REQUIRED", connector_key
        assert missing.value.stage == "authenticate"

        unresolved = ConnectorRequest(
            **{
                **request.__dict__,
                "secret_ref": f"secret://workspace-step3b/{connector_key}",
            }
        )
        with pytest.raises(ConnectorAdapterError) as unavailable:
            adapter.authenticate(unresolved)
        assert unavailable.value.code == "EXTERNAL_CREDENTIAL_UNAVAILABLE", (
            connector_key
        )


def test_external_adapters_report_missing_official_driver_after_valid_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = {
        "oracle": {"username": "reader", "password": "runtime"},
        "sqlserver": {"username": "reader", "password": "runtime"},
        "clickhouse": {"username": "reader", "password": "runtime"},
        "snowflake": {"username": "reader", "password": "runtime"},
        "bigquery": {
            "type": "service_account",
            "project_id": "project",
            "private_key_id": "runtime-key-id",
            "private_key": "runtime-private-key",
            "client_email": "reader@example.invalid",
            "client_id": "runtime-client-id",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        "hive": {"username": "reader", "password": "runtime"},
        "s3": {"accessKeyId": "runtime", "secretAccessKey": "runtime"},
        "oss": {"accessKeyId": "runtime", "accessKeySecret": "runtime"},
        "kafka": {},
    }
    application = SourceGoldenApplication(
        database_path=tmp_path / "drivers.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda ref: json.dumps(credentials[ref.rsplit("/", 1)[-1]]),
    )
    monkeypatch.setattr(
        provider_adapters.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )

    for connector_key in sorted(credentials):
        request = ConnectorRequest(
            connector_key=connector_key,
            workspace_id=_context().workspace_id,
            principal_id=_context().principal_id,
            configuration=_valid_external_configuration(connector_key),
            secret_ref=f"secret://workspace-step3b/{connector_key}",
            trace_id=f"trace-driver-{connector_key}",
        )
        with pytest.raises(ConnectorAdapterError) as missing:
            application.connector_adapters()[connector_key].authenticate(request)
        assert missing.value.code == "EXTERNAL_DRIVER_UNAVAILABLE", connector_key


def test_external_provider_connection_persists_exact_typed_blocker(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)

    result = application.create_connection(
        _context(),
        connector_key="oracle",
        display_name="Oracle reporting",
        scope="team",
        configuration=cast(dict[str, object], _valid_external_configuration("oracle")),
        secret_ref="secret://workspace-step3b/oracle",
        idempotency_key="oracle-external-blocked",
        trace_id="trace-oracle-external-blocked",
    )

    assert result.connection.status == "credential_blocked"
    assert result.validation.status == "succeeded"
    assert result.validation.reason.code == "PROVIDER_CONFIGURATION_VALIDATED"
    assert result.discovery.reason.code == "EXTERNAL_CREDENTIAL_UNAVAILABLE"
    assert result.connection.last_error == result.discovery.reason
    operations = application.connector_operations(_context(), result.connection.id)
    assert [operation.operation for operation in operations] == [
        "validate",
        "authenticate",
        "authorize",
        "discover",
        "introspect",
        "sample",
        "close",
    ]
    assert [operation.status for operation in operations] == [
        "succeeded",
        "credential_blocked",
        "credential_blocked",
        "credential_blocked",
        "credential_blocked",
        "credential_blocked",
        "succeeded",
    ]
    assert {operation.reason.code for operation in operations[1:6]} == {
        "EXTERNAL_CREDENTIAL_UNAVAILABLE"
    }


def test_external_provider_with_runtime_resolver_persists_unavailable_secret(
    tmp_path: Path,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "resolver.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: None,
    )

    result = application.create_connection(
        _context(),
        connector_key="oracle",
        display_name="Oracle unavailable secret",
        scope="team",
        configuration=cast(dict[str, object], _valid_external_configuration("oracle")),
        secret_ref="secret://workspace-step3b/oracle",
        idempotency_key="oracle-unavailable-secret",
        trace_id="trace-oracle-unavailable-secret",
    )

    assert result.connection.status == "credential_blocked"
    assert result.validation.status == "succeeded"
    assert result.connection.last_error is not None
    assert result.connection.last_error.code == "EXTERNAL_CREDENTIAL_UNAVAILABLE"
    assert (
        application.connection_detail(_context(), result.connection.id).connection
        == result.connection
    )


def test_webhook_without_runtime_secret_resolver_is_typed_blocked_not_local_file(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "event.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            }
        ),
        encoding="utf-8",
    )
    application = _application(tmp_path)

    result = application.create_connection(
        _context(),
        connector_key="webhook",
        display_name="Inbound events",
        scope="team",
        configuration={
            "listenPath": "/events",
            "schemaRef": "event.schema.json",
        },
        secret_ref="secret://workspace-step3b/webhook",
        idempotency_key="webhook-no-resolver",
        trace_id="trace-webhook-no-resolver",
    )

    assert result.connection.status == "credential_blocked"
    assert result.discovery.reason.code == "WEBHOOK_CREDENTIAL_UNAVAILABLE"


def test_capability_matrix_has_one_complete_truthful_row_per_adapter(
    tmp_path: Path,
) -> None:
    matrix = _application(tmp_path).connector_capability_matrix()

    assert matrix.total == 37
    assert len(matrix.connectors) == 37
    assert len({row.connector_key for row in matrix.connectors}) == 37
    assert {row.capability_state for row in matrix.connectors} == {
        "available",
        "credential_blocked",
    }
    assert sum(
        row.capability_state == "available" for row in matrix.connectors
    ) == 16
    assert sum(
        row.capability_state == "credential_blocked" for row in matrix.connectors
    ) == 21
    for row in matrix.connectors:
        assert row.capability.catalog == "present"
        assert row.capability.form == "validated"
        assert row.capability.adapter == row.certification.implementation
        assert row.capability.discovery == "implemented"
        assert row.capability.read == "implemented"
        assert row.capability.refresh == "implemented"
        assert row.capability.checkpoint
        assert row.capability.typed_error == "implemented"
        assert row.permissions.read_scopes
        assert len(row.capability.evidence) >= 4
        assert all(
            reference.startswith("tests/frontend/knowledge_workspace_v21141/test_step3")
            for reference in row.capability.evidence
        )
        if row.capability_state == "credential_blocked":
            assert row.capability.blocker
            assert row.capability.live_e2e == "external_blocked"
            assert row.capability.credential_state == "external_blocked"
            assert row.certification.verification_command.endswith(row.connector_key)
            assert "provider_verify" in row.certification.verification_command
        else:
            assert row.capability.blocker is None


def test_legacy_xls_is_not_advertised_without_a_runtime_parser(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "legacy.xls").write_bytes(b"not-an-xlsx-workbook")
    adapter = _application(tmp_path).connector_adapters()["excel"]
    request = ConnectorRequest(
        connector_key="excel",
        workspace_id=_context().workspace_id,
        principal_id=_context().principal_id,
        configuration={"sourceRef": "legacy.xls"},
        secret_ref=None,
        trace_id="trace-legacy-xls",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        adapter.validate(request)

    assert failure.value.code == "SOURCE_VALIDATION_FAILED"
    assert failure.value.stage == "validate"
    assert "unsupported extension" in failure.value.message


def test_committed_capability_matrix_matches_runtime_registry(
    tmp_path: Path,
) -> None:
    matrix_path = (
        Path(__file__).parents[3]
        / "docs"
        / "knowledge-assets"
        / "implementation"
        / "STEP3_W1_CAPABILITY_MATRIX.json"
    )
    committed = json.loads(matrix_path.read_text(encoding="utf-8"))
    runtime = (
        _application(tmp_path)
        .connector_capability_matrix()
        .model_dump(mode="json", by_alias=True)
    )

    assert committed == runtime


@contextmanager
def _remote_mcp_service(tmp_path: Path, transport: str):
    port = _unused_port()
    data_path = tmp_path / f"remote-mcp-{transport}.json"
    data_path.write_text(
        json.dumps(
            [
                {"sku": "A-1", "region": "north", "stock": 8},
                {"sku": "B-2", "region": "south", "stock": 3},
            ]
        ),
        encoding="utf-8",
    )
    server = (
        Path(__file__).parents[2]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "mcp_sdk_remote_server.py"
    )
    environment = {
        **os.environ,
        "MCP_FIXTURE_PORT": str(port),
        "MCP_FIXTURE_TRANSPORT": transport,
        "MCP_FIXTURE_DATA_PATH": str(data_path),
    }
    process = subprocess.Popen(
        [sys.executable, str(server)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read().decode() if process.stderr else ""
            raise RuntimeError(f"remote MCP fixture exited: {stderr}")
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)
    else:
        process.kill()
        process.wait()
        raise RuntimeError("remote MCP fixture did not start")
    try:
        path = "/mcp" if transport == "streamable-http" else "/sse"
        yield data_path, f"http://127.0.0.1:{port}{path}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class _JsonServiceState(TypedDict):
    rows: list[dict[str, object]]
    requests: list[dict[str, object]]


@contextmanager
def _json_service() -> Iterator[tuple[_JsonServiceState, str]]:
    state: _JsonServiceState = {
        "rows": [
            {"id": 1, "name": "alpha"},
            {"id": 2, "name": "beta"},
        ],
        "requests": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state["requests"].append(
                {
                    "method": "GET",
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            parsed = urlsplit(self.path)
            if parsed.path == "/items":
                body = json.dumps(state["rows"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("ETag", '"items-v1"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/paged":
                offset = int(parse_qs(parsed.query).get("offset", ["0"])[0])
                rows = state["rows"]
                assert isinstance(rows, list)
                body = json.dumps(
                    {
                        "data": rows[offset : offset + 1],
                        "next": "/paged" if offset + 1 < len(rows) else None,
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("ETag", f'"page-{offset}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/page":
                body = (
                    b"<html><head><style>secret-style</style></head>"
                    b"<body><h1>Inventory</h1><script>steal()</script>"
                    b"<p>Current stock</p></body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            state["requests"].append(
                {
                    "method": "POST",
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": request,
                }
            )
            if self.path != "/graphql":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"data": {"items": state["rows"]}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self) -> None:
            state["requests"].append({"method": "HEAD", "path": self.path})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("ETag", '"head-v1"')
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_json_runs_the_real_lifecycle_and_survives_restart(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "accounts.json").write_text(
        json.dumps(
            [
                {"account": "north", "active": True, "balance": 12.5},
                {"account": "south", "active": False, "balance": 7},
            ]
        ),
        encoding="utf-8",
    )
    application = _application(tmp_path)

    definition = next(
        item
        for item in application.connector_catalog(_context()).connectors
        if item.connector_key == "json"
    )
    assert definition.capability_state == "available"

    created = application.create_connection(
        _context(),
        connector_key="json",
        display_name="Accounts JSON",
        scope="personal",
        configuration={
            "sourceRef": "accounts.json",
            "maxDepth": 8,
            "maxRows": 100,
        },
        secret_ref=None,
        idempotency_key="json-create",
        trace_id="trace-json-create",
    )
    assert created.connection.status == "ready"
    assert created.discovery.resources[0].row_count == 2
    assert [field.name for field in created.discovery.resources[0].fields] == [
        "account",
        "active",
        "balance",
    ]

    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="json-ingest",
        trace_id="trace-json-ingest",
    )
    assert ingested.source_revision.source_type == "json"
    assert ingested.profile_run.row_count == 2
    assert application.golden_data(
        _context(), ingested.golden_asset_revision.id
    ).rows == [
        {"account": "north", "active": True, "balance": 12.5},
        {"account": "south", "active": False, "balance": 7},
    ]

    reopened = _application(tmp_path)
    assert (
        reopened.golden_data(_context(), ingested.golden_asset_revision.id).rows[1][
            "account"
        ]
        == "south"
    )


def test_context_reference_is_pinned_reauthorized_and_freshness_bounded(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "context.json").write_text('[{"fact":"verified"}]', encoding="utf-8")
    application = _application(tmp_path)
    created = application.create_connection(
        _context(),
        connector_key="json",
        display_name="Context",
        scope="personal",
        configuration={"sourceRef": "context.json"},
        secret_ref=None,
        idempotency_key="context-create",
        trace_id="trace-context-create",
    )
    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=[],
        idempotency_key="context-ingest",
        trace_id="trace-context-ingest",
    )
    golden = ingested.golden_asset_revision
    reference = GoldenContextReference(
        object_id=golden.asset_id,
        revision=golden.id,
        provider_revision=ingested.source_revision.id,
    )

    assert application.resolve_context_reference(_context(), reference).revision == (
        golden.id
    )
    with pytest.raises(SourcesGoldenError) as cross_workspace:
        application.resolve_context_reference(
            AccessContext(
                workspace_id="workspace-other",
                principal_id=_context().principal_id,
                role="editor",
            ),
            reference,
        )
    assert cross_workspace.value.code == "GOLDEN_REVISION_NOT_FOUND"
    with pytest.raises(SourcesGoldenError) as forged_caller:
        application.resolve_context_reference(
            AccessContext(
                workspace_id=_context().workspace_id,
                principal_id="forged-caller",
                role="editor",
            ),
            reference,
        )
    assert forged_caller.value.code == "PERMISSION_DENIED"
    with pytest.raises(SourcesGoldenError) as mismatched_object:
        application.resolve_context_reference(
            _context(),
            reference.model_copy(update={"object_id": "golden-forged"}),
        )
    assert mismatched_object.value.code == "CONTEXT_OBJECT_MISMATCH"
    with pytest.raises(SourcesGoldenError) as mismatched_provider:
        application.resolve_context_reference(
            _context(),
            reference.model_copy(update={"provider_revision": "source-forged"}),
        )
    assert mismatched_provider.value.code == "CONTEXT_PROVIDER_REVISION_MISMATCH"
    with pytest.raises(SourcesGoldenError) as expired:
        application.resolve_context_reference(
            _context(),
            reference,
            max_age_seconds=60,
            as_of=datetime.fromisoformat(golden.freshness_at) + timedelta(seconds=61),
        )
    assert expired.value.code == "CONTEXT_REVISION_EXPIRED"
    with pytest.raises(SourcesGoldenError) as mutable:
        application.resolve_context_reference(
            _context(),
            reference.model_copy(update={"revision": "latest"}),
        )
    assert mutable.value.code == "MUTABLE_CONTEXT_REFERENCE"

    application.revoke_connection(
        _context(),
        created.connection.id,
        reason="source ACL revoked",
        trace_id="trace-context-revoke",
    )
    with pytest.raises(SourcesGoldenError) as revoked:
        application.resolve_context_reference(_context(), reference)
    assert revoked.value.code == "GOLDEN_REVISION_NOT_FOUND"


def test_json_depth_limit_fails_closed_before_connection_is_saved(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "deep.json").write_text(
        '{"one":{"two":{"three":"too deep"}}}',
        encoding="utf-8",
    )
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError, match="depth"):
        application.create_connection(
            _context(),
            connector_key="json",
            display_name="Too deep",
            scope="personal",
            configuration={
                "sourceRef": "deep.json",
                "maxDepth": 2,
                "maxRows": 100,
            },
            secret_ref=None,
            idempotency_key="deep-json",
            trace_id="trace-deep-json",
        )

    assert application.data_overview(_context()).connections == []


def test_local_source_rejects_symlink_replacement_after_discovery(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = uploads / "notes.md"
    source.write_text("approved content", encoding="utf-8")
    replacement = uploads / "replacement.md"
    replacement.write_text("replacement content", encoding="utf-8")
    application = _application(tmp_path)

    created = application.create_connection(
        _context(),
        connector_key="local_file",
        display_name="Notes",
        scope="personal",
        configuration={"sourceRef": "notes.md"},
        secret_ref=None,
        idempotency_key="symlink-create",
        trace_id="trace-symlink-create",
    )
    source.unlink()
    source.symlink_to(replacement)

    with pytest.raises(SourcesGoldenError, match="symlink"):
        application.ingest(
            _context(),
            connection_id=created.connection.id,
            resource_id=created.discovery.resources[0].id,
            recipe_operations=[],
            idempotency_key="symlink-ingest",
            trace_id="trace-symlink-ingest",
        )


@pytest.mark.parametrize(
    ("member_name", "content", "message"),
    [
        ("../escaped.xml", b"safe", "path"),
        ("xl/sharedStrings.xml", b"A" * 2_000_000, "compression"),
    ],
)
def test_excel_rejects_unsafe_xlsx_archives_before_parser_execution(
    tmp_path: Path,
    member_name: str,
    content: bytes,
    message: str,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    workbook = uploads / "unsafe.xlsx"
    with zipfile.ZipFile(workbook, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError, match=message):
        application.create_connection(
            _context(),
            connector_key="excel",
            display_name="Unsafe workbook",
            scope="personal",
            configuration={"sourceRef": workbook.name},
            secret_ref=None,
            idempotency_key=f"unsafe-xlsx-{message}",
            trace_id=f"trace-unsafe-xlsx-{message}",
        )

    assert application.data_overview(_context()).connections == []


def test_parquet_discovers_schema_and_builds_a_golden_revision(
    tmp_path: Path,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    parquet.write_table(
        pyarrow.table(
            {
                "region": ["north", "south"],
                "orders": [12, 7],
                "conversion": [0.31, 0.27],
            }
        ),
        uploads / "sales.parquet",
    )
    application = _application(tmp_path)

    created = application.create_connection(
        _context(),
        connector_key="parquet",
        display_name="Sales Parquet",
        scope="team",
        configuration={
            "sourceRef": "sales.parquet",
            "maxRows": 100,
            "maxColumns": 10,
            "maxUncompressedBytes": 1_000_000,
        },
        secret_ref=None,
        idempotency_key="parquet-create",
        trace_id="trace-parquet-create",
    )
    assert created.connection.status == "ready"
    assert created.discovery.resources[0].row_count == 2
    assert [
        (field.name, field.data_type) for field in created.discovery.resources[0].fields
    ] == [
        ("region", "string"),
        ("orders", "int64"),
        ("conversion", "double"),
    ]

    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=[],
        idempotency_key="parquet-ingest",
        trace_id="trace-parquet-ingest",
    )
    assert ingested.source_revision.source_type == "parquet"
    assert application.golden_data(
        _context(), ingested.golden_asset_revision.id
    ).rows == [
        {"conversion": 0.31, "orders": 12, "region": "north"},
        {"conversion": 0.27, "orders": 7, "region": "south"},
    ]


def test_parquet_budget_rejects_oversized_schema_before_save(tmp_path: Path) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    parquet.write_table(
        pyarrow.table({"one": [1], "two": [2]}),
        uploads / "wide.parquet",
    )
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError, match="column limit"):
        application.create_connection(
            _context(),
            connector_key="parquet",
            display_name="Wide Parquet",
            scope="personal",
            configuration={
                "sourceRef": "wide.parquet",
                "maxRows": 100,
                "maxColumns": 1,
                "maxUncompressedBytes": 1_000_000,
            },
            secret_ref=None,
            idempotency_key="parquet-wide",
            trace_id="trace-parquet-wide",
        )


@pytest.mark.parametrize(
    ("name", "content", "expected_type", "expected_text"),
    [
        ("guide.md", "# Guide\n\nRun checks.", "markdown", "# Guide"),
        ("guide.txt", "Run checks.\nEscalate failures.", "text", "Run checks."),
        (
            "guide.html",
            (
                "<html><body><h1>Guide</h1><script>steal()</script>"
                "<p>Run checks.</p></body></html>"
            ),
            "html",
            "Guide",
        ),
    ],
)
def test_document_connector_reads_text_formats_without_executable_html(
    tmp_path: Path,
    name: str,
    content: str,
    expected_type: str,
    expected_text: str,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / name).write_text(content, encoding="utf-8")
    application = _application(tmp_path)

    created = application.create_connection(
        _context(),
        connector_key="doc_txt",
        display_name=name,
        scope="personal",
        configuration={"sourceRef": name, "maxTextChars": 100_000},
        secret_ref=None,
        idempotency_key=f"create-{name}",
        trace_id=f"trace-create-{name}",
    )
    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        idempotency_key=f"ingest-{name}",
        trace_id=f"trace-ingest-{name}",
    )

    assert ingested.source_revision.source_type == expected_type
    rows = application.golden_data(_context(), ingested.golden_asset_revision.id).rows
    assert any(expected_text in str(row["text"]) for row in rows)
    if name.endswith(".html"):
        assert "steal()" not in json.dumps(rows)


def test_pdf_rejects_extracted_text_over_configured_character_budget(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    _write_text_pdf(uploads / "oversized.pdf", ["This extracted text is too long."])
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError, match="extracted character limit"):
        application.create_connection(
            _context(),
            connector_key="doc_txt",
            display_name="Oversized PDF",
            scope="personal",
            configuration={"sourceRef": "oversized.pdf", "maxTextChars": 8},
            secret_ref=None,
            idempotency_key="oversized-pdf",
            trace_id="trace-oversized-pdf",
        )

    assert application.data_overview(_context()).connections == []


@pytest.mark.parametrize(
    ("extension", "message"),
    [
        (
            {"nested": {"nested": {"nested": {"nested": {"nested": {}}}}}},
            "nesting depth",
        ),
        ({"nodes": [0] * 100_001}, "node limit"),
    ],
)
def test_openapi_rejects_specs_over_parsed_structure_budgets(
    tmp_path: Path,
    extension: dict[str, object],
    message: str,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    if message == "nesting depth":
        nested: dict[str, object] = {}
        extension = nested
        for _ in range(70):
            child: dict[str, object] = {}
            nested["nested"] = child
            nested = child
    spec = {
        "openapi": "3.1.0",
        "servers": [{"url": "https://api.example.invalid"}],
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "x-structure-budget-test": extension,
    }
    (uploads / "oversized.openapi.json").write_text(
        json.dumps(spec),
        encoding="utf-8",
    )
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError, match=message):
        application.create_connection(
            _context(),
            connector_key="openapi_spec",
            display_name="Oversized OpenAPI",
            scope="personal",
            configuration={
                "specRef": "oversized.openapi.json",
                "operationAllowlist": ["listItems"],
            },
            secret_ref=None,
            idempotency_key=f"oversized-openapi-{message}",
            trace_id=f"trace-oversized-openapi-{message}",
        )

    assert application.data_overview(_context()).connections == []


def test_openapi_allowlisted_operation_reads_real_http_and_detects_schema_drift(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    with _json_service() as (state, endpoint):
        spec = {
            "openapi": "3.1.0",
            "info": {"title": "Local inventory", "version": "1"},
            "servers": [{"url": endpoint}],
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "id": {"type": "integer"},
                                                    "name": {"type": "string"},
                                                },
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                },
                "/admin": {
                    "post": {
                        "operationId": "deleteEverything",
                        "responses": {"204": {"description": "never allowed"}},
                    }
                },
            },
        }
        (uploads / "inventory.openapi.json").write_text(
            json.dumps(spec), encoding="utf-8"
        )
        application = SourceGoldenApplication(
            database_path=tmp_path / "sources-golden.sqlite3",
            artifact_root=tmp_path / "artifacts",
            source_root=uploads,
            network_allow_private_hosts={"127.0.0.1"},
        )

        created = application.create_connection(
            _context(),
            connector_key="openapi_spec",
            display_name="Inventory API",
            scope="team",
            configuration={
                "specRef": "inventory.openapi.json",
                "operationAllowlist": ["listItems"],
                "maxResponseBytes": 100_000,
                "timeoutSeconds": 2,
            },
            secret_ref=None,
            idempotency_key="openapi-create",
            trace_id="trace-openapi-create",
        )
        assert created.connection.status == "ready"
        assert [resource.name for resource in created.discovery.resources] == [
            "listItems"
        ]

        ingested = application.ingest(
            _context(),
            connection_id=created.connection.id,
            resource_id=created.discovery.resources[0].id,
            recipe_operations=[],
            idempotency_key="openapi-ingest",
            trace_id="trace-openapi-ingest",
        )
        assert ingested.source_revision.source_type == "http"
        assert (
            application.golden_data(_context(), ingested.golden_asset_revision.id).rows
            == state["rows"]
        )

        state["rows"] = [{"id": 1, "name": "alpha", "stock": 8}]
        refreshed = application.refresh(
            _context(),
            asset_id=ingested.golden_asset_revision.asset_id,
            idempotency_key="openapi-refresh",
            trace_id="trace-openapi-refresh",
        )
        assert refreshed.run.status == "schema_drift"
        assert refreshed.last_good_revision is not None
        assert refreshed.last_good_revision.id == ingested.golden_asset_revision.id


def test_openapi_rejects_non_allowlisted_and_mutating_operations(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Unsafe", "version": "1"},
        "servers": [{"url": "https://api.example.invalid"}],
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "responses": {"200": {"description": "ok"}},
                },
                "delete": {
                    "operationId": "deleteItems",
                    "responses": {"204": {"description": "deleted"}},
                },
            }
        },
    }
    (uploads / "unsafe.yaml").write_text(
        json.dumps(spec),
        encoding="utf-8",
    )
    application = _application(tmp_path)

    with pytest.raises(SourcesGoldenError, match="operationAllowlist"):
        application.create_connection(
            _context(),
            connector_key="openapi_spec",
            display_name="No allowlist",
            scope="personal",
            configuration={
                "specRef": "unsafe.yaml",
                "operationAllowlist": [],
                "maxResponseBytes": 100_000,
                "timeoutSeconds": 2,
            },
            secret_ref=None,
            idempotency_key="openapi-no-allowlist",
            trace_id="trace-openapi-no-allowlist",
        )

    with pytest.raises(SourcesGoldenError, match="read-only"):
        application.create_connection(
            _context(),
            connector_key="openapi_spec",
            display_name="Mutation",
            scope="personal",
            configuration={
                "specRef": "unsafe.yaml",
                "operationAllowlist": ["deleteItems"],
                "maxResponseBytes": 100_000,
                "timeoutSeconds": 2,
            },
            secret_ref=None,
            idempotency_key="openapi-mutation",
            trace_id="trace-openapi-mutation",
        )


def test_rest_http_runs_paginated_lifecycle_with_durable_checkpoint_and_secret_safety(
    tmp_path: Path,
) -> None:
    secret_value = "runtime-only-token"
    with _json_service() as (state, endpoint):
        application = SourceGoldenApplication(
            database_path=tmp_path / "sources-golden.sqlite3",
            artifact_root=tmp_path / "artifacts",
            source_root=tmp_path / "uploads",
            network_allow_private_hosts={"127.0.0.1"},
            secret_resolver=lambda ref: (
                secret_value if ref == "secret://workspace-step3b/inventory" else None
            ),
        )
        created = application.create_connection(
            _context(),
            connector_key="rest_api",
            display_name="Paged inventory",
            scope="team",
            configuration={
                "endpoint": f"{endpoint}/paged",
                "operationAllowlist": ["read"],
                "paginationMode": "offset",
                "pageSize": 1,
                "maxPages": 3,
                "maxRows": 10,
                "maxResponseBytes": 100_000,
                "rateLimitPerMinute": 20,
                "timeoutSeconds": 2,
            },
            secret_ref="secret://workspace-step3b/inventory",
            idempotency_key="rest-create",
            trace_id="trace-rest-create",
        )
        assert created.connection.status == "ready"
        assert created.discovery.resources[0].row_count == 2
        assert state["requests"][0]["authorization"] == f"Bearer {secret_value}"

        ingested = application.ingest(
            _context(),
            connection_id=created.connection.id,
            resource_id=created.discovery.resources[0].id,
            recipe_operations=[],
            idempotency_key="rest-ingest",
            trace_id="trace-rest-ingest",
        )
        assert ingested.source_revision.source_type == "http"
        assert ingested.source_revision.checkpoint == {"etag": '"page-1"'}
        assert ingested.golden_asset_revision.lineage.checkpoint == {"etag": '"page-1"'}
        assert (
            application.golden_data(_context(), ingested.golden_asset_revision.id).rows
            == state["rows"]
        )

        bootstrap = application.bootstrap_projection(_context())
        serialized = json.dumps(bootstrap)
        assert secret_value not in serialized
        connections = bootstrap["connections"]
        assert isinstance(connections, list)
        assert all(
            "secretRef" not in connection and "configuration" not in connection
            for connection in connections
            if isinstance(connection, dict)
        )

        reopened = SourceGoldenApplication(
            database_path=tmp_path / "sources-golden.sqlite3",
            artifact_root=tmp_path / "artifacts",
            source_root=tmp_path / "uploads",
            network_allow_private_hosts={"127.0.0.1"},
            secret_resolver=lambda _ref: secret_value,
        )
        assert (
            reopened.golden_data(_context(), ingested.golden_asset_revision.id).rows
            == state["rows"]
        )


def test_graphql_web_and_custom_http_use_real_read_only_endpoints(
    tmp_path: Path,
) -> None:
    with _json_service() as (state, endpoint):
        application = SourceGoldenApplication(
            database_path=tmp_path / "sources-golden.sqlite3",
            artifact_root=tmp_path / "artifacts",
            source_root=tmp_path / "uploads",
            network_allow_private_hosts={"127.0.0.1"},
        )
        cases = [
            (
                "graphql",
                {
                    "endpoint": f"{endpoint}/graphql",
                    "query": "query Inventory { items { id name } }",
                    "operationAllowlist": ["Inventory"],
                    "maxRows": 10,
                    "maxResponseBytes": 100_000,
                    "timeoutSeconds": 2,
                },
                state["rows"],
            ),
            (
                "web_discovery",
                {
                    "endpoint": f"{endpoint}/page",
                    "operationAllowlist": ["page"],
                    "paginationMode": "none",
                    "maxRows": 10,
                    "maxResponseBytes": 100_000,
                    "timeoutSeconds": 2,
                },
                [{"text": "Inventory"}, {"text": "Current stock"}],
            ),
            (
                "custom_http",
                {
                    "name": "inventory-head",
                    "endpoint": f"{endpoint}/items",
                    "method": "HEAD",
                    "operationAllowlist": ["inventory-head"],
                    "paginationMode": "none",
                    "maxRows": 10,
                    "maxResponseBytes": 100_000,
                    "timeoutSeconds": 2,
                },
                [
                    {
                        "status": 200,
                        "contentType": "application/json",
                        "etag": '"head-v1"',
                        "lastModified": None,
                    }
                ],
            ),
        ]
        for connector_key, configuration, expected in cases:
            created = application.create_connection(
                _context(),
                connector_key=connector_key,
                display_name=connector_key,
                scope="personal",
                configuration=configuration,
                secret_ref=None,
                idempotency_key=f"{connector_key}-create",
                trace_id=f"trace-{connector_key}-create",
            )
            ingested = application.ingest(
                _context(),
                connection_id=created.connection.id,
                resource_id=created.discovery.resources[0].id,
                recipe_operations=[],
                idempotency_key=f"{connector_key}-ingest",
                trace_id=f"trace-{connector_key}-ingest",
            )
            rows = application.golden_data(
                _context(), ingested.golden_asset_revision.id
            ).rows
            assert rows == expected
            if connector_key == "web_discovery":
                assert "steal()" not in json.dumps(rows)
                assert "secret-style" not in json.dumps(rows)


def test_graphql_and_custom_http_reject_mutating_or_unlisted_operations(
    tmp_path: Path,
) -> None:
    with _json_service() as (_state, endpoint):
        application = SourceGoldenApplication(
            database_path=tmp_path / "sources-golden.sqlite3",
            artifact_root=tmp_path / "artifacts",
            source_root=tmp_path / "uploads",
            network_allow_private_hosts={"127.0.0.1"},
        )
        with pytest.raises(SourcesGoldenError, match="read-only"):
            application.create_connection(
                _context(),
                connector_key="graphql",
                display_name="mutation",
                scope="personal",
                configuration={
                    "endpoint": f"{endpoint}/graphql",
                    "query": "mutation DeleteAll { deleteAll }",
                    "operationAllowlist": ["DeleteAll"],
                },
                secret_ref=None,
                idempotency_key="graphql-mutation",
                trace_id="trace-graphql-mutation",
            )
        with pytest.raises(SourcesGoldenError, match="allowlist"):
            application.create_connection(
                _context(),
                connector_key="custom_http",
                display_name="unlisted",
                scope="personal",
                configuration={
                    "name": "inventory",
                    "endpoint": f"{endpoint}/items",
                    "method": "GET",
                    "operationAllowlist": ["different-operation"],
                },
                secret_ref=None,
                idempotency_key="custom-unlisted",
                trace_id="trace-custom-unlisted",
            )
        with pytest.raises(SourcesGoldenError, match="read-only"):
            application.create_connection(
                _context(),
                connector_key="custom_http",
                display_name="mutation",
                scope="personal",
                configuration={
                    "name": "inventory",
                    "endpoint": f"{endpoint}/items",
                    "method": "DELETE",
                    "operationAllowlist": ["inventory"],
                },
                secret_ref=None,
                idempotency_key="custom-mutation",
                trace_id="trace-custom-mutation",
            )


def test_http_transport_rejects_cross_origin_redirect_before_forwarding_secrets() -> (
    None
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            request=request,
        )

    transport = SecureHttpTransport(
        resolver=lambda _host: ["93.184.216.34"],
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ValueError, match="cross-origin"):
        transport.request(
            method="GET",
            url="https://public.example/data",
            trace_id="trace-redirect",
            timeout_seconds=1,
            max_response_bytes=1_000,
            rate_limit_per_minute=10,
            accepted_media_types={"application/json"},
            headers={"Authorization": "Bearer runtime-secret"},
        )
    assert len(seen) == 1
    assert seen[0].url.host == "public.example"


def test_http_transport_rejects_dns_rebinding_after_response() -> None:
    answers = iter([["93.184.216.34"], ["93.184.216.35"]])
    transport = SecureHttpTransport(
        resolver=lambda _host: next(answers),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"[]",
                request=request,
            )
        ),
    )
    with pytest.raises(ValueError, match="DNS resolution changed"):
        transport.request(
            method="GET",
            url="https://public.example/data",
            trace_id="trace-rebinding",
            timeout_seconds=1,
            max_response_bytes=1_000,
            rate_limit_per_minute=10,
            accepted_media_types={"application/json"},
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"not json",
            ),
            "content type",
        ),
        (
            httpx.Response(
                429,
                headers={
                    "content-type": "application/json",
                    "retry-after": "60",
                },
            ),
            "rate limited",
        ),
        (
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"value":"' + b"x" * 100 + b'"}',
            ),
            "byte limit",
        ),
    ],
)
def test_http_transport_fails_closed_for_mime_rate_and_size(
    response: httpx.Response,
    message: str,
) -> None:
    transport = SecureHttpTransport(
        resolver=lambda _host: ["93.184.216.34"],
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=request,
            )
        ),
    )
    with pytest.raises(ValueError, match=message):
        transport.request(
            method="GET",
            url="https://public.example/data",
            trace_id=f"trace-{message}",
            timeout_seconds=1,
            max_response_bytes=50,
            rate_limit_per_minute=10,
            accepted_media_types={"application/json"},
        )


def test_http_transport_reports_timeout_without_returning_data() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport = SecureHttpTransport(
        resolver=lambda _host: ["93.184.216.34"],
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(TimeoutError, match="timed out"):
        transport.request(
            method="GET",
            url="https://public.example/data",
            trace_id="trace-timeout",
            timeout_seconds=1,
            max_response_bytes=1_000,
            rate_limit_per_minute=10,
            accepted_media_types={"application/json"},
        )


def test_database_query_parameters_keep_json_types_after_restart(
    tmp_path: Path,
) -> None:
    application = _application(tmp_path)
    parameters = {
        "minimum": 10,
        "active": True,
        "note": None,
        "regions": ["north", "south"],
    }

    created = application.create_connection(
        _context(),
        connector_key="postgresql",
        display_name="Typed parameters",
        scope="team",
        configuration={
            "host": "database.example",
            "port": 5432,
            "database": "analytics",
            "schemaAllowlist": ["reporting"],
            "tableAllowlist": ["orders"],
            "query": (
                "SELECT * FROM reporting.orders "
                "WHERE amount >= :minimum AND active = :active"
            ),
            "queryParameters": parameters,
        },
        secret_ref="secret://workspace-step3b/postgresql",
        idempotency_key="typed-parameters",
        trace_id="trace-typed-parameters",
    )

    persisted = application.repository.connection(
        _context().workspace_id, created.connection.id
    )
    assert persisted is not None
    assert persisted.configuration["queryParameters"] == parameters
    reopened = _application(tmp_path)
    restored = reopened.repository.connection(
        _context().workspace_id, created.connection.id
    )
    assert restored is not None
    assert restored.configuration["queryParameters"] == parameters


@pytest.mark.parametrize(
    ("server_transport", "connector_transport"),
    [
        ("streamable-http", "streamable_http"),
        ("sse", "sse"),
    ],
)
def test_official_remote_mcp_transports_run_and_persist_the_lifecycle(
    tmp_path: Path,
    server_transport: str,
    connector_transport: str,
) -> None:
    with _remote_mcp_service(tmp_path, server_transport) as (data_path, endpoint):
        application = SourceGoldenApplication(
            database_path=tmp_path / f"{connector_transport}.sqlite3",
            artifact_root=tmp_path / f"{connector_transport}-artifacts",
            source_root=tmp_path,
            network_allow_private_hosts={"127.0.0.1"},
            secret_resolver=lambda _ref: None,
        )
        created = application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name=f"Remote MCP {connector_transport}",
            scope="team",
            configuration={
                "transport": connector_transport,
                "endpoint": endpoint,
                "toolAllowlist": ["inventory.read"],
                "startupTimeoutSeconds": 5,
                "callTimeoutSeconds": 5,
                "outputBytes": 100_000,
                "maxPages": 5,
            },
            secret_ref=None,
            idempotency_key=f"{connector_transport}-create",
            trace_id=f"trace-{connector_transport}-create",
        )
        assert created.connection.status == "ready"
        assert [tool.name for tool in created.discovery.resources] == ["inventory.read"]

        ingested = application.ingest(
            _context(),
            connection_id=created.connection.id,
            resource_id=created.discovery.resources[0].id,
            recipe_operations=[],
            tool_arguments={"region": "north"},
            idempotency_key=f"{connector_transport}-ingest",
            trace_id=f"trace-{connector_transport}-ingest",
        )
        assert application.golden_data(
            _context(), ingested.golden_asset_revision.id
        ).rows == [{"region": "north", "sku": "A-1", "stock": 8}]

        traces = application.connector_traces(_context(), created.connection.id)
        assert [trace.transport for trace in traces] == [
            connector_transport,
            connector_transport,
        ]
        assert all(
            [exchange.method for exchange in trace.exchanges][:2]
            == ["initialize", "tools/list"]
            for trace in traces
        )
        assert [exchange.method for exchange in traces[-1].exchanges][-2:] == [
            "tools/call",
            "close",
        ]
        assert all(
            "Authorization" not in json.dumps(trace.model_dump()) for trace in traces
        )

        data_path.write_text(
            json.dumps([{"sku": "A-1", "region": "north", "stock": 9}]),
            encoding="utf-8",
        )
        refreshed = application.refresh(
            _context(),
            asset_id=ingested.golden_asset_revision.asset_id,
            idempotency_key=f"{connector_transport}-refresh",
            trace_id=f"trace-{connector_transport}-refresh",
        )
        assert refreshed.run.status == "succeeded"
        assert refreshed.golden_asset_revision is not None

        reopened = SourceGoldenApplication(
            database_path=tmp_path / f"{connector_transport}.sqlite3",
            artifact_root=tmp_path / f"{connector_transport}-artifacts",
            source_root=tmp_path,
            network_allow_private_hosts={"127.0.0.1"},
            secret_resolver=lambda _ref: None,
        )
        assert len(reopened.connector_traces(_context(), created.connection.id)) == 3


def test_webhook_accepts_signed_schema_valid_events_and_refreshes(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "inventory-event.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["sku", "stock"],
                "properties": {
                    "sku": {"type": "string"},
                    "stock": {"type": "integer"},
                },
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    secret = "webhook-test-secret-value"
    application = SourceGoldenApplication(
        database_path=tmp_path / "webhook.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=uploads,
        secret_resolver=lambda ref: (
            secret if ref == "secret://workspace-step3b/webhook" else None
        ),
    )
    created = application.create_connection(
        _context(),
        connector_key="webhook",
        display_name="Inventory webhook",
        scope="team",
        configuration={
            "listenPath": "/inventory/events",
            "schemaRef": "inventory-event.schema.json",
            "maxEventBytes": 10_000,
            "maxEvents": 10,
            "rateLimitPerMinute": 60,
        },
        secret_ref="secret://workspace-step3b/webhook",
        idempotency_key="webhook-create",
        trace_id="trace-webhook-create",
    )
    assert created.connection.status == "ready"
    assert created.discovery.resources[0].name == "/inventory/events"

    def deliver(event_id: str, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = (
            "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        )
        accepted = application.receive_webhook(
            _context(),
            connection_id=created.connection.id,
            path="/inventory/events",
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Id": event_id,
                "X-Webhook-Signature": signature,
            },
            body=body,
            trace_id=f"trace-{event_id}",
        )
        assert accepted.event_type == "webhook.delivery.accepted"

    deliver("delivery-1", {"sku": "A-1", "stock": 8})
    with pytest.raises(SourcesGoldenError) as replay:
        deliver("delivery-1", {"sku": "A-1", "stock": 8})
    assert replay.value.code == "WEBHOOK_REPLAY"

    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=[],
        idempotency_key="webhook-ingest",
        trace_id="trace-webhook-ingest",
    )
    assert ingested.source_revision.checkpoint["lastSequence"] == "1"
    assert application.golden_data(
        _context(), ingested.golden_asset_revision.id
    ).rows == [{"sku": "A-1", "stock": 8}]

    deliver("delivery-2", {"sku": "B-2", "stock": 3})
    refreshed = application.refresh(
        _context(),
        asset_id=ingested.golden_asset_revision.asset_id,
        idempotency_key="webhook-refresh",
        trace_id="trace-webhook-refresh",
    )
    assert refreshed.run.status == "succeeded"
    assert refreshed.golden_asset_revision is not None
    assert application.golden_data(
        _context(), refreshed.golden_asset_revision.id
    ).rows == [
        {"sku": "A-1", "stock": 8},
        {"sku": "B-2", "stock": 3},
    ]

    reopened = SourceGoldenApplication(
        database_path=tmp_path / "webhook.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=uploads,
        secret_resolver=lambda _ref: secret,
    )
    trace = reopened.connector_trace(
        _context(),
        created.connection.id,
        "trace-webhook-refresh",
    )
    assert [operation.operation for operation in trace.operations] == [
        "authenticate",
        "authorize",
        "refresh",
        "read",
        "profile",
        "clean",
        "golden",
        "checkpoint",
        "close",
    ]
    assert len(reopened.connector_events(_context(), created.connection.id)) == 2


def test_webhook_rejects_bad_signature_and_schema_without_persisting(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "event.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}},
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    secret = "webhook-test-secret-value"
    application = SourceGoldenApplication(
        database_path=tmp_path / "webhook.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=uploads,
        secret_resolver=lambda _ref: secret,
    )
    connection = application.create_connection(
        _context(),
        connector_key="webhook",
        display_name="Guarded webhook",
        scope="personal",
        configuration={
            "listenPath": "/guarded",
            "schemaRef": "event.schema.json",
        },
        secret_ref="secret://workspace-step3b/webhook",
        idempotency_key="guarded-create",
        trace_id="trace-guarded-create",
    ).connection

    with pytest.raises(SourcesGoldenError) as bad_signature:
        application.receive_webhook(
            _context(),
            connection_id=connection.id,
            path="/guarded",
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Id": "bad-signature",
                "X-Webhook-Signature": "sha256=wrong",
            },
            body=b'{"value":1}',
            trace_id="trace-bad-signature",
        )
    assert bad_signature.value.code == "WEBHOOK_AUTHENTICATION_FAILED"

    invalid = b'{"value":"not-an-integer"}'
    signature = (
        "sha256=" + hmac.new(secret.encode(), invalid, hashlib.sha256).hexdigest()
    )
    with pytest.raises(SourcesGoldenError) as bad_schema:
        application.receive_webhook(
            _context(),
            connection_id=connection.id,
            path="/guarded",
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Id": "bad-schema",
                "X-Webhook-Signature": signature,
            },
            body=invalid,
            trace_id="trace-bad-schema",
        )
    assert bad_schema.value.code == "WEBHOOK_SCHEMA_INVALID"
    assert application.connector_events(_context(), connection.id) == []
