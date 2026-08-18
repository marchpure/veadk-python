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
    assert data["rows"] == [
        {"store": "VNPTTE", "ticket_count": 56},
        {"store": "SG - ANTA VIVO City", "ticket_count": 9},
    ]
    assert "SALES_ORDER" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["status"] == "fresh"
    assert data["execution"]["governed_rest"] is True
    assert data["execution"]["direct_database_access"] is False
    assert "secret" not in response.text.lower()


def test_askdata_uses_e2_schema_only_governed_query_without_fixture_result(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "schema-only-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    data = body["data"]
    assert data["rows"] == []
    assert data["returnedCount"] == 0
    assert "SELECT" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["decision"] == "allow"
    assert data["execution"]["mode"] == "schema_only"
    assert data["execution"]["governed_rest"] is True
    assert data["execution"]["direct_database_access"] is False
    assert "COUNT(DISTINCT" in data["sql"]


def test_askdata_accepts_current_e2_inline_mdl_package_without_fixture_result(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="e2-inline-sales",
        governed_result=False,
        artifacts_mdl=False,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "e2-inline-sales",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "question": "按门店统计最近销售票数 Top 3",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution"]["mode"] == "schema_only"
    assert data["rows"] == []
    assert data["returnedCount"] == 0
    assert data["sql"].startswith("SELECT")
    assert "COUNT(DISTINCT" in data["sql"]
    assert data["metricDefinition"] == "Count distinct tickets."
    assert data["policyDecision"]["direct_database_access"] is False


def test_schema_only_query_sanitizes_mdl_metadata_in_sql_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
        malicious_metadata=True,
    )

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "schema-only-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "filters": {"region; DROP TABLE audit": "SG' OR '1'='1"},
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    sql = response.json()["data"]["sql"]
    assert "DROP" not in sql
    assert "--" not in sql
    assert "COUNT(DISTINCT" in sql
    assert '"sales_order_TABLE_users"' in sql
    assert '"store_name_TABLE_users"' in sql
    assert '"region_TABLE_audit"' in sql
    assert "SG'' OR ''1''=''1" in sql
    assert "ticket_id) FROM" not in sql


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
    assert body["data"]["sql"].startswith("-- policy denied")
    assert body["data"]["metricDefinition"] == "Count distinct tickets."
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
    assert view["result"] == [
        {"store": "VNPTTE", "ticket_count": 56},
        {"store": "SG - ANTA VIVO City", "ticket_count": 9},
    ]
    assert view["sql"]
    assert view["metricDefinition"] == "Count distinct tickets."
    assert view["freshness"]["status"] == "fresh"


def test_dashboard_skill_build_accepts_e2_schema_only_semantic_package(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    space_id = _semantic_skill(
        client,
        asset_id="schema-only-sales",
        governed_result=False,
        artifacts_mdl=True,
    )

    response = client.post(
        "/api/knowledge-assets/build/dashboard-skill",
        json={
            "space_id": space_id,
            "semantic_asset_id": "schema-only-sales",
            "name": "Schema Only Sales Dashboard",
            "intent": "按门店查看销售票数",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "publish": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["askdata"]["data"]["execution"]["mode"] == "schema_only"
    views = body["preview"]["data_views"]
    assert views[0]["rows"] == []
    assert views[0]["sql"]
    assert views[0]["policyDecision"]["decision"] == "allow"


def test_semantic_asset_query_route_matches_e2_governed_contract(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client, artifacts_mdl=True)

    response = client.post(
        "/api/external/assets/semantic_model/oracle-sales/query",
        json={
            "metric": "ticket_count",
            "dimensions": ["store"],
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "agentkit.semantic_query_result.v1"
    data = body["data"]
    assert data["rows"][0]["ticket_count"] == 56
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"]["as_of"] == "2026-08-18T00:00:00Z"


def test_askdata_normalizes_byaan_external_query_result_shape(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _semantic_skill(client, asset_id="byaan-sales", byaan_shape=True)

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "byaan-sales",
            "metric": "ticket_count",
            "dimension": "store",
            "question": "按门店查看销售票数",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rows"] == [{"store": "VNPTTE", "ticket_count": 56}]
    assert data["metric"]["name"] == "Ticket Count"
    assert data["policyDecision"]["decision"] == "allow"
    assert data["freshness"] == {
        "status": "fresh",
        "as_of": "2026-08-18T06:55:06Z",
    }


def _semantic_skill(
    client: TestClient,
    *,
    asset_id: str = "oracle-sales",
    governed_result: bool = True,
    artifacts_mdl: bool = False,
    byaan_shape: bool = False,
    malicious_metadata: bool = False,
) -> str:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "Oracle"}).json()
    mdl = {
        "schema": "agentkit.mdl.v1",
        "model": {"id": asset_id, "slug": asset_id, "version": "v1"},
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
    }
    if malicious_metadata:
        mdl["entities"][0]["table"] = "sales_order; DROP TABLE users"
        mdl["metrics"][0]["formula"] = "count(distinct ticket_id) FROM users --"
        mdl["metrics"][0]["field"] = "ticket_id"
        mdl["metrics"][0]["kind"] = "count_distinct"
        mdl["dimensions"][0]["field"] = "store_name; DROP TABLE users"
    result = {
        "schema": "agentkit.semantic_query_result.v1",
        "data": {
            "rows": [
                {"store": "VNPTTE", "ticket_count": 56},
                {"store": "SG - ANTA VIVO City", "ticket_count": 9},
            ],
            "returnedCount": 2,
            "metric": {
                "id": "ticket_count",
                "name": "Ticket Count",
                "definition": "Count distinct tickets.",
                "formula": "count_distinct(ticket_id)",
            },
            "dimensions": [{"id": "store", "name": "Store", "field": "store_name"}],
            "sql": (
                "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count "
                "FROM SALES_ORDER GROUP BY store_name ORDER BY ticket_count DESC LIMIT 100"
            ),
            "metricDefinition": "Count distinct tickets.",
            "policyDecision": {
                "decision": "allow",
                "reason": "Aggregates only.",
                "raw_sql_fallback": False,
                "denied_fields": [{"field": "customer_phone"}],
            },
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            "lineage": [{"kind": "snapshot", "title": "oracle sanitized"}],
            "evidence": [{"kind": "metric", "title": "ticket"}],
            "execution": {
                "mode": "governed_semantic_skill_fixture",
                "governed_rest": True,
                "direct_database_access": False,
                "raw_sql_fallback": False,
            },
        },
        "mock": False,
    }
    if byaan_shape:
        result = {
            "status": "completed",
            "resolvedMetric": "Ticket Count",
            "result": [{"store": "VNPTTE", "ticket_count": 56}],
            "returnedCount": 1,
            "sql": (
                "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count "
                "FROM SALES_ORDER GROUP BY store_name ORDER BY ticket_count DESC LIMIT 100"
            ),
            "lineage": [{"kind": "snapshot", "title": "oracle sanitized"}],
            "freshness": "2026-08-18T06:55:06Z",
            "policyDecision": "allowed",
        }
    package = {
        "package_type": "semantic_skill",
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": f"/api/knowledge-assets/assets/semantic_model/{asset_id}/query",
            "direct_database_access": False,
            "raw_sql_fallback": False,
        },
        "governance": {
            "raw_sql_fallback": False,
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
    }
    if artifacts_mdl:
        package["artifacts"] = {
            "mdl/models.json": {
                "schema": mdl["schema"],
                "model": mdl["model"],
                "entities": mdl["entities"],
            },
            "mdl/metrics.json": {"schema": "agentkit.mdl.metrics.v1", "metrics": mdl["metrics"]},
            "mdl/dimensions.json": {
                "schema": "agentkit.mdl.dimensions.v1",
                "dimensions": mdl["dimensions"],
            },
            "mdl/permissions.json": {
                "schema": "agentkit.mdl.permissions.v1",
                "permissions": mdl["permissions"],
            },
            "mdl/freshness.json": {
                "schema": "agentkit.mdl.freshness.v1",
                "freshness": mdl["freshness"],
            },
        }
    else:
        package["mdl"] = mdl
    if governed_result:
        package["governed_query_result"] = result
    response = client.post(
        "/api/knowledge-assets/skill-packages",
        json={
            "space_id": space["id"],
            "asset_type": "semantic_model",
            "asset_id": asset_id,
            "capability_kind": "semantic_skill",
            "name": "Oracle Sales",
            "status": "ready",
            "publish_state": "published",
            "type": "semantic_skill",
            "query_url": f"/api/knowledge-assets/assets/semantic_model/{asset_id}/query",
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
