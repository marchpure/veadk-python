from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.knowledge_step3_w3_dashboard_evidence import generate_evidence

from frontend.server.knowledge_assets.contracts import (
    GoldenAssetRevision,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    SkillManifest,
    StorageRef,
)
from frontend.server.knowledge_assets.kind_runtime.dashboard_artifacts import (
    DashboardArtifactRequest,
    DashboardBuildPlan,
    DashboardChartPlan,
    DashboardInsightPlan,
    DashboardKpiPlan,
    DashboardTablePlan,
    capture_dashboard_screenshot,
    generate_dashboard_artifact,
)


NOW = "2026-08-25T00:00:00+08:00"
ZERO = "0" * 64


def _schema(name: str) -> SchemaRef:
    return SchemaRef(uri=f"local://schema/{name}", version="1", sha256=ZERO)


def _manifest() -> SkillManifest:
    return SkillManifest.model_validate(
        {
            "apiVersion": "knowledge.veadk.io/v1alpha1",
            "kind": "Skill",
            "metadata": {
                "id": "infra-dashboard-skill",
                "version": "1.0.0",
                "displayName": "基础设施容量健康看板",
                "description": "按服务查看基础设施健康风险",
                "owner": {"workspaceId": "ws", "principalId": "tester"},
            },
            "spec": {
                "kind": "analysis",
                "contract": {
                    "inputSchemaRef": _schema("input").model_dump(
                        mode="json", by_alias=True
                    ),
                    "outputSchemaRef": _schema("output").model_dump(
                        mode="json", by_alias=True
                    ),
                },
                "dependencies": {"goldenAssets": ["golden-infra"]},
                "policyRef": {"uri": "permission://workspace/ws/read", "version": "1"},
                "runtimeRef": "runtime://analysis/worker3",
                "kindSpec": {
                    "kind": "analysis",
                    "question": "按服务查看基础设施健康风险",
                    "queryPlanRef": "query-plan://readonly/open_tickets/service",
                },
            },
        }
    )


def _golden(
    content: str, *, permission: str = "permission://workspace/ws/read"
) -> GoldenAssetRevision:
    import hashlib

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return GoldenAssetRevision(
        id="golden-infra",
        asset_kind="dataset",
        revision=7,
        schema_ref=_schema("infra"),
        storage_ref=StorageRef(
            uri=f"local://golden/{digest}",
            kind="object",
            sha256=digest,
            media_type="text/csv",
            bytes=len(content.encode("utf-8")),
        ),
        source_revision_refs=["source-mcp-infra"],
        owner=OwnerRef(workspace_id="ws", principal_id="tester"),
        permissions_ref=PermissionRef(uri=permission, version="1"),
        lineage_digest=hashlib.sha256(
            f"source-mcp-infra:{digest}".encode()
        ).hexdigest(),
        freshness_at="2026-08-25T08:00:00+08:00",
        last_good=True,
    )


def _plan() -> DashboardBuildPlan:
    return DashboardBuildPlan(
        build_plan_id="w2-build-plan-infra-capacity",
        user_goal="帮我看基础设施服务工单积压与响应风险",
        title="基础设施服务工单健康看板",
        required_golden_revision_id="golden-infra",
        data_query_ref="mcp://local-infra/tools/list_service_health",
        invocation_ref="invocation://w2/session/trace-1/tool-call-1",
        kpis=[
            DashboardKpiPlan(
                key="open_tickets",
                label="待处理工单",
                field="open_tickets",
                aggregation="sum",
                unit="tickets",
            ),
            DashboardKpiPlan(
                key="avg_response_hours",
                label="平均响应时长",
                field="response_hours",
                aggregation="avg",
                unit="hours",
            ),
        ],
        chart=DashboardChartPlan(
            title="各服务待处理工单",
            x_field="service",
            y_field="open_tickets",
            aggregation="sum",
            chart_type="bar",
        ),
        table=DashboardTablePlan(
            fields=["service", "owner_team", "open_tickets", "response_hours"],
            max_rows=20,
        ),
        insights=[
            DashboardInsightPlan(
                template="{top_dimension} 当前积压最高，为 {top_value:g} tickets。"
            ),
            DashboardInsightPlan(
                template="共覆盖 {row_count} 条基础设施服务记录，目标：{user_goal}"
            ),
        ],
        layout=["kpis", "chart", "table", "insights"],
    )


