from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.agents import (
    AgentRunOutput,
    AgentRunRequest,
    AgentRunResult,
    AgentRuntimeMetadata,
    StudioInternalAgentRunner,
)
from frontend.server.knowledge_assets.agents.runner import _parse_agent_json
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import (
    KnowledgeAssetStore,
    redact_sensitive,
)


class FakeAgentRunner:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured
        self.requests: list[AgentRunRequest] = []

    def health(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "status": "available" if self.configured else "not_configured",
            "runner_backend": "fake-runner",
            "model_name": "fake-model" if self.configured else "not_configured",
        }

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        payload: dict[str, object] = {
            "status": "completed",
            "generation_mode": "agent",
            "agent_status": "completed",
        }
        if request.agent_name == "studio_semantic_builder_agent":
            if request.payload.get("operation") == "refine":
                payload.update(
                    {
                        "patch": {
                            "operation": "update",
                            "object_type": "metric",
                            "object_id": "ticket_count",
                            "operations": [
                                {
                                    "operation": "add",
                                    "object_type": "view",
                                    "object_id": "view_agent_runner_refine",
                                    "before": {},
                                    "after": {
                                        "id": "view_agent_runner_refine",
                                        "name": "view_agent_runner_refine",
                                        "business_name": "Agent Runner Refine View",
                                        "base_metric": "ticket_count",
                                        "dimensions": ["store_id"],
                                        "time_grain": "month",
                                        "status": "suggested",
                                    },
                                    "reason": "Agent suggested a view from the user refinement.",
                                    "evidence_refs": [],
                                }
                            ],
                            "before": {"definition": "COUNT(*)"},
                            "after": {
                                "definition_append": request.payload.get("message"),
                                "formula_hint": "COUNT(DISTINCT billid)",
                            },
                            "reason": "User asked to refine the ticket metric.",
                            "evidence_refs": [],
                            "metric_updates": [
                                {
                                    "id": "ticket_count",
                                    "definition_append": request.payload.get("message"),
                                    "formula_hint": "COUNT(DISTINCT billid)",
                                    "review_status": "needs_review",
                                }
                            ],
                            "instruction": {
                                "kind": "semantic_builder_feedback",
                                "text": request.payload.get("message"),
                            },
                            "field_policy_updates": [
                                {
                                    "fields": ["customer_phone"],
                                    "policy": "masked",
                                    "reason": request.payload.get("message"),
                                }
                            ],
                        },
                        "diff": [
                            {
                                "kind": "metrics",
                                "action": "updated",
                                "id": "ticket_count",
                            },
                            {
                                "kind": "policy",
                                "action": "updated",
                                "fields": ["customer_phone"],
                            },
                        ],
                    }
                )
            else:
                seed = request.payload["deterministic_seed"]
                payload.update(
                    {
                        "mdl": seed["mdl"],
                        "metrics": seed["metrics"],
                        "dimensions": seed["dimensions"],
                        "relationships": seed["relationships"],
                        "policies": seed["policies"],
                        "evidence": seed["evidence"],
                    }
                )
        return AgentRunResult(
            output=AgentRunOutput(
                generation_mode="agent",
                agent_status="completed",
                payload=payload,
                tool_calls=[
                    {"name": name, "status": "called"} for name in request.tool_names
                ],
                validation_result={"valid": True},
            ),
            metadata=AgentRuntimeMetadata(
                agent_name=request.agent_name,
                agent_invocation_id=f"fake-{len(self.requests)}",
                runner_backend="fake-runner",
                model_name="fake-model",
                tool_calls=[
                    {"name": name, "status": "called"} for name in request.tool_names
                ],
                generation_mode="agent",
                agent_status="completed",
                validation_result={"valid": True},
            ),
        )


def _client(tmp_path, monkeypatch, runner) -> TestClient:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "knowledge asset agent tests")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        service=KnowledgeAssetStore(
            repository=KnowledgeAssetRepository(tmp_path / "knowledge-assets.db")
        ),
        internal_agent_runner=runner,
    )
    return TestClient(app)


