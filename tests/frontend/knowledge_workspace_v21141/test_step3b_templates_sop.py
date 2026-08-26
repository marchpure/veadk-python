from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from frontend.server.knowledge_assets.contracts import (
    ContextRevisionRef,
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
    KindExecutionRequest,
    KindRuntime,
    SemanticDependencySnapshot,
)
from frontend.server.knowledge_assets.skill_builder import TemplateSkillBuilder
from frontend.server.knowledge_assets.template_registry import (
    SqliteTemplateRegistry,
    parse_spec_md,
    template_ref,
)

NOW = "2026-08-25T08:00:00+08:00"
ZERO = "0" * 64


def schema(name: str) -> SchemaRef:
    return SchemaRef(uri=f"schema://{name}", version="1", sha256=ZERO)


def golden(content: str, *, workspace: str = "ws") -> GoldenAssetRevision:
    digest = hashlib.sha256(content.encode()).hexdigest()
    return GoldenAssetRevision(
        id=f"golden-{digest[:12]}",
        asset_kind="dataset",
        revision=1,
        schema_ref=schema("golden"),
        storage_ref=StorageRef(
            uri=f"local://golden/{digest}",
            kind="object",
            sha256=digest,
            media_type="text/csv",
            bytes=len(content.encode()),
        ),
        source_revision_refs=[f"source-{digest[:12]}"],
        owner=OwnerRef(workspace_id=workspace, principal_id="tester"),
        permissions_ref=PermissionRef(
            uri=f"permission://workspace/{workspace}/read", version="1"
        ),
        lineage_digest=digest,
        freshness_at=NOW,
    )


def manifest(
    skill_id: str, kind: str, kind_spec: dict, template=None, *, workspace: str = "ws"
) -> SkillManifest:
    return SkillManifest.model_validate(
        {
            "metadata": {
                "id": skill_id,
                "version": "1.0.0",
                "displayName": skill_id.replace("-", " ").title(),
                "owner": {"workspaceId": workspace, "principalId": "tester"},
            },
            "spec": {
                "kind": kind,
                "contract": {
                    "inputSchemaRef": schema("input").model_dump(
                        mode="json", by_alias=True
                    ),
                    "outputSchemaRef": schema("output").model_dump(
                        mode="json", by_alias=True
                    ),
                },
                "policyRef": {"uri": "permission://workspace/ws/read", "version": "1"},
                "runtimeRef": f"runtime://{kind}/v1",
                "templateRef": (
                    template.model_dump(mode="json", by_alias=True)
                    if template
                    else None
                ),
                "defaultRenderer": (
                    {
                        "analysis": "dashboard",
                        "semantic": "semantic",
                        "sop": "sop",
                        "knowledge": "knowledge",
                        "graph_ontology": "graph_ontology",
                        "monitoring": "monitoring",
                    }[kind]
                    if template
                    else None
                ),
                "kindSpec": kind_spec,
            },
        }
    )


def draft_for(
    skill_id: str,
    kind: str,
    kind_spec: dict,
    template,
    revision: int = 1,
    workspace: str = "ws",
) -> SkillDraftRevision:
    value = manifest(skill_id, kind, kind_spec, template, workspace=workspace)
    return SkillDraftRevision(
        id=f"{skill_id}:{revision}",
        skill_id=skill_id,
        revision=revision,
        manifest=value,
        template_ref=template,
        created_at=NOW,
    )


def request(
    draft: SkillDraftRevision,
    content: str,
    *,
    workspace: str = "ws",
    inputs=None,
    tools=None,
    semantic_dependencies=None,
) -> KindExecutionRequest:
    asset = golden(content, workspace=workspace)
    return KindExecutionRequest(
        draft_revision=draft,
        caller_id="tester",
        workspace_id=workspace,
        golden_asset_revisions=[asset],
        golden_asset_contents={asset.id: content},
        downstream_skill_revision_refs=[
            item.skill_revision_id for item in (semantic_dependencies or [])
        ],
        semantic_dependencies=semantic_dependencies or [],
        inputs=inputs or {},
        tool_results=tools or {},
        idempotency_key=f"{draft.id}-{asset.storage_ref.sha256}",
        trace_id=f"trace-{draft.id}-{asset.storage_ref.sha256[:8]}",
        now=NOW,
    )


