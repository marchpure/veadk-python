from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from frontend.server.knowledge_assets.contracts import (
    GoldenAssetRevision,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    SkillDraftRevision,
    SkillManifest,
    StorageRef,
)
from frontend.server.knowledge_assets.kind_runtime import (
    ContentAddressedStore,
    ExecutionBudget,
    KindExecutionRequest,
    KindRuntime,
)
from frontend.server.knowledge_assets.kind_runtime.handlers import (
    AnalysisHandler,
    GraphOntologyHandler,
    KnowledgeHandler,
    SemanticHandler,
)
from frontend.server.knowledge_assets.kind_runtime.models import (
    GraphMapping,
    QueryPlan,
    RetrievalHit,
    SemanticField,
    SemanticModelProjection,
    SemanticRelationship,
)
from frontend.server.knowledge_assets.kind_runtime.repository import (
    SqliteKindRuntimeRepository,
)


NOW = "2026-08-25T00:00:00+00:00"
FRESH = "2026-08-24T23:00:00+00:00"
ZERO = "0" * 64


def _schema(name: str = "schema") -> SchemaRef:
    return SchemaRef(uri=f"local://{name}", version="1", sha256=ZERO)


def _storage(digest: str | None = None) -> StorageRef:
    return StorageRef(
        uri=f"local://golden/{digest or ZERO}",
        kind="object",
        sha256=digest or ZERO,
        media_type="text/csv",
        bytes=100,
    )


def _golden(
    golden_id: str,
    *,
    digest: str | None = None,
    permission_uri: str = "permission://workspace/ws/read",
) -> GoldenAssetRevision:
    return GoldenAssetRevision(
        id=golden_id,
        asset_kind="dataset",
        revision=1,
        schema_ref=_schema("golden-schema"),
        storage_ref=_storage(digest),
        source_revision_refs=[f"source-{golden_id}"],
        owner=OwnerRef(workspace_id="ws", principal_id="tester"),
        permissions_ref=PermissionRef(uri=permission_uri, version="1"),
        lineage_digest=ZERO,
        freshness_at=FRESH,
        last_good=True,
    )


def _manifest(skill_id: str, kind: str) -> SkillManifest:
    kind_spec: dict[str, object]
    if kind == "knowledge":
        kind_spec = {"kind": "knowledge", "retrievalMode": "keyword"}
    elif kind == "semantic":
        kind_spec = {
            "kind": "semantic",
            "relationshipRefs": ["customer.amount"],
        }
    elif kind == "analysis":
        kind_spec = {
            "kind": "analysis",
            "question": "show revenue by customer",
            "queryPlanRef": "query-plan://readonly/amount/customer",
        }
    elif kind == "graph_ontology":
        kind_spec = {
            "kind": "graph_ontology",
            "entitySchemaRef": _schema("entity").model_dump(mode="json", by_alias=True),
            "relationshipSchemaRef": _schema("relationship").model_dump(mode="json", by_alias=True),
            "constraintRefs": ["customer->amount"],
        }
    elif kind == "monitoring":
        kind_spec = {
            "kind": "monitoring",
            "refreshScheduleRef": "schedule://hourly",
            "alertPolicyRef": "alert://threshold/50",
        }
    else:
        raise AssertionError(kind)
    return SkillManifest.model_validate(
        {
            "apiVersion": "knowledge.veadk.io/v1alpha1",
            "kind": "Skill",
            "metadata": {
                "id": skill_id,
                "version": "1.0.0",
                "displayName": f"{kind} skill",
                "description": "customer revenue",
                "owner": {"workspaceId": "ws", "principalId": "tester"},
            },
            "spec": {
                "kind": kind,
                "contract": {
                    "inputSchemaRef": _schema("input").model_dump(mode="json", by_alias=True),
                    "outputSchemaRef": _schema("output").model_dump(mode="json", by_alias=True),
                },
                "dependencies": {"goldenAssets": ["golden-a"]},
                "policyRef": {"uri": "permission://workspace/ws/read", "version": "1"},
                "runtimeRef": f"runtime://{kind}/worker3",
                "kindSpec": kind_spec,
            },
        }
    )