def test_semantic_builder_agent_invokes_runner_and_records_provenance(
    tmp_path,
    monkeypatch,
) -> None:
    runner = FakeAgentRunner()
    client = _client(tmp_path, monkeypatch, runner)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle",
        },
    ).json()
    doc = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "file",
            "provider": "manual",
            "name": "Sales playbook",
            "metadata": {"content": "Ticket count means distinct billid."},
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "oracle-schema",
            "capability_kind": "retrieval_binding",
            "name": "Oracle schema",
            "kind": "schema_snapshot",
            "schema": _schema(),
        },
    ).json()
    client.post(
        "/api/knowledge-assets/semantic/question-sql-pairs",
        json={
            "space_id": space["id"],
            "question": "ticket count by store",
            "sql": "SELECT store_id, COUNT(DISTINCT billid) FROM sales_order GROUP BY 1",
            "tables": ["sales_order"],
        },
    )
    client.post(
        "/api/knowledge-assets/semantic/instructions",
        json={
            "space_id": space["id"],
            "instruction": "Ticket count means distinct billid.",
            "is_default": True,
        },
    )

    queued = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "document_source_ids": [doc["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Sales Semantic",
            "publish": True,
        },
    ).json()

    job = client.get(f"/api/knowledge-assets/build-jobs/{queued['id']}").json()
    assert job["status"] == "succeeded"
    assert runner.requests[0].agent_name == "studio_semantic_builder_agent"
    assert runner.requests[0].payload["operation"] == "start"
    assert runner.requests[0].payload["source_ids"] == [source["id"]]
    assert runner.requests[0].payload["document_source_ids"] == [doc["id"]]
    assert (
        runner.requests[0].payload["few_shot"][0]["question"] == "ticket count by store"
    )
    assert (
        runner.requests[0]
        .payload["instructions"][0]["instruction"]
        .startswith("Ticket count")
    )
    assert runner.requests[0].payload["current_mdl"]["metrics"]
    assert "build_schema_graph" in runner.requests[0].tool_names
    assert job["output"]["runner_backend"] == "fake-runner"
    assert job["output"]["agent_run_id"] == "fake-1"
    assert job["output"]["generation_mode"] == "agent"
    assert job["output"]["agent_status"] == "completed"
    assert job["output"]["validation_result"]["valid"] is True
    assert job["output"]["publish_state"] == "published"
    assert job["output"]["conversation_id"]

    asset = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()["asset"]
    assert asset["publish_state"] == "published"
    assert asset["provenance"]["agent_name"] == "studio_semantic_builder_agent"
    assert asset["provenance"]["runner_backend"] == "fake-runner"
    assert asset["provenance"]["agent_run"]["operation"] == "start"


def test_semantic_builder_refine_invokes_runner_with_current_context(
    tmp_path,
    monkeypatch,
) -> None:
    runner = FakeAgentRunner()
    client = _client(tmp_path, monkeypatch, runner)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle",
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "oracle-schema",
            "capability_kind": "retrieval_binding",
            "name": "Oracle schema",
            "kind": "schema_snapshot",
            "schema": _schema(),
        },
    ).json()
    client.post(
        "/api/knowledge-assets/semantic/question-sql-pairs",
        json={
            "space_id": space["id"],
            "question": "ticket count by store",
            "sql": "SELECT store_id, COUNT(DISTINCT billid) FROM sales_order GROUP BY 1",
            "tables": ["sales_order"],
        },
    )
    client.post(
        "/api/knowledge-assets/semantic/instructions",
        json={
            "space_id": space["id"],
            "instruction": "Ticket count means distinct billid.",
            "is_default": True,
        },
    )
    queued = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Sales Semantic",
        },
    ).json()
    job = client.get(f"/api/knowledge-assets/build-jobs/{queued['id']}").json()
    conversation_id = job["output"]["conversation_id"]

    refined = client.post(
        f"/api/knowledge-assets/semantic-builder/conversations/{conversation_id}/messages",
        json={
            "semantic_pack_id": "sales_semantic",
            "message": "把票数定义改成去重 billid",
        },
    ).json()

    assert len(runner.requests) == 2
    refine_request = runner.requests[1]
    assert refine_request.agent_name == "studio_semantic_builder_agent"
    assert refine_request.payload["operation"] == "refine"
    assert refine_request.payload["current_mdl"]["metrics"]
    assert refine_request.payload["current_revision"]["revision_number"] == 1
    assert refine_request.payload["few_shot"][0]["question"] == "ticket count by store"
    assert refine_request.payload["instructions"][0]["instruction"].startswith(
        "Ticket count"
    )
    assert refined["latest_revision"]["revision_number"] == 2
    assert refined["latest_revision"]["patch"]["operation"] == "update"
    detail = client.get(
        "/api/knowledge-assets/semantic-packs/sales_semantic/detail"
    ).json()
    history = detail["asset"]["capability_package"]["revision_history"]
    assert history[-1]["agent_run"]["operation"] == "refine"
    assert history[-1]["agent_run"]["runner_backend"] == "fake-runner"
    assert any(
        item.get("id") == "view_agent_runner_refine"
        for item in detail["structured_mdl"].get("views", [])
    )