def _request(
    content: str, tmp_path: Path, *, permission: str = "permission://workspace/ws/read"
) -> DashboardArtifactRequest:
    return DashboardArtifactRequest(
        build_plan=_plan(),
        skill_manifest=_manifest(),
        golden_asset_revision=_golden(content, permission=permission),
        golden_asset_content=content,
        workspace_root=str(tmp_path / "dashboard-workspaces"),
        workspace_id="ws",
        caller_id="tester",
        now=NOW,
    )


def test_dashboard_artifact_workspaces_are_independent_built_and_data_driven(
    tmp_path: Path,
) -> None:
    first_data = (
        "service,owner_team,open_tickets,response_hours\n"
        "gateway,platform,8,1.5\n"
        "scheduler,infra,4,3.0\n"
    )
    second_data = (
        "service,owner_team,open_tickets,response_hours\n"
        "gateway,platform,2,0.8\n"
        "scheduler,infra,12,5.5\n"
    )

    first = generate_dashboard_artifact(_request(first_data, tmp_path))
    second = generate_dashboard_artifact(_request(second_data, tmp_path))

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.workspace_path != second.workspace_path
    assert first.html_ref.sha256 != second.html_ref.sha256
    assert first.kpis[0].value == 12
    assert second.kpis[0].value == 14
    assert first.chart.points == [("gateway", 8.0), ("scheduler", 4.0)]
    assert second.chart.points == [("gateway", 2.0), ("scheduler", 12.0)]
    assert first.table_rows != second.table_rows
    assert first.publish_ready.main_publish_action == "MAIN_PUBLISH_CHAIN_REQUIRED"
    assert second.publish_ready.main_publish_action == "MAIN_PUBLISH_CHAIN_REQUIRED"

    for result in (first, second):
        workspace = Path(result.workspace_path)
        assert (workspace / "skill-manifest.json").is_file()
        assert (workspace / "build-plan.json").is_file()
        assert (workspace / "data" / "golden.json").is_file()
        assert (workspace / "src" / "index.html").is_file()
        assert (workspace / "src" / "styles.css").is_file()
        assert (workspace / "src" / "dashboard.js").is_file()
        assert (workspace / "src" / "build.mjs").is_file()
        assert (workspace / "src" / "serve.mjs").is_file()
        assert (workspace / "src" / "chart-config.json").is_file()
        assert (workspace / "dist" / "index.html").is_file()
        assert (workspace / "dist" / "styles.css").is_file()
        assert (workspace / "dist" / "dashboard.js").is_file()
        assert (workspace / "dist" / "dashboard-data.json").is_file()
        assert (workspace / "package-lock.json").is_file()
        assert (workspace / "artifact-manifest.json").is_file()
        assert (workspace / "revision.json").is_file()
        assert (workspace / "lineage.json").is_file()
        assert (workspace / "build.json").is_file()
        assert (workspace / "publish-ready-artifact.json").is_file()
        assert result.build_command[:3] == ["npm", "run", "build"]
        assert result.serve_command[:3] == ["npm", "run", "serve"]
        assert result.page_url.startswith("file://")
        data = json.loads((workspace / "dist" / "dashboard-data.json").read_text())
        assert data["title"] == "基础设施服务工单健康看板"
        assert data["layout"] == ["kpis", "chart", "table", "insights"]
        html = (workspace / "dist" / "index.html").read_text(encoding="utf-8")
        js = (workspace / "dist" / "dashboard.js").read_text(encoding="utf-8")
        assert "<pre" not in html.lower()
        assert "mockKpis" not in html
        assert "mockTrendData" not in html
        assert "mockKpis" not in js
        assert "mockTrendData" not in js
        assert "sales" not in html.lower()
        assert "基础设施服务工单健康看板" in html
        assert "待处理工单" in html
        assert "各服务待处理工单" in html
        assert "数据来源" in js
        assert "lineage" in html
        artifact_manifest = json.loads(
            (workspace / "artifact-manifest.json").read_text(encoding="utf-8")
        )
        assert artifact_manifest["schemaVersion"] == (
            "knowledge-assets.worker3.dashboard-artifact.v1"
        )
        assert artifact_manifest["designSystemVersion"] == "v2.13.1"
        assert artifact_manifest["inputs"]["w2BuildPlanId"] == (
            "w2-build-plan-infra-capacity"
        )
        assert artifact_manifest["inputs"]["w1GoldenAssetRevisionId"] == "golden-infra"
        assert artifact_manifest["dependencies"]["runtime"] == "node"
        assert artifact_manifest["dependencies"]["npm"] == "package-lock.json"
        assert "artifact-manifest.json" in artifact_manifest["configFiles"]
        assert artifact_manifest["forbiddenPatterns"] == {
            "mockData": False,
            "fixedSalesContent": False,
            "jsonPreReplacementPage": False,
            "staticScreenshot": False,
            "selfPublishingRuntime": False,
        }
        rerun = subprocess.run(
            result.build_command,
            cwd=Path(__file__).parents[3],
            capture_output=True,
            text=True,
            check=False,
        )
        assert rerun.returncode == 0, rerun.stderr


