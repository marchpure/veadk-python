from __future__ import annotations

import asyncio
import hashlib
import time

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.knowledge_workspace.autoskill import UnavailableAutoSkillClient
from frontend.server.knowledge_workspace.models import (
    Invocation,
    InvocationKind,
    InvocationStatus,
    SkillDraft,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.routes import mount_knowledge_workspace_routes
from frontend.server.knowledge_workspace.service import Actor, KnowledgeWorkspaceService


@pytest.mark.asyncio
async def test_oauth_routes_use_same_origin_envelopes_and_tenant_actor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth/configs":
            return httpx.Response(200, json={"config": {"configured": True}})
        if request.url.path == "/v1/oauth/authorizations":
            return httpx.Response(
                200,
                json={
                    "authorizationUrl": "https://accounts.feishu.cn/authorize?state=opaque",
                    "state": "opaque",
                },
            )
        if request.url.path == "/oauth/status":
            assert request.url.params["state"] == "opaque"
            return httpx.Response(
                200,
                json={
                    "service": "feishu",
                    "connectionName": "My-Feishu",
                    "status": "connected",
                },
            )
        raise AssertionError(request.url.path)

    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    from frontend.server.knowledge_workspace.connection import (
        ConnectionServiceConfig,
        ConnectionServiceGateway,
    )

    mount_knowledge_workspace_routes(
        app,
        service,
        connection_gateway=ConnectionServiceGateway(
            ConnectionServiceConfig("https://connections.test", "test-secret"),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
        allow_insecure_test_headers=True,
    )
    headers = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/api/knowledge/v1/oauth/authorize",
            headers=headers,
            json={
                "service": "feishu",
                "client_id": "cli_test",
                "client_secret": "app-secret",
                "connection_name": "My Feishu",
            },
        )
        status = await client.get(
            "/api/knowledge/v1/oauth/status",
            headers=headers,
            params={"state": "opaque"},
        )

    assert started.status_code == 200
    assert started.json()["data"]["connectionName"] == "My-Feishu"
    assert status.status_code == 200
    assert status.json()["data"]["status"] == "connected"
    assert "app-secret" not in started.text
    assert [request.url.path for request in requests] == [
        "/v1/oauth/configs",
        "/v1/oauth/authorizations",
        "/oauth/status",
    ]


def test_routes_require_trusted_actor_resolver_by_default() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    with pytest.raises(ValueError, match="trusted server-side actor_resolver"):
        mount_knowledge_workspace_routes(app, service)


@pytest.mark.asyncio
async def test_same_origin_routes_scope_draft_by_server_actor() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "x-tenant-id": "tenant-a",
            "x-workspace-id": "workspace-a",
            "x-principal-id": "user-a",
            "idempotency-key": "draft-key-123456-a",
        }
        response = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers=headers,
            json={"goal": "build a safe skill", "connection_ids": ["conn-a"]},
        )
        assert response.status_code == 201
        draft_id = response.json()["data"]["draft_id"]
        assert (
            await client.get(
                f"/api/knowledge/v1/skills/drafts/{draft_id}",
                headers=headers,
            )
        ).status_code == 200
        assert (
            await client.get(
                f"/api/knowledge/v1/skills/drafts/{draft_id}",
                headers={**headers, "x-tenant-id": "tenant-b"},
            )
        ).status_code == 404
        assert (
            await client.get(
                f"/api/knowledge/v1/skills/drafts/{draft_id}",
                headers={**headers, "x-workspace-id": "workspace-b"},
            )
        ).status_code == 404
        loaded = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers=headers,
        )
        assert loaded.headers["etag"]
        updated = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers={
                **headers,
                "if-match": loaded.headers["etag"],
                "idempotency-key": "patch-key-a-123456",
            },
            json={"goal": "updated goal"},
        )
        assert updated.status_code == 200
        conflict = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers={
                **headers,
                "if-match": loaded.headers["etag"],
                "idempotency-key": "patch-key-b-123456",
            },
            json={"goal": "stale write"},
        )
        assert conflict.status_code == 412