def test_asktable_dashboard_agent_invokes_runner_for_query_and_dashboard(
    tmp_path,
    monkeypatch,
) -> None:
    runner = FakeAgentRunner()
    client = _client(tmp_path, monkeypatch, runner)
    space_id = _semantic_skill(client)

    query = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "metric": "ticket_count",
            "dimensions": ["store"],
            "question": "按门店查看销售票数",
        },
    ).json()

    assert query["status"] == "completed"
    assert query["agent"]["agent_name"] == "studio_asktable_dashboard_agent"
    assert query["agent"]["runner_backend"] == "fake-runner"

    built = client.post(
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
    ).json()

    assert built["status"] == "succeeded"
    assert (
        built["dashboard"]["provenance"]["agent_name"]
        == "studio_asktable_dashboard_agent"
    )
    assert built["dashboard"]["provenance"]["runner_backend"] == "fake-runner"
    assert [request.agent_name for request in runner.requests].count(
        "studio_asktable_dashboard_agent"
    ) == 2


def test_not_configured_runner_blocks_askdata_without_fake_success(
    tmp_path,
    monkeypatch,
) -> None:
    for name in (
        "MODEL_AGENT_API_KEY",
        "ARK_API_KEY",
        "OPENAI_API_KEY",
        "VEADK_SEMANTIC_BUILDER_API_KEY",
        "VEADK_KNOWLEDGE_AGENT_API_KEY",
        "VEADK_KNOWLEDGE_AGENT_DETERMINISTIC_FALLBACK",
        "VEADK_SEMANTIC_BUILDER_DETERMINISTIC",
    ):
        monkeypatch.delenv(name, raising=False)
    runner = StudioInternalAgentRunner(deterministic_fallback_enabled=False)
    client = _client(tmp_path, monkeypatch, runner)
    _semantic_skill(client)

    health = client.get("/api/knowledge-assets/health").json()
    assert health["agents"]["asktable_dashboard"]["status"] == "not_configured"

    response = client.post(
        "/api/knowledge-assets/askdata/query",
        json={
            "semantic_asset_id": "oracle-sales",
            "question": "按门店查看销售票数",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["agent_status"] == "not_configured"
    assert body["agent"]["model_name"] == "not_configured"
    assert "not configured" in body["data"]["sql"]


def test_deterministic_fallback_is_explicit_not_agent_success(
    tmp_path,
    monkeypatch,
) -> None:
    for name in (
        "MODEL_AGENT_API_KEY",
        "ARK_API_KEY",
        "OPENAI_API_KEY",
        "VEADK_SEMANTIC_BUILDER_API_KEY",
        "VEADK_KNOWLEDGE_AGENT_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VEADK_KNOWLEDGE_AGENT_DETERMINISTIC_FALLBACK", "1")
    runner = StudioInternalAgentRunner()
    client = _client(tmp_path, monkeypatch, runner)
    space = client.post("/api/knowledge-assets/spaces", json={"name": "KC"}).json()
    source = client.post(
        "/api/knowledge-assets/sources",
        json={
            "space_id": space["id"],
            "source_type": "database",
            "provider": "oracle",
            "name": "Oracle",
        },
    ).json()
    snapshot = client.post(
        "/api/knowledge-assets/snapshots",
        json={
            "source_id": source["id"],
            "asset_type": "knowledge_resource",
            "asset_id": "oracle-schema",
            "capability_kind": "retrieval_binding",
            "name": "Oracle schema",
            "kind": "schema_snapshot",
            "schema": _schema(),
        },
    ).json()

    queued = client.post(
        "/api/knowledge-assets/build/semantic-skill",
        json={
            "space_id": space["id"],
            "source_ids": [source["id"]],
            "snapshot_ids": [snapshot["id"]],
            "name": "Fallback Sales Semantic",
            "publish": True,
        },
    ).json()
    job = client.get(f"/api/knowledge-assets/build-jobs/{queued['id']}").json()

    assert job["status"] == "blocked"
    assert job["output"]["generation_mode"] == "deterministic_fallback"
    assert job["output"]["agent_status"] == "not_configured"
    assert job["output"]["runner_backend"] == "not_configured"
    assert job["output"]["model_name"] == "not_configured"
    assert job["output"]["validation_result"]["configured"] is False
    assert "AGENT_NOT_CONFIGURED" in json.dumps(
        job["output"]["gate"], ensure_ascii=False
    )

    asset = client.get(
        "/api/knowledge-assets/semantic-packs/fallback_sales_semantic/detail"
    ).json()["asset"]
    assert asset["capability_package"]["generation"]["mode"] == "deterministic_fallback"
    assert asset["capability_package"]["generation"]["model_configured"] is False
    assert asset["provenance"]["agent_status"] == "not_configured"
    assert asset["provenance"]["generation_mode"] == "deterministic_fallback"
    assert asset["publish_state"] == "draft"


def test_secret_redaction_covers_agent_payloads() -> None:
    redacted = redact_sensitive(
        {
            "agent_output": {
                "api_key": "sk-live-secret",
                "database": "postgres://user:password@example.invalid/db",
                "nested": [{"cookie": "sid=secret"}],
            }
        }
    )
    serialized = json.dumps(redacted)
    assert "sk-live-secret" not in serialized
    assert "password@example" not in serialized
    assert "sid=secret" not in serialized


def test_studio_runner_parses_common_model_json_envelope_noise() -> None:
    fenced = _parse_agent_json(
        '```json\n{"status":"completed","payload":{"metric":"ticket_count"}}\n```'
    )
    assert fenced.payload["payload"]["metric"] == "ticket_count"
    assert fenced.validation_result["output_repair"] == "strip_markdown_fence"

    wrapped = _parse_agent_json(
        'Here is the result:\n{"status":"completed","payload":{"metric":"gmv"}}\nDone.'
    )
    assert wrapped.payload["payload"]["metric"] == "gmv"
    assert wrapped.validation_result["output_repair"] == "extract_first_json_object"

    repaired = _parse_agent_json(
        '{"status":"completed","eval_cases":[{"expected_dimensions":["store_name"]"}]}'
    )
    assert repaired.payload["eval_cases"][0]["expected_dimensions"] == ["store_name"]
    assert (
        repaired.validation_result["output_repair"] == "repair_stray_quote_after_value"
    )


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
                ],
            },
            {
                "name": "store",
                "primary_key": ["store_id"],
                "columns": [
                    {"name": "store_id", "type": "number", "primary_key": True},
                    {"name": "store_name", "type": "varchar"},
                ],
            },
        ]
    }