def test_registry_persists_versions_and_custom_spec_md(tmp_path: Path) -> None:
    path = tmp_path / "registry.sqlite3"
    registry = SqliteTemplateRegistry(path)
    assert {item.template_id for item in registry.list("workspace-a")} == {
        "dashboard",
        "semantic",
        "sop",
        "knowledge",
        "graph-ontology",
        "monitoring",
    }
    copied_ref = registry.copy_builtin(
        "sop",
        "1.0.0",
        workspace_id="workspace-a",
        new_template_id="store-inspection",
        display_name="门店巡检",
    )
    markdown = registry.spec_md("store-inspection", "1.0.0", "workspace-a")
    assert markdown is not None
    parsed = parse_spec_md(markdown)
    assert parsed.owner_workspace_id == "workspace-a"
    assert parsed.copied_from.template_id == "sop"
    restarted = SqliteTemplateRegistry(path)
    assert restarted.get("store-inspection", "1.0.0", "workspace-a") is not None
    assert restarted.get("store-inspection", "1.0.0", "workspace-b") is None
    changed = parsed.model_copy(update={"scenario": "changed in place"})
    with pytest.raises(ValueError, match="immutable"):
        restarted.put(changed)
    assert copied_ref.digest == template_ref(parsed).digest


def test_builder_binds_template_and_context_without_keyword_inference() -> None:
    registry = SqliteTemplateRegistry(":memory:")
    selected = template_ref(registry.get("dashboard", "1.0.0", "ws"))
    context = ContextRevisionRef(
        kind="golden_asset",
        resource_id="sales",
        revision_id="sales:7",
        digest="7" * 64,
    )
    value = manifest(
        "board",
        "analysis",
        {
            "kind": "analysis",
            "question": "arbitrary wording",
            "queryPlanRef": "query-plan://readonly/revenue/region",
        },
    )
    built = TemplateSkillBuilder(registry).build(
        workspace_id="ws",
        manifest=value,
        selected_template=selected,
        context_revision_refs=[context],
        created_at=NOW,
    )
    assert built.template_ref == selected
    assert built.context_revision_refs == [context]
    assert built.manifest.spec.kind == "analysis"
    with pytest.raises(ValueError, match="kind"):
        TemplateSkillBuilder(registry).build(
            workspace_id="ws",
            manifest=manifest("wrong", "knowledge", {"kind": "knowledge"}),
            selected_template=selected,
            context_revision_refs=[context],
            created_at=NOW,
        )


def test_two_real_dashboards_are_data_derived_and_not_fixed(tmp_path: Path) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("dashboard", "1.0.0", "ws"))
    runtime = KindRuntime(ContentAddressedStore(tmp_path))
    sales = draft_for(
        "regional-sales",
        "analysis",
        {
            "kind": "analysis",
            "question": "Revenue by region",
            "queryPlanRef": "query-plan://readonly/revenue/region",
        },
        ref,
        workspace="workspace-sales",
    )
    inventory = draft_for(
        "warehouse-stock",
        "analysis",
        {
            "kind": "analysis",
            "question": "Units by warehouse",
            "queryPlanRef": "query-plan://readonly/units/warehouse",
        },
        ref,
        workspace="workspace-inventory",
    )
    first = runtime.execute(
        request(
            sales,
            "region,revenue\nEast,110\nWest,230\n",
            workspace="workspace-sales",
        )
    )
    second = runtime.execute(
        request(
            inventory,
            "warehouse,units,category\nWH-A,7,Shoe\nWH-B,19,Hat\n",
            workspace="workspace-inventory",
        )
    )
    left = first.skill_view_revision
    right = second.skill_view_revision
    assert left.view_model.template == right.view_model.template == "dashboard"
    assert left.view_model.title == "Regional Sales"
    assert right.view_model.title == "Warehouse Stock"
    assert left.view_model.kpis[0].value == 340
    assert right.view_model.kpis[0].value == 26
    assert left.view_model.charts[0].x_field == "region"
    assert right.view_model.charts[0].x_field == "warehouse"
    assert left.html_digest != right.html_digest
    for view in (left, right):
        document = (tmp_path / "views" / f"{view.result_ref.sha256}.html").read_text()
        assert "Content-Security-Policy" in document
        assert "<script" not in document.lower()
        assert "<iframe" not in document.lower()
        assert view.etag == f'"sha256-{view.result_ref.sha256}"'
        restarted_store = ContentAddressedStore(tmp_path)
        assert hashlib.sha256(
            restarted_store.read_bytes(view.result_ref)
        ).hexdigest() == (view.html_digest)


