from __future__ import annotations

import sqlite3

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.extensions.agentkit_mcp import (
    AgentKitMcpClient,
    AgentKitMcpPublicationRepository,
    AgentKitMcpPublisher,
    GatewayVerification,
    ManagedPublicationRepository,
    ManagedPublicationService,
    mount_managed_mcp_routes,
)
from frontend.server.extensions.agentkit_mcp.domain import (
    ActionPolicy,
    ManagedPublicationCreateRequest,
    ManagedPublicationStatus,
    assert_publication_transition,
)
from frontend.server.extensions.agentkit_mcp.managed_service import resolve_actions
from frontend.server.knowledge_workspace.connection import ConnectionServiceConfig
from frontend.server.knowledge_workspace.service import Actor


class FakeConnectionGateway:
    config = ConnectionServiceConfig(
        base_url="https://connections.example",
        auth_secret="test-only-signing-value",
        runtime_public_url="https://openconnector.example/mcp",
    )

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.revoked: list[str] = []

    async def list_connections(self, **actor):
        return [
            {
                "connection_id": "connection-1",
                "connector_key": "sales",
                "display_name": "Sales",
                "status": "ready",
                "mcp_endpoint": "https://openconnector.example/mcp",
            },
            {
                "connection_id": "connection-2",
                "connector_key": "sales",
                "display_name": "Sales archive",
                "status": "ready",
                "mcp_endpoint": "https://openconnector.example/mcp",
            },
        ]

    async def catalog(self, **actor):
        return [
            {
                "connector_key": "sales",
                "actionIds": [
                    "orders.list",
                    "orders.get",
                    "orders.create",
                    "orders.mystery",
                ],
            }
        ]

    async def create_runtime_token(self, **kwargs):
        self.created.append(kwargs)
        number = len(self.created)
        return f"runtime-record-{number}", f"one-time-secret-{number}"

    async def revoke_runtime_token(self, record_id, **actor):
        self.revoked.append(record_id)


class FakeCredentialProvider:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.fail_once = False
        self.fail_delete = False

    async def create(self, *, name: str, plaintext: str) -> str:
        self.created.append((name, plaintext))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("credential secret=must-not-leak")
        return f"credential-provider://{name}"

    async def delete(self, provider_ref: str) -> None:
        if self.fail_delete:
            raise RuntimeError("credential secret=must-not-leak")
        self.deleted.append(provider_ref)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.count = 0

    async def post(self, *, region: str, action: str, payload: dict) -> dict:
        self.calls.append((action, payload))
        metadata = {"ResponseMetadata": {"RequestId": f"request-{len(self.calls)}"}}
        if action == "CreateMCPService":
            self.count += 1
            return {**metadata, "Result": {"MCPServiceId": f"service-{self.count}"}}
        if action == "GetMCPService":
            return {
                **metadata,
                "Result": {
                    "MCPService": {"Id": payload["MCPServiceId"], "Status": "Ready"}
                },
            }
        if action == "CreateMCPToolset":
            return {**metadata, "Result": {"MCPToolsetId": f"toolset-{self.count}"}}
        if action == "GetMCPToolset":
            return {
                **metadata,
                "Result": {
                    "MCPToolset": {
                        "Id": payload["MCPToolsetId"],
                        "Status": "Ready",
                        "Path": "/mcp",
                        "NetworkConfigurations": [{"Endpoint": "gateway.example"}],
                    }
                },
            }
        if action == "DeleteMCPToolset":
            return metadata
        raise AssertionError(action)


class FakeVerifier:
    live = True

    async def verify(self, publication):
        return GatewayVerification(
            initialize_pass=True,
            tools_list_pass=True,
            allowed_call_pass=self.live,
            denied_call_pass=self.live,
            live_tools_count=4,
            observed_version="test",
        )


def actor() -> Actor:
    return Actor(
        tenant_id="tenant-a", workspace_id="workspace-a", principal_id="owner-a"
    )


