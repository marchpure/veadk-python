from __future__ import annotations

import asyncio
import json

import pytest

from frontend.server.knowledge_assets.models import CreateSourceBody, CreateSpaceBody
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.semantic_build import (
    CreateSemanticBuildJobBody,
    SemanticBuildRunBody,
    SemanticBuildService,
    SemanticQueryBody,
)
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


@pytest.fixture()
def store(tmp_path, monkeypatch) -> KnowledgeAssetStore:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "semantic build local key")
    return KnowledgeAssetStore(
        repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
    )


def _schema() -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "sales_ticket",
                "columns": [
                    {"name": "bill_id", "type": "integer", "primary_key": True},
                    {"name": "store_name", "type": "varchar"},
                    {"name": "sell_date", "type": "date"},
                    {"name": "sales_amount", "type": "decimal"},
                    {"name": "customer_tel", "type": "varchar"},
                ],
            }
        ],
        "freshness": {
            "snapshot_id": "oracle-local-extract-sanitized",
            "snapshot_hash": "abc123",
            "data_through": "2026-08-15",
        },
    }


def test_semantic_build_service_creates_drafts_publishes_and_queries(store: KnowledgeAssetStore) -> None:
    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="Sales"))
        source = await store.create_source(
            CreateSourceBody(
                space_id=space["id"],
                source_type="database",
                provider="oracle",
                name="Oracle sanitized snapshot",
                metadata={
                    "schema": _schema(),
                    "profile": {"sample_mode": "schema_only"},
                    "password": "must-not-leak-build-service",
                },
            )
        )
        service = SemanticBuildService(store)
        job = await service.create_job(
            CreateSemanticBuildJobBody(
                space_id=space["id"],
                source_ids=[source["id"]],
                mode="schema_only",
                target_domain="sales",
                dashboard_goal="sales overview",
            )
        )
        assert job["status"] == "queued"

        ready = await service.run_job(job["job_id"], SemanticBuildRunBody(publish=False))
        assert ready["status"] == "ready_to_publish"
        assert ready["semantic_model_slug"]
        assert ready["dashboard_asset_id"]

        listed_before = await store.list_assets()
        assert listed_before["total"] == 0

        published = await service.publish_job(job["job_id"])
        assert published["status"] == "published"
        listed = await store.list_assets()
        assert listed["total"] == 2
        assert {item["asset_type"] for item in listed["items"]} == {
            "semantic_model",
            "dashboard",
        }
        joined = json.dumps(listed, ensure_ascii=False)
        assert "must-not-leak-build-service" not in joined
        assert "customer_tel" in joined

        result = await service.query_asset(
            "semantic_model",
            ready["semantic_model_slug"],
            SemanticQueryBody(question="按门店统计最近销售票数 Top 3"),
        )
        assert result["data"]["rows"]
        assert "sql" in result["data"]
        assert "metricDefinition" in result["data"]
        assert result["data"]["policyDecision"]["decision"] == "allow"
        assert result["data"]["freshness"]["snapshot_id"] == "oracle-local-extract-sanitized"

        denial = await service.query_asset(
            "semantic_model",
            ready["semantic_model_slug"],
            SemanticQueryBody(question="显示客户电话和联系方式"),
        )
        assert denial["data"]["policyDecision"]["decision"] == "deny"

    asyncio.run(scenario())