@pytest.mark.asyncio
async def test_authoring_routes_scope_drafts_sessions_and_invocations_by_principal() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    owner = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
    }
    other = {**owner, "x-principal-id": "user-b"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={**owner, "idempotency-key": "draft-key-principal-1"},
            json={"goal": "principal scoped skill", "connection_ids": ["conn-a"]},
        )
        assert created.status_code == 201
        draft_id = created.json()["data"]["draft_id"]
        sessions = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions",
            headers=owner,
        )
        session_id = sessions.json()["data"][0]["authoring_session_id"]
        invocation = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}/generate",
            headers={
                **owner,
                "if-match": created.headers["etag"],
                "idempotency-key": "generate-key-principal-1",
            },
        )
        invocation_id = invocation.json()["data"]["invocation_id"]

        hidden_list = await client.get("/api/knowledge/v1/skills/drafts", headers=other)
        hidden_draft = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}", headers=other
        )
        hidden_sessions = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions", headers=other
        )
        hidden_session = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}",
            headers=other,
        )
        hidden_conversation = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}/conversation",
            headers=other,
        )
        hidden_revisions = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/revisions",
            headers=other,
        )
        blocked_generate = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}/generate",
            headers={
                **other,
                "if-match": created.headers["etag"],
                "idempotency-key": "generate-key-principal-2",
            },
        )
        hidden_events = await client.get(
            f"/api/knowledge/v1/invocations/{invocation_id}/events",
            headers=other,
        )
        hidden_cancel = await client.post(
            f"/api/knowledge/v1/invocations/{invocation_id}/cancel",
            headers={**other, "idempotency-key": "cancel-key-principal-1"},
        )

    assert hidden_list.status_code == 200
    assert hidden_list.json()["data"] == []
    assert hidden_draft.status_code == 404
    assert hidden_sessions.status_code == 404
    assert hidden_session.status_code == 404
    assert hidden_conversation.status_code == 404
    assert hidden_revisions.status_code == 404
    assert blocked_generate.status_code == 404
    assert hidden_events.status_code == 404
    assert hidden_cancel.status_code == 404


@pytest.mark.asyncio
async def test_create_draft_idempotency_replays_and_conflicts() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "x-tenant-id": "tenant-a",
            "x-workspace-id": "workspace-a",
            "x-principal-id": "user-a",
            "idempotency-key": "draft-key-123456",
        }
        payload = {"goal": "same", "connection_ids": ["conn-a"]}
        first = await client.post(
            "/api/knowledge/v1/skills/drafts", headers=headers, json=payload
        )
        replay = await client.post(
            "/api/knowledge/v1/skills/drafts", headers=headers, json=payload
        )
        assert first.status_code == replay.status_code == 201
        assert first.json()["data"]["draft_id"] == replay.json()["data"]["draft_id"]
        conflict = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers=headers,
            json={"goal": "different", "connection_ids": ["conn-a"]},
        )
        assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_draft_routes_accept_and_return_w4_template_metadata() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-tenant-id": "t", "x-workspace-id": "w", "x-principal-id": "p"}
        created = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={**headers, "idempotency-key": "draft-key-123456-template"},
            json={
                "goal": "create a dashboard",
                "connection_ids": ["c"],
                "template_key": "dashboard",
                "template_config": {"refresh": True, "api_key": "secret"},
            },
        )

        assert created.status_code == 201
        assert created.json()["data"]["template_key"] == "dashboard"
        assert created.json()["data"]["template_config"] == {"refresh": True}

        patched = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{created.json()['data']['draft_id']}",
            headers={
                **headers,
                "if-match": created.headers["etag"],
                "idempotency-key": "patch-key-123456-template",
            },
            json={
                "template_key": "sop",
                "template_config": {"source": "openviking", "token": "secret"},
            },
        )

        assert patched.status_code == 200
        assert patched.json()["data"]["template_key"] == "sop"
        assert patched.json()["data"]["template_config"] == {"source": "openviking"}


@pytest.mark.asyncio
async def test_create_draft_accepts_unified_knowledge_source_refs() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
        knowledge_context_resolver=lambda actor, refs: {
            "profiles": [ref.profile_ref for ref in refs if ref.profile_ref],
            "resources": [ref.resource_ref for ref in refs if ref.resource_ref],
        },
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    headers = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
        "idempotency-key": "draft-unified-123456",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers=headers,
            json={
                "goal": "unified refs",
                "connection_ids": [],
                "knowledge_source_refs": [
                    {"provider": "openviking", "profile_ref": "profile-a"},
                    {"provider": "openviking", "resource_ref": "resource-a"},
                ],
            },
        )
    assert response.status_code == 201
    assert response.json()["data"]["knowledge_source_refs"] == [
        {"provider": "openviking", "profile_ref": "profile-a"},
        {"provider": "openviking", "resource_ref": "resource-a"},
    ]


