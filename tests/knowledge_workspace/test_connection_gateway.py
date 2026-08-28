from __future__ import annotations

import base64
import io
import json
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.knowledge_workspace.autoskill import UnavailableAutoSkillClient
from frontend.server.knowledge_workspace.connection import (
    ConnectionServiceConfig,
    ConnectionServiceError,
    ConnectionServiceGateway,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.routes import mount_knowledge_workspace_routes
from frontend.server.knowledge_workspace.service import KnowledgeWorkspaceService


ACTOR = {
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "principal_id": "user-a",
}


def decode_principal(request: httpx.Request) -> dict[str, object]:
    token = request.headers["authorization"].removeprefix("Bearer ")
    prefix, payload, _signature = token.split(".")
    assert prefix == "cp1"
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def gateway(handler: Callable[[httpx.Request], httpx.Response]) -> ConnectionServiceGateway:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ConnectionServiceGateway(
        ConnectionServiceConfig("https://connections.test", "test-secret"),
        client=client,
    )


class RecordingAutoSkill:
    def __init__(self, state: bytes | None = None, *, fail_upload: bool = False) -> None:
        self.state = state
        self.fail_upload = fail_upload
        self.uploaded: bytes | None = None

    async def download_optional_state(self, **_: object) -> bytes | None:
        return self.state

    async def upload(self, *, content: bytes, **_: object) -> dict[str, bool]:
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.uploaded = content
        return {"ok": True}


def bridge_gateway(
    requests: list[httpx.Request],
    *,
    audit_persisted: bool = True,
) -> ConnectionServiceGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/connections/connection-1/discover":
            return httpx.Response(
                202,
                json={
                    "job": {
                        "id": "discovery-1",
                        "status": "succeeded",
                        "result": {
                            "actions": [
                                {
                                    "id": "fixture.read",
                                    "description": "Read fixture",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"query": {"type": "string"}},
                                    },
                                    "executable": True,
                                },
                                {
                                    "id": "fixture.admin",
                                    "description": "Not granted",
                                    "executable": True,
                                },
                                {
                                    "id": "fixture.remote",
                                    "description": "Not executable here",
                                    "executable": False,
                                },
                            ]
                        },
                    }
                },
            )
        if request.url.path == "/v1/runtime/actions/fixture.read":
            assert request.headers["x-connection-lease"] == "lease-token-secret"
            assert json.loads(request.content) == {
                "invocationId": "invocation-bridge",
                "audience": "knowledge-runtime",
                "connectionId": "connection-1",
                "input": {"query": "safe"},
            }
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"rows": 1},
                    "executionId": "execution-1",
                    "auditPersisted": audit_persisted,
                },
            )
        raise AssertionError(request.url.path)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ConnectionServiceGateway(
        ConnectionServiceConfig(
            "https://connections.test",
            "test-secret",
            runtime_public_url="https://runtime.connections.test",
        ),
        client=client,
    )


def bridge_context(gateway: ConnectionServiceGateway):
    from frontend.server.knowledge_workspace.connection import (
        EphemeralConnectionContext,
    )

    return EphemeralConnectionContext(
        lease_id=gateway._lease_reference(
            "tenant-a", "workspace-a", "user-a", ["lease-jti"]
        ),
        connection_ids=("connection-1",),
        allowed_actions=("fixture.read",),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        runtime_ref=json.dumps(
            {
                "audience": "knowledge-runtime",
                "leases": [
                    {
                        "connection_id": "connection-1",
                        "token": "lease-token-secret",
                        "allowed_actions": ["fixture.read"],
                    }
                ],
            }
        ),
    )


