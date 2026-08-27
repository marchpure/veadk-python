from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
    mount_source_golden_routes,
)


def _client(tmp_path: Path) -> tuple[TestClient, SourceGoldenApplication]:
    application = SourceGoldenApplication(
        database_path=tmp_path / "sources.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path / "uploads",
    )
    app = FastAPI()

    def identity(request: Request) -> AccessContext:
        role = cast(
            Literal["viewer", "editor", "admin"],
            request.headers.get("X-Role", "editor"),
        )
        return AccessContext(
            workspace_id=request.headers.get("X-Workspace", "workspace-a"),
            principal_id=request.headers.get("X-Principal", "user-a"),
            role=role,
        )

    mount_source_golden_routes(
        app,
        application=application,
        identity_resolver=identity,
    )
    return TestClient(app), application


def _headers(key: str, **extra: str) -> dict[str, str]:
    return {"Idempotency-Key": key, "X-Request-ID": f"trace-{key}", **extra}


def test_http_api_upload_create_ingest_read_refresh_context_and_revoke(
    tmp_path: Path,
) -> None:
    client, _application = _client(tmp_path)
    catalog = client.get("/api/source-golden/v1/catalog")
    assert catalog.status_code == 200
    mcp = next(
        item
        for item in catalog.json()["connectors"]
        if item["connectorKey"] == "mcp_custom"
    )
    assert mcp["inputSchema"]["properties"] == {
        "profileId": {
            "type": "string",
            "title": "Server MCP profile",
            "required": True,
            "description": (
                "Identifier of an MCP profile registered and resolved by the server."
            ),
            "default": None,
            "options": [],
            "secretReference": False,
            "format": None,
            "min": None,
            "max": None,
            "conditional": None,
        }
    }
    assert mcp["credentialSchema"]["properties"] == {}
    serialized_mcp = json.dumps(mcp)
    for server_only_field in ("command", "args", "env", "cwd"):
        assert f'"{server_only_field}"' not in serialized_mcp
    assert '"secretRef"' not in serialized_mcp

    uploaded = client.post(
        "/api/source-golden/v1/uploads",
        files={"upload": ("metrics.csv", b"service,cpu\nedge,21\n", "text/csv")},
    )
    assert uploaded.status_code == 201
    upload = uploaded.json()
    assert upload["sourceRef"].startswith("workspace-")
    assert upload["sourceRef"].endswith(".csv")
    assert "/" not in upload["sourceRef"].split("/", 1)[1]

    created = client.post(
        "/api/source-golden/v1/connections",
        headers=_headers("create"),
        json={
            "connectorKey": "csv",
            "displayName": "Metrics",
            "scope": "personal",
            "configuration": {"sourceRef": upload["sourceRef"]},
        },
    )
    assert created.status_code == 201
    connection = created.json()["connection"]
    assert "configuration" not in connection
    assert "secretRef" not in connection
    resource_id = created.json()["discovery"]["resources"][0]["id"]

    ingested = client.post(
        f"/api/source-golden/v1/connections/{connection['id']}/ingestions",
        headers=_headers("ingest"),
        json={"resourceId": resource_id, "recipeOperations": ["trim"]},
    )
    assert ingested.status_code == 200
    result = ingested.json()
    golden = result["goldenAssetRevision"]
    source = result["sourceRevision"]

    detail = client.get(f"/api/source-golden/v1/connections/{connection['id']}")
    assert detail.status_code == 200
    assert detail.json()["connection"]["id"] == connection["id"]
    assert "configuration" not in detail.json()["connection"]
    operations = client.get(
        f"/api/source-golden/v1/connections/{connection['id']}/operations"
    )
    assert operations.status_code == 200
    assert {item["operation"] for item in operations.json()} >= {
        "discover",
        "read",
        "checkpoint",
    }
    trace = client.get(
        f"/api/source-golden/v1/connections/{connection['id']}/traces/trace-ingest"
    )
    assert trace.status_code == 200
    assert trace.json()["traceId"] == "trace-ingest"
    assert {item["operation"] for item in trace.json()["operations"]} >= {
        "read",
        "checkpoint",
    }

    data = client.get(f"/api/source-golden/v1/golden-revisions/{golden['id']}")
    assert data.status_code == 200
    assert data.json()["rows"] == [{"cpu": 21, "service": "edge"}]
    asset_detail = client.get(
        f"/api/source-golden/v1/golden-assets/{golden['assetId']}"
    )
    assert asset_detail.status_code == 200
    assert asset_detail.json()["asset"]["id"] == golden["id"]
    content = client.get(
        f"/api/source-golden/v1/golden-revisions/{golden['id']}/content"
    )
    assert content.status_code == 200
    assert content.headers["cache-control"] == "private, no-store"
    assert b'"service": "edge"' in content.content

    reference = {
        "kind": "golden_asset",
        "objectId": golden["assetId"],
        "revision": golden["id"],
        "providerRevision": source["id"],
    }
    resolved = client.post(
        "/api/source-golden/v1/context/resolve",
        json={"reference": reference},
    )
    assert resolved.status_code == 200
    assert resolved.json()["revision"] == golden["id"]
    caller_freshness_override = client.post(
        "/api/source-golden/v1/context/resolve",
        json={"reference": reference, "maxAgeSeconds": 31_536_000},
    )
    assert caller_freshness_override.status_code == 422

    refreshed = client.post(
        f"/api/source-golden/v1/golden-assets/{golden['assetId']}/refresh",
        headers=_headers("refresh"),
        json={},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["run"]["status"] == "succeeded"

    restarted_client, _restarted_application = _client(tmp_path)
    restored = restarted_client.get("/api/source-golden/v1/overview")
    assert restored.status_code == 200
    assert [item["id"] for item in restored.json()["connections"]] == [connection["id"]]
    assert restored.json()["goldenAssets"][0]["assetId"] == golden["assetId"]
    restored_content = restarted_client.get(
        f"/api/source-golden/v1/golden-revisions/"
        f"{refreshed.json()['goldenAssetRevision']['id']}/content"
    )
    assert restored_content.status_code == 200
    assert b'"service": "edge"' in restored_content.content

    revoked = restarted_client.request(
        "DELETE",
        f"/api/source-golden/v1/connections/{connection['id']}",
        headers=_headers("revoke"),
        json={"reason": "test complete"},
    )
    assert revoked.status_code == 204
    denied = restarted_client.post(
        "/api/source-golden/v1/context/resolve",
        json={"reference": reference},
    )
    assert denied.status_code == 404
    assert denied.json()["code"] == "GOLDEN_REVISION_NOT_FOUND"


def test_http_api_rejects_browser_supplied_mcp_execution_configuration(
    tmp_path: Path,
) -> None:
    client, application = _client(tmp_path)
    response = client.post(
        "/api/source-golden/v1/connections",
        headers=_headers("unsafe-mcp"),
        json={
            "connectorKey": "mcp_custom",
            "displayName": "Unsafe MCP",
            "configuration": {
                "transport": "stdio",
                "command": "python",
                "args": ["server.py"],
                "env": {"TOKEN": "plaintext"},
                "cwd": "/tmp",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "MCP_BROWSER_CONFIGURATION_FORBIDDEN"
    assert (
        application.data_overview(
            AccessContext(
                workspace_id="workspace-a",
                principal_id="user-a",
                role="editor",
            )
        ).connections
        == []
    )


def test_http_api_uses_server_identity_and_workspace_scoped_uploads(
    tmp_path: Path,
) -> None:
    client, _application = _client(tmp_path)
    first = client.post(
        "/api/source-golden/v1/uploads",
        headers={"X-Workspace": "workspace-a"},
        files={"upload": ("same.csv", b"id\n1\n", "text/csv")},
    ).json()
    second = client.post(
        "/api/source-golden/v1/uploads",
        headers={"X-Workspace": "workspace-b"},
        files={"upload": ("same.csv", b"id\n1\n", "text/csv")},
    ).json()
    assert first["sha256"] == second["sha256"]
    assert first["sourceRef"] != second["sourceRef"]

    cross_workspace_source = client.post(
        "/api/source-golden/v1/connections",
        headers=_headers("cross-source", **{"X-Workspace": "workspace-b"}),
        json={
            "connectorKey": "csv",
            "displayName": "Foreign upload",
            "configuration": {"sourceRef": first["sourceRef"]},
        },
    )
    assert cross_workspace_source.status_code == 422
    assert cross_workspace_source.json()["code"] == "UPLOAD_WORKSPACE_MISMATCH"

    traversal_source = client.post(
        "/api/source-golden/v1/connections",
        headers=_headers("traversal-source"),
        json={
            "connectorKey": "csv",
            "displayName": "Traversed upload",
            "configuration": {
                "sourceRef": f"{first['sourceRef'].split('/', 1)[0]}/../"
                f"{second['sourceRef']}"
            },
        },
    )
    assert traversal_source.status_code == 422
    assert traversal_source.json()["code"] == "UPLOAD_WORKSPACE_MISMATCH"

    created = client.post(
        "/api/source-golden/v1/connections",
        headers=_headers("create-private"),
        json={
            "connectorKey": "csv",
            "displayName": "Private",
            "scope": "personal",
            "configuration": {"sourceRef": first["sourceRef"]},
        },
    ).json()
    resource_id = created["discovery"]["resources"][0]["id"]
    ingested = client.post(
        f"/api/source-golden/v1/connections/{created['connection']['id']}/ingestions",
        headers=_headers("ingest-private"),
        json={"resourceId": resource_id},
    ).json()
    reference = {
        "objectId": ingested["goldenAssetRevision"]["assetId"],
        "revision": ingested["goldenAssetRevision"]["id"],
        "providerRevision": ingested["sourceRevision"]["id"],
    }

    foreign_workspace = client.post(
        "/api/source-golden/v1/context/resolve",
        headers={"X-Workspace": "workspace-b"},
        json={"reference": reference},
    )
    forged_principal = client.post(
        "/api/source-golden/v1/context/resolve",
        headers={"X-Principal": "user-forged"},
        json={"reference": reference},
    )
    assert foreign_workspace.status_code == 404
    assert forged_principal.status_code == 403


def test_http_api_requires_idempotency_and_rejects_oversized_upload(
    tmp_path: Path,
) -> None:
    client, _application = _client(tmp_path)
    missing_key = client.post(
        "/api/source-golden/v1/connections",
        json={
            "connectorKey": "csv",
            "displayName": "Missing key",
            "configuration": {"sourceRef": "missing.csv"},
        },
    )
    oversized = client.post(
        "/api/source-golden/v1/uploads",
        files={
            "upload": (
                "oversized.csv",
                b"x" * (10 * 1024 * 1024 + 1),
                "text/csv",
            )
        },
    )
    unsupported = client.post(
        "/api/source-golden/v1/uploads",
        files={"upload": ("payload.exe", b"binary", "application/octet-stream")},
    )

    assert missing_key.status_code == 422
    assert missing_key.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "UPLOAD_SIZE_LIMIT"
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "UPLOAD_TYPE_UNSUPPORTED"