def test_dashboard_artifact_creates_new_workspace_for_each_generation(
    tmp_path: Path,
) -> None:
    data = (
        "service,owner_team,open_tickets,response_hours\n"
        "gateway,platform,8,1.5\n"
        "scheduler,infra,4,3.0\n"
    )
    request = _request(data, tmp_path)

    first = generate_dashboard_artifact(request)
    second = generate_dashboard_artifact(request)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.workspace_path != second.workspace_path
    assert Path(first.workspace_path).name.startswith(request.artifact_id)
    assert Path(second.workspace_path).name.startswith(request.artifact_id)
    assert Path(first.workspace_path).is_dir()
    assert Path(second.workspace_path).is_dir()
    assert first.html_ref.sha256 == second.html_ref.sha256


def test_dashboard_artifact_uses_build_plan_copy_for_visible_content(
    tmp_path: Path,
) -> None:
    content = "region,latency_ms,error_budget_burn\nap-south,181,1.7\neu-west,94,0.6\n"
    request = _request(content, tmp_path).model_copy(
        update={
            "artifact_id": "latency-dashboard",
            "build_plan": DashboardBuildPlan(
                build_plan_id="w2-build-plan-latency",
                user_goal="按地域排查端到端延迟和错误预算风险",
                title="全球链路延迟健康看板",
                required_golden_revision_id="golden-infra",
                data_query_ref="w2://build-plan/latency/data@golden-infra",
                invocation_ref="trace://w2/latency",
                kpis=[
                    DashboardKpiPlan(
                        key="latency_ms",
                        label="平均延迟",
                        field="latency_ms",
                        aggregation="avg",
                        unit="ms",
                    ),
                ],
                chart=DashboardChartPlan(
                    title="按地域拆解延迟",
                    x_field="region",
                    y_field="latency_ms",
                    aggregation="avg",
                    chart_type="bar",
                ),
                table=DashboardTablePlan(
                    fields=["region", "latency_ms", "error_budget_burn"],
                    max_rows=20,
                ),
                insights=[
                    DashboardInsightPlan(
                        template="{top_dimension} 延迟最高，为 {top_value:g} ms。"
                    )
                ],
                layout=["kpis", "chart", "table", "insights"],
            ),
        },
        deep=True,
    )

    result = generate_dashboard_artifact(request)

    assert result.status == "succeeded"
    assert result.kpis[0].key == "latency_ms"
    assert result.kpis[0].label == "平均延迟"
    assert result.chart.name == "latency_ms"
    assert result.chart.points == [("ap-south", 181.0), ("eu-west", 94.0)]
    assert result.table_rows == [
        {"region": "ap-south", "latency_ms": 181, "error_budget_burn": 1.7},
        {"region": "eu-west", "latency_ms": 94, "error_budget_burn": 0.6},
    ]
    assert result.insights == ["ap-south 延迟最高，为 181 ms。"]
    html = Path(result.index_html_path).read_text(encoding="utf-8")
    assert "全球链路延迟健康看板" in html
    assert "按地域拆解延迟" in html
    assert "ap-south 延迟最高" in html
    assert "基础设施服务工单健康看板" not in html