@pytest.mark.asyncio
async def test_gateway_signs_server_actor_and_never_returns_credentials() -> None:
    secret = "must-never-leave-the-service"

    def handler(request: httpx.Request) -> httpx.Response:
        assert decode_principal(request) == {
            "tenantId": "tenant-a",
            "workspaceId": "workspace-a",
            "subject": "user-a",
            "audience": "knowledge-runtime",
            "ownerId": "user-a",
        }
        if request.url.path == "/v1/catalog":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "service": "fixture",
                            "connectorDefinitionVersion": "1.0.0",
                            "displayName": "Fixture",
                            "tier": "beta",
                            "actionIds": ["fixture.read"],
                            "configSchema": {
                                "type": "object",
                                "properties": {"region": {"type": "string"}},
                            },
                            "authSchema": {
                                "type": "object",
                                "required": ["secret"],
                                "properties": {
                                    "secret": {
                                        "type": "string",
                                        "format": "password",
                                    }
                                },
                            },
                        }
                    ]
                },
            )
        if request.url.path == "/v1/connections":
            body = json.loads(request.content)
            assert body["values"]["secret"] == secret
            return httpx.Response(
                201,
                json={
                    "connection": {
                        "id": "connection-1",
                        "service": "fixture",
                        "connectionName": "fixture-one",
                        "visibility": "personal",
                        "status": "ready",
                        "connectorDefinitionVersion": "1.0.0",
                        "profile": {"accountId": "safe-account"},
                        "createdAt": "2026-08-28T00:00:00Z",
                        "updatedAt": "2026-08-28T00:00:00Z",
                        "revision": 1,
                    }
                },
            )
        raise AssertionError(request.url.path)

    result = await gateway(handler).create_connection(
        {
            "connector_key": "fixture",
            "display_name": "fixture-one",
            "scope": "personal",
            "config": {},
            "credential": {"secret": secret},
        },
        **ACTOR,
    )
    assert result["profile"] == {"accountId": "safe-account"}
    assert secret not in json.dumps(result)


@pytest.mark.asyncio
async def test_gateway_forwards_connection_service_catalog_schemas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/catalog"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "service": "fixture",
                        "connectorDefinitionVersion": "1.0.0",
                        "displayName": "Fixture",
                        "tier": "beta",
                        "actionIds": ["fixture.read"],
                        "configSchema": {
                            "type": "object",
                            "required": ["region"],
                            "properties": {"region": {"type": "string"}},
                        },
                        "authSchema": {
                            "type": "object",
                            "required": ["secret"],
                            "properties": {
                                "secret": {
                                    "type": "string",
                                    "format": "password",
                                }
                            },
                        },
                    }
                ]
            },
        )

    items = await gateway(handler).catalog(**ACTOR)

    assert items[0]["config_schema"]["required"] == ["region"]
    assert items[0]["auth_schema"]["properties"]["secret"]["format"] == "password"


@pytest.mark.asyncio
async def test_gateway_rejects_catalog_entries_without_service_owned_schemas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/catalog"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "service": "fixture",
                        "connectorDefinitionVersion": "1.0.0",
                        "displayName": "Fixture",
                        "tier": "beta",
                        "actionIds": [],
                    }
                ]
            },
        )

    with pytest.raises(ConnectionServiceError) as captured:
        await gateway(handler).catalog(**ACTOR)

    assert captured.value.code == "CONNECTION_CATALOG_INVALID"


@pytest.mark.asyncio
async def test_gateway_returns_connection_audit_with_invocation_correlation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audit"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "execution-1",
                        "invocationId": "autoskill-request-1",
                        "connectionId": "connection-1",
                        "actionId": "fixture.read",
                        "ok": True,
                    }
                ]
            },
        )

    items = await gateway(handler).list_audit(**ACTOR)

    assert items == [
        {
            "id": "execution-1",
            "invocationId": "autoskill-request-1",
            "connectionId": "connection-1",
            "actionId": "fixture.read",
            "ok": True,
        }
    ]


