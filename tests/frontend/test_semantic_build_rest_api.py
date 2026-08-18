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
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "semantic rest local key")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
    )
    with TestClient(app) as http:
        yield http


def _schema() -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "store_sales",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "store", "type": "varchar"},
                    {"name": "sell_date", "type": "date"},
                    {"name": "ticket_count", "type": "integer"},
                    {"name": "member_card_no", "type": "varchar"},
                ],
            }
        ],
        "freshness": {"snapshot_id": "snap-rest", "data_through": "2026-08-15"},
    }


def test_semantic_build_routes_are_registered(client: TestClient) -> None:
    paths = {getattr(route, "path", "") for route in client.app.router.routes}
    assert "/api/knowledge-assets/semantic-build/jobs" in paths
    assert "/api/knowledge-assets/semantic-build/jobs/{job_id}/run" in paths
    assert "/api/knowledge-assets/semantic-build/jobs/{job_id}/publish" in paths
    assert "/api/knowledge-assets/semantic-build/jobs/{job_id}/artifacts" in paths
    assert "/api/knowledge-assets/assets/{asset_type}/{asset_id}/query" in paths
    assert "/api/external/assets/{asset_type}/{asset_id}/query" in paths


def test_semantic_build_rest_api_runs_publishes_and_queries(client: TestClient) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle sanitized",
            "metadata": {
                "schema": _schema(),
                "api_key": "must-not-leak-rest",
            },
        },
    ).json()

    created = client.post(
        "/api/knowledge-assets/semantic-build/jobs",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "mode": "schema_only",
            "target_domain": "sales",
            "dashboard_goal": "sales overview",
            "publish": False,
        },
    )
    assert created.status_code == 201
    job_id = created.json()["job_id"]

    ready = client.post(f"/api/knowledge-assets/semantic-build/jobs/{job_id}/run")
    assert ready.status_code == 200
    ready_payload = ready.json()
    assert ready_payload["status"] == "ready_to_publish"
    assert ready_payload["blocked_reasons"] == []

    published = client.post(f"/api/knowledge-assets/semantic-build/jobs/{job_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    assets = client.get("/api/external/assets?types=semantic_model,dashboard").json()
    assert assets["total"] == 2
    assert {item["asset_type"] for item in assets["items"]} == {
        "semantic_model",
        "dashboard",
    }
    assert "must-not-leak-rest" not in json.dumps(assets, ensure_ascii=False)

    semantic_id = ready_payload["semantic_model_slug"]
    query = client.post(
        f"/api/external/assets/semantic_model/{semantic_id}/query",
        json={"question": "按门店统计最近销售票数 Top 3", "limit": 3},
    )
    assert query.status_code == 200
    data = query.json()["data"]
    assert data["rows"]
    assert "SELECT" in data["sql"]
    assert data["metricDefinition"]
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["snapshot_id"] == "snap-rest"

    denied = client.post(
        f"/api/knowledge-assets/assets/semantic_model/{semantic_id}/query",
        json={"question": "列出会员卡号和客户联系方式"},
    )
    assert denied.status_code == 200
    assert denied.json()["data"]["policyDecision"]["decision"] == "deny"

    artifacts = client.get(
        f"/api/knowledge-assets/semantic-build/jobs/{job_id}/artifacts"
    )
    assert artifacts.status_code == 200
    assert "must-not-leak-rest" not in artifacts.text