def test_dashboard_artifact_renders_loading_empty_error_permission_and_refresh_states(
    tmp_path: Path,
) -> None:
    result = generate_dashboard_artifact(
        _request(
            "service,owner_team,open_tickets,response_hours\ngateway,platform,8,1.5\n",
            tmp_path,
        )
    )
    html = Path(result.index_html_path).read_text(encoding="utf-8")
    js = (Path(result.workspace_path) / "dist" / "dashboard.js").read_text(
        encoding="utf-8"
    )

    for state in ("loading", "empty", "error", "permission_denied", "refreshing"):
        assert 'data-state-template="${name}"' in js
        assert state in html

    empty = generate_dashboard_artifact(
        _request(
            "service,owner_team,open_tickets,response_hours\n",
            tmp_path,
        )
    )
    assert empty.status == "empty"
    assert "暂无可展示数据" in Path(empty.index_html_path).read_text(encoding="utf-8")

    denied = generate_dashboard_artifact(
        _request(
            "service,owner_team,open_tickets,response_hours\ngateway,platform,8,1.5\n",
            tmp_path,
            permission="permission://workspace/ws/deny",
        )
    )
    assert denied.status == "permission_denied"
    assert "权限不足" in Path(denied.index_html_path).read_text(encoding="utf-8")


def test_dashboard_artifact_rejects_mismatched_revision_and_missing_fields(
    tmp_path: Path,
) -> None:
    request = _request(
        "service,owner_team,open_tickets,response_hours\ngateway,platform,8,1.5\n",
        tmp_path,
    )
    request.build_plan.required_golden_revision_id = "different-golden"

    mismatch = generate_dashboard_artifact(request)

    assert mismatch.status == "error"
    assert "Golden revision mismatch" in mismatch.message

    missing = _request(
        "service,owner_team,response_hours\ngateway,platform,1.5\n",
        tmp_path,
    )
    missing = missing.model_copy(
        update={"artifact_id": "missing-fields"},
        deep=True,
    )

    failed = generate_dashboard_artifact(missing)

    assert failed.status == "error"
    assert "open_tickets" in failed.message


def test_dashboard_visual_regression_screenshot_smoke(tmp_path: Path) -> None:
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    assert chrome.exists(), "Chrome executable is required for W3 visual regression"
    result = generate_dashboard_artifact(
        _request(
            "service,owner_team,open_tickets,response_hours\n"
            "gateway,platform,8,1.5\n"
            "scheduler,infra,4,3.0\n",
            tmp_path,
        )
    )

    screenshot = capture_dashboard_screenshot(
        result,
        output_path=tmp_path / "visual" / "dashboard.png",
        executable_path=str(chrome),
    )

    assert screenshot.status == "succeeded"
    assert screenshot.screenshot_ref is not None
    assert Path(screenshot.screenshot_path).is_file()
    assert screenshot.viewport == "1440x960"
    assert screenshot.image_width == 1440
    assert screenshot.image_height == 960
    assert screenshot.title == "基础设施服务工单健康看板"
    assert screenshot.browser_executable == str(chrome)
    assert screenshot.browser_version
    assert "Google Chrome" in screenshot.browser_version
    assert screenshot.visual_baseline == "v2.13.1"
    assert screenshot.visual_checks == [
        "dashboard root rendered",
        "hero/content/table regions rendered",
        "no horizontal overflow",
        "panel radius and 1px border align with v2.13.1",
        "title typography aligns with v2.13.1",
        "refresh control size aligns with v2.13.1",
    ]
    assert screenshot.interaction_checked is True
    assert screenshot.page_url.startswith("http://127.0.0.1:")