def test_semantic_dependency_is_pinned_and_schema_drift_is_typed(
    tmp_path: Path,
) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("dashboard", "1.0.0", "ws"))
    draft = draft_for(
        "semantic-board",
        "analysis",
        {
            "kind": "analysis",
            "question": "GMV by store",
            "queryPlanRef": "query-plan://readonly/gmv/store",
        },
        ref,
    )
    stable = SemanticDependencySnapshot(
        skill_revision_id="semantic-commerce:4",
        schema_digest="1" * 64,
        current_schema_digest="1" * 64,
        metric_refs=["gmv"],
        dimension_refs=["store"],
        relationship_refs=["store.order"],
    )
    runtime = KindRuntime(ContentAddressedStore(tmp_path))
    ok = runtime.execute(
        request(draft, "store,gmv\nA,42\n", semantic_dependencies=[stable])
    )
    drift = stable.model_copy(update={"current_schema_digest": "2" * 64})
    failed = runtime.execute(
        request(draft, "store,gmv\nA,42\n", semantic_dependencies=[drift]).model_copy(
            update={"idempotency_key": "schema-drift"}
        )
    )
    assert ok.status == "succeeded"
    assert failed.status == "failed"
    assert failed.state == "schema_drift"
    assert "semantic-commerce:4" in failed.message


def sop_spec(journey: str) -> dict:
    if journey == "im":
        return {
            "kind": "sop",
            "trigger": "vehicle Bluetooth repeatedly disconnects",
            "scope": "IM LS6 after-sales diagnosis",
            "inputFields": [
                {"name": "vin", "label": "VIN", "valueType": "string"},
                {
                    "name": "disconnect_count",
                    "label": "断连次数",
                    "valueType": "number",
                },
            ],
            "steps": [
                {
                    "id": "signals",
                    "title": "读取诊断信号",
                    "instruction": "Read current Bluetooth signals.",
                    "toolRef": {
                        "toolId": "im-diagnostics",
                        "revision": "3",
                        "operation": "read_signals",
                    },
                    "evidenceRequirements": [{"kind": "tool_result"}],
                },
                {
                    "id": "ticket",
                    "title": "检索历史工单",
                    "instruction": "Compare matching repair history.",
                    "condition": {
                        "field": "disconnect_count",
                        "operator": "gte",
                        "value": 3,
                    },
                    "evidenceRequirements": [{"kind": "source_citation"}],
                },
                {
                    "id": "repair",
                    "title": "创建维修建议",
                    "instruction": "Prepare a service action.",
                    "toolRef": {
                        "toolId": "work-orders",
                        "revision": "2",
                        "operation": "create",
                        "risk": "high_risk",
                    },
                    "failureMode": "propose_action",
                },
            ],
            "outputs": [{"name": "diagnosis", "valueType": "string"}],
            "failureHandling": "Escalate with collected evidence.",
            "actionProposal": "Inspect antenna firmware and connector.",
        }
    return {
        "kind": "sop",
        "trigger": "scheduled restaurant hygiene inspection",
        "scope": "Haidilao dining room and kitchen",
        "inputFields": [
            {"name": "store_code", "label": "门店", "valueType": "string"},
            {
                "name": "zone",
                "label": "区域",
                "valueType": "enum",
                "enumValues": ["kitchen", "dining"],
            },
        ],
        "steps": [
            {
                "id": "standard",
                "title": "读取门店规范",
                "instruction": "Retrieve the hygiene standard.",
                "evidenceRequirements": [{"kind": "source_citation"}],
            },
            {
                "id": "history",
                "title": "比对历史巡检",
                "instruction": "Compare prior findings for this store.",
                "toolRef": {
                    "toolId": "inspection-history",
                    "revision": "5",
                    "operation": "search",
                },
                "evidenceRequirements": [{"kind": "tool_result"}],
            },
        ],
        "outputs": [{"name": "inspection_result", "valueType": "string"}],
        "failureHandling": "Mark unresolved items for manager review.",
        "actionProposal": "Reinspect failed hygiene controls.",
    }