def request(key: str = "idempotency-key-0001") -> ManagedPublicationCreateRequest:
    return ManagedPublicationCreateRequest.model_validate(
        {
            "name": "经营数据只读",
            "connectionIds": ["connection-1"],
            "actionPolicy": {"preset": "read_only"},
            "audience": {
                "type": "applications",
                "clientIds": ["client-a", "client-b"],
            },
            "idempotencyKey": key,
        }
    )


def service(tmp_path, *, credential=None):
    connection = FakeConnectionGateway()
    credential = credential or FakeCredentialProvider()
    transport = FakeTransport()
    low_repository = AgentKitMcpPublicationRepository(tmp_path / "low.sqlite3")
    publisher = AgentKitMcpPublisher(
        low_repository,
        AgentKitMcpClient(transport, poll_interval_seconds=0),
        verifier=FakeVerifier(),
    )
    managed = ManagedPublicationService(
        ManagedPublicationRepository(tmp_path / "managed.sqlite3"),
        connection,  # type: ignore[arg-type]
        credential,
        publisher,
        jwt_discovery_url="https://identity.example/.well-known/openid-configuration",
    )
    return managed, connection, credential, transport


def test_read_only_is_allowlist_and_unknown_actions_fail_closed():
    result = resolve_actions(
        ("orders.list", "orders.get", "orders.create", "orders.mystery"),
        ActionPolicy(preset="read_only"),
    )
    assert result == ("orders.list", "orders.get")


@pytest.mark.asyncio
async def test_mixed_connection_endpoints_fail_closed(tmp_path):
    managed, connection, _, _ = service(tmp_path)
    original = connection.list_connections

    async def mixed_connections(**actor):
        items = await original(**actor)
        items[1] = {**items[1], "mcp_endpoint": "https://other.example/mcp"}
        return items

    connection.list_connections = mixed_connections
    body = request().model_copy(
        update={"connection_ids": ("connection-1", "connection-2")}
    )
    failed = await managed.create(body, actor(), "request-a")

    assert failed.publication.status == "failed"
    assert failed.operations[0].last_error is not None
    assert failed.operations[0].last_error["code"] == "MIXED_MCP_ENDPOINTS"
    assert not connection.created


@pytest.mark.asyncio
async def test_missing_connection_endpoint_fails_closed(tmp_path):
    managed, connection, _, _ = service(tmp_path)
    original = connection.list_connections

    async def missing_endpoint(**actor):
        items = await original(**actor)
        items[0] = {**items[0], "mcp_endpoint": ""}
        return items

    connection.list_connections = missing_endpoint
    failed = await managed.create(request(), actor(), "request-missing-endpoint")

    assert failed.publication.status == "failed"
    assert failed.operations[0].last_error is not None
    assert failed.operations[0].last_error["code"] == "CONNECTION_NOT_READY"
    assert not connection.created


@pytest.mark.asyncio
async def test_create_is_idempotent_and_never_persists_plaintext(tmp_path):
    managed, connection, credential, transport = service(tmp_path)
    first = await managed.create(request(), actor(), "request-a")
    second = await managed.create(request(), actor(), "request-b")

    assert first.publication.status == "active"
    assert first.publication.id == second.publication.id
    assert first.active_revision is not None
    assert first.active_revision.runtime_token_record_id == "runtime-record-1"
    assert first.active_revision.credential_provider_ref is not None
    assert first.active_revision.credential_provider_ref.startswith(
        "credential-provider://"
    )
    assert [item.subject_ref for item in first.subjects] == ["client-a", "client-b"]
    assert len(connection.created) == 1
    assert len(credential.created) == 1
    toolset_payload = next(
        payload for action, payload in transport.calls if action == "CreateMCPToolset"
    )
    allowed = toolset_payload["AuthorizerConfiguration"]["Authorizer"][
        "CustomJwtAuthorizer"
    ]["AllowedClients"]
    assert allowed == ["client-a", "client-b"]
    database = (tmp_path / "managed.sqlite3").read_bytes()
    low_database = (tmp_path / "low.sqlite3").read_bytes()
    assert b"one-time-secret" not in database + low_database


