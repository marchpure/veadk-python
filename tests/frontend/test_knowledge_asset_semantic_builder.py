from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
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


def _client(tmp_path, monkeypatch, *, model_configured: bool = False) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "semantic local key material")
    for name in (
        "MODEL_AGENT_API_KEY",
        "ARK_API_KEY",
        "OPENAI_API_KEY",
        "VEADK_SEMANTIC_BUILDER_API_KEY",
        "VEADK_KNOWLEDGE_AGENT_API_KEY",
        "VEADK_SEMANTIC_BUILDER_DETERMINISTIC",
    ):
        monkeypatch.delenv(name, raising=False)
    if model_configured:
        monkeypatch.setenv("VEADK_KNOWLEDGE_AGENT_API_KEY", "unit-test-model-key")
    app = FastAPI()
    service = KnowledgeAssetStore(
        repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
    )
    mount_knowledge_asset_routes(app, service=service)
    return TestClient(app)


def _sse_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        event_type = "message"
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
            if line.startswith("data: "):
                data = line.removeprefix("data: ")
        payload = json.loads(data)
        payload["_event"] = event_type
        events.append(payload)
    return events


def test_semantic_stream_endpoint_emits_tool_events_and_blocks_publish_without_model(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, model_configured=False)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "duckdb",
            "name": "Sales DB",
            "metadata": {"password": "must-not-leak"},
        },
    ).json()
    doc = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "file",
            "provider": "manual",
            "name": "Sales playbook",
            "description": "Ticket Count means distinct bill IDs by Store.",
            "metadata": {
                "content": "Ticket Count means distinct bill IDs. Store is the reporting entity."
            },
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "sales-schema",
            "capability_kind": "retrieval_binding",
            "name": "Sales schema snapshot",
            "kind": "schema_snapshot",
            "schema": _schema(),
        },
    ).json()
    client.post(
        "/api/knowledge-assets/semantic/question-sql-pairs",
        json={
            "space_id": space["id"],
            "question": "top stores by ticket count",
            "sql": "SELECT store_id, COUNT(DISTINCT order_id) FROM sales_order GROUP BY store_id",
            "tables": ["sales_order"],
        },
    )
    client.post(
        "/api/knowledge-assets/semantic/instructions",
        json={
            "space_id": space["id"],
            "instruction": "Ticket Count always means distinct order_id.",
            "is_default": True,
        },
    )

    response = client.post(
        "/api/knowledge-assets/semantic-build/stream",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"], doc["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Sales Semantic",
            "intent": "build sales question answering semantics",
            "publish": True,
        },
    )

    assert response.status_code == 200
    events = _sse_events(response.text)
    event_types = [event["_event"] for event in events]
    assert "tool_call_start" in event_types
    assert "tool_call_result" in event_types
    assert "artifact_preview" in event_types
    assert "validation_result" in event_types
    assert "job_status" in event_types
    assert any(
        event.get("payload", {}).get("tool_name") == "inspect_schema_snapshot"
        for event in events
        if isinstance(event.get("payload"), dict)
    )
    assert "must-not-leak" not in response.text

    final_status = [event for event in events if event["_event"] == "job_status"][-1]
    job_id = final_status["payload"]["job_id"]
    job = client.get(f"/api/knowledge-assets/build-jobs/{job_id}").json()
    assert job["status"] == "blocked"
    assert job["output"]["publish_state"] == "draft"
    assert job["output"]["validation_result"]["configured"] is False
    assert "模型未配置" in json.dumps(job["output"]["gate"], ensure_ascii=False)
    persisted_events = client.get(
        f"/api/knowledge-assets/semantic-build/{job_id}/events"
    ).json()["items"]
    assert len(persisted_events) >= 8
    detail = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()
    assert detail["few_shot"][0]["question"] == "top stores by ticket count"
    assert detail["instructions"][0]["instruction"].startswith("Ticket Count")
    assert detail["doc_graph"]["entities"]
    assert detail["alignments"]


