from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.evaluation.models import (
    CreateKnowledgeAssetEvalCaseBody,
    CreateKnowledgeAssetEvalSuiteBody,
    RunKnowledgeAssetEvalBody,
)
from frontend.server.knowledge_assets.evaluation.repository import (
    install_evaluation_repository_methods,
)
from frontend.server.knowledge_assets.evaluation.service import (
    KnowledgeAssetEvaluatorService,
    NoConfiguredJudge,
)
from frontend.server.knowledge_assets.models import CreateSpaceBody, RecordSkillPackageBody
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


@pytest.fixture()
def store(tmp_path, monkeypatch) -> KnowledgeAssetStore:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "knowledge asset eval test key")
    monkeypatch.delenv("VEADK_STUDIO_KNOWLEDGE_ASSET_EVALUATION_MODEL", raising=False)
    monkeypatch.delenv("VEADK_STUDIO_EVALUATION_MODEL", raising=False)
    return KnowledgeAssetStore(
        repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
    )


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "knowledge asset eval route key")
    monkeypatch.delenv("VEADK_STUDIO_KNOWLEDGE_ASSET_EVALUATION_MODEL", raising=False)
    monkeypatch.delenv("VEADK_STUDIO_EVALUATION_MODEL", raising=False)
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
    )
    return TestClient(app)


def test_eval_models_validate_target_kind_and_prompt() -> None:
    with pytest.raises(ValidationError):
        CreateKnowledgeAssetEvalSuiteBody(
            spaceId="space_1",
            name="Bad",
            targetKind="chat_session",
            targetAssetId="asset",
        )
    with pytest.raises(ValidationError, match="input, question, or intent"):
        CreateKnowledgeAssetEvalCaseBody()

    case = CreateKnowledgeAssetEvalCaseBody(
        question="GMV by store",
        expectedMetric="gmv",
        expectedDimensions=["store", ""],
        expectedSqlContains=["sales_order"],
    )
    assert case.expected_dimensions == ["store"]


def test_sqlite_repository_persists_suites_cases_runs_results(store: KnowledgeAssetStore) -> None:
    install_evaluation_repository_methods()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        service = KnowledgeAssetEvaluatorService(store, judge=NoConfiguredJudge())
        suite = await service.create_suite(
            CreateKnowledgeAssetEvalSuiteBody(
                spaceId=space["id"],
                name="Semantic Suite",
                targetKind="semantic_skill",
                targetAssetId="oracle-sales",
            )
        )
        case = await service.create_case(
            suite.id,
            CreateKnowledgeAssetEvalCaseBody(
                question="ticket count by store",
                expectedMetric="ticket_count",
                expectedDimensions=["store"],
                tags=["smoke"],
            ),
        )
        assert case.suite_id == suite.id
        listed_cases = await service.list_cases(suite.id)
        assert listed_cases[0].tags == ["smoke"]

        run = await asyncio.to_thread(
            store._repository.create_eval_run,
            {
                "id": "eval_run_manual",
                "suite_id": suite.id,
                "target_kind": "semantic_skill",
                "target_asset_id": "oracle-sales",
                "status": "running",
                "score": 0,
                "started_at": "2026-08-18T00:00:00Z",
                "completed_at": None,
                "model_status": "not_configured",
                "generation_mode": "deterministic",
                "result_summary_json": "{}",
            },
        )
        result = await asyncio.to_thread(
            store._repository.create_eval_result,
            {
                "id": "eval_result_manual",
                "run_id": run["id"],
                "case_id": case.id,
                "status": "passed",
                "score": 1,
                "reason": "ok",
                "actual_output_json": "{}",
                "actual_sql": "SELECT 1",
                "actual_rows_preview_json": "[]",
                "actual_policy_decision_json": "{}",
                "actual_freshness_json": "{}",
                "tool_calls_json": "[]",
                "evidence_json": "[]",
                "dashboard_spec_diff_json": "{}",
            },
        )
        assert result["actual_sql"] == "SELECT 1"
        runs = await service.list_runs(suite_id=suite.id)
        assert runs[0].id == "eval_run_manual"

    asyncio.run(scenario())


def test_schema_contains_evaluation_tables(store: KnowledgeAssetStore, tmp_path) -> None:
    asyncio.run(store.list_spaces())
    with sqlite3.connect(tmp_path / "knowledge-assets.db") as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "knowledge_asset_eval_suites",
        "knowledge_asset_eval_cases",
        "knowledge_asset_eval_runs",
        "knowledge_asset_eval_results",
        "knowledge_asset_eval_optimizations",
    }.issubset(tables)