@pytest.mark.asyncio
async def test_unconfigured_autoskill_fails_closed_on_generate() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("credential missing"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-tenant-id": "t", "x-workspace-id": "w", "x-principal-id": "p"}
        draft = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={**headers, "idempotency-key": "draft-key-123456-unconfigured"},
            json={"goal": "goal", "connection_ids": ["c"]},
        )
        response = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.json()['data']['draft_id']}/generate",
            headers={
                **headers,
                "idempotency-key": "generate-key-123456",
                "if-match": draft.headers["etag"],
            },
        )
        assert response.status_code == 202
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_browser_invocation_response_does_not_expose_upstream_ids() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("credential missing"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-tenant-id": "t", "x-workspace-id": "w", "x-principal-id": "p"}
        draft = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={**headers, "idempotency-key": "draft-key-123456-browser"},
            json={"goal": "goal", "connection_ids": ["c"]},
        )
        response = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.json()['data']['draft_id']}/generate",
            headers={
                **headers,
                "idempotency-key": "generate-key-123456-browser",
                "if-match": draft.headers["etag"],
            },
        )
        payload = response.json()["data"]
        assert response.status_code == 202
        assert "autoskill_agent_id" not in payload
        assert "autoskill_session_id" not in payload
        assert "autoskill_request_id" not in payload


@pytest.mark.asyncio
async def test_upload_is_idempotent_and_workspace_scoped() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    owner = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
        "idempotency-key": "upload-key-123456",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/knowledge/v1/uploads",
            headers=owner,
            files={"file": ("context.txt", b"context", "text/plain")},
        )
        replay = await client.post(
            "/api/knowledge/v1/uploads",
            headers=owner,
            files={"file": ("context.txt", b"context", "text/plain")},
        )
        assert first.status_code == replay.status_code == 201
        assert first.json()["data"]["upload_id"] == replay.json()["data"]["upload_id"]
        upload_id = first.json()["data"]["upload_id"]

        conflict = await client.post(
            "/api/knowledge/v1/uploads",
            headers=owner,
            files={"file": ("other.txt", b"other", "text/plain")},
        )
        assert conflict.status_code == 409

        hidden = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={
                **owner,
                "x-tenant-id": "tenant-b",
                "idempotency-key": "draft-key-123456-hidden",
            },
            json={
                "goal": "goal",
                "connection_ids": ["connection"],
                "upload_ids": [upload_id],
            },
        )
        assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_invocation_response_has_same_origin_event_url_and_etag_guard() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    headers = {
        "x-tenant-id": "tenant",
        "x-workspace-id": "workspace",
        "x-principal-id": "principal",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={**headers, "idempotency-key": "draft-key-123456-etag"},
            json={"goal": "goal", "connection_ids": ["connection"]},
        )
        draft_id = draft.json()["data"]["draft_id"]
        etag = (
            await client.get(
                f"/api/knowledge/v1/skills/drafts/{draft_id}", headers=headers
            )
        ).headers["etag"]
        updated = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers={
                **headers,
                "if-match": etag,
                "idempotency-key": "patch-key-etag-123456",
            },
            json={"goal": "new goal"},
        )
        assert updated.status_code == 200
        current_etag = updated.headers["etag"]
        invocation = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/generate",
            headers={
                **headers,
                "if-match": current_etag,
                "idempotency-key": "generate-key-123456-etag",
            },
        )
        assert invocation.status_code == 202
        payload = invocation.json()["data"]
        assert (
            payload["event_url"]
            == f"/api/knowledge/v1/invocations/{payload['invocation_id']}/events"
        )
        assert set(payload) == {
            "invocation_id",
            "authoring_session_id",
            "kind",
            "status",
            "message",
            "model",
            "started_at",
            "finished_at",
            "created_at",
            "knowledge_source_refs",
            "event_url",
        }
        stale = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/messages",
            headers={
                **headers,
                "if-match": etag,
                "idempotency-key": "message-key-stale-1",
            },
            json={"message": "stale", "intent": "update"},
        )
        assert stale.status_code == 412