def _draft(kind: str, revision: int = 1) -> SkillDraftRevision:
    return SkillDraftRevision(
        id=f"draft-{kind}:{revision}",
        skill_id=f"draft-{kind}",
        revision=revision,
        manifest=_manifest(f"draft-{kind}", kind),
        source_revision_refs=["source-golden-a"],
        golden_asset_revision_refs=["golden-a"],
        status="draft",
        created_at=NOW,
    )


def _request(
    kind: str,
    content: str,
    tmp_path: Path,
    *,
    budget: ExecutionBudget | None = None,
    permission_uri: str = "permission://workspace/ws/read",
    trace_id: str | None = None,
) -> KindExecutionRequest:
    digest = __import__("hashlib").sha256(content.encode("utf-8")).hexdigest()
    golden = _golden("golden-a", digest=digest, permission_uri=permission_uri)
    return KindExecutionRequest(
        draft_revision=_draft(kind),
        caller_id="tester",
        workspace_id="ws",
        golden_asset_revisions=[golden],
        golden_asset_contents={golden.id: content},
        data_access_revision_refs=["data-access:1"],
        downstream_skill_revision_refs=["downstream:1"],
        budget=budget or ExecutionBudget(max_rows=100),
        freshness_at=FRESH,
        idempotency_key=f"idempotent-{kind}-{digest[:8]}",
        trace_id=trace_id or f"trace-{kind}-{digest[:8]}",
        now=NOW,
    )


@pytest.mark.parametrize(
    "kind,template",
    [
        ("knowledge", "knowledge"),
        ("semantic", "semantic"),
        ("analysis", "chart"),
        ("graph_ontology", "graph_ontology"),
        ("monitoring", "monitoring"),
    ],
)
def test_worker3_runtime_executes_each_kind_with_typed_projection(
    tmp_path: Path, kind: str, template: str
) -> None:
    content = "customer,amount,date\nAlice,10,2026-08-24\nBob,70,2026-08-25\n"

    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request(kind, content, tmp_path)
    )

    assert result.status == "succeeded"
    assert result.state == "ok"
    assert result.skill_result is not None
    assert result.skill_result.kind == kind
    assert result.skill_result.golden_asset_revision_refs == ["golden-a"]
    assert result.view_intent is not None
    assert result.view_intent.template == template
    assert result.skill_view_revision is not None
    assert result.skill_view_revision.view_model.template == template
    assert result.trace_ref is not None
    assert result.evidence_ref is not None
    html_file = tmp_path / "views" / f"{result.skill_view_revision.result_ref.sha256}.html"
    rendered = html_file.read_text(encoding="utf-8")
    assert 'role="region"' in rendered
    assert 'data-csp="trusted-renderer-v1"' in rendered
    assert "<script" not in rendered.lower()
    assert "<iframe" not in rendered.lower()


def test_structured_data_changes_analysis_and_semantic_digests(tmp_path: Path) -> None:
    runtime = KindRuntime(ContentAddressedStore(tmp_path))
    first = "customer,amount\nAlice,10\nBob,20\n"
    second = "customer,amount\nAlice,10\nBob,200\n"

    analysis_a = runtime.execute(_request("analysis", first, tmp_path, trace_id="trace-analysis"))
    analysis_b = runtime.execute(_request("analysis", second, tmp_path, trace_id="trace-analysis"))
    semantic_a = runtime.execute(_request("semantic", first, tmp_path, trace_id="trace-semantic"))
    semantic_b = runtime.execute(
        _request("semantic", "customer,amount,region\nAlice,10,East\nBob,200,West\n", tmp_path, trace_id="trace-semantic")
    )

    assert analysis_a.result_payload_ref is not None
    assert analysis_b.result_payload_ref is not None
    assert semantic_a.skill_view_revision is not None
    assert semantic_b.skill_view_revision is not None
    assert analysis_a.result_payload_ref.sha256 != analysis_b.result_payload_ref.sha256
    assert (
        semantic_a.skill_view_revision.manifest.view_model_schema_ref.sha256
        != semantic_b.skill_view_revision.manifest.view_model_schema_ref.sha256
    )