def test_semantic_evaluator_deterministic_pass_and_judge_not_configured(
    store: KnowledgeAssetStore,
) -> None:
    async def scenario() -> None:
        space_id = await _semantic_skill(store)
        service = KnowledgeAssetEvaluatorService(store, judge=NoConfiguredJudge())
        suite = await service.create_suite(
            CreateKnowledgeAssetEvalSuiteBody(
                spaceId=space_id,
                name="Semantic Suite",
                targetKind="semantic_skill",
                targetAssetId="oracle-sales",
            )
        )
        await service.create_case(
            suite.id,
            CreateKnowledgeAssetEvalCaseBody(
                question="按门店查看销售票数",
                expectedMetric="ticket_count",
                expectedDimensions=["store"],
                expectedSqlContains=["SALES_ORDER"],
                expectedPolicyDecision="allow",
                expectedEvidenceKeys=["ticket"],
            ),
        )

        detail = await service.run(
            RunKnowledgeAssetEvalBody(suiteId=suite.id)
        )

        assert detail.run.status == "succeeded"
        assert detail.run.model_status == "not_configured"
        assert detail.results[0].status == "passed"
        assert detail.results[0].score == 1
        assert "SALES_ORDER" in detail.results[0].actual_sql
        assert detail.results[0].actual_policy_decision["decision"] == "allow"

    asyncio.run(scenario())


def test_asktable_evaluator_rejects_raw_sql_fallback(store: KnowledgeAssetStore) -> None:
    async def scenario() -> None:
        space_id = await _semantic_skill(store, raw_sql_fallback=True)
        service = KnowledgeAssetEvaluatorService(store, judge=NoConfiguredJudge())
        suite = await service.create_suite(
            CreateKnowledgeAssetEvalSuiteBody(
                spaceId=space_id,
                name="AskTable Suite",
                targetKind="asktable",
                targetAssetId="oracle-sales",
            )
        )
        await service.create_case(
            suite.id,
            CreateKnowledgeAssetEvalCaseBody(
                question="按门店查看销售票数",
                expectedMetric="ticket_count",
                expectedDimensions=["store"],
                expectedPolicyDecision="allow",
            ),
        )

        detail = await service.run(
            RunKnowledgeAssetEvalBody(suiteId=suite.id)
        )

        assert detail.run.status == "failed"
        assert detail.results[0].status == "failed"
        assert "Raw SQL fallback" in detail.results[0].reason

    asyncio.run(scenario())


def test_dashboard_evaluator_validates_spec_and_data_views(
    store: KnowledgeAssetStore,
) -> None:
    async def scenario() -> None:
        space_id = await _semantic_skill(store)
        await _dashboard_skill(store, space_id=space_id)
        service = KnowledgeAssetEvaluatorService(store, judge=NoConfiguredJudge())
        suite = await service.create_suite(
            CreateKnowledgeAssetEvalSuiteBody(
                spaceId=space_id,
                name="Dashboard Suite",
                targetKind="dashboard_skill",
                targetAssetId="sales-dashboard",
            )
        )
        await service.create_case(
            suite.id,
            CreateKnowledgeAssetEvalCaseBody(
                intent="门店销售看板",
                expectedDashboardTiles=["primary_metric"],
                expectedPolicyDecision="allow",
            ),
        )

        detail = await service.run(
            RunKnowledgeAssetEvalBody(suiteId=suite.id)
        )

        assert detail.run.status == "succeeded"
        assert detail.results[0].status == "passed"
        assert detail.results[0].dashboard_spec_diff["missing_tiles"] == []
        assert detail.results[0].actual_freshness["status"] == "fresh"

    asyncio.run(scenario())


def test_evaluation_routes_run_and_redact_secret(client: TestClient) -> None:
    space_id = _semantic_skill_route(client)
    suite = client.post(
        "/api/knowledge-assets/evaluation/suites",
        json={
            "spaceId": space_id,
            "name": "Route Suite",
            "targetKind": "semantic_skill",
            "targetAssetId": "oracle-sales",
            "description": "Route-level smoke suite",
        },
    )
    assert suite.status_code == 201
    assert suite.json()["mock"] is False

    case = client.post(
        f"/api/knowledge-assets/evaluation/suites/{suite.json()['id']}/cases",
        json={
            "question": "按门店查看销售票数",
            "expectedMetric": "ticket_count",
            "expectedDimensions": ["store"],
            "expectedSqlContains": ["SALES_ORDER"],
            "expectedPolicyDecision": "allow",
        },
    )
    assert case.status_code == 201
    assert case.json()["mock"] is False

    run = client.post(
        "/api/knowledge-assets/evaluation/runs",
        json={"suiteId": suite.json()["id"]},
    )

    assert run.status_code == 200
    body = run.json()
    assert body["mock"] is False
    assert body["run"]["status"] == "succeeded"
    assert body["run"]["modelStatus"] == "not_configured"
    assert body["results"][0]["status"] == "passed"
    assert "redact-me" not in run.text

    optimizations = client.get("/api/knowledge-assets/evaluation/optimizations")
    assert optimizations.status_code == 200
    assert optimizations.json()["mock"] is False


