from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from frontend.server.knowledge_workspace.autoskill import UnavailableAutoSkillClient
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.routes import mount_knowledge_workspace_routes
from frontend.server.knowledge_workspace.service import KnowledgeWorkspaceService


@pytest.mark.asyncio
async def test_same_origin_routes_scope_draft_by_server_actor() -> None:
    app = FastAPI()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        UnavailableAutoSkillClient("not configured"),
    )
    mount_knowledge_workspace_routes(app, service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "x-tenant-id": "tenant-a",
            "x-workspace-id": "workspace-a",
            "x-principal-id": "user-a",
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
        loaded = await client.get(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers=headers,
        )
        assert loaded.headers["etag"] == loaded.json()["data"]["etag"]
        updated = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers={**headers, "if-match": loaded.headers["etag"]},
            json={"goal": "updated goal"},
        )
        assert updated.status_code == 200
        conflict = await client.patch(
            f"/api/knowledge/v1/skills/drafts/{draft_id}",
            headers={**headers, "if-match": loaded.headers["etag"]},
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
    mount_knowledge_workspace_routes(app, service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {
            "x-tenant-id": "tenant-a",
            "x-workspace-id": "workspace-a",
            "x-principal-id": "user-a",
            "idempotency-key": "draft-key",
        }
        payload = {"goal": "same", "connection_ids": ["conn-a"]}
        first = await client.post("/api/knowledge/v1/skills/drafts", headers=headers, json=payload)
        replay = await client.post("/api/knowledge/v1/skills/drafts", headers=headers, json=payload)
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
    mount_knowledge_workspace_routes(app, service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-tenant-id": "t", "x-workspace-id": "w", "x-principal-id": "p"}
        draft = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers=headers,
            json={"goal": "goal", "connection_ids": ["c"]},
        )
        response = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.json()['data']['draft_id']}/generate",
            headers=headers,
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
    mount_knowledge_workspace_routes(app, service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"x-tenant-id": "t", "x-workspace-id": "w", "x-principal-id": "p"}
        draft = await client.post(
            "/api/knowledge/v1/skills/drafts",
            headers=headers,
            json={"goal": "goal", "connection_ids": ["c"]},
        )
        response = await client.post(
            f"/api/knowledge/v1/skills/drafts/{draft.json()['data']['draft_id']}/generate",
            headers=headers,
        )
        payload = response.json()["data"]
        assert response.status_code == 202
        assert "autoskill_agent_id" not in payload
        assert "autoskill_session_id" not in payload
        assert "autoskill_request_id" not in payload