def test_document_changes_update_knowledge_citation_and_digest(tmp_path: Path) -> None:
    runtime = KindRuntime(ContentAddressedStore(tmp_path))
    first = "Customer revenue policy: approve refunds within 7 days."
    second = "Customer revenue policy: approve refunds within 30 days."

    result_a = runtime.execute(_request("knowledge", first, tmp_path, trace_id="trace-knowledge"))
    result_b = runtime.execute(_request("knowledge", second, tmp_path, trace_id="trace-knowledge"))

    assert result_a.skill_view_revision is not None
    assert result_b.skill_view_revision is not None
    assert result_a.result_payload_ref is not None
    assert result_b.result_payload_ref is not None
    citations_a = result_a.skill_view_revision.view_model.citations
    citations_b = result_b.skill_view_revision.view_model.citations
    assert citations_a[0].locator != citations_b[0].locator
    assert result_a.result_payload_ref.sha256 != result_b.result_payload_ref.sha256


def test_permission_empty_budget_cancel_and_schema_drift_states(tmp_path: Path) -> None:
    runtime = KindRuntime(ContentAddressedStore(tmp_path))

    denied = runtime.execute(
        _request(
            "knowledge",
            "classified answer",
            tmp_path,
            permission_uri="permission://workspace/ws/deny",
        )
    )
    empty = runtime.execute(_request("analysis", "", tmp_path))
    over_budget = runtime.execute(
        _request(
            "analysis",
            "customer,amount\nAlice,10\nBob,20\n",
            tmp_path,
            budget=ExecutionBudget(max_rows=1),
        )
    )
    cancelled = runtime.execute(
        _request("monitoring", "day,amount\n2026-08-25,100\n", tmp_path).model_copy(
            update={"cancel_requested": True}
        )
    )
    drift = runtime.execute(
        _request("semantic", "Amount,amount\n10,20\n", tmp_path)
    )

    assert denied.status == "failed"
    assert denied.state == "permission_denied"
    assert empty.status == "awaiting_input"
    assert empty.state == "no_data"
    assert over_budget.status == "failed"
    assert over_budget.state == "over_budget"
    assert cancelled.status == "cancelled"
    assert cancelled.state == "cancelled"
    assert drift.status == "failed"
    assert drift.state == "schema_drift"


def test_timeout_and_replay_stability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    original_handler = runtime_module.HANDLERS["analysis"]

    class SlowHandler:
        kind = "analysis"

        def execute(self, request: KindExecutionRequest):
            __import__("time").sleep(0.002)
            return original_handler.execute(request)

    monkeypatch.setitem(runtime_module.HANDLERS, "analysis", SlowHandler())
    timed_out = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request(
            "analysis",
            "customer,amount\nAlice,10\n",
            tmp_path,
            budget=ExecutionBudget(timeout_ms=1),
        )
    )
    assert timed_out.status == "failed"
    assert timed_out.state == "timeout"

    monkeypatch.setitem(runtime_module.HANDLERS, "analysis", original_handler)
    runtime = KindRuntime(ContentAddressedStore(tmp_path))
    request = _request(
        "analysis",
        "customer,amount\nAlice,10\n",
        tmp_path,
        trace_id="trace-stable",
    )
    first = runtime.execute(request)
    second = runtime.execute(request)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.result_payload_ref == second.result_payload_ref
    assert first.skill_view_revision is not None
    assert second.skill_view_revision is not None
    assert first.skill_view_revision.id == second.skill_view_revision.id


def test_monitoring_generates_preview_only_action_candidates(tmp_path: Path) -> None:
    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request(
            "monitoring",
            "date,amount\n2026-08-24,10\n2026-08-25,80\n",
            tmp_path,
        )
    )

    assert result.status == "succeeded"
    assert result.skill_view_revision is not None
    assert "threshold" in result.skill_view_revision.view_model.alerts[0]
    payload_file = tmp_path / "results" / f"{result.result_payload_ref.sha256}.json"
    payload = __import__("json").loads(payload_file.read_text(encoding="utf-8"))
    assert payload["payload"]["externalActionsExecuted"] is False
    assert payload["payload"]["actionCandidates"][0]["previewOnly"] is True