@pytest.mark.asyncio
async def test_retry_revokes_orphan_token_and_redacts_failure(tmp_path):
    credential = FakeCredentialProvider()
    credential.fail_once = True
    managed, connection, _, _ = service(tmp_path, credential=credential)
    failed = await managed.create(request(), actor(), "request-a")

    assert failed.publication.status == "failed"
    assert failed.operations[0].last_error == {
        "code": "GATEWAY_PROVISION_FAILED",
        "message": "credential [REDACTED]",
        "retryable": False,
    }
    recovered = await managed.retry(failed.publication, actor(), "request-b")
    assert recovered.publication.status == "active"
    assert connection.revoked == ["runtime-record-1"]
    assert len(connection.created) == 2
    assert b"must-not-leak" not in (tmp_path / "managed.sqlite3").read_bytes()


@pytest.mark.asyncio
async def test_rotation_activates_new_revision_before_retiring_old(tmp_path):
    managed, connection, credential, transport = service(tmp_path)
    created = await managed.create(request(), actor(), "request-a")
    rotated = await managed.rotate(created.publication, actor(), "request-b")

    assert rotated.publication.status == "active"
    assert rotated.active_revision is not None
    assert rotated.active_revision.version == 2
    assert [item.state for item in rotated.revisions] == ["active", "retired"]
    assert connection.revoked == ["runtime-record-1"]
    assert len(credential.deleted) == 1
    assert [action for action, _ in transport.calls].count("CreateMCPToolset") == 2


@pytest.mark.asyncio
async def test_failed_verification_persists_summary_for_recovery(tmp_path):
    connection = FakeConnectionGateway()
    credential = FakeCredentialProvider()
    transport = FakeTransport()
    verifier = FakeVerifier()
    verifier.live = False
    low_repository = AgentKitMcpPublicationRepository(tmp_path / "low.sqlite3")
    publisher = AgentKitMcpPublisher(
        low_repository,
        AgentKitMcpClient(transport, poll_interval_seconds=0),
        verifier=verifier,
    )
    managed = ManagedPublicationService(
        ManagedPublicationRepository(tmp_path / "managed.sqlite3"),
        connection,  # type: ignore[arg-type]
        credential,
        publisher,
        jwt_discovery_url="https://identity.example/.well-known/openid-configuration",
    )

    failed = await managed.create(request(), actor(), "request-verification-failure")

    assert failed.publication.status == "failed"
    assert failed.revisions[0].verification_summary["allowed_call_pass"] is False


@pytest.mark.asyncio
async def test_disable_failure_returns_to_retryable_failed_state(tmp_path):
    managed, _, credential, _ = service(tmp_path)
    created = await managed.create(request(), actor(), "request-disable-failure")
    credential.fail_delete = True

    with pytest.raises(Exception) as error:
        await managed.disable(created.publication, actor(), "request-disable-failure")

    assert getattr(error.value, "code", "") == "GATEWAY_PROVISION_FAILED"
    current = managed.require(created.publication.id, actor())
    assert current.status == ManagedPublicationStatus.FAILED
    credential.fail_delete = False
    recovered = await managed.retry(current, actor(), "request-disable-retry")
    assert recovered.publication.status == ManagedPublicationStatus.DISABLED


