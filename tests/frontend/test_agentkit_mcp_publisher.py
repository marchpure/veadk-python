from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.extensions.agentkit_mcp import (
    AgentKitMcpClient,
    AgentKitMcpPublicationRepository,
    AgentKitMcpPublisher,
    PublicationCreateRequest,
    mount_agentkit_mcp_routes,
)
from frontend.server.knowledge_workspace.service import Actor


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = False
        self.fail_toolset = False

    async def post(self, *, region: str, action: str, payload: dict) -> dict:
        self.calls.append((action, payload))
        if self.fail or (self.fail_toolset and action == "CreateMCPToolset"):
            raise RuntimeError("control plane unavailable")
        if action == "CreateMCPService":
            return {"Result": {"MCPServiceId": "svc-1"}, "ResponseMetadata": {"RequestId": "req-1"}}
        if action == "CreateMCPToolset":
            return {
                "Result": {
                    "MCPToolsetId": "toolset-1",
                    "GatewayEndpoint": "https://gateway.example/mcp",
                    "Version": "v1",
                },
                "ResponseMetadata": {"RequestId": "req-2"},
            }
        if action == "VerifyMCPToolset":
            return {"Result": {"verified": True}}
        return {}


def build_publisher(fake: FakeTransport) -> AgentKitMcpPublisher:
    return AgentKitMcpPublisher(
        AgentKitMcpPublicationRepository(),
        AgentKitMcpClient(fake),
    )


@pytest.mark.asyncio
async def test_publication_is_idempotent_and_does_not_persist_runtime_secret() -> None:
    fake = FakeTransport()
    publisher = build_publisher(fake)
    request = PublicationCreateRequest(
        accessPackageId="pkg-1",
        runtimeTokenId="credential-provider://runtime-token-1",
        backendEndpointRef="https://connector.example",
        desiredVersion="v1",
    )
    first = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request,
        idempotency_key="pub-key",
    )
    second = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request,
        idempotency_key="pub-key",
    )

    assert first.publication_id == second.publication_id
    assert [action for action, _ in fake.calls] == [
        "CreateMCPService",
        "CreateMCPToolset",
    ]
    assert "runtime-secret" not in first.model_dump_json()
    assert request.runtime_token_id in fake.calls[0][1]["OutboundCredentialRef"]


@pytest.mark.asyncio
async def test_failed_retry_reuses_partial_resource_reference() -> None:
    fake = FakeTransport()
    publisher = build_publisher(fake)
    request = PublicationCreateRequest(
        accessPackageId="pkg-1",
        runtimeTokenId="credential-provider://runtime-token-1",
        backendEndpointRef="https://connector.example",
        desiredVersion="v1",
    )
    fake.fail_toolset = True
    failed = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request,
        idempotency_key="pub-key",
    )
    assert failed.status == "FAILED"
    fake.fail_toolset = False
    fake.fail = False
    recovered = await publisher.retry(failed, idempotency_key="retry-key")
    assert recovered.status == "LIVE"
    assert [action for action, _ in fake.calls] == [
        "CreateMCPService",
        "CreateMCPToolset",
        "CreateMCPToolset",
        "CreateMCPToolset",
    ]


@pytest.mark.asyncio
async def test_routes_scope_publications_to_actor_and_require_idempotency() -> None:
    app = FastAPI()
    publisher = build_publisher(FakeTransport())
    mount_agentkit_mcp_routes(
        app,
        publisher,
        actor_resolver=lambda request: Actor(
            tenant_id=request.headers["x-tenant-id"],
            workspace_id=request.headers["x-workspace-id"],
            principal_id="principal-a",
        ),
    )
    body = {
        "accessPackageId": "pkg-1",
        "runtimeTokenId": "credential-provider://runtime-token-1",
        "backendEndpointRef": "https://connector.example",
        "desiredVersion": "v1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"x-tenant-id": "tenant-a", "x-workspace-id": "workspace-a"}
        missing = await client.post("/api/data-workshop/v1/publications", headers=headers, json=body)
        created = await client.post(
            "/api/data-workshop/v1/publications",
            headers={**headers, "idempotency-key": "key-a"},
            json=body,
        )
        foreign = await client.get(
            f"/api/data-workshop/v1/publications/{created.json()['data']['publicationId']}",
            headers={**headers, "x-workspace-id": "workspace-b"},
        )
    assert missing.status_code == 400
    assert created.status_code == 202
    assert foreign.status_code == 404
