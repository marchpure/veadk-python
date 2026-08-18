from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.builders.semantic.metric_dimension_candidates import (
    generate_candidates,
)
from frontend.server.knowledge_assets.builders.semantic.mdl_writer import write_mdl
from frontend.server.knowledge_assets.builders.semantic.schema_graph import build_schema_graph
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


def _schema() -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "sales_order",
                "primary_key": ["order_id"],
                "columns": [
                    {"name": "order_id", "type": "number", "primary_key": True},
                    {"name": "store_id", "type": "number"},
                    {"name": "sell_date", "type": "date"},
                    {"name": "amount", "type": "decimal"},
                    {"name": "customer_phone", "type": "varchar"},
                ],
            },
            {
                "name": "store",
                "primary_key": ["store_id"],
                "columns": [
                    {"name": "store_id", "type": "number", "primary_key": True},
                    {"name": "store_name", "type": "varchar"},
                    {"name": "region", "type": "varchar"},
                ],
            },
        ]
    }


def _job(client: TestClient, job_id: str) -> dict[str, object]:
    return client.get(f"/api/knowledge-assets/build-jobs/{job_id}").json()


def test_schema_graph_discovers_relationships_and_pii_policy() -> None:
    graph = build_schema_graph(_schema())

    assert [table.name for table in graph.tables] == ["sales_order", "store"]
    assert graph.tables[0].table_type == "fact"
    assert graph.relationships[0].from_table == "sales_order"
    assert graph.relationships[0].to_table == "store"
    pii = [
        column.name
        for table in graph.tables
        for column in table.columns
        if column.pii
    ]
    assert pii == ["customer_phone"]


def test_candidates_and_mdl_are_wren_style_and_governed() -> None:
    graph = build_schema_graph(_schema())
    candidates = generate_candidates(graph, source_ids=["src_sales"], snapshot_ids=["snap_schema"])
    mdl = write_mdl(
        graph,
        candidates,
        model_id="sales-semantic",
        display_name="Sales Semantic",
    )

    assert {metric["id"] for metric in mdl["metrics"]} >= {
        "sales_order_count",
        "sales_order_amount_sum",
    }
    assert "sales_order_sell_date" in {dimension["id"] for dimension in mdl["dimensions"]}
    assert mdl["permissions"]["raw_sql_fallback"] is False
    assert mdl["permissions"]["masked_fields"][0]["field"] == "customer_phone"
    assert "connection" not in json.dumps(mdl).lower()


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "semantic local key material")
    app = FastAPI()
    service = KnowledgeAssetStore(
        repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
    )
    mount_knowledge_asset_routes(app, service=service)
    with TestClient(app) as http:
        yield http


def test_semantic_skill_build_blocks_without_snapshot(client: TestClient) -> None:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle sanitized",
        },
    ).json()

    response = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "name": "Sales Semantic",
            "intent": "sales overview",
        },
    )

    assert response.status_code == 201
    queued = response.json()
    assert queued["status"] == "queued"
    job = _job(client, queued["id"])
    assert job["status"] == "blocked"
    assert "schema snapshot" in job["error"]["message"]


def test_semantic_skill_build_creates_published_capability(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("VEADK_SEMANTIC_BUILDER_DETERMINISTIC", "1")
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle sanitized",
            "metadata": {"password": "must-not-leak"},
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "oracle-schema",
            "capability_kind": "retrieval_binding",
            "name": "Oracle schema snapshot",
            "kind": "schema_snapshot",
            "schema": _schema(),
            "profile": {"snapshot": {"id": "oracle-sanitized", "hash": "abc123"}},
        },
    ).json()

    response = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Sales Semantic",
            "intent": "sales overview",
            "publish": True,
        },
    )

    assert response.status_code == 201
    queued = response.json()
    assert queued["status"] == "queued"
    job = _job(client, queued["id"])
    assert job["status"] == "succeeded"
    assert job["output"]["semantic_skill_asset_id"] == "sales_semantic"
    assets = client.get(
        "/api/knowledge-assets/assets?asset_type=semantic_model&capability_kind=semantic_skill"
    ).json()
    assert assets["total"] == 1
    asset = assets["items"][0]
    assert asset["publish_state"] == "published"
    assert asset["query_url"] == "/api/external/assets/semantic_model/sales_semantic/query"
    assert asset["capability_package"]["runtime"]["direct_database_access"] is False
    assert asset["capability_package"]["mdl"]["permissions"]["masked_fields"][0]["field"] == "customer_phone"
    package_files = asset["capability_package"]["files"]
    assert {
        "manifest.json",
        "SKILL.md",
        "mdl/models.json",
        "mdl/fields.json",
        "mdl/relationships.json",
        "mdl/metrics.json",
        "mdl/dimensions.json",
        "mdl/permissions.json",
        "mdl/freshness.json",
        "tools/query.py",
        "policies/access.json",
        "policies/masking.json",
        "policies/refusal.json",
        "evals/suite.json",
        "evals/evidence.json",
    }.issubset(package_files)
    assert "customer_phone" in json.dumps(package_files["policies/masking.json"])
    assert "requests.post(" in package_files["tools/query.py"]
    assert "oracledb" not in package_files["tools/query.py"]
    assert "cx_Oracle" not in package_files["tools/query.py"]
    joined = json.dumps(asset, ensure_ascii=False)
    assert "must-not-leak" not in joined
    assert "customer_phone" in joined