@pytest.mark.asyncio
async def test_business_routes_hide_low_level_fields_and_scope_tenant(tmp_path):
    managed, _, _, _ = service(tmp_path)
    app = FastAPI()
    mount_managed_mcp_routes(
        app,
        managed,
        actor_resolver=lambda request: Actor(
            tenant_id=request.headers["x-tenant-id"],
            workspace_id=request.headers["x-workspace-id"],
            principal_id="owner-a",
        ),
    )
    body = request().model_dump(mode="json", by_alias=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {"x-tenant-id": "tenant-a", "x-workspace-id": "workspace-a"}
        rejected = await client.post(
            "/api/data-workshop/v1/mcp-publications",
            headers=headers,
            json={**body, "runtimeTokenId": "forbidden"},
        )
        created = await client.post(
            "/api/data-workshop/v1/mcp-publications", headers=headers, json=body
        )
        publication_id = created.json()["data"]["publication"]["id"]
        foreign = await client.get(
            f"/api/data-workshop/v1/mcp-publications/{publication_id}",
            headers={**headers, "x-workspace-id": "workspace-b"},
        )

    assert rejected.status_code == 422
    assert "forbidden" not in rejected.text
    assert created.status_code == 202
    assert "one-time-secret" not in created.text
    assert "runtime-record" not in created.text
    assert "credential-provider" not in created.text
    assert "service-1" not in created.text
    assert "toolset-1" not in created.text
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_business_route_errors_include_request_id(tmp_path):
    managed, _, _, _ = service(tmp_path)
    app = FastAPI()
    mount_managed_mcp_routes(
        app,
        managed,
        actor_resolver=lambda request: Actor(
            tenant_id=request.headers["x-tenant-id"],
            workspace_id=request.headers["x-workspace-id"],
            principal_id="owner-a",
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/data-workshop/v1/mcp-publications/missing",
            headers={
                "x-tenant-id": "tenant-a",
                "x-workspace-id": "workspace-a",
                "x-request-id": "route-request-1",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Publication not found",
        "retryable": False,
        "request_id": "route-request-1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        mutation = await client.post(
            "/api/data-workshop/v1/mcp-publications/missing/retry",
            headers={
                "x-tenant-id": "tenant-a",
                "x-workspace-id": "workspace-a",
                "x-request-id": "route-request-2",
            },
        )

    assert mutation.status_code == 404
    assert mutation.json()["detail"]["request_id"] == "route-request-2"


def test_schema_uses_normalized_tables(tmp_path):
    ManagedPublicationRepository(tmp_path / "schema.sqlite3")
    database = sqlite3.connect(tmp_path / "schema.sqlite3")
    tables = {
        row[0]
        for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "mcp_publications",
        "mcp_publication_revisions",
        "publication_subjects",
        "publication_operations",
        "publication_audit_events",
    }.issubset(tables)


def test_state_machine_rejects_illegal_transition():
    with pytest.raises(ValueError, match="illegal publication transition"):
        assert_publication_transition(
            ManagedPublicationStatus.DRAFT, ManagedPublicationStatus.ACTIVE
        )


def test_legacy_records_become_read_only_external_managed(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy = AgentKitMcpPublicationRepository(path)
    from tests.frontend.test_agentkit_mcp_publisher import _publication, request_body

    legacy.save(_publication("legacy-1", request_body()), idempotency_key="legacy")
    managed = ManagedPublicationRepository(path)
    imported = managed.get_publication(
        "external-legacy-1", tenant_id="tenant-a", workspace_id="workspace-a"
    )
    assert imported is not None
    assert imported.status == "external-managed"


@pytest.mark.asyncio
async def test_external_managed_publications_reject_mutations(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy = AgentKitMcpPublicationRepository(path)
    from tests.frontend.test_agentkit_mcp_publisher import _publication, request_body

    legacy.save(_publication("legacy-1", request_body()), idempotency_key="legacy")
    managed, _, _, _ = service(tmp_path)
    managed.repository = ManagedPublicationRepository(path)
    imported = managed.require("external-legacy-1", actor())

    with pytest.raises(Exception) as error:
        await managed.disable(imported, actor(), "request-a")

    assert getattr(error.value, "code", "") == "EXTERNAL_MANAGED_READ_ONLY"
