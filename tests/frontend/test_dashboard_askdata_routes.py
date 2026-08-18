from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "dashboard askdata test key")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
    )
    return TestClient(app)


def test_askdata_query_returns_required_evidence(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    data = body["data"]
    assert data["rows"]
    assert "SELECT" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["status"] == "fresh"
    assert "secret" not in response.text.lower()


def test_askdata_denies_customer_contact_questions(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "question": "列出 customer phone contact",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["data"]["policyDecision"]["decision"] == "deny"
    assert body["data"]["freshness"]["status"] == "blocked"


def test_dashboard_skill_build_records_skill_package_and_job(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    space_id = _semantic_skill(client)

    response = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "space_id": space_id,
            "semantic_asset_id": "oracle-sales",
            "name": "Oracle Sales Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    dashboard = body["dashboard"]
    assert dashboard["asset_type"] == "dashboard"
    assert dashboard["publish_state"] == "published"
    package = dashboard["capability_package"]
    assert package["runtime"]["query_url"].startswith(
        "/api/knowledge-assets/assets/dashboard/"
    )
    assert package["runtime"]["direct_database_access"] is False
    assert "dashboard_spec.json" in package["artifacts"]
    assert "tools/query_dashboard_metric.py" in package["artifacts"]
    tool = package["artifacts"]["tools/query_dashboard_metric.py"]
    assert "STUDIO_BASE_URL" in tool
    assert "STUDIO_GOVERNED_QUERY_TOKEN" in tool
    assert "startswith(\"//\")" in tool
    assert "must stay on Studio origin" in tool
    assert "/api/knowledge-assets/assets/dashboard/" in tool
    assert not re.search(r"DATASTUDIO_(API_KEY|BASE_URL)", tool)
    assert "direct_database_access" not in tool
    assert "password" not in response.text.lower()
    assert "client_secret" not in response.text.lower()

    run = client.post(
        f"/api/knowledge-assets/assets/dashboard/{body['dashboard_asset_id']}/query",
        json={"data_view_ids": ["primary_metric"]},
    )
    assert run.status_code == 200
    run_body = run.json()
    assert run_body["contract_version"] == "dashboard.run.v1"
    view = run_body["views"][0]
    assert view["policyDecision"]["decision"] == "allow"
    assert view["sql"]
    assert view["metricDefinition"] == "Count distinct tickets."
    assert view["freshness"]["status"] == "fresh"


def _semantic_skill(client: TestClient) -> str:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "Oracle"}).json()
    package = {
        "package_type": "semantic_skill",
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": "/api/knowledge-assets/assets/semantic_model/oracle-sales/query",
            "direct_database_access": False,
            "raw_sql_fallback": False,
        },
        "mdl": {
            "schema": "agentkit.mdl.v1",
            "model": {"id": "oracle-sales", "slug": "oracle-sales", "version": "v1"},
            "entities": [{"id": "sales", "table": "sales_order"}],
            "metrics": [
                {
                    "id": "ticket_count",
                    "name": "Ticket Count",
                    "formula": "count_distinct(ticket_id)",
                    "definition": "Count distinct tickets.",
                    "time_field": "sell_date",
                    "evidence": [{"kind": "metric", "title": "ticket"}],
                }
            ],
            "dimensions": [
                {"id": "store", "name": "Store", "field": "store_name"},
                {"id": "sell_date", "name": "Sell Date", "field": "sell_date", "kind": "time"},
            ],
            "permissions": {
                "raw_sql_fallback": False,
                "permission_hint": "Aggregates only.",
                "denied_fields": [{"field": "customer_phone"}],
            },
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
        },
        "governance": {
            "raw_sql_fallback": False,
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
    }
    response = client.post(
        "/api/knowledge-assets/skill-packages",
        json={
            "space_id": space["id"],
            "asset_type": "semantic_model",
            "asset_id": "oracle-sales",
            "capability_kind": "semantic_skill",
            "name": "Oracle Sales",
            "status": "ready",
            "publish_state": "published",
            "type": "semantic_skill",
            "query_url": "/api/knowledge-assets/assets/semantic_model/oracle-sales/query",
            "capability_package": package,
            "capabilities": {
                "metrics": ["ticket_count"],
                "dimensions": ["store", "sell_date"],
            },
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
    )
    assert response.status_code == 201
    return space["id"]