@pytest.mark.asyncio
async def test_gateway_lease_uses_real_actions_caps_ttl_and_survives_restart() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/v1/catalog":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "service": "fixture",
                            "connectorDefinitionVersion": "1.0.0",
                            "displayName": "Fixture",
                            "tier": "beta",
                            "actionIds": ["fixture.read"],
                            "configSchema": {
                                "type": "object",
                                "properties": {},
                            },
                            "authSchema": {
                                "type": "object",
                                "properties": {},
                            },
                        }
                    ]
                },
            )
        if request.url.path == "/v1/connections":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "connection-1",
                            "service": "fixture",
                            "connectionName": "fixture-one",
                            "visibility": "personal",
                            "status": "ready",
                            "connectorDefinitionVersion": "1.0.0",
                            "profile": {},
                            "createdAt": "2026-08-28T00:00:00Z",
                            "updatedAt": "2026-08-28T00:00:00Z",
                            "revision": 1,
                        }
                    ]
                },
            )
        if request.url.path == "/v1/connections/connection-1/lease":
            assert body["allowedActions"] == ["fixture.read"]
            assert body["ttlSeconds"] == 900
            return httpx.Response(
                201,
                json={
                    "token": "cl_secret-runtime-token",
                    "claims": {
                        "jti": "lease-jti",
                        "expiresAt": "2026-08-28T00:15:00Z",
                    },
                },
            )
        if request.url.path == "/v1/leases/lease-jti/revoke":
            return httpx.Response(200, json={"revoked": True})
        raise AssertionError(request.url.path)

    first = gateway(handler)
    context = await first.issue(
        **ACTOR,
        invocation_id="invocation-1",
        connection_ids=["connection-1"],
        allowed_actions=["connection.read"],
        ttl_seconds=1800,
    )
    assert context.allowed_actions == ("fixture.read",)
    assert "cl_secret-runtime-token" in context.runtime_ref
    assert "cl_secret-runtime-token" not in context.lease_id

    restarted = gateway(handler)
    await restarted.revoke(context.lease_id)
    assert ("POST", "/v1/leases/lease-jti/revoke", {}) in requests


@pytest.mark.asyncio
async def test_gateway_uploads_direct_lease_scoped_connection_service_runtime() -> None:
    existing = io.BytesIO()
    with zipfile.ZipFile(existing, "w") as archive:
        archive.writestr("memory.md", "safe context")
        archive.writestr(
            "mcp_config.yaml",
            "servers:\n  old:\n    headers:\n      Authorization: secret\n",
        )
    requests: list[httpx.Request] = []
    target = bridge_gateway(requests)
    autoskill = RecordingAutoSkill(existing.getvalue())

    await target.prepare_autoskill(
        context=bridge_context(target),
        autoskill=autoskill,
        agent_id="agent-1",
        session_id="session-1",
        invocation_id="invocation-bridge",
    )

    assert autoskill.uploaded is not None
    with zipfile.ZipFile(io.BytesIO(autoskill.uploaded)) as archive:
        assert set(archive.namelist()) == {"memory.md", "mcp_config.yaml"}
        state_text = archive.read("mcp_config.yaml").decode()
    assert (
        "https://runtime.connections.test/v1/runtime/mcp/sse?"
        "connectionId=connection-1&invocationId=invocation-bridge"
        "&audience=knowledge-runtime"
    ) in state_text
    assert "X-Connection-Lease: lease-token-secret" in state_text
    assert "connection-runtime" not in state_text
    assert requests == []


@pytest.mark.asyncio
async def test_gateway_requires_public_https_for_connection_service_runtime() -> None:
    requests: list[httpx.Request] = []
    target = bridge_gateway(requests)
    invalid = ConnectionServiceGateway(
        ConnectionServiceConfig(
            "https://connections.test",
            "test-secret",
            runtime_public_url="http://127.0.0.1:3400",
        ),
        client=target._client,
    )
    with pytest.raises(ConnectionServiceError, match="public HTTPS"):
        await invalid.prepare_autoskill(
            context=bridge_context(invalid),
            autoskill=RecordingAutoSkill(),
            agent_id="agent-1",
            session_id="session-1",
            invocation_id="invocation-bridge",
        )

@pytest.mark.asyncio
async def test_gateway_maps_upstream_errors_without_echoing_authorization() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "unauthorized", "message": "token rejected"}},
        )

    with pytest.raises(ConnectionServiceError) as caught:
        await gateway(handler).list_connections(**ACTOR)
    assert caught.value.status_code == 401
    assert caught.value.code == "UNAUTHORIZED"
    assert "Bearer" not in str(caught.value)