def test_semantic_skill_build_prefers_sanitized_semantic_reference(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VEADK_SEMANTIC_BUILDER_DETERMINISTIC", "1")
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle sanitized",
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "oracle-schema",
            "capability_kind": "retrieval_binding",
            "name": "Oracle schema snapshot",
            "kind": "schema_snapshot",
            "schema": {
                "tables": [
                    {
                        "name": "P_BL_SELL_HD",
                        "primary_key": ["BILLID"],
                        "columns": [
                            {"name": "BILLID", "type": "unknown", "primary_key": True},
                            {"name": "SELLDATE", "type": "unknown"},
                            {"name": "STOREID", "type": "unknown"},
                            {"name": "ACCOUNT_SALES", "type": "unknown"},
                        ],
                    }
                ]
            },
            "profile": {
                "snapshot": {"id": "oracle-sanitized", "hash": "abc123"},
                "golden_results": {
                    "ticket_count_last_30_snapshot_days": 86,
                    "top_3_stores_by_ticket_count": [
                        {"store": "VNPTTE", "ticket_count": 56},
                        {"store": "SG - ANTA VIVO City", "ticket_count": 9},
                    ],
                },
                "semantic_reference": {
                    "metrics": [
                        {
                            "id": "ticket_count",
                            "name": "Ticket Count",
                            "formula": "count(distinct hd.BILLID)",
                            "definition": "Count of distinct sales bill IDs.",
                            "approved": True,
                        }
                    ],
                    "dimensions": [
                        {"id": "store", "field": "store.STORENAME"},
                        {"id": "sell_date", "field": "hd.SELLDATE"},
                    ],
                    "policy": {
                        "deny_fields": ["direct_customer_identifiers"],
                        "relative_time_anchor": "2026-08-15",
                    },
                    "provenance": {"data_through": "2026-08-15"},
                },
            },
        },
    ).json()

    queued = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Oracle Sales Semantic",
            "publish": True,
        },
    ).json()
    assert _job(client, queued["id"])["status"] == "succeeded"
    asset = client.get(
        "/api/knowledge-assets/assets?asset_type=semantic_model&capability_kind=semantic_skill"
    ).json()["items"][0]

    assert asset["capabilities"]["metrics"][0] == "ticket_count"
    assert "sell_date" in asset["capabilities"]["dimensions"]
    assert asset["freshness"]["data_through"] == "2026-08-15"
    assert any(
        item["field"] == "direct_customer_identifiers"
        for item in asset["usage_policy"]["denied_fields"]
    )

    query = client.post(
        "/api/external/assets/semantic_model/oracle_sales_semantic/query",
        json={"metric": "ticket_count", "dimension": "store", "limit": 3},
    )
    assert query.status_code == 200
    result = query.json()["data"]
    assert result["rows"][0] == {"store": "VNPTTE", "ticket_count": 56}
    assert result["execution_mode"] == "snapshot_evidence_plan"
    assert "SELECT" in result["sql"]
    assert '"P_BL_SELL_HD"' in result["sql"]
    assert result["metricDefinition"]["id"] == "ticket_count"
    assert result["policyDecision"]["decision"] == "allow"
    assert result["freshness"]["data_through"] == "2026-08-15"

    pii_query = client.post(
        "/api/external/assets/semantic_model/oracle_sales_semantic/query",
        json={"metric": "ticket_count", "question": "show customer phone contacts"},
    )
    assert pii_query.status_code == 200
    pii_result = pii_query.json()["data"]
    assert pii_result["policyDecision"]["decision"] == "deny"
    assert pii_result["rows"] == []
