from __future__ import annotations

import base64
import json
import socket
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from frontend.server.knowledge_workspace import (
    KnowledgeWorkspaceRepository,
    KnowledgeWorkspaceService,
    UnavailableAutoSkillClient,
)
from frontend.server.knowledge_workspace.models import (
    WorkspaceResource,
    WorkspaceResourceKind,
)
from frontend.server.extensions.openviking.connection_resource import (
    resolve_connection_resource,
)
from frontend.server.extensions.openviking.service import (
    OpenVikingConfig,
    OpenVikingError,
    OpenVikingProfileRepository,
    OpenVikingService,
)
from frontend.server.extensions.openviking.routes import mount_openviking_routes
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


def cloud_profile(service: OpenVikingService, base_url: str):
    return service.create_profile(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        principal_id="user-a",
        display_name="VikingDB OpenViking",
        base_url=base_url,
        api_key="secret-api-key",
        workspace_uri="viking://resources/",
    )


def stub_openviking_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolved_address(host: str, port: int, *, type: int):
        assert host in {"api.vikingdb.cn-beijing.volces.com", "localhost"}
        address = "127.0.0.1" if host == "localhost" else "8.8.8.8"
        return [(socket.AF_INET, type, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolved_address)


@pytest.mark.asyncio
async def test_cloud_base_path_is_preserved_for_fs_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_openviking_dns(monkeypatch)
    observed: dict[str, str] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        return httpx.Response(200, json={"status": "ok", "result": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = cloud_profile(
        service, "https://api.vikingdb.cn-beijing.volces.com/openviking"
    )

    await service.request(value, "fs_list", payload={})

    assert observed["path"] == "/openviking/api/v1/fs/ls"
    await client.aclose()


@pytest.mark.parametrize("path", ["/openviking/../admin", "/openviking/./api"])
def test_base_url_rejects_path_traversal(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_openviking_dns(monkeypatch)
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    with pytest.raises(OpenVikingError) as raised:
        cloud_profile(service, f"https://api.vikingdb.cn-beijing.volces.com{path}")

    assert raised.value.code == "INVALID_BASE_URL"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.vikingdb.cn-beijing.volces.com/openviking\\admin",
        "https://api.vikingdb.cn-beijing.volces.com/open\nviking",
        "https://api.vikingdb.cn-beijing.volces.com/openviking\x00",
        "https://api.vikingdb.cn-beijing.volces.com/openviking\x7f",
        "https://api.vikingdb.cn-beijing.volces.com/openviking\x85",
    ],
)
def test_base_url_rejects_backslashes_and_control_characters(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_openviking_dns(monkeypatch)
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    with pytest.raises(OpenVikingError) as raised:
        cloud_profile(service, base_url)

    assert raised.value.code == "INVALID_BASE_URL"


@pytest.mark.parametrize(
    "path",
    [
        "/openviking/%2e%2e/admin",
        "/openviking/%252e%252e/admin",
        "/openviking%2fadmin",
        "/openviking%5cadmin",
        "/openviking%00",
        "/openviking%3fadmin",
        "/openviking%23admin",
        "/openviking%2",
    ],
)
def test_base_url_rejects_encoded_path_bypasses(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_openviking_dns(monkeypatch)
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    with pytest.raises(OpenVikingError) as raised:
        cloud_profile(service, f"https://api.vikingdb.cn-beijing.volces.com{path}")

    assert raised.value.code == "INVALID_BASE_URL"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user@api.vikingdb.cn-beijing.volces.com/openviking",
        "https://user:password@api.vikingdb.cn-beijing.volces.com/openviking",
        "https://@api.vikingdb.cn-beijing.volces.com/openviking",
        "https://api.vikingdb.cn-beijing.volces.com/openviking?region=beijing",
        "https://api.vikingdb.cn-beijing.volces.com/openviking?",
        "https://api.vikingdb.cn-beijing.volces.com/openviking#section",
        "https://api.vikingdb.cn-beijing.volces.com/openviking#",
    ],
)
def test_base_url_rejects_userinfo_query_and_fragment(
    base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_openviking_dns(monkeypatch)
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    with pytest.raises(OpenVikingError) as raised:
        cloud_profile(service, base_url)

    assert raised.value.code == "INVALID_BASE_URL"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://[::1/openviking",
        "https://api.vikingdb.cn-beijing.volces.com:not-a-port/openviking",
        "https://api.vikingdb.cn-beijing.volces.com:70000/openviking",
    ],
)
def test_base_url_rejects_malformed_authority(base_url: str) -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    with pytest.raises(OpenVikingError) as raised:
        cloud_profile(service, base_url)

    assert raised.value.code == "INVALID_BASE_URL"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expected_path"),
    [
        (
            "https://api.vikingdb.cn-beijing.volces.com",
            "/api/v1/fs/ls",
        ),
        ("http://localhost:38110/", "/api/v1/fs/ls"),
        (
            "https://api.vikingdb.cn-beijing.volces.com/%6fpenviking/",
            "/openviking/api/v1/fs/ls",
        ),
    ],
)
async def test_base_url_keeps_origin_and_localhost_compatibility(
    base_url: str, expected_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_openviking_dns(monkeypatch)
    observed: dict[str, str] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        return httpx.Response(200, json={"status": "ok", "result": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = cloud_profile(service, base_url)

    await service.request(value, "fs_list", payload={})

    assert observed["path"] == expected_path
    await client.aclose()


@pytest.mark.asyncio
async def test_base_path_is_preserved_for_upload_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_openviking_dns(monkeypatch)
    observed: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        observed.append(request.url.path)
        if request.url.path.endswith("/resources/temp_upload"):
            return httpx.Response(
                200,
                json={"status": "ok", "result": {"temp_file_id": "upload-1.md"}},
            )
        return httpx.Response(200, json={"status": "ok", "result": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = cloud_profile(
        service, "https://api.vikingdb.cn-beijing.volces.com/openviking/"
    )

    await service.upload(
        value,
        filename="guide.md",
        content_type="text/markdown",
        content=b"# Guide",
    )
    await service.validate(value)

    assert observed == [
        "/openviking/api/v1/resources/temp_upload",
        "/openviking/api/v1/fs/ls",
    ]
    refreshed = service.repository.get(
        value.profile_id, tenant_id=value.tenant_id, workspace_id=value.workspace_id
    )
    assert refreshed is not None
    assert refreshed.status == "ready"
    await client.aclose()


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


def test_operation_allowlist_matches_frozen_watch_api() -> None:
    from frontend.server.extensions.openviking.service import OPERATIONS

    assert "watches" in OPERATIONS
    assert "watch_create" not in OPERATIONS


@pytest.mark.asyncio
async def test_session_commit_retry_uses_fixed_scoped_upstream_path() -> None:
    observed: dict[str, object] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        observed.update(
            method=request.method,
            url=str(request.url),
            key=request.headers.get("X-API-Key"),
            body=json.loads(request.content),
        )
        return httpx.Response(200, json={"result": {"reason": "committed"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    result = await service.request(
        value,
        "session_commit",
        item_id="session_123",
        payload={"keep_recent_count": 3},
    )

    assert result == {"result": {"reason": "committed"}}
    assert observed == {
        "method": "POST",
        "url": "http://localhost:38110/api/v1/sessions/session_123/commit",
        "key": "secret-api-key",
        "body": {"keep_recent_count": 3},
    }
    with pytest.raises(OpenVikingError) as rejected:
        await service.request(
            value,
            "session_commit",
            item_id="session_123",
            payload={"owner_id": "browser-owner"},
        )
    assert rejected.value.code == "INVALID_ARGUMENT"
    assert observed["body"] == {"keep_recent_count": 3}
    await client.aclose()


def test_resource_refs_are_signed_profile_scoped_and_workspace_scoped() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    first = profile(service)
    second = profile(service, tenant="tenant-b")
    ref = service.resource_ref(first, "viking://resources/workspace-a/guide.md")

    assert service.resolve_ref(first, ref).endswith("/guide.md")
    assert (
        service.resolve_ref(
            first, service.resource_ref(first, "viking://resources/workspace-a")
        )
        == "viking://resources/workspace-a/"
    )
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
                    "source_path": "/private/tmp/upstream/guide.md",
                    "temp_uri": "viking://temp/default/upload",
                    "archive_uri": "viking://user/default/sessions/private",
                    "account_id": "upstream-account",
                    "processor_kwargs": {
                        "resource_lock": {
                            "owner_id": "internal-owner",
                            "lock_paths": ["/private/data/workspace"],
                        }
                    },
                    "overview": (
                        "Read [guide](viking://resources/workspace-a/guide.md)"
                    ),
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
    assert "/private/" not in serialized
    assert "viking://temp/" not in serialized
    assert "viking://user/" not in serialized
    assert "upstream-account" not in serialized
    assert result["result"]["source_path"] == "guide.md"
    assert result["result"]["processor_kwargs"] == {}
    assert result["result"]["overview"] == "Read [guide](viking://workspace/guide.md)"
    assert "resource_ref" in serialized
    assert "viking://workspace/guide.md" in serialized
    await client.aclose()


@pytest.mark.asyncio
async def test_task_metadata_never_exposes_upstream_identity_or_paths() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "task_id": "task-1",
                        "account_id": "internal-account",
                        "user_id": "internal-user",
                        "meta": {"source_path": "/private/tmp/parser/input.md"},
                        "processor_kwargs": {
                            "resource_lock": {
                                "owner_id": "internal-owner",
                                "lock_paths": ["/private/data/workspace"],
                            }
                        },
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    serialized = json.dumps(await service.request(value, "tasks"))

    assert "internal-account" not in serialized
    assert "internal-user" not in serialized
    assert "internal-owner" not in serialized
    assert "/private/" not in serialized
    assert "resource_lock" not in serialized
    assert "input.md" in serialized
    await client.aclose()


@pytest.mark.asyncio
async def test_task_history_survives_bff_restart(tmp_path: Path) -> None:
    responses = [
        {
            "result": [
                {
                    "task_id": "task-completed",
                    "task_type": "add_resource",
                    "status": "completed",
                    "created_at": 100.0,
                    "account_id": "internal-account",
                    "meta": {"source_path": "/private/tmp/parser/input.md"},
                }
            ]
        },
        {"result": []},
    ]

    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    database = tmp_path / "profiles.sqlite3"
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    first_service = OpenVikingService(
        OpenVikingProfileRepository(database), config(), client=client
    )
    value = profile(first_service)
    first = await first_service.request(value, "tasks")

    restarted_service = OpenVikingService(
        OpenVikingProfileRepository(database), config(), client=client
    )
    stored = restarted_service.repository.get(
        value.profile_id, tenant_id=value.tenant_id, workspace_id=value.workspace_id
    )
    assert stored is not None
    recovered = await restarted_service.request(stored, "tasks")

    assert recovered == first
    serialized = json.dumps(recovered)
    assert "internal-account" not in serialized
    assert "/private/" not in serialized
    assert "input.md" in serialized
    await client.aclose()


@pytest.mark.asyncio
async def test_task_history_is_profile_scoped_filtered_and_revoked(
    tmp_path: Path,
) -> None:
    responses = [
        {
            "result": [
                {
                    "task_id": "task-old",
                    "task_type": "add_resource",
                    "status": "completed",
                    "created_at": 100.0,
                    "resource_id": "viking://resources/workspace-a/old.md",
                },
                {
                    "task_id": "task-new",
                    "task_type": "session_commit",
                    "status": "failed",
                    "created_at": 200.0,
                },
            ]
        },
        {"result": []},
        {"result": []},
    ]

    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses.pop(0))

    database = tmp_path / "profiles.sqlite3"
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(
        OpenVikingProfileRepository(database), config(), client=client
    )
    value = profile(service)
    other = profile(service, tenant="tenant-b")
    await service.request(value, "tasks")

    filtered = await service.request(
        value,
        "tasks",
        payload={
            "status": "completed",
            "resource_id_ref": service.resource_ref(
                value, "viking://resources/workspace-a/old.md"
            ),
            "limit": 1,
        },
    )
    isolated = await service.request(other, "tasks")

    assert [item["task_id"] for item in filtered["result"]] == ["task-old"]
    assert isolated["result"] == []
    assert service.repository.delete(
        value.profile_id,
        tenant_id=value.tenant_id,
        workspace_id=value.workspace_id,
    )
    assert service.repository.list_task_history(value) == []
    await client.aclose()


@pytest.mark.asyncio
async def test_resource_import_is_idempotent_across_service_restart(
    tmp_path: Path,
) -> None:
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"result": {"task_id": f"task-{calls}", "status": "queued"}},
        )

    database = tmp_path / "profiles.sqlite3"
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    first_service = OpenVikingService(
        OpenVikingProfileRepository(database), config(), client=client
    )
    value = profile(first_service)
    payload = {"path": "https://example.com/guide.md"}

    first = await first_service.request_idempotent(
        value, "resource_import", payload=payload, idempotency_key="import-guide"
    )
    restarted_service = OpenVikingService(
        OpenVikingProfileRepository(database), config(), client=client
    )
    stored = restarted_service.repository.get(
        value.profile_id, tenant_id=value.tenant_id, workspace_id=value.workspace_id
    )
    assert stored is not None
    repeated = await restarted_service.request_idempotent(
        stored, "resource_import", payload=payload, idempotency_key="import-guide"
    )

    assert repeated == first
    assert calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_idempotency_key_is_bound_to_request_body() -> None:
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"result": {"task_id": f"task-{calls}"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    first = await service.request_idempotent(
        value,
        "resource_import",
        payload={"path": "https://example.com/first.md"},
        idempotency_key="import",
    )
    second = await service.request_idempotent(
        value,
        "resource_import",
        payload={"path": "https://example.com/second.md"},
        idempotency_key="import",
    )

    assert first != second
    assert calls == 2
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
async def test_empty_workspace_listing_uses_profile_root() -> None:
    observed: dict[str, str] = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        return httpx.Response(200, json={"status": "ok", "result": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    await service.request(value, "fs_list", payload={})

    assert observed["url"].endswith(
        "/api/v1/fs/ls?uri=viking%3A%2F%2Fresources%2Fworkspace-a%2F"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_operation_is_not_a_general_proxy() -> None:
    service = OpenVikingService(OpenVikingProfileRepository(), config())
    value = profile(service)

    with pytest.raises(OpenVikingError, match="not allowed"):
        await service.request(value, "../admin", payload={})


@pytest.mark.asyncio
async def test_operation_schema_rejects_unknown_owner_and_invalid_types() -> None:
    calls = 0

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"result": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    for payload in (
        {"owner_id": "attacker"},
        {"limit": "200"},
    ):
        with pytest.raises(OpenVikingError) as raised:
            await service.request(value, "tasks", payload=payload)
        assert raised.value.code == "INVALID_ARGUMENT"
    with pytest.raises(OpenVikingError) as raised:
        await service.request(
            value, "tasks", payload={"uri": "viking://resources/workspace-a/"}
        )
    assert raised.value.code == "OPAQUE_RESOURCE_REF_REQUIRED"
    assert calls == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_resource_import_rejects_browser_credentials_before_upstream() -> None:
    calls = 0

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"result": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    credential_args = (
        {"auth_config": {"username": "oauth2", "token": "secret"}},
        {"feishu_access_token": "secret"},
        {"nested": {"password": "secret"}},
    )
    for args in credential_args:
        with pytest.raises(OpenVikingError) as raised:
            await service.request(
                value,
                "resource_import",
                payload={"path": "https://example.com/guide.md", "args": args},
            )
        assert raised.value.code == "INVALID_ARGUMENT"
    with pytest.raises(OpenVikingError) as raised:
        await service.request(
            value,
            "resource_import",
            payload={
                "path": "https://example.com/guide.md",
                "args": {"include_paths": ["viking://resources/workspace-a/private"]},
            },
        )
    assert raised.value.code == "OPAQUE_RESOURCE_REF_REQUIRED"
    assert calls == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_operation_schema_allows_safe_advanced_payloads() -> None:
    observed: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    await service.request(
        value,
        "search",
        payload={
            "query": "deployment",
            "mode": "context",
            "query_expansion": "auto",
            "max_tokens": 4096,
            "quotas": {"resources": 3},
            "purpose": "coding",
            "detail": {"resources": "full"},
            "dedup_turns": 2,
            "exclude_uris": [],
            "peer_scope": "all",
            "other_peer_penalty": 0.25,
            "rewrite": True,
            "rewrite_max_bullets": 4,
        },
    )
    await service.request(
        value,
        "resource_import",
        payload={
            "path": "https://example.com/docs",
            "args": {
                "depth": 2,
                "max_pages": 10,
                "include_paths": ["/guide"],
                "skip_download_links": True,
            },
            "processing_mode": "vectors_only",
            "tags": ["env=test"],
            "tag_mode": "append",
        },
    )

    assert observed[0]["mode"] == "context"
    assert observed[0]["max_tokens"] == 4096
    assert observed[1]["args"] == {
        "depth": 2,
        "max_pages": 10,
        "include_paths": ["/guide"],
        "skip_download_links": True,
    }
    await client.aclose()


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


@pytest.mark.asyncio
async def test_manual_text_composes_target_from_opaque_parent_ref() -> None:
    observed: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/resources/temp_upload":
            observed.append(
                {
                    "path": request.url.path,
                    "has_filename": b'filename="notes.md"' in request.content,
                    "has_content": b"# Verified knowledge" in request.content,
                }
            )
            return httpx.Response(
                200, json={"status": "ok", "result": {"temp_file_id": "upload-1.md"}}
            )
        body = json.loads(request.content)
        observed.append({"path": request.url.path, "body": body})
        return httpx.Response(
            200,
            json={
                "result": {
                    "uri": "viking://resources/workspace-a/notes",
                    "root_uri": "viking://resources/workspace-a",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)
    parent_ref = service.resource_ref(value, value.workspace_uri)

    result = await service.write_text(
        value,
        parent_ref=parent_ref,
        filename="notes.md",
        content="# Verified knowledge",
    )

    assert observed == [
        {
            "path": "/api/v1/resources/temp_upload",
            "has_filename": True,
            "has_content": True,
        },
        {
            "path": "/api/v1/resources",
            "body": {
                "temp_file_id": "upload-1.md",
                "parent": "viking://resources/workspace-a/",
                "wait": True,
                "timeout": 30.0,
            },
        },
    ]
    assert result["result"]["uri"] == "viking://workspace/notes"
    assert result["result"]["resource_ref"].startswith("ovr_")
    assert result["result"]["root_uri"] == "viking://workspace/"
    assert result["result"]["display_path"] == ""
    await client.aclose()


@pytest.mark.asyncio
async def test_manual_text_rejects_unsafe_name_and_raw_parent() -> None:
    upstream_called = False

    def upstream(_request: httpx.Request) -> httpx.Response:
        nonlocal upstream_called
        upstream_called = True
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)
    with pytest.raises(OpenVikingError, match="filename"):
        await service.write_text(
            value,
            parent_ref=service.resource_ref(value, value.workspace_uri),
            filename="../secret.md",
            content="secret",
        )
    with pytest.raises(OpenVikingError) as raw_parent:
        await service.write_text(
            value,
            parent_ref=value.workspace_uri,
            filename="safe.md",
            content="content",
        )
    assert raw_parent.value.code == "OPAQUE_RESOURCE_REF_REQUIRED"
    assert not upstream_called
    await client.aclose()


@pytest.mark.asyncio
async def test_creator_context_resolves_bounded_content_server_side() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "uri": "viking://resources/workspace-a/guide.md",
                    "content": "server-resolved knowledge",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)
    service.repository.save(value.__class__(**{**value.__dict__, "status": "ready"}))
    ref = service.resource_ref(value, f"{value.workspace_uri}guide.md")

    context = await service.resolved_creator_context(
        tenant_id=value.tenant_id,
        workspace_id=value.workspace_id,
        profile_ids=(value.profile_id,),
        resource_refs=(ref,),
    )

    assert context["resource_refs"] == [ref]
    assert "server-resolved knowledge" in str(context["resolved_resources"])
    await client.aclose()


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
        ssrf = await client.post(
            "/api/knowledge/v1/openviking/profiles",
            headers=first,
            json=body | {"base_url": "https://127.0.0.1"},
        )

    assert invalid.status_code == 422
    assert created.status_code == 201
    assert hidden.status_code == 404
    assert ssrf.status_code == 422
    assert ssrf.json()["detail"]["code"] == "SSRF_BLOCKED"


@pytest.mark.asyncio
async def test_profile_update_replaces_encrypted_credentials_and_revoke_is_scoped() -> (
    None
):
    app = FastAPI()
    service = OpenVikingService(OpenVikingProfileRepository(), config())

    def actor(request):
        return Actor(
            request.headers["x-tenant-id"],
            request.headers["x-workspace-id"],
            request.headers["x-principal-id"],
        )

    mount_openviking_routes(app, service, actor_resolver=actor)
    headers = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
    }
    other = headers | {"x-tenant-id": "tenant-b"}
    body = {
        "display_name": "Viking",
        "base_url": "http://localhost:38110",
        "api_key": "old-secret",
        "workspace_uri": "viking://resources/workspace-a/",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/knowledge/v1/openviking/profiles", headers=headers, json=body
        )
        profile_id = created.json()["data"]["profile_id"]
        denied_update = await client.patch(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}",
            headers=other,
            json={"api_key": "attacker-secret"},
        )
        updated = await client.patch(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}",
            headers=headers,
            json={
                "display_name": "Updated",
                "base_url": "http://localhost:38111",
                "api_key": "new-secret",
            },
        )
        stored_updated = service.repository.get(
            profile_id, tenant_id="tenant-a", workspace_id="workspace-a"
        )
        denied_revoke = await client.delete(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}", headers=other
        )
        revoked = await client.delete(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}", headers=headers
        )
        missing = await client.get(
            f"/api/knowledge/v1/openviking/profiles/{profile_id}", headers=headers
        )

    assert denied_update.status_code == denied_revoke.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["data"]["display_name"] == "Updated"
    assert "localhost" not in updated.text
    assert "secret" not in updated.text
    assert stored_updated is not None
    assert b"new-secret" not in stored_updated.encrypted_api_key
    assert b"localhost" not in stored_updated.encrypted_base_url
    assert service._credentials(stored_updated) == (
        "http://localhost:38111",
        "new-secret",
    )
    assert revoked.status_code == 204
    assert missing.status_code == 404
    assert (
        service.repository.get(
            profile_id, tenant_id="tenant-a", workspace_id="workspace-a"
        )
        is None
    )


@pytest.mark.asyncio
async def test_connection_resource_import_reauthorizes_and_strips_secrets() -> None:
    class RecordingGateway:
        calls: list[tuple[str, str, str, str]] = []

        async def get_adapter_resource(
            self,
            resource_id: str,
            *,
            tenant_id: str,
            workspace_id: str,
            principal_id: str,
        ) -> dict:
            self.calls.append((resource_id, tenant_id, workspace_id, principal_id))
            return {"resourceId": resource_id}

    knowledge = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    knowledge.repository.save_resource(
        WorkspaceResource(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            resource_id="resource-a",
            kind=WorkspaceResourceKind.REST_OPENAPI,
            display_name="Orders API",
            scope="team",
            status="verified",
            source_id="source-a",
            adapter_resource_id="adapter-private-a",
            metadata={
                "summary": "Order schema",
                "api_key": "top-secret",
                "clientSecret": "also-hidden",
                "nested": {
                    "password": "hidden",
                    "access_token": "nested-hidden",
                    "columns": ["order_id", "status"],
                },
            },
        )
    )
    gateway = RecordingGateway()
    actor = Actor("tenant-a", "workspace-a", "user-a")
    observed: list[dict[str, object]] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/resources/temp_upload":
            observed.append(
                {
                    "path": request.url.path,
                    "has_filename": b'filename="orders.json"' in request.content,
                    "has_schema": b"order_id" in request.content,
                    "has_secret": b"top-secret" in request.content
                    or b"also-hidden" in request.content
                    or b"nested-hidden" in request.content,
                    "has_adapter_id": b"adapter-private-a" in request.content,
                }
            )
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {"temp_file_id": "upload-orders.json"},
                },
            )
        body = json.loads(request.content)
        observed.append({"path": request.url.path, "body": body})
        return httpx.Response(
            200,
            json={"result": {"uri": "viking://resources/workspace-a/orders"}},
        )

    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    openviking = OpenVikingService(
        OpenVikingProfileRepository(), config(), client=upstream_client
    )
    openviking_profile = profile(openviking)
    parent_ref = openviking.resource_ref(
        openviking_profile, openviking_profile.workspace_uri
    )
    app = FastAPI()

    async def resolver(principal: Actor, resource_id: str):
        return await resolve_connection_resource(
            principal,
            resource_id,
            knowledge_service=knowledge,
            connection_gateway=gateway,
        )

    mount_openviking_routes(
        app,
        openviking,
        actor_resolver=lambda _request: actor,
        connection_resource_resolver=resolver,
    )
    transport = httpx.ASGITransport(app=app)
    path = (
        f"/api/knowledge/v1/openviking/profiles/{openviking_profile.profile_id}"
        "/connection-resource"
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            path,
            json={
                "parent_ref": parent_ref,
                "filename": "orders.json",
                "resource_id": "resource-a",
            },
        )

    assert observed == [
        {
            "path": "/api/v1/resources/temp_upload",
            "has_filename": True,
            "has_schema": True,
            "has_secret": False,
            "has_adapter_id": False,
        },
        {
            "path": "/api/v1/resources",
            "body": {
                "temp_file_id": "upload-orders.json",
                "parent": "viking://resources/workspace-a/",
                "wait": True,
                "timeout": 30.0,
            },
        },
    ]
    assert imported.status_code == 200
    assert gateway.calls == [("adapter-private-a", "tenant-a", "workspace-a", "user-a")]
    serialized = json.dumps(observed)
    assert "top-secret" not in serialized
    assert "also-hidden" not in serialized
    assert "nested-hidden" not in serialized
    assert "password" not in serialized
    assert "adapter-private-a" not in serialized

    with pytest.raises(HTTPException) as missing:
        await resolve_connection_resource(
            Actor("tenant-b", "workspace-a", "user-b"),
            "resource-a",
            knowledge_service=knowledge,
            connection_gateway=gateway,
        )
    assert getattr(missing.value, "status_code", None) == 404
    assert len(gateway.calls) == 1

    with pytest.raises(HTTPException) as absent:
        await resolve_connection_resource(
            actor,
            "missing-resource",
            knowledge_service=knowledge,
            connection_gateway=gateway,
        )
    assert getattr(absent.value, "status_code", None) == 404
    assert len(gateway.calls) == 1
    await upstream_client.aclose()


@pytest.mark.asyncio
async def test_text_import_rejects_upload_without_temporary_file_id() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"status": "ok", "result": {}})
        )
    )
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)

    with pytest.raises(OpenVikingError) as rejected:
        await service.write_text(
            value,
            parent_ref=service.resource_ref(value, value.workspace_uri),
            filename="notes.md",
            content="verified",
        )

    assert rejected.value.code == "OPENVIKING_INVALID_RESPONSE"
    await client.aclose()


@pytest.mark.asyncio
async def test_operation_route_forwards_idempotency_key() -> None:
    calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"result": {"task_id": f"task-{calls}"}})

    app = FastAPI()
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = OpenVikingService(OpenVikingProfileRepository(), config(), client=client)
    value = profile(service)
    service.repository.save(value.__class__(**{**value.__dict__, "status": "ready"}))

    def actor(_request):
        return Actor("tenant-a", "workspace-a", "user-a")

    mount_openviking_routes(app, service, actor_resolver=actor)
    transport = httpx.ASGITransport(app=app)
    path = (
        f"/api/knowledge/v1/openviking/profiles/{value.profile_id}"
        "/operations/resource_import"
    )
    body = {"payload": {"path": "https://example.com/guide.md"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as bff:
        rejected = await bff.post(
            path,
            json={"payload": {"path": "https://example.com/guide.md", "owner_id": "x"}},
        )
        first = await bff.post(path, json=body, headers={"Idempotency-Key": "upload"})
        repeated = await bff.post(
            path, json=body, headers={"Idempotency-Key": "upload"}
        )

    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "INVALID_ARGUMENT"
    assert first.status_code == 200
    assert repeated.json() == first.json()
    assert calls == 1
    await client.aclose()