@pytest.mark.asyncio
async def test_gateway_uploads_to_tenant_file_intake_and_returns_only_opaque_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/files"
        assert request.method == "POST"
        assert decode_principal(request)["workspaceId"] == "workspace-a"
        assert b'filename="people.csv"' in request.content
        assert b"name,email" in request.content
        return httpx.Response(
            201,
            json={
                "file": {
                    "fileId": "tenant-file-1",
                    "downloadUrl": "https://private.invalid/files/tenant-file-1",
                    "tenantId": "tenant-a",
                    "workspaceId": "workspace-a",
                    "sha256": "not-browser-visible",
                }
            },
        )

    result = await gateway(handler).upload_file(
        filename="people.csv",
        content=b"name,email\nAda,ada@example.test\n",
        media_type="text/csv",
        **ACTOR,
    )
    assert result == "tenant-file-1"


@pytest.mark.asyncio
async def test_upload_route_scans_with_connection_service_without_exposing_file_id(
    tmp_path,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1/files"
        return httpx.Response(201, json={"file": {"fileId": "private-file-1"}})

    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(object_root=tmp_path / "objects"),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(
        app,
        service,
        connection_gateway=gateway(handler),
        allow_insecure_test_headers=True,
    )
    headers = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
        "idempotency-key": "upload-key-123456",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/knowledge/v1/uploads",
            headers=headers,
            data={"purpose": "skill_input"},
            files={"file": ("people.csv", b"name\nAda\n", "text/csv")},
        )
        replay = await client.post(
            "/api/knowledge/v1/uploads",
            headers=headers,
            data={"purpose": "skill_input"},
            files={"file": ("people.csv", b"name\nAda\n", "text/csv")},
        )
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert calls == 1
    assert "private-file-1" not in first.text


@pytest.mark.asyncio
async def test_connection_routes_replay_idempotently_and_use_error_contract() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/v1/catalog":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "service": "fixture",
                            "connectorDefinitionVersion": "1.0.0",
                            "displayName": "Fixture",
                            "tier": "beta",
                            "actionIds": ["fixture.read"],
                            "configSchema": {
                                "type": "object",
                                "properties": {},
                            },
                            "authSchema": {
                                "type": "object",
                                "properties": {
                                    "secret": {
                                        "type": "string",
                                        "format": "password",
                                    }
                                },
                            },
                        }
                    ]
                },
            )
        if request.url.path == "/v1/connections":
            calls += 1
            return httpx.Response(
                201,
                json={
                    "connection": {
                        "id": "connection-1",
                        "service": "fixture",
                        "connectionName": "fixture-one",
                        "visibility": "personal",
                        "status": "ready",
                        "connectorDefinitionVersion": "1.0.0",
                        "profile": {},
                        "createdAt": "2026-08-28T00:00:00Z",
                        "updatedAt": "2026-08-28T00:00:00Z",
                        "revision": 1,
                    }
                },
            )
        raise AssertionError(request.url.path)

    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(
        app,
        service,
        connection_gateway=gateway(handler),
        allow_insecure_test_headers=True,
    )
    transport = httpx.ASGITransport(app=app)
    headers = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
        "idempotency-key": "connection-key-123456",
    }
    payload = {
        "connector_key": "fixture",
        "display_name": "fixture-one",
        "scope": "personal",
        "config": {},
        "credential": {"secret": "hidden"},
    }
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/knowledge/v1/connections", headers=headers, json=payload
        )
        replay = await client.post(
            "/api/knowledge/v1/connections", headers=headers, json=payload
        )
        conflict = await client.post(
            "/api/knowledge/v1/connections",
            headers=headers,
            json={**payload, "display_name": "different"},
        )
    assert first.status_code == replay.status_code == 201
    assert first.json()["data"] == replay.json()["data"]
    assert calls == 1
    assert conflict.status_code == 409
    assert set(conflict.json()) == {"error", "meta"}
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_unconfigured_connection_route_uses_same_origin_error_envelope() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(
        app, service, allow_insecure_test_headers=True
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.get("/api/knowledge/v1/connections")
        invalid = await client.post(
            "/api/knowledge/v1/connections",
            headers={"idempotency-key": "connection-key-123456"},
            json={},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONNECTION_SERVICE_UNAVAILABLE"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_ARGUMENT"
