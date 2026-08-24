from pathlib import Path

import pytest

from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.contracts import (
    SkillDraftRunPayload,
    SkillManifest,
    SourceCleanPayload,
)
from frontend.server.knowledge_assets.repository import SqliteKnowledgeAssetRepository


def _manifest(draft_id: str, golden_id: str, kind: str) -> dict[str, object]:
    kind_spec: dict[str, object] = {"kind": kind}
    if kind == "semantic":
        kind_spec.update(
            metricRefs=[],
            dimensionRefs=[],
            relationshipRefs=["orders.customer"],
        )
    elif kind == "analysis":
        kind_spec.update(
            question="按客户查看销售额",
            queryPlanRef="local://query-plan/sales",
        )
    elif kind == "knowledge":
        kind_spec.update(retrievalMode="keyword", sourceRevisionRefs=[])
    elif kind == "graph_ontology":
        zero = "0" * 64
        kind_spec.update(
            entitySchemaRef={"uri": "local://schema/entity", "version": "1", "sha256": zero},
            relationshipSchemaRef={"uri": "local://schema/relationship", "version": "1", "sha256": zero},
        )
    elif kind == "monitoring":
        kind_spec.update(
            metricRefs=[],
            refreshScheduleRef="schedule://hourly",
            alertPolicyRef="alert://sales",
        )
    return {
        "apiVersion": "knowledge.veadk.io/v1alpha1",
        "kind": "Skill",
        "metadata": {
            "id": draft_id,
            "version": "1.0.0",
            "displayName": f"{kind} skill",
            "description": "typed execution test",
            "owner": {"workspaceId": "ws", "principalId": "test"},
        },
        "spec": {
            "kind": kind,
            "contract": {
                "inputSchemaRef": {
                    "uri": "local://schema/input",
                    "version": "1",
                    "sha256": "0" * 64,
                },
                "outputSchemaRef": {
                    "uri": "local://schema/output",
                    "version": "1",
                    "sha256": "0" * 64,
                },
            },
            "dependencies": {"goldenAssets": [golden_id]},
            "policyRef": {"uri": "permission://workspace/ws", "version": "1"},
            "runtimeRef": f"runtime://{kind}/v1",
            "kindSpec": kind_spec,
        },
    }


@pytest.mark.parametrize(
    "kind,template",
    [
        ("semantic", "semantic"),
        ("analysis", "chart"),
        ("knowledge", "knowledge"),
        ("graph_ontology", "graph_ontology"),
        ("monitoring", "monitoring"),
    ],
)
def test_csv_golden_asset_drives_each_typed_skill_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, template: str
) -> None:
    source = tmp_path / "sales.csv"
    source.write_text("customer,amount\nAlice,10\nBob,20\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    source_revision = application._register_local_source(
        str(source), workspace_id="ws", request_id="source"
    )
    assert source_revision is not None
    cleaned = application._run_clean(
        SourceCleanPayload(source_revision_id=source_revision.id, recipe_id="clean"),
        "ws",
    )
    assert cleaned.golden_asset_revision is not None
    golden = cleaned.golden_asset_revision
    draft, _ = repository.create_skill_draft(
        workspace_id="ws",
        name=f"{kind} skill",
        description="typed execution test",
        source_refs=[str(source)],
        request_id="create",
        idempotency_key=f"create-{kind}",
    )
    updated, _ = repository.save_manifest(
        draft_id=draft.id,
        base_revision=draft.revision,
        manifest=SkillManifest.model_validate(_manifest(draft.id, golden.id, kind)),
        request_id="save",
        idempotency_key=f"save-{kind}",
    )

    result = application._run_skill_draft(
        SkillDraftRunPayload(
            draft_id=updated.id,
            revision=updated.revision,
            trace_id=f"trace-{kind}",
        ),
        request_id=f"run-{kind}",
    )

    assert result.status == "ready_for_evaluation"
    assert result.skill_result is not None
    assert result.skill_result.kind == kind
    assert result.view_intent is not None
    assert result.view_intent.template == template
    assert result.skill_view_revision is not None
    assert result.skill_view_revision.invocation_id is not None
    invocation = repository._connection.execute(
        "SELECT invocation_json FROM invocations WHERE id = ?",
        (result.skill_view_revision.invocation_id,),
    ).fetchone()
    assert invocation is not None
    view_model = result.skill_view_revision.view_model
    if hasattr(view_model, "data_ref"):
        assert view_model.data_ref == golden.storage_ref
    elif kind == "knowledge":
        assert view_model.citations[0].locator.endswith(golden.storage_ref.sha256)
    else:
        assert view_model.evidence_ref == golden.storage_ref
    if kind == "semantic":
        assert "amount" in result.skill_view_revision.view_model.metric_refs
        assert "customer" in result.skill_view_revision.view_model.dimension_refs
    if kind == "analysis":
        assert result.skill_view_revision.view_model.series[0].points == [
            ("Alice", 10.0),
            ("Bob", 20.0),
        ]
    if kind == "monitoring":
        assert result.skill_view_revision.view_model.values == [
            ("Alice", 10.0),
            ("Bob", 20.0),
        ]
