from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.knowledge_workspace.autoskill import UnavailableAutoSkillClient
from frontend.server.knowledge_workspace.models import Invocation, InvocationKind
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
            "kind",
            "status",
            "message",
            "model",
            "started_at",
            "finished_at",
            "created_at",
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
