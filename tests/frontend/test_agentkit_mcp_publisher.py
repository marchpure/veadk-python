from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.extensions.agentkit_mcp import (
    AgentKitMcpClient,
    AgentKitMcpError,
    AgentKitMcpPublicationRepository,
    AgentKitMcpPublisher,
    GatewayVerification,
    PublicationCreateRequest,
    mount_agentkit_mcp_routes,
)
from frontend.server.knowledge_workspace.service import Actor


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_toolset = False
        self.toolset_generation = 0

    async def post(self, *, region: str, action: str, payload: dict) -> dict:
        self.calls.append((action, payload))
        metadata = {"ResponseMetadata": {"RequestId": f"req-{len(self.calls)}"}}
        if action == "CreateMCPService":
            return {**metadata, "Result": {"MCPServiceId": "m-service-1"}}
        if action == "GetMCPService":
            return {
                **metadata,
                "Result": {
                    "MCPService": {
                        "Id": "m-service-1",
                        "Status": "Ready",
                    }
                },
            }
        if action == "CreateMCPToolset":
            if self.fail_toolset:
                raise RuntimeError("control plane unavailable")
            self.toolset_generation += 1
            return {
                **metadata,
                "Result": {"MCPToolsetId": f"mt-toolset-{self.toolset_generation}"},
            }
        if action == "GetMCPToolset":
            toolset_id = payload["MCPToolsetId"]
            return {
                **metadata,
                "Result": {
                    "MCPToolset": {
                        "Id": toolset_id,
                        "Status": "Ready",
                        "Path": "/mcp",
                        "NetworkConfigurations": [
                            {"Endpoint": "gateway.example"}
                        ],
                    }
                },
            }
        if action == "DeleteMCPToolset":
            return {**metadata, "Result": {"MCPToolsetId": payload["MCPToolsetId"]}}
        raise AssertionError(action)


class FakeVerifier:
    def __init__(self, *, live: bool = True) -> None:
        self.live = live
        self.calls = 0

    async def verify(self, publication) -> GatewayVerification:
        self.calls += 1
        return GatewayVerification(
            initialize_pass=self.live,
            tools_list_pass=self.live,
            allowed_call_pass=self.live,
            denied_call_pass=self.live,
            live_tools_count=6 if self.live else 0,
            observed_version="2025-03-26" if self.live else None,
        )


def request_body() -> PublicationCreateRequest:
    return PublicationCreateRequest(
        accessPackageId="pkg-1",
        runtimeTokenId="credential-provider://openconnector-runtime-pkg-1",
        backendEndpointRef="https://connector.example/mcp",
        desiredVersion="v1",
        allowedClientRef="client-1",
        customJwtDiscoveryUrl="https://identity.example/.well-known/openid-configuration",
    )


def build_publisher(
    fake: FakeTransport, *, verifier: FakeVerifier | None = None
) -> AgentKitMcpPublisher:
    return AgentKitMcpPublisher(
        AgentKitMcpPublicationRepository(),
        AgentKitMcpClient(
            fake,
            poll_attempts=2,
            poll_interval_seconds=0,
        ),
        verifier=verifier,
    )


@pytest.mark.asyncio
async def test_official_payload_is_idempotent_and_code_ready_until_live_verify() -> None:
    fake = FakeTransport()
    verifier = FakeVerifier()
    publisher = build_publisher(fake, verifier=verifier)
    request = request_body()

    first = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request,
    )
    second = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request,
    )

    assert first.publication_id == second.publication_id
    assert first.status == "CODE_READY"
    assert [action for action, _ in fake.calls] == [
        "CreateMCPService",
        "GetMCPService",
        "CreateMCPToolset",
        "GetMCPToolset",
    ]
    service_payload = fake.calls[0][1]
    assert service_payload["ProtocolType"] == "MCP"
    assert service_payload["Path"] == "/mcp"
    assert service_payload["BackendType"] == "Domain"
    assert service_payload["BackendConfiguration"]["CustomConfiguration"] == {
        "Domain": "connector.example",
        "Port": 443,
        "ProtocolType": "HTTPS",
        "TlsSettings": {"TlsMode": "SIMPLE"},
    }
    identity = service_payload["OutboundAuthorizerConfiguration"]["Authorizer"][
        "IdentityAuthorizer"
    ]
    assert identity == {
        "CredentialProviderName": "openconnector-runtime-pkg-1",
        "ProviderType": "ApiKey",
    }
    assert "runtime-secret" not in first.model_dump_json()
    assert len(service_payload["ClientToken"]) == 64

    verified = await publisher.verify(first)
    assert verified.live is True
    assert first.status == "LIVE"
    assert first.observed_version == "2025-03-26"


@pytest.mark.asyncio
async def test_failed_toolset_retry_reuses_service_and_preserves_ids() -> None:
    fake = FakeTransport()
    publisher = build_publisher(fake)
    fake.fail_toolset = True
    failed = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )

    assert failed.status == "FAILED"
    assert failed.mcp_service_id == "m-service-1"
    assert failed.toolset_id is None
    assert failed.last_error == "RuntimeError"

    fake.fail_toolset = False
    recovered = await publisher.retry(failed)
    assert recovered.status == "CODE_READY"
    assert recovered.mcp_service_id == "m-service-1"
    assert [action for action, _ in fake.calls].count("CreateMCPService") == 1
    assert [action for action, _ in fake.calls].count("CreateMCPToolset") == 3