def test_two_sop_journeys_execute_tools_evidence_and_safe_proposals(
    tmp_path: Path,
) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("sop", "1.0.0", "ws"))
    runtime = KindRuntime(ContentAddressedStore(tmp_path))
    im = draft_for("im-bluetooth", "sop", sop_spec("im"), ref)
    restaurant = draft_for("haidilao-inspection", "sop", sop_spec("haidilao"), ref)
    im_result = runtime.execute(
        request(
            im,
            "manual: inspect antenna; ticket history: firmware issue",
            inputs={"vin": "LS6-001", "disconnect_count": 5},
            tools={"im-diagnostics:read_signals": {"rssi": -88, "drops": 5}},
        )
    )
    store_result = runtime.execute(
        request(
            restaurant,
            "standard: surface ATP must pass; inspection history attached",
            inputs={"store_code": "HDL-88", "zone": "kitchen"},
            tools={"inspection-history:search": {"prior_failures": ["cold storage"]}},
        )
    )
    im_view = im_result.skill_view_revision.view_model
    store_view = store_result.skill_view_revision.view_model
    assert im_result.status == store_result.status == "succeeded"
    assert im_view.trigger != store_view.trigger
    assert len(im_view.step_results) == 3
    assert len(store_view.step_results) == 2
    assert im_view.step_results[0].evidence[0].locator.startswith("tool-result://")
    assert (
        store_view.step_results[1].evidence[0].summary
        == '{"prior_failures": ["cold storage"]}'
    )
    assert im_view.action_proposals[0].confirmation_required is True
    assert (
        im_result.skill_view_revision.html_digest
        != store_result.skill_view_revision.html_digest
    )
    payload = json.loads(
        (
            tmp_path / "results" / f"{im_result.result_payload_ref.sha256}.json"
        ).read_text()
    )
    assert payload["payload"]["externalActionsExecuted"] is False


def test_typed_patches_create_revision_and_diff() -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("sop", "1.0.0", "ws"))
    draft = draft_for("sop-patch", "sop", sop_spec("im"), ref)
    revised, diff = TemplateSkillBuilder(registry).patch(
        draft,
        changes={"kindSpec.steps[1].condition.value": 6},
        created_at=NOW,
    )
    assert revised.revision == 2
    assert revised.id == "sop-patch:2"
    assert revised.manifest.spec.kind_spec.steps[1].condition.value == 6
    assert diff.changed_paths == ("kindSpec.steps[1].condition.value",)
    with pytest.raises(ValueError, match="Unsupported"):
        TemplateSkillBuilder(registry).patch(
            draft, changes={"kindSpec.kind": "analysis"}, created_at=NOW
        )


def test_dashboard_patch_changes_kpi_chart_and_filter_projection(
    tmp_path: Path,
) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("dashboard", "1.0.0", "ws"))
    original = draft_for(
        "editable-board",
        "analysis",
        {
            "kind": "analysis",
            "question": "Revenue by region",
            "queryPlanRef": "query-plan://readonly/revenue/region",
            "dashboard": {
                "title": "Revenue",
                "kpiLabels": {},
                "filterFields": ["region"],
                "drillFields": ["revenue"],
            },
        },
        ref,
    )
    revised, diff = TemplateSkillBuilder(registry).patch(
        original,
        changes={
            "kindSpec.dashboard.title": "Regional performance",
            "kindSpec.dashboard.kpiLabels": {"sum_revenue": "Net revenue"},
            "kindSpec.dashboard.chartTitle": "Revenue distribution",
            "kindSpec.dashboard.filterFields": ["channel"],
        },
        created_at=NOW,
    )
    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        request(revised, "region,channel,revenue\nEast,Online,10\nWest,Store,20\n")
    )
    view = result.skill_view_revision.view_model
    assert diff.to_revision == 2
    assert view.title == "Regional performance"
    assert view.kpis[0].label == "Net revenue"
    assert view.charts[0].title == "Revenue distribution"
    assert view.filters[0].field == "channel"
    assert result.skill_view_revision.revision == 2


