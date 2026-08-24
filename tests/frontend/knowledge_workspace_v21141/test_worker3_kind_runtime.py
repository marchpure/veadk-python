from __future__ import annotations

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
            "relationshipRefs": ["customers.orders"],
        }
    elif kind == "analysis":
        kind_spec = {
            "kind": "analysis",
            "question": "show revenue by customer",
            "queryPlanRef": "query-plan://readonly/customer-revenue",
        }
    elif kind == "graph_ontology":
        kind_spec = {
            "kind": "graph_ontology",
            "entitySchemaRef": _schema("entity").model_dump(mode="json", by_alias=True),
            "relationshipSchemaRef": _schema("relationship").model_dump(mode="json", by_alias=True),
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
    first = "Refund policy: approve refunds within 7 days."
    second = "Refund policy: approve refunds within 30 days."

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