def test_knowledge_uses_replaceable_retrieval_provider_and_preserves_citation_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class Provider:
        def retrieve(
            self, request: KindExecutionRequest, question: str
        ) -> list[RetrievalHit]:
            return [
                RetrievalHit(
                    source_revision_id="source-golden-a",
                    chunk_locator="vector://retrieval/hit-1",
                    text="Provider-selected answer with policy-bound citation.",
                    score=0.91,
                    permission_ref="permission://workspace/ws/read",
                )
            ]

        def answer(
            self,
            request: KindExecutionRequest,
            question: str,
            hits: list[RetrievalHit],
        ) -> tuple[str | None, str]:
            return hits[0].text, "ANSWERED_FROM_PROVIDER"

    monkeypatch.setitem(runtime_module.HANDLERS, "knowledge", KnowledgeHandler(Provider()))

    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("knowledge", "unrelated local text", tmp_path)
    )

    assert result.status == "succeeded"
    assert result.state == "ok"
    assert result.skill_view_revision is not None
    assert result.skill_view_revision.view_model.answer == (
        "Provider-selected answer with policy-bound citation."
    )
    citation = result.skill_view_revision.view_model.citations[0]
    assert citation.locator == "vector://retrieval/hit-1"
    assert result.evidence_ref is not None
    evidence = json.loads(
        (tmp_path / "evidence" / f"{result.evidence_ref.sha256}.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["items"][0]["permissionRef"] == "permission://workspace/ws/read"


def test_knowledge_no_answer_has_explicit_refusal_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class NoAnswerProvider:
        def retrieve(
            self, request: KindExecutionRequest, question: str
        ) -> list[RetrievalHit]:
            return []

        def answer(
            self,
            request: KindExecutionRequest,
            question: str,
            hits: list[RetrievalHit],
        ) -> tuple[str | None, str]:
            return None, "NO_AUTHORIZED_RETRIEVAL_HIT"

    monkeypatch.setitem(
        runtime_module.HANDLERS, "knowledge", KnowledgeHandler(NoAnswerProvider())
    )

    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("knowledge", "customer revenue", tmp_path)
    )

    assert result.status == "succeeded"
    assert result.state == "unable_to_answer"
    assert result.skill_view_revision is not None
    assert result.skill_view_revision.view_model.refusal is True
    assert result.result_payload_ref is not None
    payload = json.loads(
        (tmp_path / "results" / f"{result.result_payload_ref.sha256}.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["payload"]["answerReason"] == "NO_AUTHORIZED_RETRIEVAL_HIT"
    assert payload["payload"]["citations"] == []


def test_semantic_provider_supplies_entities_joins_metrics_units_and_mdl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class Provider:
        def build_model(self, request: KindExecutionRequest) -> SemanticModelProjection:
            return SemanticModelProjection(
                entities=["merchant", "campaign"],
                fields=[
                    SemanticField(
                        name="merchant",
                        role="dimension",
                        source_field="merchant_name",
                        permission_ref="permission://workspace/ws/read",
                    ),
                    SemanticField(
                        name="event_date",
                        role="time",
                        source_field="date",
                        permission_ref="permission://workspace/ws/read",
                    ),
                    SemanticField(
                        name="gross_margin",
                        role="measure",
                        aggregation="avg",
                        unit="%",
                        source_field="margin_pct",
                        permission_ref="permission://workspace/ws/read",
                    ),
                ],
                relationships=[
                    SemanticRelationship(
                        source="merchant",
                        target="campaign",
                        relation="owns",
                        join_type="one_to_many",
                        evidence_locator="mapping://merchant-campaign",
                    )
                ],
                mdl="model commerce { measure gross_margin aggregate: avg unit: % }",
            )

    monkeypatch.setitem(runtime_module.HANDLERS, "semantic", SemanticHandler(Provider()))

    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("semantic", "merchant_name,date,margin_pct\nA,2026-08-24,0.3\n", tmp_path)
    )

    assert result.status == "succeeded"
    assert result.result_payload_ref is not None
    payload = json.loads(
        (tmp_path / "results" / f"{result.result_payload_ref.sha256}.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["payload"]["entities"] == [
        {"name": "merchant", "source": "golden-a"},
        {"name": "campaign", "source": "golden-a"},
    ]
    assert payload["payload"]["metrics"][0]["aggregation"] == "avg"
    assert payload["payload"]["metrics"][0]["unit"] == "%"
    assert payload["payload"]["relationships"][0]["relation"] == "owns"
    assert payload["payload"]["editableMdl"].startswith("model commerce")


def test_semantic_rejects_provider_ambiguity_and_dependency_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class AmbiguousProvider:
        def build_model(self, request: KindExecutionRequest) -> SemanticModelProjection:
            return SemanticModelProjection(
                entities=["merchant"],
                fields=[],
                relationships=[],
                mdl="model bad {}",
                ambiguities=["merchant maps to two source fields"],
            )

    monkeypatch.setitem(
        runtime_module.HANDLERS, "semantic", SemanticHandler(AmbiguousProvider())
    )
    ambiguous = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("semantic", "merchant,amount\nA,1\n", tmp_path)
    )
    assert ambiguous.status == "failed"
    assert ambiguous.state == "schema_drift"

    class BrokenProvider:
        def build_model(self, request: KindExecutionRequest) -> SemanticModelProjection:
            return SemanticModelProjection(
                entities=["merchant"],
                fields=[
                    SemanticField(
                        name="amount",
                        role="measure",
                        aggregation="sum",
                        source_field="amount",
                        permission_ref="permission://workspace/ws/read",
                    )
                ],
                relationships=[
                    SemanticRelationship(
                        source="merchant",
                        target="missing_metric",
                        relation="measures",
                        evidence_locator="mapping://bad",
                    )
                ],
                mdl="model bad { join merchant -> missing_metric }",
                dependency_errors=["relationship target not found: merchant->missing_metric"],
            )

    monkeypatch.setitem(runtime_module.HANDLERS, "semantic", SemanticHandler(BrokenProvider()))
    broken = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("semantic", "merchant,amount\nA,1\n", tmp_path).model_copy(
            update={"idempotency_key": "semantic-broken"}
        )
    )
    assert broken.status == "failed"
    assert broken.state == "validation_failed"


def test_analysis_requires_fixed_plan_and_executes_through_readonly_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class Executor:
        plan: QueryPlan | None = None

        def execute(self, request: KindExecutionRequest, plan: QueryPlan):
            self.plan = plan
            return {
                "rows": [{"label": "merchant-a", "value": 42.0}],
                "metric": plan.metric,
                "dimension": plan.dimension,
                "compiled": "select merchant, sum(net_revenue) from golden_asset group by merchant",
                "dataAsOf": FRESH,
                "source": "golden-a",
                "nulls": {},
            }

    executor = Executor()
    monkeypatch.setitem(runtime_module.HANDLERS, "analysis", AnalysisHandler(executor))

    request = _request(
        "analysis",
        "first_dimension,first_metric,merchant,net_revenue\nignored,999,merchant-a,42\n",
        tmp_path,
    )
    request.draft_revision.manifest.spec.kind_spec.query_plan_ref = (
        "query-plan://readonly/net_revenue/merchant"
    )
    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(request)

    assert result.status == "succeeded"
    assert executor.plan is not None
    assert executor.plan.metric == "net_revenue"
    assert executor.plan.dimension == "merchant"
    assert result.skill_view_revision is not None
    assert result.skill_view_revision.view_model.y_field == "net_revenue"
    assert result.skill_view_revision.view_model.x_field == "merchant"

    invalid = _request(
        "analysis",
        "first_dimension,first_metric,merchant,net_revenue\nignored,999,merchant-a,42\n",
        tmp_path,
    )
    invalid.draft_revision.manifest.spec.kind_spec.query_plan_ref = "query-plan://dynamic"
    invalid = invalid.model_copy(update={"idempotency_key": "invalid-query-plan"})
    missing_plan = KindRuntime(ContentAddressedStore(tmp_path)).execute(invalid)
    assert missing_plan.status == "awaiting_input"
    assert missing_plan.state == "no_data"


def test_readonly_query_executor_enforces_field_permissions(tmp_path: Path) -> None:
    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("analysis", "customer,ssn,amount\nAlice,111-22-3333,10\n", tmp_path)
    )

    assert result.status == "failed"
    assert result.state == "permission_denied"