def _semantic_skill(client: TestClient) -> str:
    space = client.post("/api/knowledge-assets/spaces", json={"name": "Oracle"}).json()
    mdl = {
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
            {
                "id": "sell_date",
                "name": "Sell Date",
                "field": "sell_date",
                "kind": "time",
            },
        ],
        "permissions": {
            "raw_sql_fallback": False,
            "permission_hint": "Aggregates only.",
            "denied_fields": [{"field": "customer_phone"}],
        },
        "freshness": {"status": "fresh", "as_of": "2026-08-18T00:00:00Z"},
    }
    result = {
        "schema": "agentkit.semantic_query_result.v1",
        "data": {
            "rows": [{"store": "VNPTTE", "ticket_count": 56}],
            "returnedCount": 1,
            "metric": {
                "id": "ticket_count",
                "name": "Ticket Count",
                "definition": "Count distinct tickets.",
                "formula": "count_distinct(ticket_id)",
            },
            "dimensions": [{"id": "store", "name": "Store", "field": "store_name"}],
            "sql": "SELECT store_name AS store, COUNT(DISTINCT ticket_id) AS ticket_count FROM SALES_ORDER GROUP BY store_name",
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
            "capability_package": {
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
                "mdl": mdl,
                "governed_query_result": result,
            },
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
