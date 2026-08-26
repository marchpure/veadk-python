"""Seed a real, isolated STEP3B acceptance workspace.

This command writes domain objects through the same SQLite repositories used by
the BFF.  It is intentionally separate from the WebUI: no browser fixtures,
localStorage state, or hard-coded React read model is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.server.knowledge_assets.contract_base import (
    AnalysisKindSpec,
    CompatibilityTargets,
    GraphOntologyKindSpec,
    KnowledgeKindSpec,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    SemanticKindSpec,
    SkillContract,
    SkillDependencies,
    SkillManifest,
    SkillMetadata,
    SkillOperation,
    SkillSpec,
    SopInputField,
    SopKindSpec,
    SopOutputField,
    SopStep,
    StorageRef,
    TemplateRef,
)
from frontend.server.knowledge_assets.contract_data import SkillDraft, SkillResult
from frontend.server.knowledge_assets.contract_views import (
    DashboardChart,
    DashboardKpi,
    DashboardViewModel,
    GraphEdge,
    GraphNode,
    GraphOntologyViewModel,
    KnowledgeCitation,
    KnowledgeViewModel,
    Invocation,
    MonitoringViewModel,
    PolicyGateResult,
    PublishedSkillVersion,
    SemanticViewField,
    SemanticViewModel,
    SkillViewManifest,
    SkillViewRevision,
    SopStepResult,
    SopViewModel,
    EvaluationCaseResult,
    EvaluationRun,
    ViewIntent,
)
from frontend.server.knowledge_assets.repository.sqlite import (
    SqliteKnowledgeAssetRepository,
)
from frontend.server.knowledge_assets.trusted_renderers import render_trusted_html
from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def ref(uri: str, *, kind: str = "inline", payload: str = "") -> StorageRef:
    return StorageRef(
        uri=uri,
        kind=kind,
        sha256=digest(payload or uri),
        media_type="application/json",
        bytes=len(payload.encode()) if payload else 1,
    )


def manifest(
    *,
    draft_id: str,
    workspace: str,
    name: str,
    kind: str,
    golden_id: str,
    template: str,
) -> SkillManifest:
    schema = SchemaRef(
        uri=f"schema://acceptance/{draft_id}",
        version="1",
        sha256=digest(draft_id),
    )
    policy = PermissionRef(uri=f"permission://workspace/{workspace}", version="1")
    contract = SkillContract(
        input_schema_ref=schema,
        output_schema_ref=schema,
        operations=[
            SkillOperation(
                name="execute",
                description="Read-only acceptance operation",
                input_schema_ref=schema,
                output_schema_ref=schema,
            )
        ],
    )
    if kind == "analysis":
        kind_spec = AnalysisKindSpec(
            question=f"Acceptance analysis for {name}",
            query_plan_ref=f"query-plan://acceptance/{draft_id}",
        )
    elif kind == "semantic":
        kind_spec = SemanticKindSpec(metric_refs=["value"], dimension_refs=["label"])
    elif kind == "knowledge":
        kind_spec = KnowledgeKindSpec(source_revision_refs=[golden_id])
    elif kind == "graph_ontology":
        kind_spec = GraphOntologyKindSpec(
            entity_schema_ref=schema,
            relationship_schema_ref=schema,
        )
    elif kind == "sop":
        kind_spec = SopKindSpec(
            trigger="业务请求进入",
            scope="验收工作区",
            input_fields=[
                SopInputField(
                    name="request",
                    label="业务请求",
                    value_type="string",
                )
            ],
            steps=[
                SopStep(
                    id="step_1",
                    title="读取业务上下文",
                    instruction="读取已授权的工作区数据。",
                ),
                SopStep(
                    id="step_2",
                    title="输出处理建议",
                    instruction="输出可追溯的处理建议。",
                ),
            ],
            outputs=[
                SopOutputField(
                    name="recommendation",
                    description="处理建议",
                    value_type="string",
                )
            ],
            failure_handling="缺少输入时请求补充",
            action_proposal="仅建议，不执行外部写入",
        )
    else:
        kind = "monitoring"
        kind_spec = __import__(
            "frontend.server.knowledge_assets.contract_base",
            fromlist=["MonitoringKindSpec"],
        ).MonitoringKindSpec(
            metric_refs=["value"],
            refresh_schedule_ref="schedule://acceptance/manual",
            alert_policy_ref="policy://acceptance",
        )
    return SkillManifest(
        metadata=SkillMetadata(
            id=draft_id,
            version="1.0.0",
            display_name=name,
            description=f"真实验收对象：{name}",
            owner=OwnerRef(workspace_id=workspace, principal_id=workspace),
        ),
        spec=SkillSpec(
            kind=kind,
            contract=contract,
            dependencies=SkillDependencies(golden_assets=[golden_id]),
            policy_ref=policy,
            runtime_ref=f"runtime://{kind}/v1",
            compatibility=CompatibilityTargets(targets=["agentkit"]),
            template_ref=TemplateRef(
                template_id="graph-ontology" if template == "graph_ontology" else template,
                version="1.0.0",
                digest=digest(template),
            ),
            default_renderer=template,
            kind_spec=kind_spec,
        ),
    )


def view_for(
    *, draft: SkillDraft, golden_id: str, template: str, index: int
) -> SkillViewRevision:
    schema = SchemaRef(
        uri=f"schema://view/{draft.id}",
        version="1",
        sha256=digest(f"view:{draft.id}"),
    )
    data = ref(f"local://acceptance/{golden_id}", kind="table")
    if template == "dashboard":
        model = DashboardViewModel(
            title=draft.name,
            kpis=[
                DashboardKpi(
                    key="value",
                    label="业务值",
                    value=128 + index,
                    trend="up",
                )
            ],
            charts=[
                DashboardChart(
                    chart_id=f"chart-{index}",
                    title="业务趋势",
                    x_field="label",
                    y_field="value",
                    series=[{"name": "value", "points": [("一", 80.0), ("二", 128.0)]}],
                )
            ],
            data_ref=data,
        )
        purpose = "overview"
    elif template == "semantic":
        model = SemanticViewModel(
            schema_ref=schema,
            entities=["业务记录"],
            fields=[
                SemanticViewField(
                    name="label",
                    role="dimension",
                    source_field="label",
                ),
                SemanticViewField(
                    name="value",
                    role="measure",
                    aggregation="sum",
                    source_field="value",
                ),
            ],
            mdl="entity 业务记录 { dimension label; measure value; }",
            data_ref=data,
        )
        purpose = "schema"
    elif template == "sop":
        model = SopViewModel(
            title=draft.name,
            trigger="蓝牙设备业务请求",
            scope="验收工作区",
            step_results=[
                SopStepResult(
                    step_id="step_1", title="读取业务上下文", status="succeeded"
                ),
                SopStepResult(
                    step_id="step_2", title="输出处理建议", status="succeeded"
                ),
            ],
            recommendation="根据真实上下文给出处理建议。",
            outputs={"sourceRevision": golden_id},
        )
        purpose = "explore"
    elif template == "monitoring":
        model = MonitoringViewModel(
            metric_refs=["value"],
            values=[("value", 128.0)],
            call_volume=3,
            success_rate=1.0,
            latency_ms=42,
            status="healthy",
        )
        purpose = "monitor"
    elif template == "graph_ontology":
        model = GraphOntologyViewModel(
            nodes=[GraphNode(id="device", label="设备", entity_type="Device")],
            edges=[],
            evidence_locators=[golden_id],
        )
        purpose = "explore"
    elif template == "knowledge":
        model = KnowledgeViewModel(
            answer=f"基于真实验收数据，为「{draft.name}」生成可追溯回答。",
            citations=[
                KnowledgeCitation(
                    citation_id=f"citation-{index}",
                    source_revision_id=golden_id,
                    title="验收数据集",
                    locator="acceptance.csv:1-3",
                )
            ],
        )
        purpose = "answer"
    else:
        raise ValueError(template)
    revision_id = f"view-{draft.id}-{index}"
    skill_revision_id = f"{draft.id}:{draft.revision}"
    return SkillViewRevision(
        id=revision_id,
        skill_revision_id=skill_revision_id,
        revision=draft.revision,
        manifest=SkillViewManifest(
            id=f"manifest-{revision_id}",
            skill_revision_id=skill_revision_id,
            renderer_ref=f"renderer://{template}/v1",
            view_model_schema_ref=schema,
            allowed_components=["SkillViewShell", f"{template}View"],
        ),
        intent=ViewIntent(
            id=f"intent-{revision_id}",
            skill_id=draft.id,
            skill_revision=draft.revision,
            template=template,
            purpose=purpose,
            result_ref=f"local://result/{draft.id}",
        ),
        view_model=model,
        data_revision_refs=[golden_id],
        trace_id=f"trace-{draft.id}",
        created_at="2026-08-26T00:00:00Z",
    )


def materialize_html(
    *,
    view: SkillViewRevision,
    workspace: str,
    artifact_root: Path,
) -> SkillViewRevision:
    html_bytes = render_trusted_html(
        view.intent.template,
        view.view_model,
        data_revision_refs=view.data_revision_refs,
    )
    html_digest = hashlib.sha256(html_bytes).hexdigest()
    views_root = artifact_root / "kind-runtime" / "views"
    views_root.mkdir(parents=True, exist_ok=True)
    (views_root / f"{html_digest}.html").write_bytes(html_bytes)
    return view.model_copy(
        update={
            "result_ref": StorageRef(
                uri=(
                    f"/api/knowledge-assets/v1/workspaces/{workspace}"
                    f"/skill-view-revisions/{view.id}/artifacts/{html_digest}"
                    f"?workspace={quote(workspace)}"
                ),
                kind="object",
                sha256=html_digest,
                media_type="text/html",
                bytes=len(html_bytes),
            ),
            "html_digest": html_digest,
            "etag": html_digest[:32],
        }
    )


def seed(database: Path, source_root: Path, workspace: str, filled: bool) -> dict[str, object]:
    database.parent.mkdir(parents=True, exist_ok=True)
    # `create_app()` derives its Source/Golden runtime from the repository
    # database parent.  Keep the seed and the BFF on the same durable store;
    # accepting an arbitrary sibling directory here silently produced a
    # workspace whose drafts existed but whose Golden assets were invisible to
    # bootstrap.
    runtime_source_root = database.parent / "sources-golden"
    runtime_source_root.mkdir(parents=True, exist_ok=True)
    if not filled:
        return {"workspace": workspace, "resources": 0, "publications": 0}
    repository = SqliteKnowledgeAssetRepository(database)
    source = SourceGoldenApplication(
        database_path=runtime_source_root / "sources-golden.sqlite3",
        artifact_root=runtime_source_root / "artifacts",
        source_root=runtime_source_root / "sources",
    )
    context = AccessContext(workspace_id=workspace, principal_id=workspace, role="editor")
    golden_ids: list[str] = []
    golden_names = [
        "全球金融实时行情 API",
        "PostgreSQL_ERP",
        "库存明细.csv",
        "销售话术知识库",
        "销售业务知识图谱",
    ]
    source_names = [
        "全球金融实时行情 API.csv",
        "PostgreSQL_ERP.csv",
        "库存明细.csv",
        "销售话术知识库.csv",
        "销售业务知识图谱.csv",
    ]
    for index in range(5):
        filename = source_names[index]
        (runtime_source_root / "sources" / filename).parent.mkdir(
            parents=True, exist_ok=True
        )
        (runtime_source_root / "sources" / filename).write_text(
            "label,value\nA,80\nB,128\n", encoding="utf-8"
        )
        created = source.create_connection(
            context,
            connector_key="csv",
            display_name=golden_names[index],
            scope="personal",
            configuration={"sourceRef": filename},
            secret_ref=None,
            idempotency_key=f"acceptance-connection-{index}",
            trace_id=f"acceptance-connection-trace-{index}",
        )
        ingested = source.ingest(
            context,
            connection_id=created.connection.id,
            resource_id=created.connection.discovered_resources[0].id,
            recipe_operations=["trim"],
            idempotency_key=f"acceptance-ingest-{index}",
            trace_id=f"acceptance-ingest-trace-{index}",
        )
        record = ingested.golden_asset_revision
        golden_ids.append(record.id)
        repository.save_golden_asset_revision(
            __import__(
                "frontend.server.knowledge_assets.runtime",
                fromlist=["_canonical_golden"],
            )._canonical_golden(record)
        )
    templates = ["sop", "dashboard", "semantic", "sop", "monitoring", "knowledge", "graph_ontology"]
    drafts: list[SkillDraft] = []
    draft_names = [
        "金融行情监控 Skill",
        "蓝牙断连排查 SOP",
        "区域异常经营分析",
        "门店卫生巡检与处置 SOP",
        "华东销售经营看板",
        "金融行情监控看板",
        "全球招聘供需看板",
        "渠道转化趋势",
        "销售主题模型",
        "销售话术知识库",
        "华东销售看板",
    ]
    for index in range(11):
        draft_id = f"acceptance-draft-{index + 1}"
        template = templates[index % len(templates)]
        kind = "analysis" if template == "dashboard" else template
        draft = repository.create_skill_draft(
            workspace_id=workspace,
            name=draft_names[index],
            description="来自真实 BFF acceptance seed 的持久化草稿。",
            source_refs=[golden_ids[index % len(golden_ids)]],
            request_id=f"acceptance-draft-request-{index}",
            idempotency_key=f"acceptance-draft-{index}",
        )[0]
        hydrated = draft.model_copy(
            update={
                "name": draft.name,
                "manifest": manifest(
                    draft_id=draft.id,
                    workspace=workspace,
                    name=draft.name,
                    kind=kind,
                    golden_id=golden_ids[index % len(golden_ids)],
                    template=template,
                ),
            }
        )
        repository.sync_authoring_draft(draft=hydrated, status="ready_for_evaluation")
        drafts.append(hydrated)
        result = SkillResult(
            id=f"result-{draft.id}",
            skill_id=draft.id,
            skill_revision=1,
            kind=kind,
            output_schema_ref=hydrated.manifest.spec.contract.output_schema_ref,
            result_ref=ref(f"local://result/{draft.id}"),
            golden_asset_revision_refs=[golden_ids[index % len(golden_ids)]],
            trace_id=f"trace-{draft.id}",
        )
        if repository.latest_skill_result(draft.id, 1) is None:
            repository.save_skill_result(result)
        if repository.latest_skill_view_revision(f"{draft.id}:1") is None:
            repository.save_skill_view_revision(
                materialize_html(
                    view=view_for(
                        draft=hydrated,
                        golden_id=golden_ids[index % len(golden_ids)],
                        template=template,
                        index=index,
                    ),
                    workspace=workspace,
                    artifact_root=runtime_source_root,
                )
            )
    published_draft = drafts[0]
    view = repository.skill_view_revision_for_template(
        f"{published_draft.id}:1", "sop"
    )
    monitoring_view = materialize_html(
        view=view_for(
            draft=published_draft,
            golden_id=golden_ids[0],
            template="monitoring",
            index=99,
        ),
        workspace=workspace,
        artifact_root=runtime_source_root,
    )
    repository.save_skill_view_revision(monitoring_view)
    evaluation = EvaluationRun(
        id=f"evaluation-{published_draft.id}",
        suite_id=f"suite-{published_draft.id}",
        suite_version=1,
        skill_revision_id=f"{published_draft.id}:1",
        status="succeeded",
        score=1.0,
        case_results=[EvaluationCaseResult(case_id="case-1", status="passed", score=1.0)],
        started_at="2026-08-26T00:00:00Z",
        finished_at="2026-08-26T00:00:01Z",
    )
    repository.save_evaluation_run(evaluation)
    gate = PolicyGateResult(
        id=f"gate-{evaluation.id}",
        skill_revision_id=evaluation.skill_revision_id,
        evaluation_run_id=evaluation.id,
        decision="publishable",
        machine_reasons=["ACCEPTANCE_SEED_REAL_OBJECTS"],
        checked_at="2026-08-26T00:00:02Z",
    )
    repository.save_policy_gate_result(gate)
    if view is not None:
        published = PublishedSkillVersion(
            id=f"published://{published_draft.id}:1.0.0",
            skill_id=published_draft.id,
            semver="1.0.0",
            manifest=published_draft.manifest,
            skill_revision_id=published_draft.id + ":1",
            digest=digest(monitoring_view.id),
            evaluation_run_id=evaluation.id,
            policy_gate_result_id=gate.id,
            skill_view_ref=monitoring_view.id,
            published_at="2026-08-26T00:00:03Z",
        )
        repository.save_published_skill_version(published)
        repository.save_invocation(
            Invocation(
                id=f"invocation-{published.id}",
                skill_version_id=published.id,
                skill_view_revision_id=monitoring_view.id,
                caller_id=workspace,
                workspace_id=workspace,
                status="succeeded",
                input_ref=ref(f"local://input/{published.id}"),
                result_ref=ref(f"local://result/{published.id}"),
                trace_id=f"trace-{published.id}",
                actual_data_revision_refs=[golden_ids[0]],
                started_at="2026-08-26T00:00:04Z",
                finished_at="2026-08-26T00:00:05Z",
            )
        )
    repository.record_audit(
        request_id="acceptance-conversation",
        operation_id="acceptance-conversation",
        workspace_id=workspace,
        action="agent.conversation",
        resource_id=published_draft.id,
        outcome="succeeded",
        details={"source": "real acceptance seed", "turns": "3"},
    )
    return {
        "workspace": workspace,
        "resources": len(repository.bootstrap(workspace, "editor").resources),
        "publications": len(repository.bootstrap(workspace, "editor").publications),
        "golden": golden_ids,
        "drafts": [draft.id for draft in drafts],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--workspace", default="acceptance-workspace")
    parser.add_argument("--empty", action="store_true")
    args = parser.parse_args()
    print(seed(args.database, args.source_root, args.workspace, not args.empty))


if __name__ == "__main__":
    main()