@pytest.mark.asyncio
async def test_artifact_snapshot_content_is_same_origin_no_store_and_tenant_scoped() -> None:
    app = FastAPI()
    repository = KnowledgeWorkspaceRepository()
    service = KnowledgeWorkspaceService(
        repository,
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    html = b"<!doctype html><html><body>real preview</body></html>"
    digest = hashlib.sha256(html).hexdigest()
    uri = repository.put_object(digest, html, suffix=".html")
    repository.save_artifact_snapshot(
        "snapshot-live",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        invocation_id="invocation-a",
        expires_at=time.time() + 300,
        payload={
            "uri": uri,
            "sha256": digest,
            "media_type": "text/html",
            "csp": "default-src 'none'; connect-src 'none'",
            "sandbox": "allow-scripts",
            "source": html.decode("utf-8"),
        },
    )
    repository.save_artifact_snapshot(
        "snapshot-expired",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        invocation_id="invocation-a",
        expires_at=time.time() - 1,
        payload={
            "uri": uri,
            "sha256": digest,
            "media_type": "text/html",
            "csp": "default-src 'none'",
            "sandbox": "allow-scripts",
        },
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner_headers = {
            "x-tenant-id": "tenant-a",
            "x-workspace-id": "workspace-a",
            "x-principal-id": "user-a",
        }
        loaded = await client.get(
            "/api/knowledge/v1/artifact-snapshots/snapshot-live/content",
            headers=owner_headers,
        )
        cross_tenant = await client.get(
            "/api/knowledge/v1/artifact-snapshots/snapshot-live/content",
            headers={**owner_headers, "x-tenant-id": "tenant-b"},
        )
        expired = await client.get(
            "/api/knowledge/v1/artifact-snapshots/snapshot-expired/content",
            headers=owner_headers,
        )

    assert loaded.status_code == 200
    assert loaded.text == html.decode("utf-8")
    assert loaded.headers["content-type"].startswith("text/html")
    assert loaded.headers["cache-control"] == "no-store"
    assert loaded.headers["referrer-policy"] == "no-referrer"
    assert "connect-src 'none'" in loaded.headers["content-security-policy"]
    assert "allow-same-origin" not in loaded.text
    assert cross_tenant.status_code == 410
    assert expired.status_code == 410


@pytest.mark.asyncio
async def test_routes_require_concurrency_headers_and_support_not_modified() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    transport = httpx.ASGITransport(app=app)
    headers = {
        "x-tenant-id": "tenant",
        "x-workspace-id": "workspace",
        "x-principal-id": "principal",
        "idempotency-key": "draft-key-required-1",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={
                key: value for key, value in headers.items() if key != "idempotency-key"
            },
            json={"goal": "goal", "connection_ids": ["connection"]},
        )
        assert missing.status_code == 422
        created = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers=headers,
            json={"goal": "goal", "connection_ids": ["connection"]},
        )
        draft_id = created.json()["data"]["draft_id"]
        etag = created.headers["etag"]
        loaded = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers={**headers, "if-none-match": etag},
        )
        assert loaded.status_code == 304