def test_graph_ontology_uses_mapping_evidence_not_sequential_related_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class Provider:
        def build_graph(self, request: KindExecutionRequest) -> GraphMapping:
            return GraphMapping(
                entities=["merchant", "campaign", "gmv"],
                relationships=[
                    SemanticRelationship(
                        source="merchant",
                        target="campaign",
                        relation="owns",
                        evidence_locator="mapping://merchant-campaign",
                    ),
                    SemanticRelationship(
                        source="campaign",
                        target="gmv",
                        relation="measures",
                        evidence_locator="schema://campaign-gmv",
                    ),
                ],
                evidence_locators=["mapping://merchant-campaign", "schema://campaign-gmv"],
            )

    monkeypatch.setitem(
        runtime_module.HANDLERS, "graph_ontology", GraphOntologyHandler(Provider())
    )

    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        _request("graph_ontology", "merchant,campaign,gmv\nA,C1,100\n", tmp_path)
    )

    assert result.status == "succeeded"
    assert result.skill_view_revision is not None
    relations = [edge.relation for edge in result.skill_view_revision.view_model.edges]
    assert relations == ["owns", "measures"]
    assert "related_to" not in relations
    assert result.result_payload_ref is not None
    payload = json.loads(
        (tmp_path / "results" / f"{result.result_payload_ref.sha256}.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["payload"]["mappingEvidence"] == [
        "mapping://merchant-campaign",
        "schema://campaign-gmv",
    ]


def test_repository_replays_completed_operation_after_runtime_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class Provider:
        calls = 0

        def retrieve(
            self, request: KindExecutionRequest, question: str
        ) -> list[RetrievalHit]:
            self.calls += 1
            return [
                RetrievalHit(
                    source_revision_id="source-golden-a",
                    chunk_locator="provider://hit",
                    text="persisted answer",
                    score=1.0,
                    permission_ref="permission://workspace/ws/read",
                )
            ]

        def answer(
            self,
            request: KindExecutionRequest,
            question: str,
            hits: list[RetrievalHit],
        ) -> tuple[str | None, str]:
            return hits[0].text, "ANSWERED_FROM_PROVIDER"

    provider = Provider()
    monkeypatch.setitem(
        runtime_module.HANDLERS, "knowledge", KnowledgeHandler(provider)
    )
    repository_path = tmp_path / "w3.sqlite3"
    request = _request("knowledge", "customer revenue", tmp_path)
    first = KindRuntime(
        ContentAddressedStore(tmp_path / "store-a"),
        repository=SqliteKindRuntimeRepository(repository_path),
    ).execute(request)

    class RaisingProvider:
        def retrieve(
            self, request: KindExecutionRequest, question: str
        ) -> list[RetrievalHit]:
            raise AssertionError("provider should not run for persisted idempotency replay")

        def answer(
            self,
            request: KindExecutionRequest,
            question: str,
            hits: list[RetrievalHit],
        ) -> tuple[str | None, str]:
            raise AssertionError("provider should not run for persisted idempotency replay")

    monkeypatch.setitem(
        runtime_module.HANDLERS, "knowledge", KnowledgeHandler(RaisingProvider())
    )
    second = KindRuntime(
        ContentAddressedStore(tmp_path / "store-b"),
        repository=SqliteKindRuntimeRepository(repository_path),
    ).execute(request)

    assert provider.calls == 1
    assert second.operation_id == first.operation_id
    assert second.result_payload_ref == first.result_payload_ref


def test_repository_reports_incomplete_operations_for_restart_recovery(
    tmp_path: Path,
) -> None:
    repository_path = tmp_path / "w3.sqlite3"
    repository = SqliteKindRuntimeRepository(repository_path)
    request = _request("knowledge", "customer revenue", tmp_path)
    operation_id = repository.operation_id_for_key("stuck-op")
    request_json = request.model_copy(update={"idempotency_key": "stuck-op"}).model_dump(
        mode="json", by_alias=True
    )

    assert repository.begin(operation_id, request_json) is None

    recovered = SqliteKindRuntimeRepository(repository_path).recover_incomplete()
    assert operation_id in recovered


def test_concurrent_idempotent_execution_runs_provider_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    class SlowProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.lock = threading.Lock()

        def retrieve(
            self, request: KindExecutionRequest, question: str
        ) -> list[RetrievalHit]:
            with self.lock:
                self.calls += 1
            time.sleep(0.05)
            return [
                RetrievalHit(
                    source_revision_id="source-golden-a",
                    chunk_locator="provider://slow-hit",
                    text="slow answer",
                    score=1.0,
                    permission_ref="permission://workspace/ws/read",
                )
            ]

        def answer(
            self,
            request: KindExecutionRequest,
            question: str,
            hits: list[RetrievalHit],
        ) -> tuple[str | None, str]:
            return hits[0].text, "ANSWERED_FROM_PROVIDER"

    provider = SlowProvider()
    monkeypatch.setitem(
        runtime_module.HANDLERS, "knowledge", KnowledgeHandler(provider)
    )
    runtime = KindRuntime(
        ContentAddressedStore(tmp_path / "store"),
        repository=SqliteKindRuntimeRepository(tmp_path / "w3.sqlite3"),
    )
    request = _request("knowledge", "customer revenue", tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runtime.execute, request)
        second = pool.submit(runtime.execute, request)
        first_result = first.result()
        second_result = second.result()

    assert provider.calls == 1
    assert first_result.operation_id == second_result.operation_id
    assert first_result.result_payload_ref == second_result.result_payload_ref


def test_running_execution_can_be_cancelled_without_persisting_late_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from frontend.server.knowledge_assets.kind_runtime import runtime as runtime_module

    started = threading.Event()
    may_finish = threading.Event()

    class SlowExecutor:
        def execute(self, request: KindExecutionRequest, plan: QueryPlan):
            started.set()
            may_finish.wait(timeout=1)
            return {
                "rows": [{"label": "Alice", "value": 10.0}],
                "metric": plan.metric,
                "dimension": plan.dimension,
                "compiled": "select customer, sum(amount) from golden_asset group by customer",
                "dataAsOf": FRESH,
                "source": "golden-a",
                "nulls": {},
            }

    monkeypatch.setitem(
        runtime_module.HANDLERS, "analysis", AnalysisHandler(SlowExecutor())
    )
    repository = SqliteKindRuntimeRepository(tmp_path / "w3.sqlite3")
    runtime = KindRuntime(ContentAddressedStore(tmp_path), repository=repository)
    request = _request("analysis", "customer,amount\nAlice,10\n", tmp_path)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.execute, request)
        assert started.wait(timeout=1)
        runtime.cancel(request.idempotency_key)
        result = future.result(timeout=1)
        may_finish.set()

    assert result.status == "cancelled"
    assert result.state == "cancelled"
    assert repository.get(result.operation_id).status == "cancelled"


