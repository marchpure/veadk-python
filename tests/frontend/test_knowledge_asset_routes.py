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
    assert "/api/knowledge-assets/connectors" in paths
    assert "/api/knowledge-assets/sources" in paths
    assert "/api/knowledge-assets/sources/import" in paths
    assert "/api/knowledge-assets/source-resources" in paths
    assert "/api/knowledge-assets/source-resources/{resource_row_id}" in paths
    assert "/api/knowledge-assets/sources/{source_id}/credential" in paths
    assert "/api/knowledge-assets/build/semantic-skill" in paths
    assert "/api/knowledge-assets/build-jobs" in paths
    assert "/api/knowledge-assets/workbench/overview" in paths
    assert "/api/knowledge-assets/assets/{asset_type}/{asset_id}" in paths
    assert "/api/external/assets/{asset_type}/{asset_id}/query" in paths


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
    assert body["status"] == "connected"
    assert "algorithm" not in body
    assert "key_id" not in body
    assert "redact-me-route-alpha" not in json.dumps(body)
    assert "redact-me-route-beta" not in json.dumps(body)

    status = client.get(
        f"/api/knowledge-assets/sources/{source['id']}/credential"
    ).json()
    assert status["configured"] is True
    assert status["status"] == "connected"
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
    assert item["id"] == "byaan-datastudio"
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


def test_import_route_records_metadata_only_database_without_fake_success(
    client: TestClient,
) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    response = client.post(
        "/api/knowledge-assets/sources/import",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "name": "Oracle 销售库",
            "metadata": {"password": "redact-me-db"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source"]["status"] == "needs_configuration"
    assert payload["job"]["status"] == "blocked"
    assert payload["resource"]["sync_status"] == "needs_configuration"
    assert payload["resource"]["source_type"] == "database_schema"
    assert "redact-me-db" not in response.text


def test_import_route_feishu_requires_configuration_without_fake_success(
    client: TestClient,
) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    response = client.post(
        "/api/knowledge-assets/sources/import",
        json={
            "space_id": space["id"],
            "source_type": "feishu_doc",
            "name": "飞书文档",
            "uri": "https://example.feishu.cn/docx/doc_token",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source"]["status"] == "needs_configuration"
    assert payload["job"]["status"] == "blocked"
    assert "OAuth" in payload["source"]["status_reason"]
    assert payload["resource"]["sync_status"] == "needs_configuration"


def test_schema_snapshot_import_route_registers_ready_source(
    client: TestClient,
) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    imported = client.post(
        "/api/knowledge-assets/sources/import",
        json={
            "space_id": space["id"],
            "source_type": "schema_snapshot",
            "name": "销售 Schema",
            "schema": {
                "models": [{"name": "orders"}],
                "fields": [{"model": "orders", "name": "gmv", "role": "measure"}],
            },
        },
    )
    assert imported.status_code == 201
    payload = imported.json()
    assert payload["source"]["status"] == "ready"
    assert payload["job"]["status"] == "succeeded"
    assert payload["document"]["kind"] == "schema_snapshot"
    assert payload["resource"]["source_type"] == "database_schema"
    assert payload["resource"]["sync_status"] == "ready"

    snapshots = client.get(
        f"/api/knowledge-assets/snapshots?source_id={payload['source']['id']}"
    ).json()
    assert snapshots["total"] == 1
    assert snapshots["items"][0]["schema"]["models"][0]["name"] == "orders"


def test_connector_registry_route_returns_manifest_contract(
    client: TestClient,
) -> None:
    response = client.get("/api/knowledge-assets/connectors")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "knowledge_asset.connector_registry.v1"
    assert payload["mock"] is False
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["web"]["availability"] == "available"
    assert by_id["web"]["category"] == "document"
    assert "import_resource" in by_id["web"]["capabilities"]
    assert by_id["feishu_doc"]["availability"] == "needs_auth"
    assert by_id["postgres"]["availability"] == "preview"
    assert by_id["custom_rest"]["availability"] == "planned"

    database = client.get("/api/knowledge-assets/connectors?category=database")
    assert database.status_code == 200
    assert {item["category"] for item in database.json()["items"]} == {"database"}


def test_source_resource_routes_crud_and_redaction(client: TestClient) -> None:
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
        "/api/knowledge-assets/source-resources",
        json={
            "asset_space_id": space["id"],
            "source_id": source["id"],
            "resource_id": "doc-1",
            "source_type": "web_page",
            "provider": "web",
            "uri": "https://example.com/docs",
            "content_hash": "sha256:abc",
            "tags": ["docs"],
            "permission_scope": "public",
            "sync_status": "indexed",
            "metadata": {"cookie": "redact-me-resource"},
        },
    )
    assert created.status_code == 201
    resource = created.json()
    assert resource["metadata"]["cookie"] == "[REDACTED]"
    assert "redact-me-resource" not in created.text

    listed = client.get(
        f"/api/knowledge-assets/source-resources?asset_space_id={space['id']}"
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == resource["id"]

    updated = client.patch(
        f"/api/knowledge-assets/source-resources/{resource['id']}",
        json={"sync_status": "stale", "freshness": {"state": "stale"}},
    )
    assert updated.status_code == 200
    assert updated.json()["sync_status"] == "stale"

    deleted = client.delete(f"/api/knowledge-assets/source-resources/{resource['id']}")
    assert deleted.status_code == 204
    assert client.get(
        f"/api/knowledge-assets/source-resources?asset_space_id={space['id']}"
    ).json()["total"] == 0


def test_semantic_build_route_reports_missing_space_without_fake_success(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={"space_id": "space_missing", "name": "销售语义 Skill"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "KNOWLEDGE_ASSET_INVALID_REQUEST"


def test_workbench_overview_is_real_aggregation(client: TestClient) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    client.post(
        "/api/knowledge-assets/sources/import",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "name": "DB",
        },
    )
    overview = client.get(
        f"/api/knowledge-assets/workbench/overview?space_id={space['id']}"
    )
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["mock"] is False
    assert payload["source_counts"]["needs_configuration"] == 1
    assert payload["recent_jobs"][0]["status"] == "blocked"


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
