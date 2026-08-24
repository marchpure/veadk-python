#!/usr/bin/env python3
"""Generate repeatable Worker 3 dashboard artifact acceptance evidence.

This script intentionally stays inside the W3 boundary:

- input is a W2-shaped DashboardBuildPlan plus W1-shaped GoldenAssetRevision
  and Golden Data content;
- output is publish-ready dashboard artifact workspaces;
- no MCP process, veadk.Agent/Runner, Skill publication, or reinvocation
  runtime is created here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from frontend.server.knowledge_assets.contracts import (  # noqa: E402
    GoldenAssetRevision,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    SkillManifest,
    StorageRef,
)
from frontend.server.knowledge_assets.kind_runtime.dashboard_artifacts import (  # noqa: E402
    DESIGN_SYSTEM_VERSION,
    DashboardArtifactRequest,
    DashboardBuildPlan,
    DashboardChartPlan,
    DashboardInsightPlan,
    DashboardKpiPlan,
    DashboardTablePlan,
    capture_dashboard_screenshot,
    generate_dashboard_artifact,
)


DEFAULT_EVIDENCE_ROOT = Path(
    "/Users/bytedance/.codex/coordination/knowledge-step3/"
    "w3-dashboard-generation-evidence"
)
DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_W2_SMOKE_SUCCESS = Path(
    "/Users/bytedance/.codex/worktrees/knowledge-step3-worker2-agent-authoring/"
    "tests/fixtures/w2_real_smoke_success.json"
)
DEFAULT_W2_GOLDEN_DATA = Path(
    "/Users/bytedance/.codex/worktrees/knowledge-step3-worker2-agent-authoring/"
    "tests/fixtures/w2_infrastructure_metrics.json"
)
NOW = "2026-08-25T00:00:00+08:00"
ZERO = "0" * 64


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument(
        "--w2-smoke-success", type=Path, default=DEFAULT_W2_SMOKE_SUCCESS
    )
    parser.add_argument("--w2-golden-data", type=Path, default=DEFAULT_W2_GOLDEN_DATA)
    args = parser.parse_args()

    summary = generate_evidence(
        args.output_root,
        args.chrome,
        w2_smoke_success=args.w2_smoke_success,
        w2_golden_data=args.w2_golden_data,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def generate_evidence(
    output_root: Path,
    chrome: Path,
    *,
    w2_smoke_success: Path = DEFAULT_W2_SMOKE_SUCCESS,
    w2_golden_data: Path = DEFAULT_W2_GOLDEN_DATA,
) -> dict[str, Any]:
    if not chrome.exists():
        raise FileNotFoundError(f"Chrome executable is required: {chrome}")
    w2_evidence, first_rows = _load_w2_inputs(w2_smoke_success, w2_golden_data)
    plan = _plan_from_w2(w2_evidence)

    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root = output_root / "artifact-workspaces"
    screenshot_root = output_root / "screenshots"
    workspace_root.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)

    before = generate_dashboard_artifact(
        _request(
            artifact_id="w3-dashboard-before",
            rows=first_rows,
            workspace_root=workspace_root,
            plan=plan,
            golden_revision_number=1,
        )
    )
    after = generate_dashboard_artifact(
        _request(
            artifact_id="w3-dashboard-after",
            rows=_mutated_rows(first_rows),
            workspace_root=workspace_root,
            plan=plan,
            golden_revision_number=2,
        )
    )

    build_results = {
        "before": _rerun_build(before.build_command),
        "after": _rerun_build(after.build_command),
    }
    screenshots = {
        "before": capture_dashboard_screenshot(
            before,
            output_path=screenshot_root / "before.png",
            executable_path=str(chrome),
        ),
        "after": capture_dashboard_screenshot(
            after,
            output_path=screenshot_root / "after.png",
            executable_path=str(chrome),
        ),
    }
    for name, screenshot in screenshots.items():
        if screenshot.status != "succeeded":
            raise RuntimeError(f"{name} screenshot failed: {screenshot.error}")

    summary: dict[str, Any] = {
        "schemaVersion": "knowledge-assets.worker3.dashboard-evidence.v2",
        "status": "succeeded",
        "scope": (
            "W3-only dashboard generation/build/render; no MCP, veadk.Agent, "
            "veadk.Runner, publication, reinvocation runtime, shared BFF, "
            "application.py, or frozen-ui wiring."
        ),
        "inputContracts": {
            "w2": {
                "kind": "DashboardBuildPlan",
                "buildPlanId": plan.build_plan_id,
                "planDigest": w2_evidence["build_plan"]["plan_digest"],
                "source": str(w2_smoke_success),
                "normalizedDashboardBuildPlan": plan.model_dump(
                    mode="json", by_alias=True
                ),
                "metrics": w2_evidence["build_plan"]["metrics"],
                "dimensions": w2_evidence["build_plan"]["dimensions"],
                "dataRefs": w2_evidence["build_plan"]["data_refs"],
                "lineage": w2_evidence["build_plan"]["lineage"],
            },
            "w1": {
                "kind": "GoldenAssetRevision+GoldenData",
                "requiredGoldenRevisionId": plan.required_golden_revision_id,
                "source": str(w2_golden_data),
                "before": _artifact_manifest_inputs(before.workspace_path),
                "after": _artifact_manifest_inputs(after.workspace_path),
            },
        },
        "artifactWorkspaces": {
            "before": before.workspace_path,
            "after": after.workspace_path,
        },
        "artifactUrls": {
            "before": before.artifact_url,
            "after": after.artifact_url,
        },
        "pageUrls": {
            "before": screenshots["before"].served_page_url,
            "after": screenshots["after"].served_page_url,
        },
        "servedPageUrls": {
            "before": screenshots["before"].served_page_url,
            "after": screenshots["after"].served_page_url,
        },
        "buildCommands": {
            "before": before.build_command,
            "after": after.build_command,
        },
        "serveCommands": {
            "before": before.serve_command,
            "after": after.serve_command,
        },
        "buildResults": build_results,
        "kpis": {
            "before": _jsonable(before.kpis),
            "after": _jsonable(after.kpis),
        },
        "chart": {
            "before": _jsonable(before.chart),
            "after": _jsonable(after.chart),
        },
        "tableRows": {
            "before": before.table_rows,
            "after": after.table_rows,
            "changed": before.table_rows != after.table_rows,
        },
        "htmlDigests": {
            "before": before.html_ref.sha256,
            "after": after.html_ref.sha256,
            "changed": before.html_ref.sha256 != after.html_ref.sha256,
        },
        "publishReady": {
            "before": before.publish_ready.model_dump(mode="json", by_alias=True),
            "after": after.publish_ready.model_dump(mode="json", by_alias=True),
        },
        "screenshots": {
            "before": screenshots["before"].model_dump(mode="json", by_alias=True),
            "after": screenshots["after"].model_dump(mode="json", by_alias=True),
        },
        "visualRegression": {
            "baseline": DESIGN_SYSTEM_VERSION,
            "basis": [
                "v2.13.1 design-system typography/radius/control-size rules",
                "real Chrome screenshot of generated artifact served over HTTP",
                "refresh interaction emits host event and waits for completion",
            ],
            "browserExecutable": str(chrome),
            "browserVersion": screenshots["before"].browser_version,
            "viewport": screenshots["before"].viewport,
            "checks": screenshots["before"].visual_checks,
        },
        "forbiddenPatternsChecked": [
            "mockData",
            "fixed sales content",
            "JSON/pre replacement page",
            "static screenshot",
            "self publish/reinvoke runtime",
        ],
    }
    _assert_summary(summary)
    (output_root / "evidence-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _schema(name: str) -> SchemaRef:
    return SchemaRef(uri=f"local://schema/{name}", version="1", sha256=ZERO)


def _manifest(
    *,
    golden_asset_id: str = "golden-infra",
    query_plan_ref: str = "query-plan://readonly/infrastructure_metrics",
) -> SkillManifest:
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
                "dependencies": {"goldenAssets": [golden_asset_id]},
                "policyRef": {"uri": "permission://workspace/ws/read", "version": "1"},
                "runtimeRef": "runtime://analysis/worker3",
                "kindSpec": {
                    "kind": "analysis",
                    "question": "按服务查看基础设施健康风险",
                    "queryPlanRef": query_plan_ref,
                },
            },
        }
    )


def _golden(
    content: str,
    *,
    revision_id: str,
    source_revision_id: str,
    revision_number: int,
) -> GoldenAssetRevision:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return GoldenAssetRevision(
        id=revision_id,
        asset_kind="dataset",
        revision=revision_number,
        schema_ref=_schema("infra"),
        storage_ref=StorageRef(
            uri=f"local://golden/{digest}",
            kind="object",
            sha256=digest,
            media_type="application/json",
            bytes=len(content.encode("utf-8")),
        ),
        source_revision_refs=[source_revision_id],
        owner=OwnerRef(workspace_id="ws", principal_id="tester"),
        permissions_ref=PermissionRef(
            uri="permission://workspace/ws/read", version="1"
        ),
        lineage_digest=hashlib.sha256(
            f"{source_revision_id}:{digest}".encode("utf-8")
        ).hexdigest(),
        freshness_at="2026-08-25T08:00:00+08:00",
        last_good=True,
    )


def _load_w2_inputs(
    w2_smoke_success: Path, w2_golden_data: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not w2_smoke_success.exists():
        raise FileNotFoundError(f"W2 BuildPlan fixture is required: {w2_smoke_success}")
    if not w2_golden_data.exists():
        raise FileNotFoundError(
            f"W1/W2 Golden Data fixture is required: {w2_golden_data}"
        )
    evidence = json.loads(w2_smoke_success.read_text(encoding="utf-8"))
    rows = json.loads(w2_golden_data.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("W1/W2 Golden Data fixture must be an array of objects")
    return evidence, rows


def _plan_from_w2(w2_evidence: dict[str, Any]) -> DashboardBuildPlan:
    build_plan = w2_evidence["build_plan"]
    metric = build_plan["metrics"][0]
    dimension = build_plan["dimensions"][0]
    time_dimension = build_plan["dimensions"][1]
    golden_revision_id = build_plan["data_refs"][0]["revision"]
    return DashboardBuildPlan(
        build_plan_id=build_plan["plan_id"],
        user_goal=w2_evidence["source"]["request"],
        title="基础设施利用率健康看板",
        required_golden_revision_id=golden_revision_id,
        data_query_ref=(
            f"w2://build-plan/{build_plan['plan_id']}/data/"
            f"{build_plan['data_refs'][0]['object_id']}@{golden_revision_id}"
        ),
        invocation_ref=f"trace://w2/{w2_evidence['trace_id']}",
        kpis=[
            DashboardKpiPlan(
                key=metric,
                label="平均 CPU 利用率",
                field=metric,
                aggregation="avg",
                unit="ratio",
            ),
            DashboardKpiPlan(
                key="service_count",
                label="服务数量",
                field=dimension,
                aggregation="count",
                unit="services",
            ),
        ],
        chart=DashboardChartPlan(
            title="按服务拆解 CPU 利用率",
            x_field=dimension,
            y_field=metric,
            aggregation="avg",
            chart_type="bar",
        ),
        table=DashboardTablePlan(
            fields=[dimension, metric, time_dimension],
            max_rows=20,
        ),
        insights=[
            DashboardInsightPlan(
                template="{top_dimension} 当前利用率最高，为 {top_value:.2f} ratio。"
            ),
            DashboardInsightPlan(
                template="共消费 {row_count} 条 W1 Golden Data；目标：{user_goal}"
            ),
        ],
        layout=["kpis", "chart", "table", "insights"],
    )


def _mutated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mutated = [dict(row) for row in rows]
    if len(mutated) < 2:
        raise ValueError("expected at least two rows to prove dashboard data changes")
    mutated[0]["cpu_utilization"] = 0.82
    mutated[1]["cpu_utilization"] = 0.31
    return mutated


def _request(
    *,
    artifact_id: str,
    rows: list[dict[str, Any]],
    workspace_root: Path,
    plan: DashboardBuildPlan,
    golden_revision_number: int,
) -> DashboardArtifactRequest:
    content = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return DashboardArtifactRequest(
        artifact_id=artifact_id,
        build_plan=plan,
        skill_manifest=_manifest(
            golden_asset_id=plan.required_golden_revision_id,
            query_plan_ref=plan.data_query_ref,
        ),
        golden_asset_revision=_golden(
            content,
            revision_id=plan.required_golden_revision_id,
            source_revision_id=plan.data_query_ref,
            revision_number=golden_revision_number,
        ),
        golden_asset_content=content,
        workspace_root=str(workspace_root),
        workspace_id="ws",
        caller_id="tester",
        now=NOW,
    )


def _artifact_manifest_inputs(workspace_path: str) -> dict[str, Any]:
    manifest = json.loads(
        (Path(workspace_path) / "artifact-manifest.json").read_text(encoding="utf-8")
    )
    return dict(manifest["inputs"])


def _rerun_build(command: list[str]) -> dict[str, Any]:
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "command": command,
        "returnCode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
        "status": "passed" if process.returncode == 0 else "failed",
    }


def _assert_summary(summary: dict[str, Any]) -> None:
    assert summary["htmlDigests"]["changed"] is True
    assert summary["tableRows"]["changed"] is True
    assert summary["kpis"]["before"] != summary["kpis"]["after"]
    assert summary["chart"]["before"] != summary["chart"]["after"]
    assert summary["buildResults"]["before"]["returnCode"] == 0
    assert summary["buildResults"]["after"]["returnCode"] == 0
    assert summary["screenshots"]["before"]["status"] == "succeeded"
    assert summary["screenshots"]["after"]["status"] == "succeeded"
    assert summary["artifactUrls"]["before"].startswith("file://")
    assert summary["artifactUrls"]["after"].startswith("file://")
    assert summary["servedPageUrls"]["before"].startswith("http://127.0.0.1:")
    assert summary["servedPageUrls"]["after"].startswith("http://127.0.0.1:")
    assert summary["pageUrls"] == summary["servedPageUrls"]
    assert summary["publishReady"]["before"]["mainPublishAction"] == (
        "MAIN_PUBLISH_CHAIN_REQUIRED"
    )
    assert summary["publishReady"]["after"]["mainPublishAction"] == (
        "MAIN_PUBLISH_CHAIN_REQUIRED"
    )


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