def test_evaluation_routes_are_mounted(client: TestClient) -> None:
    paths = {getattr(route, "path", "") for route in client.app.router.routes}
    assert "/api/knowledge-assets/evaluation/suites" in paths
    assert "/api/knowledge-assets/evaluation/suites/{suite_id}/cases" in paths
    assert "/api/knowledge-assets/evaluation/runs" in paths
    assert "/api/knowledge-assets/evaluation/runs/{run_id}" in paths
    assert "/api/knowledge-assets/evaluation/optimizations" in paths


async def _semantic_skill(
    store: KnowledgeAssetStore,
    *,
    raw_sql_fallback: bool = False,
) -> str:
    space = await store.create_space(CreateSpaceBody(name="Oracle"))
    await store.record_skill_package(
        RecordSkillPackageBody(
            space_id=space["id"],
            asset_type="semantic_model",
            asset_id="oracle-sales",
            capability_kind="semantic_skill",
            name="Oracle Sales",
            status="ready",
            publish_state="published",
            type="semantic_skill",
            query_url="/api/knowledge-assets/assets/semantic_model/oracle-sales/query",
            capability_package=_semantic_package(raw_sql_fallback=raw_sql_fallback),
            capabilities={"metrics": ["ticket_count"], "dimensions": ["store"]},
            freshness={"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            usage_policy={"permission_hint": "Aggregates only."},
            sample_evidence=[{"kind": "metric", "title": "ticket"}],
        )
    )
    return space["id"]


async def _dashboard_skill(store: KnowledgeAssetStore, *, space_id: str) -> None:
    await store.record_skill_package(
        RecordSkillPackageBody(
            space_id=space_id,
            asset_type="dashboard",
            asset_id="sales-dashboard",
            capability_kind="dashboard_skill",
            name="Sales Dashboard",
            status="ready",
            publish_state="published",
            type="dashboard_skill",
            query_url="/api/knowledge-assets/assets/dashboard/sales-dashboard/query",
            capability_package={
                "dashboard_spec": {
                    "tiles": [{"id": "primary_metric", "title": "Ticket Count"}],
                    "filters": [{"id": "store"}],
                    "semantic_bindings": [{"semantic_asset_id": "oracle-sales"}],
                    "data_views": [
                        {
                            "id": "primary_metric",
                            "rows": [
                                {"store": "VNPTTE", "ticket_count": 56},
                            ],
                            "sql": "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count FROM SALES_ORDER GROUP BY store_name",
                            "metricDefinition": "Count distinct tickets.",
                            "policyDecision": {
                                "decision": "allow",
                                "raw_sql_fallback": False,
                            },
                            "freshness": {
                                "status": "fresh",
                                "as_of": "2026-08-18T00:00:00Z",
                            },
                            "evidence": [{"kind": "metric", "title": "ticket"}],
                        }
                    ],
                }
            },
            freshness={"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            sample_evidence=[{"kind": "metric", "title": "ticket"}],
        )
    )


def _semantic_skill_route(client: TestClient) -> str:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "Oracle"}).json()
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
            "capability_package": _semantic_package(),
            "capabilities": {"metrics": ["ticket_count"], "dimensions": ["store"]},
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
    )
    assert response.status_code == 201
    return space["id"]


def _semantic_package(*, raw_sql_fallback: bool = False) -> dict[str, object]:
    return {
        "package_type": "semantic_skill",
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": "/api/knowledge-assets/assets/semantic_model/oracle-sales/query",
            "direct_database_access": False,
            "raw_sql_fallback": False,
        },
        "governance": {
            "raw_sql_fallback": False,
            "usage_policy": {"permission_hint": "Aggregates only."},
        },
        "headers": {"Authorization": "Bearer redact-me-route"},
        "mdl": {
            "schema": "agentkit.mdl.v1",
            "model": {"id": "oracle-sales", "slug": "oracle-sales", "version": "v1"},
            "entities": [{"id": "sales", "table": "SALES_ORDER"}],
            "relationships": [{"from": "sales.store_id", "to": "store.id"}],
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
                {"id": "sell_date", "name": "Sell Date", "field": "sell_date"},
            ],
            "permissions": {
                "raw_sql_fallback": False,
                "permission_hint": "Aggregates only.",
                "denied_fields": [{"field": "customer_phone"}],
            },
            "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
        },
        "governed_query_result": {
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
                },
                "dimensions": [{"id": "store", "name": "Store", "field": "store_name"}],
                "sql": "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count FROM SALES_ORDER GROUP BY store_name",
                "metricDefinition": "Count distinct tickets.",
                "policyDecision": {
                    "decision": "allow",
                    "reason": "Aggregates only.",
                    "raw_sql_fallback": raw_sql_fallback,
                },
                "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
                "evidence": [{"kind": "metric", "title": "ticket"}],
                "execution": {
                    "mode": "governed_semantic_skill_fixture",
                    "governed_rest": True,
                    "direct_database_access": False,
                    "raw_sql_fallback": raw_sql_fallback,
                },
            },
            "mock": False,
        },
    }