def test_retry_links_to_failed_source_operation(
    tmp_path: Path,
) -> None:
    repository = SqliteKindRuntimeRepository(tmp_path / "w3.sqlite3")
    runtime = KindRuntime(ContentAddressedStore(tmp_path), repository=repository)
    failed = runtime.execute(
        _request("analysis", "customer,amount\nAlice,10\n", tmp_path).model_copy(
            update={"cancel_requested": True}
        )
    )
    retry_request = _request("analysis", "customer,amount\nAlice,10\n", tmp_path).model_copy(
        update={"idempotency_key": "retry-analysis"}
    )

    retried = runtime.retry(retry_request, retry_of_operation_id=failed.operation_id)

    assert failed.status == "cancelled"
    assert retried.status == "succeeded"
    assert retried.retry_of_operation_id == failed.operation_id


def test_monitoring_lifecycle_is_persisted_with_last_good_duration_and_preview_actions(
    tmp_path: Path,
) -> None:
    repository = SqliteKindRuntimeRepository(tmp_path / "w3.sqlite3")
    result = KindRuntime(ContentAddressedStore(tmp_path), repository=repository).execute(
        _request(
            "monitoring",
            "date,amount\n2026-08-24,10\n2026-08-25,80\n",
            tmp_path,
        )
    )

    stored = repository.get(result.operation_id)
    assert stored is not None
    assert stored.monitoring_lifecycle is not None
    assert stored.monitoring_lifecycle.external_actions_executed is False
    assert stored.monitoring_lifecycle.observations[0].metric == "amount"
    assert stored.monitoring_lifecycle.observations[0].duration_seconds == 86_400
    assert stored.monitoring_lifecycle.observations[0].last_good_revision_id == "golden-a"
    assert stored.monitoring_lifecycle.alerts[0].status == "open"
    assert stored.monitoring_lifecycle.action_candidates[0].status == "preview"
