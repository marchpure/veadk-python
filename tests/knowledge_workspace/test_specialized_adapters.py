from __future__ import annotations

import io
import json
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.knowledge_workspace.autoskill import UnavailableAutoSkillClient
from frontend.server.knowledge_workspace.connection import (
    ConnectionServiceConfig,
    ConnectionServiceGateway,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.routes import mount_knowledge_workspace_routes
from frontend.server.knowledge_workspace.service import KnowledgeWorkspaceService


ACTOR_HEADERS = {
    "x-tenant-id": "tenant-a",
    "x-workspace-id": "workspace-a",
    "x-principal-id": "user-a",
}


def test_adapter_capabilities_preserve_beta_tier() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/adapters/capabilities"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "service": name,
                        "displayName": name,
                        "tier": "beta",
                        "connectorDefinitionVersion": "1.0.0",
                        "capabilities": ["discover"],
                        "configSchema": {"type": "object"},
                        "authSchema": {"type": "object"},
                        "endpoints": [f"/v1/adapters/{name}"],
                    }
                    for name in ("oracle_database", "rest_openapi", "mcp", "files")
                ]
            },
        )

    gateway = ConnectionServiceGateway(
        ConnectionServiceConfig("https://connections.test", "test-secret"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    import asyncio

    items = asyncio.run(gateway.adapter_capabilities(**{
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "principal_id": "user-a",
    }))
    assert [item["connector_key"] for item in items] == [
        "oracle_database",
        "rest_openapi",
        "mcp",
        "files",
    ]
    assert all(item["status"] == "beta" for item in items)


class SpecializedGateway:
    async def catalog(self, **_: str) -> list[dict[str, object]]:
        return []

    async def adapter_capabilities(self, **_: str) -> list[dict[str, object]]:
        return [
            {
                "connector_key": name,
                "version": "1.0.0",
                "display_name": name,
                "category": "adapter",
                "status": "beta",
                "capabilities": ["validate", "discover"],
                "config_schema": {"type": "object"},
                "auth_schema": {"type": "object"},
            }
            for name in ("oracle_database", "rest_openapi", "mcp", "files")
        ]

    async def validate_rest(self, body: dict[str, object], **_: str) -> dict[str, object]:
        assert body["baseUrl"] == "https://example.test"
        return {"definitionVersion": "1", "operations": [{"operationId": "health"}]}

    async def validate_oracle(self, body: dict[str, object], **_: str) -> dict[str, object]:
        assert body["config"]["serviceName"] == "FREEPDB1"
        return {"rows": [{"OK": 1}]}

    async def discover_oracle(self, body: dict[str, object], **_: str) -> dict[str, object]:
        assert body["config"]["serviceName"] == "FREEPDB1"
        return {"schemas": ["APP"], "schema": "APP", "tables": ["ORDERS"]}

    async def discover_mcp(self, definition: dict[str, object], **_: str) -> dict[str, object]:
        assert definition["transport"] == "stdio"
        return {"tools": [{"name": "echo"}], "resources": [], "prompts": []}

    async def register_mcp(self, definition: dict[str, object], **_: str) -> dict[str, object]:
        assert definition["transport"] == "stdio"
        return {"id": "mcp-definition-1"}

    async def upload_file(self, **_: object) -> str:
        return "internal-file-1"

    async def list_files(self, **_: str) -> list[dict[str, object]]:
        return [{"fileId": "internal-file-1", "name": "data.csv", "tenantId": "tenant-a"}]

    async def preview_file(self, file_id: str, **_: str) -> dict[str, object]:
        assert file_id == "internal-file-1"
        return {"kind": "csv", "columns": ["name"], "rows": [["Ada"]]}


@pytest.fixture
def specialized_app(tmp_path) -> FastAPI:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(object_root=tmp_path / "objects"),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(
        app,
        service,
        connection_gateway=SpecializedGateway(),  # type: ignore[arg-type]
        allow_insecure_test_headers=True,
    )
    return app


@pytest.mark.asyncio
async def test_specialized_routes_validate_discover_register_and_preview(
    specialized_app: FastAPI,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=specialized_app),
        base_url="http://test",
    ) as client:
        definitions = await client.get(
            "/api/knowledge/v1/connector-definitions",
            headers=ACTOR_HEADERS,
        )
        assert definitions.status_code == 200
        assert {
            item["connector_key"] for item in definitions.json()["data"]
        } == {"oracle_database", "rest_openapi", "mcp", "files"}
        assert all(
            item["status"] == "beta" for item in definitions.json()["data"]
        )

        rest = await client.post(
            "/api/knowledge/v1/adapters/rest/validate",
            headers=ACTOR_HEADERS,
            json={"baseUrl": "https://example.test", "spec": {}},
        )
        assert rest.json()["data"]["operations"][0]["operationId"] == "health"

        oracle_body = {
            "config": {"host": "oracle.test", "port": 1521, "serviceName": "FREEPDB1"},
            "user": "reader",
            "password": "secret",
        }
        oracle = await client.post(
            "/api/knowledge/v1/adapters/oracle/validate",
            headers=ACTOR_HEADERS,
            json=oracle_body,
        )
        discovery = await client.post(
            "/api/knowledge/v1/adapters/oracle/discover",
            headers=ACTOR_HEADERS,
            json=oracle_body,
        )
        assert oracle.json()["data"]["rows"] == [{"OK": 1}]
        assert discovery.json()["data"]["tables"] == ["ORDERS"]

        definition = {"transport": "stdio", "command": "echo"}
        mcp = await client.post(
            "/api/knowledge/v1/adapters/mcp/discover",
            headers=ACTOR_HEADERS,
            json={"definition": definition},
        )
        registered = await client.post(
            "/api/knowledge/v1/adapters/mcp/register",
            headers=ACTOR_HEADERS,
            json={"definition": definition},
        )
        assert mcp.json()["data"]["tools"][0]["name"] == "echo"
        assert registered.json()["data"]["id"] == "mcp-definition-1"

        upload = await client.post(
            "/api/knowledge/v1/uploads",
            headers={**ACTOR_HEADERS, "idempotency-key": "specialized-file-key"},
            data={"purpose": "context"},
            files={"file": ("data.csv", b"name\nAda\n", "text/csv")},
        )
        assert upload.status_code == 201
        upload_id = upload.json()["data"]["upload_id"]
        files = await client.get(
            "/api/knowledge/v1/adapter-files", headers=ACTOR_HEADERS
        )
        assert "internal-file-1" not in files.text
        preview = await client.get(
            f"/api/knowledge/v1/adapter-files/{upload_id}/preview",
            headers=ACTOR_HEADERS,
        )
        assert preview.json()["data"]["rows"] == [["Ada"]]
        assert "internal-file-1" not in preview.text