def test_semantic_stream_doc_only_creates_graph_pack_not_fake_metric(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, model_configured=True)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    doc = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "file",
            "provider": "manual",
            "name": "Policy handbook",
            "description": "Revenue Policy defines masking and approval workflow.",
            "metadata": {
                "content": "Revenue Policy defines approval workflow and masking rules."
            },
        },
    ).json()

    response = client.post(
        "/api/knowledge-assets/semantic-build/stream",
        json={
            "space_id": space["id"],
            "source_ids": [doc["id"]],
            "name": "Policy Graph",
            "intent": "build document graph",
            "publish": True,
        },
    )
    assert response.status_code == 200
    events = _sse_events(response.text)
    final_status = [event for event in events if event["_event"] == "job_status"][-1]
    assert final_status["payload"]["status"] == "succeeded"
    detail = client.get(
        "/api/knowledge-assets/semantic-packs/policy_graph/detail"
    ).json()
    assert detail["structured_mdl"]["doc_only"] is True
    assert detail["structured_mdl"]["metrics"] == []
    assert detail["doc_graph"]["entities"]
    assert detail["asset"]["publish_state"] == "published"
    assert detail["skill_runtime"]["readonly_query"]["status"] == "blocked"


def test_semantic_builder_conversation_refine_view_and_publish(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, model_configured=True)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "duckdb",
            "name": "Sales DB",
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "sales-schema",
            "capability_kind": "retrieval_binding",
            "name": "Sales schema snapshot",
            "kind": "schema_snapshot",
            "schema": _schema(),
        },
    ).json()
    response = client.post(
        "/api/knowledge-assets/semantic-build/stream",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Sales Semantic",
            "intent": "build sales semantics",
            "publish": False,
        },
    )
    assert response.status_code == 200
    detail = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()
    assert detail["asset"]["publish_state"] == "draft"

    conversation = client.post(
        "/api/knowledge-assets/semantic-builder/conversations",
        json={
            "space_id": space["id"],
            "semantic_pack_id": "sales_semantic",
            "title": "Sales refinement",
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
        },
    ).json()
    assert conversation["semantic_pack_id"] == "sales_semantic"
    assert conversation["revisions"][0]["revision_number"] == 1

    refined = client.post(
        f"/api/knowledge-assets/semantic-builder/conversations/{conversation['id']}/messages",
        json={
            "message": "把销售额指标改成扣除退款，并隐藏客户手机号",
            "semantic_pack_id": "sales_semantic",
        },
    ).json()
    assert refined["semantic_pack_id"] == "sales_semantic"
    assert refined["latest_revision"]["revision_number"] == 2
    assert any(item["kind"] in {"metrics", "policy"} for item in refined["diff"])
    refined_detail = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()
    assert "instructions" in refined_detail["structured_mdl"]
    assert any(
        "customer_phone" in field
        for field in refined_detail["structured_mdl"]["permissions"].get(
            "masked_fields", []
        )
    )

    view = client.post(
        "/api/knowledge-assets/semantic-builder/drafts/sales_semantic/views",
        json={
            "name": "门店销售趋势",
            "description": "按月份查看门店销售趋势",
            "base_metric": "sales_order_amount_sum",
            "dimensions": ["store_id"],
            "time_grain": "month",
        },
    ).json()
    assert view["view"]["id"].startswith("view_")
    view_detail = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()
    assert view_detail["structured_mdl"]["views"][0]["business_name"] == "门店销售趋势"
    assert any(
        entity.get("kind") == "view"
        for entity in view_detail["structured_mdl"]["entities"]
    )

    published = client.post(
        "/api/knowledge-assets/semantic-builder/drafts/sales_semantic/publish",
        json={"publish": True},
    ).json()
    assert published["publish_state"] == "published"
    final_detail = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()
    assert final_detail["asset"]["status"] == "ready"
    assert final_detail["asset"]["publish_state"] == "published"


def test_semantic_builder_publish_blocks_when_gate_has_blockers(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, model_configured=False)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "duckdb",
            "name": "Sales DB",
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "space_id": space["id"],
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "sales-schema",
            "capability_kind": "retrieval_binding",
            "name": "Sales schema snapshot",
            "kind": "schema_snapshot",
            "schema": _schema(),
        },
    ).json()
    client.post(
        "/api/knowledge-assets/semantic-build/stream",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Blocked Semantic",
            "intent": "build sales semantics",
            "publish": False,
        },
    )

    response = client.post(
        "/api/knowledge-assets/semantic-builder/drafts/blocked_semantic/publish",
        json={"publish": True},
    )
    assert response.status_code == 400
    assert "阻断项" in response.text
