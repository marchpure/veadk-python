from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "route local key material")
    app = FastAPI()
    service = KnowledgeAssetStore(
        repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
    )
    mount_knowledge_asset_routes(app, service=service)
    with TestClient(app) as http:
        yield http


def test_routes_mount_on_fastapi_app(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "mount local key material")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
    )
    paths = {getattr(route, "path", "") for route in app.router.routes}

    assert "/api/knowledge-assets/spaces" in paths
    assert "/api/knowledge-assets/sources" in paths
    assert "/api/knowledge-assets/sources/{source_id}/credential" in paths
    assert "/api/knowledge-assets/capabilities" not in paths
    assert "/api/knowledge-assets/build-jobs" in paths
    assert "/api/knowledge-assets/skill-packages" in paths
    assert "/api/knowledge-assets/semantic-build/jobs" in paths
    assert "/api/knowledge-assets/semantic-build/jobs/{job_id}/run" in paths
    assert "/api/knowledge-assets/assets/{asset_type}/{asset_id}" in paths


def test_routes_create_store_and_never_echo_credentials(client: TestClient) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "feishu",
            "name": "Feishu",
            "metadata": {"token": "redact-me-route-meta"},
        },
    ).json()

    assert source["metadata"]["token"] == "[REDACTED]"

    response = client.put(
        f"/api/knowledge-assets/sources/{source['id']}/credential",
        json={
            "credentials": {
                "access_token": "redact-me-route-alpha",
                "client_secret": "redact-me-route-beta",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert "redact-me-route-alpha" not in json.dumps(body)
    assert "redact-me-route-beta" not in json.dumps(body)

    status = client.get(
        f"/api/knowledge-assets/sources/{source['id']}/credential"
    ).json()
    assert status["configured"] is True
    assert "redact-me-route-alpha" not in json.dumps(status)

    delete = client.delete(f"/api/knowledge-assets/sources/{source['id']}/credential")
    assert delete.status_code == 204
    missing = client.get(f"/api/knowledge-assets/sources/{source['id']}/credential")
    assert missing.status_code == 404
    assert "redact-me-route-alpha" not in missing.text


def test_contract_asset_routes_list_only_published_packages(client: TestClient) -> None:
    client.post("/api/knowledge-assets/skill-packages", json=_package("draft", "draft"))
    published = client.post(
        "/api/knowledge-assets/skill-packages",
        json=_package("published", "published"),
    )
    assert published.status_code == 201

    listed = client.get("/api/knowledge-assets/assets").json()
    assert listed["schema_version"] == "knowledge_asset.list.v1"
    assert listed["total"] == 1
    assert listed["items"][0]["asset_id"] == "published"
    assert listed["mock"] is False

    loaded = client.get(
        "/api/knowledge-assets/assets/knowledge_resource/published"
    ).json()
    assert loaded["schema_version"] == "knowledge_asset.metadata.v1"
    assert loaded["capability_kind"] == "retrieval_binding"

    draft = client.get("/api/knowledge-assets/assets/knowledge_resource/draft")
    assert draft.status_code == 404


def test_route_errors_are_structured_and_redacted(client: TestClient) -> None:
    response = client.post(
        "/api/knowledge-assets/skill-packages",
        json={
            **_package("published", "bad"),
            "query_url": "https://evil.example/?token=redact-me-query",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "KNOWLEDGE_ASSET_INVALID_REQUEST"
    assert "redact-me-query" not in response.text


def test_sidecar_status_is_safe_when_datastudio_is_unconfigured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATASTUDIO_API_KEY", raising=False)
    monkeypatch.delenv("DATASTUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("DATASTUDIO_EMBED_URL", raising=False)
    monkeypatch.setenv("DATASTUDIO_AUTO_DISCOVER", "0")

    response = client.get("/api/knowledge-assets/sidecars")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "governed-query-backend"
    assert item["status"] == "not_configured"
    assert item["configured"] is False
    assert "DATASTUDIO_API_KEY" not in response.text


def test_build_job_routes_record_state_without_echoing_secrets(
    client: TestClient,
) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "web",
            "name": "Docs",
        },
    ).json()

    created = client.post(
        "/api/knowledge-assets/build-jobs",
        json={
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "docs-retrieval",
            "job_type": "retrieval_binding",
            "status": "running",
            "input": {"Authorization": "Bearer redact-me-build"},
        },
    )

    assert created.status_code == 201
    job = created.json()
    assert job["status"] == "running"
    assert job["input"]["Authorization"] == "[REDACTED]"
    assert "redact-me-build" not in created.text

    updated = client.patch(
        f"/api/knowledge-assets/build-jobs/{job['id']}",
        json={
            "status": "failed",
            "error": {"message": "token=redact-me-failed"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "failed"
    assert "redact-me-failed" not in updated.text

    listed = client.get(
        f"/api/knowledge-assets/build-jobs?space_id={space['id']}"
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == job["id"]


def test_skill_package_route_creates_structured_semantic_package(
    client: TestClient,
) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "schema_snapshot",
            "name": "Sales schema",
        },
    ).json()

    package = {
        "package_type": "semantic_skill",
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": "/api/knowledge-assets/assets/semantic_model/sales-semantic/query",
            "direct_database_access": False,
        },
        "mdl": {
            "schema": "agentkit.mdl.v1",
            "model": {"slug": "sales-semantic", "version": "v1"},
            "metrics": [{"id": "gmv", "formula": "sum(amount)"}],
            "dimensions": [{"id": "region", "field": "region"}],
        },
        "evals": {"suite": {"contract_version": "evaluation.suite_version.v1"}},
        "governance": {
            "raw_sql_fallback": False,
            "permission_hint": "Aggregate only.",
        },
    }
    response = client.post(
        "/api/knowledge-assets/skill-packages",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "asset_type": "semantic_model",
            "asset_id": "sales-semantic",
            "capability_kind": "semantic_skill",
            "name": "Sales Semantic",
            "status": "ready",
            "publish_state": "draft",
            "type": "semantic_skill",
            "query_url": "/api/knowledge-assets/assets/semantic_model/sales-semantic/query",
            "capability_package": package,
            "metadata": {"token": "redact-me-capability"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["asset_type"] == "semantic_model"
    assert body["query_url"] == "/api/knowledge-assets/assets/semantic_model/sales-semantic/query"
    assert body["capability_package"]["package_type"] == "semantic_skill"
    assert body["capability_package"]["runtime"]["transport"] == "agentkit_governed_rest"
    assert body["capability_package"]["runtime"]["direct_database_access"] is False
    assert body["capability_package"]["mdl"]["schema"] == "agentkit.mdl.v1"
    assert body["capability_package"]["evals"]["suite"]["contract_version"] == "evaluation.suite_version.v1"
    assert "redact-me-capability" not in response.text


def _package(state: str, asset_id: str) -> dict[str, object]:
    return {
        "asset_type": "knowledge_resource",
        "asset_id": asset_id,
        "capability_kind": "retrieval_binding",
        "name": f"{asset_id} retrieval",
        "status": "ready",
        "publish_state": state,
        "query_url": f"/api/knowledge-assets/assets/knowledge_resource/{asset_id}",
    }
