from __future__ import annotations

import base64
import json

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.openviking.service import (
    OpenVikingConfig,
    OpenVikingError,
    OpenVikingProfileRepository,
    OpenVikingService,
)
from frontend.server.openviking.routes import mount_openviking_routes
from frontend.server.knowledge_workspace.service import Actor


def config() -> OpenVikingConfig:
    return OpenVikingConfig(
        encryption_key=b"e" * 32,
        ref_signing_key=b"s" * 32,
        allow_loopback=True,
    )


def profile(service: OpenVikingService, *, tenant: str = "tenant-a"):
    return service.create_profile(
        tenant_id=tenant,
        workspace_id="workspace-a",
        principal_id="user-a",
        display_name="Production Viking",
        base_url="http://localhost:38110",
        api_key="secret-api-key",
        workspace_uri="viking://resources/workspace-a/",
    )


def test_profile_is_encrypted_and_public_contract_has_no_secret_or_origin() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)

    stored = service.repository.get(
        value.profile_id, tenant_id="tenant-a", workspace_id="workspace-a"
    )
    assert stored is not None
    assert b"secret-api-key" not in stored.encrypted_api_key
    assert b"localhost" not in stored.encrypted_base_url
    public = json.dumps(service.public_profile(stored))
    assert "secret-api-key" not in public
    assert "localhost" not in public
    assert "workspace-a" not in public
    assert service.resolve_ref(
        stored, service.public_profile(stored)["root_resource_ref"]
    )


def test_profile_lookup_enforces_tenant_and_workspace() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)

    assert (
        service.repository.get(
            value.profile_id, tenant_id="tenant-b", workspace_id="workspace-a"
        )
        is None
    )
    assert (
        service.repository.get(
            value.profile_id, tenant_id="tenant-a", workspace_id="workspace-b"
        )
        is None
    )


def test_resource_refs_are_signed_profile_scoped_and_workspace_scoped() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    first = profile(service)
    second = profile(service, tenant="tenant-b")
    ref = service.resource_ref(first, "viking://resources/workspace-a/guide.md")

    assert service.resolve_ref(first, ref).endswith("/guide.md")
    with pytest.raises(OpenVikingError, match="invalid"):
        service.resolve_ref(second, ref)
    with pytest.raises(OpenVikingError, match="outside workspace"):
        service.resource_ref(first, "viking://resources/other/private.md")


def test_creator_context_rejects_wrong_tenant_and_profile() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)
    ready = value.__class__(**{**value.__dict__, "status": "ready"})
    service.repository.save(ready)
    ref = service.resource_ref(ready, "viking://resources/workspace-a/guide.md")

    context = service.creator_context(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        profile_ids=(ready.profile_id,),
        resource_refs=(ref,),
    )
    assert context == {
        "profile_ids": [ready.profile_id],
        "resource_refs": [ref],
    }
    with pytest.raises(OpenVikingError, match="not available"):
        service.creator_context(
            tenant_id="tenant-b",
            workspace_id="workspace-a",
            profile_ids=(ready.profile_id,),
            resource_refs=(ref,),
        )


@pytest.mark.asyncio
async def test_operation_injects_secret_server_side_and_sanitizes_response() -> None:
    observed: dict[str, str] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        observed["key"] = request.headers["X-API-Key"]
        observed["url"] = str(request.url)
        body = json.loads(request.content)
        observed["uri"] = body["target_uri"]
        return httpx.Response(
            200,
            json={
                "status": "success",
                "result": {
                    "uri": "viking://resources/workspace-a/guide.md",
                    "api_key": "must-not-leak",
                    "base_url": "http://internal:9999",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)
    ref = service.resource_ref(value, "viking://resources/workspace-a/guide.md")

    result = await service.request(value, "find", payload={"target_ref": ref})
    serialized = json.dumps(result)
    assert observed == {
        "key": "secret-api-key",
        "url": "http://localhost:38110/api/v1/search/find",
        "uri": "viking://resources/workspace-a/guide.md",
    }
    assert "secret-api-key" not in serialized
    assert "internal" not in serialized
    assert "resource_ref" in serialized
    assert "viking://workspace/guide.md" in serialized
    await client.aclose()


@pytest.mark.asyncio
async def test_operation_rejects_raw_browser_viking_uri() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)
    with pytest.raises(OpenVikingError, match="opaque resource"):
        await service.request(
            value, "fs_list", payload={"uri": "viking://resources/workspace-a/"}
        )


@pytest.mark.asyncio
async def test_unknown_operation_is_not_a_general_proxy() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)

    with pytest.raises(OpenVikingError, match="not allowed"):
        await service.request(value, "../admin", payload={})


@pytest.mark.asyncio
async def test_remote_import_rejects_http_and_private_hosts() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)

    with pytest.raises(OpenVikingError, match="HTTPS"):
        await service.request(
            value,
            "resource_import",
            payload={"path": "http://example.com/guide.md"},
        )
    with pytest.raises(OpenVikingError, match="restricted network"):
        await service.request(
            value,
            "resource_import",
            payload={"path": "https://127.0.0.1/private"},
        )


@pytest.mark.asyncio
async def test_upload_rejects_type_and_oversize_before_upstream() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)

    with pytest.raises(OpenVikingError, match="not supported"):
        await service.upload(
            value,
            filename="payload.exe",
            content_type="application/octet-stream",
            content=b"x",
        )
    with pytest.raises(OpenVikingError, match="too large"):
        await service.upload(
            value,
            filename="large.pdf",
            content_type="application/pdf",
            content=b"x" * (50 * 1_048_576 + 1),
        )


def test_invalid_encryption_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OPENVIKING_PROFILE_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"short").decode(),
    )
    monkeypatch.setenv("OPENVIKING_REF_SIGNING_KEY", "short")
    with pytest.raises(OpenVikingError, match="minimum strength"):
        OpenVikingConfig.from_env()


@pytest.mark.asyncio
async def test_profile_routes_reject_extra_fields_and_cross_tenant_access() -> None:
    app = FastAPI()
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    def actor(request):
        return Actor(
            request.headers["x-tenant-id"],
            request.headers["x-workspace-id"],
            request.headers["x-principal-id"],
        )

    mount_openviking_routes(app, service, actor_resolver=actor)
    transport = httpx.ASGITransport(app=app)
    first = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
    }
    second = first | {"x-tenant-id": "tenant-b"}
    body = {
        "display_name": "Viking",
        "base_url": "http://localhost:38110",
        "api_key": "secret",
        "workspace_uri": "viking://resources/workspace-a/",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post(
            "/api/knowledge/v1/openviking/profiles",
            headers=first,
            json=body | {"owner": "attacker"},
        )
        created = await client.post(
            "/api/knowledge/v1/openviking/profiles", headers=first, json=body
        )
        profile_id = created.json()["data"]["profile_id"]
        hidden = await client.get(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}", headers=second
        )

    assert invalid.status_code == 422
    assert created.status_code == 201
    assert hidden.status_code == 404
