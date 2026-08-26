from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import pytest

from frontend.server.knowledge_assets.sources_golden import SourceGoldenApplication
from frontend.server.knowledge_assets.sources_golden.connector_adapter import (
    ConnectorAdapterError,
    ConnectorRequest,
)


def test_lark_sheet_discovers_selected_sheet_and_reads_bounded_cells(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = unquote(urlsplit(str(request.url)).path)
        if path.endswith("/sheets/query"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "sheets": [
                            {
                                "sheet_id": "sheet-orders",
                                "title": "Orders",
                                "resource_type": "sheet",
                                "grid_properties": {
                                    "row_count": 200,
                                    "column_count": 20,
                                },
                            },
                            {
                                "sheet_id": "sheet-archive",
                                "title": "Archive",
                                "resource_type": "sheet",
                            },
                        ]
                    },
                },
            )
        assert path.endswith(
            "/sheets/v2/spreadsheets/sht_token/values/sheet-orders!A1:C3"
        )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "revision": 7,
                    "spreadsheetToken": "sht_token",
                    "valueRange": {
                        "majorDimension": "ROWS",
                        "range": "sheet-orders!A1:C3",
                        "revision": 7,
                        "values": [
                            ["order_id", "amount", "active"],
                            ["A-1", 12, True],
                            ["B-2", 13, False],
                        ],
                    },
                },
            },
        )

    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps({"accessToken": "runtime-token"}),
        http_transport=httpx.MockTransport(handle),
    )
    adapter = application.connector_adapters()["lark_sheet"]
    request = ConnectorRequest(
        connector_key="lark_sheet",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        connection_id="connection-step3b",
        configuration={
            "sheetRef": "sht_token",
            "sheetName": "Orders",
            "cellRange": "A1:C3",
            "scopeRef": "scope-lark-sheet",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 100,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref="secret://workspace-step3b/lark",
        trace_id="trace-lark-sheet",
    )

    discovered = adapter.discover(request)

    assert [(item.name, item.schema_name) for item in discovered.resources] == [
        ("Orders", "sheet-orders")
    ]
    selected = request.__class__(
        **{**request.__dict__, "resource": discovered.resources[0]}
    )
    result = adapter.read(selected)

    assert result.rows == [
        {"order_id": "A-1", "amount": 12, "active": True},
        {"order_id": "B-2", "amount": 13, "active": False},
    ]
    assert result.checkpoint["providerRevision"] == "7"
    assert [item.method for item in requests] == ["GET", "GET"]


@pytest.mark.parametrize(
    ("status_code", "error_code", "stage"),
    [
        (401, "OFFICE_PERMISSION_REVOKED", "authorize"),
        (403, "OFFICE_PERMISSION_REVOKED", "authorize"),
        (404, "OFFICE_RESOURCE_DELETED", "read"),
    ],
)
def test_lark_sheet_maps_http_status_to_typed_provider_error(
    tmp_path: Path,
    status_code: int,
    error_code: str,
    stage: str,
) -> None:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
        web_resolver=lambda _host: ["93.184.216.34"],
        secret_resolver=lambda _ref: json.dumps({"accessToken": "runtime-token"}),
        http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"code": status_code})
        ),
    )
    request = ConnectorRequest(
        connector_key="lark_sheet",
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        configuration={
            "sheetRef": "sht_token",
            "sheetName": "Orders",
            "cellRange": "A1:C3",
            "scopeRef": "scope-lark-sheet",
            "apiBaseUrl": "https://open.feishu.cn/open-apis",
            "pageSize": 100,
            "maxPages": 5,
            "maxResponseBytes": 100_000,
            "rateLimitPerMinute": 30,
            "timeoutSeconds": 5,
            "refreshSeconds": 60,
        },
        secret_ref="secret://workspace-step3b/lark",
        trace_id=f"trace-lark-sheet-{status_code}",
    )

    with pytest.raises(ConnectorAdapterError) as failure:
        application.connector_adapters()["lark_sheet"].discover(request)

    assert failure.value.code == error_code
    assert failure.value.stage == stage
