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
    ViewCell,
    ViewField,
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
    SopStepEvidence,
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
        if "安踏" in draft.name:
            kpis = [
                DashboardKpi(key="sales", label="总销售额", value="¥ 12,450,000", unit="", trend="up"),
                DashboardKpi(key="profit", label="总利润", value="¥ 3,210,000", unit="", trend="up"),
                DashboardKpi(key="orders", label="订单数量", value="45,678", unit="", trend="down"),
                DashboardKpi(key="aov", label="客单价", value="¥ 272", unit="", trend="up"),
            ]
            points = [
                ("周一", 8200.0), ("周二", 9100.0), ("周三", 8700.0),
                ("周四", 10100.0), ("周五", 11200.0), ("周六", 12400.0),
                ("周日", 11800.0),
            ]
            fields = [
                ViewField(name="week", label="周次", data_type="string"),
                ViewField(name="sales", label="销售额", data_type="number"),
                ViewField(name="profit", label="利润", data_type="number"),
            ]
            rows = [
                [ViewCell(field="week", value=label), ViewCell(field="sales", value=value), ViewCell(field="profit", value=round(value * .258, 2))]
                for label, value in points
            ]
        else:
            kpis = [
                DashboardKpi(key="value", label="业务值", value=128 + index, trend="up")
            ]
            points = [("一", 80.0), ("二", 128.0)]
            fields = []
            rows = []
        model = DashboardViewModel(
            title=draft.name,
            fields=fields,
            kpis=kpis,
            charts=[
                DashboardChart(
                    chart_id=f"chart-{index}",
                    title="按周销售与利润趋势" if "安踏" in draft.name else "业务趋势",
                    x_field="label",
                    y_field="value",
                    series=[{"name": "销售额" if "安踏" in draft.name else "value", "points": points}],
                )
            ],
            rows=rows,
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
        if "蓝牙" in draft.name:
            trigger = "当用户或 Agent 反馈车机蓝牙无法连接、频繁断开，且对应车型为 LS6/LS7 时"
            step_data = [
                ("读取车机软件与固件版本", "成功", "GET /vehicle/info (Params: vin)", "软件版本 OS-2.1.0，蓝牙固件 V1.2.4。"),
                ("检查蓝牙信号稳定性", "异常命中", "signal-strength API", "近 2 小时内探测到 5 次信号突降至 -92dBm，判定为硬件衰减异常。"),
                ("匹配历史相似工单与手册", "检索成功", "Vector Search / DB Query", "命中 12 条相同批次工单，建议更换蓝牙天线模块。"),
            ]
            recommendation = "综合判定该车辆蓝牙断连原因为天线硬件衰减，非软件缺陷。建议引导用户前往服务中心并升级 L2 技术支持。"
        elif "海底捞" in draft.name:
            trigger = "当门店反馈卫生隐患或例行检查时"
            step_data = [
                ("匹配最新门店卫生规范", "成功", "RAG / 门店卫生标准规范_V2.pdf", "匹配到《后厨卫生要求》第 4 章：地面不得有积水与油污。"),
                ("识别当前卫生巡检异常", "异常命中", "photo inspection", "洗碗区有明显积水，判定为违规。"),
                ("结合历史处置经验生成整改建议", "检索成功", "DB Query: 历史巡检不合格记录", "类似案例多因下水道阻塞，建议增加清理排查环节。"),
            ]
            recommendation = "综合判定该门店当前巡检结果为不合格（存在积水隐患），建议立即清理并在 1 小时内复检。"
        else:
            trigger = "业务请求进入"
            step_data = [
                ("读取业务上下文", "成功", "workspace context", "读取已授权的工作区数据。"),
                ("输出处理建议", "成功", "skill runtime", "输出可追溯的处理建议。"),
            ]
            recommendation = "根据真实上下文给出处理建议。"
        model = SopViewModel(
            title=draft.name,
            trigger=trigger,
            scope="验收工作区",
            step_results=[
                SopStepResult(
                    step_id=f"step_{step_index + 1}",
                    title=title,
                    status="succeeded",
                    message=message,
                    tool_refs=[tool],
                    evidence=[
                        SopStepEvidence(
                            kind="tool_result",
                            locator=f"local://acceptance/{golden_id}/{step_index + 1}",
                            summary=detail,
                        )
                    ],
                    # The result state is a real acceptance run, so keep its
                    # input visible in the same server-projected context card
                    # as the product journey.  The value is derived from the
                    # persisted Golden revision, never copied from prototype
                    # business data.
                    input_summary=(
                        f"验收案例：蓝牙异常排查 · 数据修订 {golden_id}"
                        if step_index == 0 and "蓝牙" in draft.name
                        else ""
                    ),
                )
                for step_index, (title, message, tool, detail) in enumerate(step_data)
            ],
            recommendation=recommendation,
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
    # Keep the acceptance journeys backed by the same durable objects that
    # the visual matrix names.  The browser still receives only the generated
    # resource ids; these labels are seed metadata used to select those
    # resources from bootstrap, never URL identifiers or UI business truth.
    templates = [
        "sop",             # bluetooth-sop-*
        "dashboard",       # anta-dashboard-*
        "semantic",
        "sop",             # haidilao-sop-*
        "monitoring",
        "knowledge",
        "graph_ontology",
        "sop",             # optimization-draft
        "dashboard",
        "semantic",
        "sop",
    ]
    drafts: list[SkillDraft] = []
    draft_names = [
        "蓝牙断连排查 SOP",
        "安踏经营 Dashboard",
        "区域异常经营分析",
        "海底捞卫生巡检 SOP",
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