def test_runtime_rejects_cross_workspace_golden_asset(tmp_path: Path) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("knowledge", "1.0.0", "ws"))
    draft = draft_for("private-knowledge", "knowledge", {"kind": "knowledge"}, ref)
    denied = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        request(draft, "private content", workspace="other")
    )
    assert denied.status == "failed"
    assert denied.state == "permission_denied"


def test_graph_typed_patch_changes_entities_and_relations(tmp_path: Path) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    ref = template_ref(registry.get("graph-ontology", "1.0.0", "ws"))
    original = draft_for(
        "commerce-graph",
        "graph_ontology",
        {
            "kind": "graph_ontology",
            "entitySchemaRef": schema("entity").model_dump(mode="json", by_alias=True),
            "relationshipSchemaRef": schema("relation").model_dump(
                mode="json", by_alias=True
            ),
            "entities": ["Store", "Order"],
            "relationships": [
                {
                    "source": "Store",
                    "target": "Order",
                    "relation": "receives",
                    "evidenceLocator": "schema://store-order",
                }
            ],
        },
        ref,
    )
    revised, _ = TemplateSkillBuilder(registry).patch(
        original,
        changes={
            "kindSpec.entities": ["Store", "Inspection"],
            "kindSpec.relationships": [
                {
                    "source": "Store",
                    "target": "Inspection",
                    "relation": "undergoes",
                    "evidenceLocator": "policy://store-inspection",
                }
            ],
        },
        created_at=NOW,
    )
    result = KindRuntime(ContentAddressedStore(tmp_path)).execute(
        request(revised, "store,inspection\nHDL-88,I-42\n")
    )
    view = result.skill_view_revision.view_model
    assert [node.label for node in view.nodes] == ["Store", "Inspection"]
    assert view.edges[0].relation == "undergoes"


def test_each_template_runtime_is_evaluable_or_explicitly_blocked(
    tmp_path: Path,
) -> None:
    registry = SqliteTemplateRegistry(":memory:")
    cases = [
        (
            "dashboard",
            "analysis",
            {
                "kind": "analysis",
                "question": "value by label",
                "queryPlanRef": "query-plan://readonly/value/label",
            },
            "label,value\nA,1\n",
            {},
            {},
        ),
        ("semantic", "semantic", {"kind": "semantic"}, "label,value\nA,1\n", {}, {}),
        ("knowledge", "knowledge", {"kind": "knowledge"}, "policy evidence", {}, {}),
        (
            "graph-ontology",
            "graph_ontology",
            {
                "kind": "graph_ontology",
                "entitySchemaRef": schema("entity").model_dump(
                    mode="json", by_alias=True
                ),
                "relationshipSchemaRef": schema("relation").model_dump(
                    mode="json", by_alias=True
                ),
            },
            "label,value\nA,1\n",
            {},
            {},
        ),
        (
            "monitoring",
            "monitoring",
            {
                "kind": "monitoring",
                "refreshScheduleRef": "schedule://daily",
                "alertPolicyRef": "alert://threshold/10",
            },
            "date,value\n2026-08-24,1\n2026-08-25,20\n",
            {},
            {},
        ),
        (
            "sop",
            "sop",
            sop_spec("haidilao"),
            "hygiene standard",
            {"store_code": "HDL-1", "zone": "dining"},
            {"inspection-history:search": {"prior_failures": []}},
        ),
    ]
    for index, (template_id, kind, kind_spec, content, inputs, tools) in enumerate(
        cases
    ):
        ref = template_ref(registry.get(template_id, "1.0.0", "ws"))
        draft = draft_for(f"quality-{index}", kind, kind_spec, ref)
        result = KindRuntime(ContentAddressedStore(tmp_path / str(index))).execute(
            request(draft, content, inputs=inputs, tools=tools)
        )
        assert result.status == "succeeded"
        assert result.evidence_ref is not None
        assert result.trace_ref is not None
        assert result.skill_view_revision is not None