@pytest.mark.asyncio
async def test_disable_deletes_owned_toolset_and_restore_reuses_service() -> None:
    fake = FakeTransport()
    publisher = build_publisher(fake)
    publication = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )
    old_toolset = publication.toolset_id
    original_token = next(
        payload["ClientToken"]
        for action, payload in fake.calls
        if action == "CreateMCPToolset"
    )

    disabled = await publisher.disable(publication)
    assert disabled.status == "DISABLED"
    assert fake.calls[-1] == (
        "DeleteMCPToolset",
        {"MCPToolsetId": old_toolset},
    )

    restored = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )
    assert restored.status == "CODE_READY"
    assert restored.mcp_service_id == "m-service-1"
    assert restored.toolset_id != old_toolset
    new_token = [
        payload["ClientToken"]
        for action, payload in fake.calls
        if action == "CreateMCPToolset"
    ][-1]
    assert new_token != original_token
    assert [action for action, _ in fake.calls].count("CreateMCPService") == 1


@pytest.mark.asyncio
async def test_routes_scope_publications_and_reject_plain_runtime_token() -> None:
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
    body = request_body().model_dump(mode="json", by_alias=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"x-tenant-id": "tenant-a", "x-workspace-id": "workspace-a"}
        rejected = await client.post(
            "/api/data-workshop/v1/publications",
            headers=headers,
            json={**body, "runtimeTokenId": "oct_plaintext"},
        )
        created = await client.post(
            "/api/data-workshop/v1/publications",
            headers=headers,
            json=body,
        )
        foreign = await client.get(
            f"/api/data-workshop/v1/publications/{created.json()['data']['publicationId']}",
            headers={**headers, "x-workspace-id": "workspace-b"},
        )

    assert rejected.status_code == 422
    assert "oct_plaintext" not in rejected.text
    assert created.status_code == 202
    assert created.json()["data"]["status"] == "CODE_READY"
    assert foreign.status_code == 404


def test_repository_reserve_is_atomic_for_business_key() -> None:
    repository = AgentKitMcpPublicationRepository()
    body = request_body()
    first = repository.reserve(
        _publication("pub-first", body),
        idempotency_key="business-key",
    )
    second = repository.reserve(
        _publication("pub-second", body),
        idempotency_key="business-key",
    )

    assert first.publication_id == "pub-first"
    assert second.publication_id == "pub-first"


def test_ecs_backend_uses_official_instance_shape() -> None:
    request = request_body().model_copy(
        update={
            "backend_type": "ECS",
            "backend_instance_id": "i-example",
            "backend_instance_ip": "10.0.0.8",
            "backend_endpoint_ref": "http://10.0.0.8:3000/mcp",
        }
    )

    payload = AgentKitMcpClient._service_payload(request, "workspace-a")

    assert payload["BackendType"] == "ECS"
    assert payload["BackendConfiguration"] == {
        "EcsConfiguration": {
            "Instances": [
                {
                    "InstanceId": "i-example",
                    "Ip": "10.0.0.8",
                    "Port": 3000,
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_same_business_key_rejects_different_configuration() -> None:
    publisher = build_publisher(FakeTransport())
    first = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )
    conflicting = request_body().model_copy(
        update={"backend_endpoint_ref": "https://other.example/mcp"}
    )

    with pytest.raises(AgentKitMcpError, match="different configuration"):
        await publisher.create_or_reuse(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            request=conflicting,
        )
    assert first.mcp_service_id == "m-service-1"


@pytest.mark.asyncio
async def test_toolset_error_and_timeout_are_not_code_ready() -> None:
    class ErrorTransport(FakeTransport):
        async def post(self, *, region: str, action: str, payload: dict) -> dict:
            response = await super().post(
                region=region, action=action, payload=payload
            )
            if action == "GetMCPToolset":
                response["Result"]["MCPToolset"]["Status"] = "Error"
            return response

    failed = await build_publisher(ErrorTransport()).create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )
    assert failed.status == "FAILED"
    assert failed.last_error == "MCP_TOOLSET_ERROR"

    class PendingTransport(FakeTransport):
        async def post(self, *, region: str, action: str, payload: dict) -> dict:
            response = await super().post(
                region=region, action=action, payload=payload
            )
            if action == "GetMCPService":
                response["Result"]["MCPService"]["Status"] = "Creating"
            return response

    timed_out = await build_publisher(PendingTransport()).create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )
    assert timed_out.status == "FAILED"
    assert timed_out.last_error == "CONTROL_PLANE_TIMEOUT"


@pytest.mark.asyncio
async def test_verify_without_live_verifier_fails_closed() -> None:
    publisher = build_publisher(FakeTransport())
    publication = await publisher.create_or_reuse(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        request=request_body(),
    )

    with pytest.raises(
        AgentKitMcpError, match="data-plane verification is not configured"
    ):
        await publisher.verify(publication)
    assert publication.status == "CODE_READY"


def _publication(
    publication_id: str, request: PublicationCreateRequest
):
    from frontend.server.extensions.agentkit_mcp.models import (
        AgentKitMcpPublication,
    )

    return AgentKitMcpPublication(
        publicationId=publication_id,
        tenantId="tenant-a",
        workspaceId="workspace-a",
        accessPackageId=request.access_package_id,
        runtimeTokenId=request.runtime_token_id,
        backendEndpointRef=request.backend_endpoint_ref,
        inboundAuthMode=request.inbound_auth_mode,
        allowedClientRef=request.allowed_client_ref,
        customJwtDiscoveryUrl=request.custom_jwt_discovery_url,
        desiredVersion=request.desired_version,
        status="PROVISIONING",
    )