def test_w3_dashboard_evidence_script_generates_repeatable_acceptance_summary(
    tmp_path: Path,
) -> None:
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    assert chrome.exists(), "Chrome executable is required for W3 visual regression"
    w2_smoke_success = tmp_path / "w2_real_smoke_success.json"
    w2_golden_data = tmp_path / "w2_infrastructure_metrics.json"
    w2_smoke_success.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "trace_id": "trace_w2_fixture",
                "source": {
                    "request": "Compare infrastructure utilization by service over time."
                },
                "build_plan": {
                    "plan_id": "plan_req_fixture",
                    "plan_digest": "plan_digest_fixture",
                    "intent": "analysis",
                    "data_refs": [
                        {
                            "kind": "golden_asset",
                            "object_id": "infrastructure_metrics",
                            "revision": "golden_rev_1",
                            "scope": "team",
                        }
                    ],
                    "metrics": ["cpu_utilization"],
                    "dimensions": ["service", "collected_at"],
                    "layout_intent": "trend",
                    "refresh_policy": {
                        "as_of": None,
                        "max_age_seconds": 3600,
                        "require_fixed_revision": True,
                    },
                    "lineage": [
                        {
                            "kind": "golden_asset",
                            "object_id": "infrastructure_metrics",
                            "revision": "golden_rev_1",
                            "scope": "team",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    w2_golden_data.write_text(
        json.dumps(
            [
                {
                    "service": "edge",
                    "cpu_utilization": 0.21,
                    "collected_at": "2026-08-25",
                },
                {
                    "service": "worker",
                    "cpu_utilization": 0.48,
                    "collected_at": "2026-08-25",
                },
            ]
        ),
        encoding="utf-8",
    )

    summary = generate_evidence(
        tmp_path / "w3-evidence",
        chrome,
        w2_smoke_success=w2_smoke_success,
        w2_golden_data=w2_golden_data,
    )

    assert summary["status"] == "succeeded"
    assert summary["schemaVersion"] == "knowledge-assets.worker3.dashboard-evidence.v2"
    assert "no MCP" in summary["scope"]
    assert "veadk.Agent" in summary["scope"]
    assert summary["inputContracts"]["w2"]["buildPlanId"] == "plan_req_fixture"
    assert summary["inputContracts"]["w2"]["metrics"] == ["cpu_utilization"]
    assert summary["inputContracts"]["w2"]["dimensions"] == ["service", "collected_at"]
    normalized_plan = summary["inputContracts"]["w2"]["normalizedDashboardBuildPlan"]
    assert normalized_plan["title"] == "基础设施利用率健康看板"
    assert normalized_plan["kpis"][0]["field"] == "cpu_utilization"
    assert normalized_plan["chart"]["xField"] == "service"
    assert normalized_plan["table"]["fields"] == [
        "service",
        "cpu_utilization",
        "collected_at",
    ]
    assert normalized_plan["insights"]
    assert summary["inputContracts"]["w1"]["requiredGoldenRevisionId"] == "golden_rev_1"
    assert summary["inputContracts"]["w1"]["before"]["w1GoldenAssetRevisionNumber"] == 1
    assert summary["inputContracts"]["w1"]["after"]["w1GoldenAssetRevisionNumber"] == 2
    assert summary["htmlDigests"]["changed"] is True
    assert summary["tableRows"]["changed"] is True
    assert summary["kpis"]["before"] != summary["kpis"]["after"]
    assert summary["chart"]["before"] != summary["chart"]["after"]
    assert summary["visualRegression"]["baseline"] == "v2.13.1"
    assert summary["visualRegression"]["browserExecutable"] == str(chrome)
    assert "Google Chrome" in summary["visualRegression"]["browserVersion"]
    assert summary["screenshots"]["before"]["interactionChecked"] is True
    assert summary["screenshots"]["after"]["interactionChecked"] is True
    assert summary["publishReady"]["before"]["mainPublishAction"] == (
        "MAIN_PUBLISH_CHAIN_REQUIRED"
    )
    assert summary["publishReady"]["after"]["mainPublishAction"] == (
        "MAIN_PUBLISH_CHAIN_REQUIRED"
    )
    summary_path = tmp_path / "w3-evidence" / "evidence-summary.json"
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