@pytest.mark.asyncio
async def test_draft_conversation_restores_ordered_turns_from_bff_events() -> None:
    app = FastAPI()
    repository = KnowledgeWorkspaceRepository()
    service = KnowledgeWorkspaceService(
        repository,
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    actor = Actor("tenant", "workspace", "principal")
    actor_headers = {
        "x-tenant-id": actor.tenant_id,
        "x-workspace-id": actor.workspace_id,
        "x-principal-id": actor.principal_id,
    }
    draft = service.create_draft(actor, "goal", ["connection"])
    session = repository.get_session(
        draft.draft_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert session is not None
    for index, message in enumerate(("first question", "second question"), start=1):
        invocation = Invocation(
            tenant_id="tenant",
            workspace_id="workspace",
            invocation_id=f"inv-{index}",
            draft_id=draft.draft_id,
            authoring_session_id=session.authoring_session_id,
            kind=InvocationKind.RUN,
            autoskill_agent_id="private-agent",
            autoskill_session_id="private-session",
            autoskill_request_id=f"private-request-{index}",
            message=message,
        )
        repository.save_invocation(invocation)
        repository.append_event(
            invocation.invocation_id,
            {"type": "final_answer", "data": {"answer": f"answer {index}"}},
            {
                "id": f"answer-{index}",
                "type": "assistant.final",
                "invocation_id": invocation.invocation_id,
                "occurred_at": f"2026-08-28T00:00:0{index}+00:00",
                "data": {"content": f"answer {index}"},
            },
            f"answer-{index}",
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/conversation",
            headers=actor_headers,
        )

    assert response.status_code == 200
    turns = response.json()["data"]
    assert [turn["invocation"]["message"] for turn in turns] == [
        "first question",
        "second question",
    ]
    assert turns[0]["events"][0]["id"] == "answer-1"
    assert turns[0]["events"][0]["cursor"] == "1"
    assert "private-agent" not in response.text
    assert "private-session" not in response.text
    assert "private-request" not in response.text


@pytest.mark.asyncio
async def test_authoring_session_routes_are_scoped_and_idempotent() -> None:
    app = FastAPI()
    repository = KnowledgeWorkspaceRepository()
    service = KnowledgeWorkspaceService(
        repository,
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    headers = {
        "x-tenant-id": "tenant-a",
        "x-workspace-id": "workspace-a",
        "x-principal-id": "user-a",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        draft = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers={**headers, "idempotency-key": "draft-key-sessions-1"},
            json={"goal": "build a reusable skill", "connection_ids": ["conn-a"]},
        )
        assert draft.status_code == 201
        draft_id = draft.json()["data"]["draft_id"]

        initial = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions",
            headers=headers,
        )
        assert initial.status_code == 200
        assert len(initial.json()["data"]) == 1
        assert set(initial.json()["data"][0]) >= {
            "authoring_session_id",
            "draft_id",
            "title",
            "status",
            "last_message_preview",
            "active_invocation_id",
            "created_at",
            "updated_at",
        }

        create_headers = {**headers, "idempotency-key": "session-key-123456"}
        first = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions",
            headers=create_headers,
            json={"title": "验证口径"},
        )
        replay = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions",
            headers=create_headers,
            json={"title": "验证口径"},
        )
        assert first.status_code == replay.status_code == 201
        assert first.json()["data"]["authoring_session_id"] == replay.json()["data"][
            "authoring_session_id"
        ]
        session_id = first.json()["data"]["authoring_session_id"]
        assert first.json()["data"]["title"] == "验证口径"

        patched = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}",
            headers={**headers, "idempotency-key": "session-patch-123456"},
            json={"title": "新版口径"},
        )
        assert patched.status_code == 200
        assert patched.json()["data"]["title"] == "新版口径"

        assert (
            await client.get(
                f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}",
                headers={**headers, "x-tenant-id": "tenant-b"},
            )
        ).status_code == 404
        assert (
            await client.get(
                f"/api/knowledge/v1/skills/drafts/{draft_id}/sessions/{session_id}",
                headers={**headers, "x-workspace-id": "workspace-b"},
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_session_listing_backfills_legacy_draft_without_session() -> None:
    app = FastAPI()
    repository = KnowledgeWorkspaceRepository()
    service = KnowledgeWorkspaceService(
        repository,
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    actor_value = Actor("tenant", "workspace", "principal")
    draft = SkillDraft(
        tenant_id=actor_value.tenant_id,
        workspace_id=actor_value.workspace_id,
        draft_id="draft-legacy",
        created_by=actor_value.principal_id,
        goal="legacy draft goal",
        connection_ids=("connection",),
        etag="etag-legacy",
    )
    repository.save_draft(draft)
    headers = {
        "x-tenant-id": actor_value.tenant_id,
        "x-workspace-id": actor_value.workspace_id,
        "x-principal-id": actor_value.principal_id,
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/sessions",
            headers=headers,
        )
        session_id = response.json()["data"][0]["authoring_session_id"]
        sent = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/messages",
            headers={
                **headers,
                "if-match": draft.etag,
                "idempotency-key": "legacy-message-key-123456",
            },
            json={"message": "continue", "intent": "run"},
        )

    assert response.status_code == 200
    assert len(response.json()["data"]) == 1
    assert response.json()["data"][0]["title"] == "legacy draft goal"
    assert sent.status_code == 202
    assert sent.json()["data"]["authoring_session_id"] == session_id


@pytest.mark.asyncio
async def test_session_scoped_messages_replay_and_restore_only_that_session() -> None:
    app = FastAPI()
    repository = KnowledgeWorkspaceRepository()
    service = KnowledgeWorkspaceService(
        repository,
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service, allow_insecure_test_headers=True)
    actor_value = Actor("tenant", "workspace", "principal")
    headers = {
        "x-tenant-id": actor_value.tenant_id,
        "x-workspace-id": actor_value.workspace_id,
        "x-principal-id": actor_value.principal_id,
    }
    draft = service.create_draft(actor_value, "goal", ["connection"])
    first_session = repository.get_session(
        draft.draft_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert first_session is not None
    second_session = service.create_session(actor_value, draft.draft_id, title="second")

    first_invocation = Invocation(
        tenant_id="tenant",
        workspace_id="workspace",
        invocation_id="inv-first",
        draft_id=draft.draft_id,
        authoring_session_id=first_session.authoring_session_id,
        kind=InvocationKind.RUN,
        status=InvocationStatus.SUCCEEDED,
        autoskill_agent_id="private-agent-1",
        autoskill_session_id="private-session-1",
        autoskill_request_id="private-request-1",
        message="first",
    )
    second_invocation = Invocation(
        tenant_id="tenant",
        workspace_id="workspace",
        invocation_id="inv-second",
        draft_id=draft.draft_id,
        authoring_session_id=second_session.authoring_session_id,
        kind=InvocationKind.RUN,
        status=InvocationStatus.RUNNING,
        autoskill_agent_id="private-agent-2",
        autoskill_session_id="private-session-2",
        autoskill_request_id="private-request-2",
        message="second",
    )
    repository.save_invocation(first_invocation)
    repository.save_invocation(second_invocation)
    repository.save_session(
        second_session.model_copy(
            update={
                "status": "running",
                "active_invocation_id": second_invocation.invocation_id,
                "last_message_preview": second_invocation.message,
            }
        )
    )
    repository.append_event(
        first_invocation.invocation_id,
        {"type": "final_answer", "data": {"answer": "first answer"}},
        {
            "id": "first-answer",
            "type": "assistant.final",
            "invocation_id": first_invocation.invocation_id,
            "occurred_at": "2026-08-28T00:00:01+00:00",
            "data": {"content": "first answer"},
        },
        "first-answer",
    )
    repository.append_event(
        second_invocation.invocation_id,
        {"type": "run.started"},
        {
            "id": "second-started",
            "type": "run.started",
            "invocation_id": second_invocation.invocation_id,
            "occurred_at": "2026-08-28T00:00:02+00:00",
            "data": {"kind": "run", "status": "running", "draft_id": draft.draft_id},
        },
        "second-started",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        restored = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/sessions/{second_session.authoring_session_id}",
            headers=headers,
        )
        conversation = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/sessions/{second_session.authoring_session_id}/conversation",
            headers=headers,
        )
        sent = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/sessions/{first_session.authoring_session_id}/messages",
            headers={
                **headers,
                "if-match": draft.etag,
                "idempotency-key": "message-session-key-123456",
            },
            json={"message": "follow up", "intent": "run"},
        )
        replay = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.draft_id}/sessions/{first_session.authoring_session_id}/messages",
            headers={
                **headers,
                "if-match": draft.etag,
                "idempotency-key": "message-session-key-123456",
            },
            json={"message": "follow up", "intent": "run"},
        )

    assert restored.status_code == 200
    assert restored.json()["data"]["active_invocation_id"] == "inv-second"
    assert restored.json()["data"]["last_event_cursor"] == "1"
    assert conversation.status_code == 200
    assert [item["invocation"]["invocation_id"] for item in conversation.json()["data"]] == [
        "inv-second"
    ]
    assert "private-agent" not in conversation.text
    assert sent.status_code == replay.status_code == 202
    assert sent.json()["data"]["invocation_id"] == replay.json()["data"][
        "invocation_id"
    ]
    assert (
        sent.json()["data"]["authoring_session_id"]
        == first_session.authoring_session_id
    )
