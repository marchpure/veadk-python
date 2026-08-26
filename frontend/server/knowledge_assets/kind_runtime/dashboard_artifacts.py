"""Worker 3 owned dashboard artifact generation/build/render seam.

The input boundary is W2 BuildPlan + W1 Golden Data revision. This module does
not create an Agent, does not connect MCP, and does not publish Skills. It
emits a publish-ready artifact contract for Main to wire into the shared Skill
publication flow.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from socket import socket
from typing import Literal
from urllib.request import urlopen

from pydantic import Field

from frontend.server.knowledge_assets.contracts import (
    ChartSeries,
    ContractModel,
    DashboardKpi,
    GoldenAssetRevision,
    SkillManifest,
    StorageRef,
)

from .tabular import parse_rows, sensitive_fields

DESIGN_SYSTEM_VERSION = "v2.13.1"
DASHBOARD_ARTIFACT_SCHEMA_VERSION = "knowledge-assets.worker3.dashboard-artifact.v1"

DashboardArtifactStatus = Literal[
    "succeeded",
    "empty",
    "error",
    "permission_denied",
]


class DashboardKpiPlan(ContractModel):
    key: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)
    field: str = Field(min_length=1, max_length=128)
    aggregation: Literal["sum", "avg", "count", "min", "max"] = "sum"
    unit: str = Field(default="", max_length=64)


class DashboardChartPlan(ContractModel):
    title: str = Field(min_length=1, max_length=128)
    x_field: str = Field(min_length=1, max_length=128)
    y_field: str = Field(min_length=1, max_length=128)
    aggregation: Literal["sum", "avg", "count", "min", "max"] = "sum"
    chart_type: Literal["bar", "line"] = "bar"


class DashboardTablePlan(ContractModel):
    fields: list[str] = Field(min_length=1, max_length=24)
    max_rows: int = Field(default=25, ge=1, le=500)


class DashboardInsightPlan(ContractModel):
    template: str = Field(min_length=1, max_length=512)


class DashboardBuildPlan(ContractModel):
    build_plan_id: str = Field(min_length=1, max_length=256)
    user_goal: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=128)
    required_golden_revision_id: str = Field(min_length=1, max_length=256)
    data_query_ref: str = Field(min_length=1, max_length=2048)
    invocation_ref: str = Field(min_length=1, max_length=2048)
    kpis: list[DashboardKpiPlan] = Field(default_factory=list, max_length=12)
    chart: DashboardChartPlan
    table: DashboardTablePlan
    insights: list[DashboardInsightPlan] = Field(default_factory=list, max_length=8)
    layout: list[Literal["kpis", "chart", "table", "insights"]] = Field(
        default_factory=lambda: ["kpis", "chart", "table", "insights"],
        max_length=8,
    )


class DashboardArtifactRequest(ContractModel):
    build_plan: DashboardBuildPlan
    skill_manifest: SkillManifest
    golden_asset_revision: GoldenAssetRevision
    golden_asset_content: str
    workspace_root: str
    workspace_id: str = Field(min_length=1, max_length=128)
    caller_id: str = Field(min_length=1, max_length=256)
    now: str
    artifact_id: str = Field(
        default_factory=lambda: f"dashboard-artifact-{uuid.uuid4().hex[:24]}",
        min_length=1,
        max_length=256,
    )


class PublishReadyArtifactContract(ContractModel):
    kind: Literal["publish_ready_dashboard_artifact"] = (
        "publish_ready_dashboard_artifact"
    )
    artifact_id: str
    workspace_path: str
    revision_id: str
    design_system_version: str = DESIGN_SYSTEM_VERSION
    html_ref: StorageRef
    artifact_manifest_ref: StorageRef
    lineage_ref: StorageRef
    build_ref: StorageRef
    entrypoint: str
    main_publish_action: Literal["MAIN_PUBLISH_CHAIN_REQUIRED"] = (
        "MAIN_PUBLISH_CHAIN_REQUIRED"
    )


class DashboardBuildResult(ContractModel):
    artifact_id: str
    status: DashboardArtifactStatus
    message: str
    workspace_path: str
    source_path: str
    index_html_path: str
    artifact_url: str
    page_url: str
    served_page_url: str | None = None
    build_command: list[str]
    serve_command: list[str]
    html_ref: StorageRef
    css_ref: StorageRef
    chart_config_ref: StorageRef
    data_ref: StorageRef
    manifest_ref: StorageRef
    artifact_manifest_ref: StorageRef
    build_ref: StorageRef
    revision_ref: StorageRef
    lineage_ref: StorageRef
    kpis: list[DashboardKpi] = Field(default_factory=list)
    chart: ChartSeries
    table_rows: list[dict[str, str | int | float | bool | None]] = Field(
        default_factory=list
    )
    insights: list[str] = Field(default_factory=list)
    revision_id: str
    generation_id: str
    lineage_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    dist_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    publish_ready: PublishReadyArtifactContract


class DashboardScreenshotResult(ContractModel):
    status: Literal["succeeded", "failed"]
    artifact_url: str
    page_url: str
    served_page_url: str
    serve_command: list[str]
    screenshot_path: str
    screenshot_ref: StorageRef | None = None
    viewport: str
    image_width: int | None = None
    image_height: int | None = None
    title: str | None = None
    browser_executable: str | None = None
    browser_version: str | None = None
    visual_baseline: str = DESIGN_SYSTEM_VERSION
    visual_checks: list[str] = Field(default_factory=list)
    interaction_checked: bool = False
    error: str | None = None


def generate_dashboard_artifact(
    request: DashboardArtifactRequest,
) -> DashboardBuildResult:
    workspace = _create_workspace_path(request)
    src = workspace / "src"
    dist = workspace / "dist"
    data_dir = workspace / "data"
    for directory in (src, dist, data_dir):
        directory.mkdir(parents=True, exist_ok=True)

    status, message, rows = _validate_request(request)
    model = (
        _dashboard_model(request, rows)
        if status == "succeeded"
        else _empty_model(request)
    )
    model["status"] = status
    model["message"] = message
    chart_config = {
        "type": request.build_plan.chart.chart_type,
        "title": request.build_plan.chart.title,
        "xField": request.build_plan.chart.x_field,
        "yField": request.build_plan.chart.y_field,
        "series": model["chart"]["series"],
    }
    manifest_json = request.skill_manifest.model_dump(mode="json", by_alias=True)
    build_plan_json = request.build_plan.model_dump(mode="json", by_alias=True)
    golden_json = {
        "revision": request.golden_asset_revision.model_dump(
            mode="json", by_alias=True
        ),
        "rows": rows,
    }
    lineage = _lineage(request, model, status)
    revision_id = f"dashboard-revision-{lineage['lineageDigest'][:24]}"
    generation_id = str(lineage["generationId"])
    revision = {
        "schemaVersion": "knowledge-assets.worker3.dashboard-revision.v1",
        "revisionId": revision_id,
        "artifactId": request.artifact_id,
        "status": status,
        "createdAt": request.now,
        "workspaceId": request.workspace_id,
        "callerId": request.caller_id,
        "buildPlanId": request.build_plan.build_plan_id,
        "goldenAssetRevisionId": request.golden_asset_revision.id,
    }

    _write_json(src / "skill-manifest.json", manifest_json)
    _write_json(workspace / "skill-manifest.json", manifest_json)
    _write_json(src / "build-plan.json", build_plan_json)
    _write_json(workspace / "build-plan.json", build_plan_json)
    _write_json(data_dir / "golden.json", golden_json)
    _write_json(src / "dashboard-data.json", model)
    _write_json(src / "chart-config.json", chart_config)
    (src / "index.html").write_text(
        _render_html(model, request, revision_id=revision_id),
        encoding="utf-8",
    )
    (src / "styles.css").write_text(_render_css(), encoding="utf-8")
    (src / "build.mjs").write_text(_build_script(), encoding="utf-8")
    (src / "serve.mjs").write_text(_serve_script(), encoding="utf-8")
    _write_json(workspace / "lineage.json", lineage)
    _write_json(workspace / "revision.json", revision)
    _write_json(workspace / "package.json", _package_json(request))
    _write_json(workspace / "package-lock.json", _package_lock(request))

    build_output = run_dashboard_build(workspace)
    _assert_safe_package(dist)
    html_ref = _content_addressed_ref(
        workspace, dist / "index.html", "text/html", "bundle", ".html"
    )
    css_ref = _content_addressed_ref(
        workspace, dist / "styles.css", "text/css", "object", ".css"
    )
    data_ref = _content_addressed_ref(
        workspace,
        dist / "dashboard-data.json",
        "application/json",
        "object",
        ".json",
    )
    chart_config_ref = _content_addressed_ref(
        workspace,
        dist / "chart-config.json",
        "application/json",
        "object",
        ".json",
    )
    dist_digest = _directory_digest(dist)
    build = {
        "schemaVersion": "knowledge-assets.worker3.dashboard-build.v1",
        "status": "succeeded",
        "command": _build_command(workspace),
        "stdout": build_output.stdout,
        "stderr": build_output.stderr,
        "outputs": [
            "dist/index.html",
            "dist/styles.css",
            "dist/dashboard-data.json",
            "dist/chart-config.json",
        ],
        "htmlDigest": html_ref.sha256,
        "distDigest": dist_digest,
        "generationId": generation_id,
    }
    _write_json(workspace / "build.json", build)
    revision["htmlDigest"] = html_ref.sha256
    revision["distDigest"] = dist_digest
    revision["generationId"] = generation_id
    _write_json(workspace / "revision.json", revision)
    build_ref = _content_addressed_ref(
        workspace, workspace / "build.json", "application/json", "object", ".json"
    )
    lineage_ref = _content_addressed_ref(
        workspace, workspace / "lineage.json", "application/json", "object", ".json"
    )
    artifact_manifest = _artifact_manifest(
        request,
        workspace=workspace,
        revision_id=revision_id,
        html_ref=html_ref,
        css_ref=css_ref,
        data_ref=data_ref,
        chart_config_ref=chart_config_ref,
        build_ref=build_ref,
        lineage_ref=lineage_ref,
        lineage_digest=lineage["lineageDigest"],
        generation_id=generation_id,
        dist_digest=dist_digest,
    )
    _write_json(workspace / "artifact-manifest.json", artifact_manifest)
    artifact_manifest_ref = _content_addressed_ref(
        workspace,
        workspace / "artifact-manifest.json",
        "application/json",
        "object",
        ".json",
    )
    publish_ready = PublishReadyArtifactContract(
        artifact_id=request.artifact_id,
        workspace_path=str(workspace),
        revision_id=revision_id,
        html_ref=html_ref,
        artifact_manifest_ref=artifact_manifest_ref,
        lineage_ref=lineage_ref,
        build_ref=build_ref,
        entrypoint="dist/index.html",
    )
    _write_json(
        workspace / "publish-ready-artifact.json",
        publish_ready.model_dump(mode="json", by_alias=True),
    )
    artifact_url = html_ref.uri
    return DashboardBuildResult(
        artifact_id=request.artifact_id,
        status=status,
        message=message,
        workspace_path=str(workspace),
        source_path=str(src),
        index_html_path=str(dist / "index.html"),
        artifact_url=artifact_url,
        page_url=artifact_url,
        build_command=_build_command(workspace),
        serve_command=_serve_command(workspace),
        html_ref=html_ref,
        css_ref=css_ref,
        chart_config_ref=chart_config_ref,
        data_ref=data_ref,
        manifest_ref=_content_addressed_ref(
            workspace,
            workspace / "skill-manifest.json",
            "application/json",
            "object",
            ".json",
        ),
        artifact_manifest_ref=artifact_manifest_ref,
        build_ref=build_ref,
        revision_ref=_content_addressed_ref(
            workspace,
            workspace / "revision.json",
            "application/json",
            "object",
            ".json",
        ),
        lineage_ref=lineage_ref,
        kpis=model["kpis"],
        chart=ChartSeries(
            name=request.build_plan.chart.y_field,
            points=[tuple(point) for point in model["chart"]["series"]],
        ),
        table_rows=model["tableRows"],
        insights=model["insights"],
        revision_id=revision_id,
        generation_id=generation_id,
        lineage_digest=lineage["lineageDigest"],
        dist_digest=dist_digest,
        publish_ready=publish_ready,
    )


def run_dashboard_build(workspace: str | Path) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        _build_command(Path(workspace)),
        cwd=Path(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"dashboard build failed with exit code {process.returncode}: {process.stderr}"
        )
    return process


def capture_dashboard_screenshot(
    result: DashboardBuildResult,
    *,
    output_path: str | Path,
    executable_path: str | None = None,
    width: int = 1440,
    height: int = 960,
) -> DashboardScreenshotResult:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright

        server = _DashboardServer(Path(result.workspace_path))
        server.start()
        try:
            with sync_playwright() as playwright:
                browser_executable = executable_path
                browser_version = _browser_version(browser_executable)
                browser = playwright.chromium.launch(
                    channel=None if executable_path else "chrome",
                    executable_path=executable_path,
                    headless=True,
                    args=["--no-sandbox"],
                )
                if browser_version is None:
                    reported_version = browser.version
                    browser_version = (
                        f"Google Chrome {reported_version}"
                        if reported_version
                        else None
                    )
                try:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(server.url, wait_until="networkidle")
                    page.locator('[data-dashboard-root="true"]').wait_for(timeout=5_000)
                    page.get_by_role("button", name="刷新").click()
                    page.locator('[data-artifact-event="filter.change"]').select_option(
                        index=1
                    )
                    page.locator('[data-artifact-event="drill.request"]').first.click()
                    title = page.locator("h1").inner_text()
                    visual_checks = _visual_baseline_checks(page)
                    page.screenshot(path=str(output), full_page=False)
                finally:
                    browser.close()
        finally:
            server.stop()
        with Image.open(output) as image:
            image_width, image_height = image.size
        return DashboardScreenshotResult(
            status="succeeded",
            artifact_url=result.artifact_url,
            page_url=server.url,
            served_page_url=server.url,
            serve_command=result.serve_command,
            screenshot_path=str(output),
            screenshot_ref=_storage_ref(output, "image/png", "object"),
            viewport=f"{width}x{height}",
            image_width=image_width,
            image_height=image_height,
            title=title,
            browser_executable=browser_executable or "channel:chrome",
            browser_version=browser_version,
            visual_checks=visual_checks,
            interaction_checked=True,
        )
    except Exception as error:  # noqa: BLE001 - browser adapters raise backend-specific errors
        return DashboardScreenshotResult(
            status="failed",
            artifact_url=result.artifact_url,
            page_url=result.page_url,
            served_page_url=server.url if "server" in locals() else "",
            serve_command=result.serve_command,
            screenshot_path=str(output),
            viewport=f"{width}x{height}",
            error=str(error),
        )


class _DashboardServer:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.process: subprocess.Popen[str] | None = None
        self.url = ""

    def start(self) -> None:
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}/index.html"
        env = {**os.environ, "PORT": str(port)}
        self.process = subprocess.Popen(
            _serve_command(self.workspace),
            cwd=self.workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=1)
                raise RuntimeError("dashboard serve failed: " + (stderr or stdout))
            try:
                with urlopen(self.url, timeout=0.25) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        raise TimeoutError("dashboard serve did not become ready")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


def _validate_request(
    request: DashboardArtifactRequest,
) -> tuple[DashboardArtifactStatus, str, list[dict[str, object]]]:
    if (
        request.build_plan.required_golden_revision_id
        != request.golden_asset_revision.id
    ):
        return "error", "Golden revision mismatch for dashboard BuildPlan.", []
    if _denied(request.golden_asset_revision.permissions_ref.uri):
        return "permission_denied", "权限不足，无法读取当前 Golden Data。", []
    rows = parse_rows(request.golden_asset_content)
    if not rows:
        return "empty", "暂无可展示数据。", []
    missing = _missing_fields(request.build_plan, rows)
    if missing:
        return (
            "error",
            f"BuildPlan references missing field(s): {', '.join(missing)}",
            rows,
        )
    denied_fields = sensitive_fields(rows)
    if denied_fields:
        return (
            "permission_denied",
            f"权限不足，字段不可展示：{', '.join(denied_fields)}",
            rows,
        )
    return "succeeded", "Dashboard artifact built.", rows


def _dashboard_model(
    request: DashboardArtifactRequest, rows: list[dict[str, object]]
) -> dict[str, object]:
    chart_points = _aggregate(
        rows,
        dimension=request.build_plan.chart.x_field,
        metric=request.build_plan.chart.y_field,
        aggregation=request.build_plan.chart.aggregation,
        limit=request.build_plan.table.max_rows,
    )
    kpis = [
        DashboardKpi(
            key=plan.key,
            label=plan.label,
            value=_aggregate_scalar(rows, plan.field, plan.aggregation),
            unit=plan.unit,
            trend=_trend(rows, plan.field),
        )
        for plan in request.build_plan.kpis
    ]
    top_dimension, top_value = _top_point(chart_points)
    insight_context = {
        "top_dimension": top_dimension,
        "top_value": top_value,
        "row_count": len(rows),
        "user_goal": request.build_plan.user_goal,
    }
    return {
        "title": request.build_plan.title,
        "userGoal": request.build_plan.user_goal,
        "statusTemplates": [
            "loading",
            "empty",
            "error",
            "permission_denied",
            "refreshing",
        ],
        "kpis": kpis,
        "chart": {
            "title": request.build_plan.chart.title,
            "type": request.build_plan.chart.chart_type,
            "xField": request.build_plan.chart.x_field,
            "yField": request.build_plan.chart.y_field,
            "series": chart_points,
        },
        "tableFields": request.build_plan.table.fields,
        "tableRows": [
            {field: row.get(field) for field in request.build_plan.table.fields}
            for row in rows[: request.build_plan.table.max_rows]
        ],
        "insights": [
            insight.template.format(**insight_context)
            for insight in request.build_plan.insights
        ],
        "layout": request.build_plan.layout,
        "source": {
            "queryRef": request.build_plan.data_query_ref,
            "invocationRef": request.build_plan.invocation_ref,
            "goldenAssetRevisionId": request.golden_asset_revision.id,
            "goldenAssetRevisionNumber": request.golden_asset_revision.revision,
            "goldenAssetDigest": request.golden_asset_revision.storage_ref.sha256,
            "freshnessAt": request.golden_asset_revision.freshness_at,
            "lineageDigest": request.golden_asset_revision.lineage_digest,
        },
    }


def _empty_model(request: DashboardArtifactRequest) -> dict[str, object]:
    return {
        "title": request.build_plan.title,
        "userGoal": request.build_plan.user_goal,
        "statusTemplates": [
            "loading",
            "empty",
            "error",
            "permission_denied",
            "refreshing",
        ],
        "kpis": [],
        "chart": {
            "title": request.build_plan.chart.title,
            "type": request.build_plan.chart.chart_type,
            "xField": request.build_plan.chart.x_field,
            "yField": request.build_plan.chart.y_field,
            "series": [],
        },
        "tableFields": request.build_plan.table.fields,
        "tableRows": [],
        "insights": [],
        "layout": request.build_plan.layout,
        "source": {
            "queryRef": request.build_plan.data_query_ref,
            "invocationRef": request.build_plan.invocation_ref,
            "goldenAssetRevisionId": request.golden_asset_revision.id,
            "goldenAssetRevisionNumber": request.golden_asset_revision.revision,
            "goldenAssetDigest": request.golden_asset_revision.storage_ref.sha256,
            "freshnessAt": request.golden_asset_revision.freshness_at,
            "lineageDigest": request.golden_asset_revision.lineage_digest,
        },
    }


def _escape(value: object) -> str:
    return html.escape(_format_value(value), quote=True)


def _render_html(
    model: dict[str, object],
    request: DashboardArtifactRequest,
    *,
    revision_id: str,
) -> str:
    """Render the immutable business document without executable content.

    Interactions are declarative ``data-artifact-event`` markers. The Studio
    trusted renderer owns the bridge and translates those markers into typed
    host events; generated artifacts never receive Studio origin capabilities.
    """
    source = model["source"]
    assert isinstance(source, dict)
    chart = model["chart"]
    assert isinstance(chart, dict)
    kpis = model["kpis"]
    rows = model["tableRows"]
    fields = model["tableFields"]
    insights = model["insights"]
    assert isinstance(kpis, list)
    assert isinstance(rows, list)
    assert isinstance(fields, list)
    assert isinstance(insights, list)
    series = chart["series"]
    assert isinstance(series, list)
    values = [
        float(point[1])
        for point in series
        if isinstance(point, (list, tuple))
        and len(point) == 2
        and isinstance(point[1], (int, float))
    ]
    maximum = max(values, default=1.0) or 1.0
    filter_options = "".join(
        f'<option value="{_escape(point[0])}">{_escape(point[0])}</option>'
        for point in series
        if isinstance(point, (list, tuple)) and len(point) == 2
    )
    kpi_html = "".join(
        (
            '<button type="button" class="kpi-card" '
            'data-artifact-event="selection.change" '
            f'data-element-id="kpi:{_escape(item.key)}">'
            f"<span>{_escape(item.label)}</span>"
            f'<strong data-kpi-key="{_escape(item.key)}">{_escape(item.value)}</strong>'
            f"<small>{_escape(item.unit)} · {_escape(item.trend)}</small>"
            "</button>"
        )
        for item in kpis
        if isinstance(item, DashboardKpi)
    )
    chart_html = "".join(
        (
            '<details class="bar-row" '
            f'data-element-id="chart:{_escape(point[0])}">'
            '<summary data-artifact-event="drill.request" '
            f'data-field="{_escape(chart["xField"])}" '
            f'data-value="{_escape(point[0])}">'
            f"<span>{_escape(point[0])}</span>"
            '<span class="bar-track" aria-hidden="true">'
            f'<span class="bar-fill" style="width:{max(4, float(point[1]) / maximum * 100):.2f}%"></span>'
            "</span>"
            f"<strong>{_escape(point[1])}</strong>"
            "</summary>"
            f"<p>钻取请求：{_escape(chart['xField'])} = {_escape(point[0])}</p>"
            "</details>"
        )
        for point in series
        if isinstance(point, (list, tuple))
        and len(point) == 2
        and isinstance(point[1], (int, float))
    )
    table_head = "".join(f"<th>{_escape(field)}</th>" for field in fields)
    table_body = "".join(
        "<tr>"
        + "".join(f"<td>{_escape(row.get(str(field)))}</td>" for field in fields)
        + "</tr>"
        for row in rows
        if isinstance(row, dict)
    )
    insight_html = "".join(f"<li>{_escape(item)}</li>" for item in insights)
    status = _escape(model["status"])
    message = _escape(model["message"])
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8" />',
            '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
            "  <meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; script-src 'none'; form-action 'none'; base-uri 'none'\" />",
            f"  <title>{_escape(model['title'])}</title>",
            f"  <style>{_render_css()}</style>",
            "</head>",
            '<body data-dashboard-root="true">',
            (
                f'<main class="ka-dashboard" role="main" aria-label="{_escape(model["title"])}" '
                f'data-artifact-id="{_escape(request.artifact_id)}" '
                f'data-revision-id="{_escape(revision_id)}">'
            ),
            '  <section class="hero">',
            "    <div>",
            f"      <h1>{_escape(model['title'])}</h1>",
            f'      <p class="goal">{_escape(model["userGoal"])}</p>',
            "    </div>",
            '    <div class="toolbar">',
            f'      <span class="status status-{status}">{status}</span>',
            '      <button type="button" data-artifact-event="refresh.request">刷新</button>',
            '      <button type="button" data-artifact-event="export.request" data-format="csv">导出</button>',
            '      <button type="button" data-artifact-event="context.reference">加入上下文</button>',
            "    </div>",
            "  </section>",
            f'  <section class="state-strip" aria-live="polite"><p>{message}</p></section>',
            '  <section class="filter-bar" aria-label="过滤状态">',
            f"    <label>筛选 {_escape(chart['xField'])}",
            (
                '      <select data-artifact-event="filter.change" '
                f'data-field="{_escape(chart["xField"])}">'
                f'<option value="">全部</option>{filter_options}</select>'
            ),
            "    </label>",
            '    <output data-filter-state="all">当前显示：全部数据</output>',
            "  </section>",
            f'  <section class="kpi-grid" aria-label="KPI 指标">{kpi_html}</section>',
            '  <section class="panel chart-panel" aria-label="趋势与分组图">',
            f"    <h2>{_escape(chart['title'])}</h2>",
            f'    <div class="chart-bars">{chart_html}</div>',
            "  </section>",
            '  <section class="panel table-panel" aria-label="明细表">',
            "    <h2>明细</h2>",
            f'    <div class="table-scroll"><table><thead><tr>{table_head}</tr></thead><tbody>{table_body}</tbody></table></div>',
            "  </section>",
            '  <section class="panel insight-panel" aria-label="洞察">',
            "    <h2>洞察</h2>",
            f"    <ul>{insight_html}</ul>",
            "  </section>",
            '  <footer class="lineage">',
            f"    <span>数据来源</span><code>{_escape(source['queryRef'])}</code>",
            f"    <span>更新于</span><code>{_escape(source['freshnessAt'])}</code>",
            f"    <span>revision</span><code>{_escape(revision_id)}</code>",
            f"    <span>lineage</span><code>{_escape(source['lineageDigest'])}</code>",
            "  </footer>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _render_css() -> str:
    return """
:root {
  color-scheme: light;
  --background: #f7f8fa;
  --panel: #ffffff;
  --foreground: #111827;
  --muted: #f1f3f5;
  --muted-foreground: #5b6472;
  --border: #d9dee7;
  --primary: #1f5eff;
  --warning: #b7791f;
  --danger: #b42318;
}
:host {
  display: block;
  min-height: 100%;
  background: #f7f8fa;
  color: #111827;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --background: #f7f8fa;
  --panel: #ffffff;
  --foreground: #111827;
  --muted: #f1f3f5;
  --muted-foreground: #5b6472;
  --border: #d9dee7;
  --primary: #1f5eff;
  --warning: #b7791f;
  --danger: #b42318;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--background);
  color: var(--foreground);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.ka-dashboard {
  width: min(1180px, calc(100vw - 48px));
  margin: 0 auto;
  padding: 32px 0;
}
.hero, .panel, .kpi-card, .lineage, .state-strip {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  padding: 24px;
}
.eyebrow {
  margin: 0 0 8px;
  color: var(--muted-foreground);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: 26px; line-height: 1.2; font-weight: 600; }
h2 { margin: 0 0 16px; font-size: 17px; line-height: 1.3; }
.goal { margin: 10px 0 0; color: var(--muted-foreground); font-size: 14px; }
.status, button {
  border-radius: 999px;
  border: 1px solid var(--border);
  padding: 6px 10px;
  font-size: 12px;
  white-space: nowrap;
}
button {
  min-height: 34px;
  background: var(--foreground);
  color: white;
  cursor: pointer;
}
.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding: 12px 16px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--muted-foreground);
  font-size: 12px;
}
.filter-bar label { display: flex; align-items: center; gap: 8px; }
.filter-bar select {
  min-height: 34px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--panel);
  color: var(--foreground);
  padding: 0 28px 0 10px;
}
.toolbar { display: flex; gap: 8px; align-items: center; }
.status-succeeded { color: #116329; background: #eefbf2; border-color: #bfe8c9; }
.status-empty { color: var(--warning); background: #fff8e5; border-color: #f1d18a; }
.status-error, .status-permission_denied {
  color: var(--danger);
  background: #fff1f0;
  border-color: #f1b8b2;
}
.state-strip {
  display: grid;
  gap: 8px;
  margin-top: 16px;
  padding: 14px;
}
.state-template {
  display: none;
  color: var(--muted-foreground);
  font-size: 13px;
}
.state-template.is-active { display: block; }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.kpi-card {
  display: block;
  min-width: 0;
  padding: 16px;
  color: var(--foreground);
  text-align: left;
  cursor: pointer;
}
.kpi-card span, .kpi-card small { color: var(--muted-foreground); font-size: 12px; }
.kpi-card strong { display: block; margin: 8px 0; font-size: 28px; line-height: 1.1; }
.panel { margin-top: 16px; padding: 20px; }
.chart-bars { display: grid; gap: 12px; }
.bar-row summary {
  display: grid;
  grid-template-columns: 144px minmax(0, 1fr) 72px;
  gap: 12px;
  align-items: center;
  font-size: 13px;
}
.bar-row summary { cursor: pointer; list-style: none; }
.bar-row summary::-webkit-details-marker { display: none; }
.bar-row p {
  margin: 8px 0 0 156px;
  color: var(--muted-foreground);
  font-size: 12px;
}
.bar-track { height: 14px; background: var(--muted); border-radius: 999px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--primary); border-radius: 999px; }
.table-scroll { overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--border); padding: 10px 8px; text-align: left; }
th { color: var(--muted-foreground); font-weight: 600; }
.insight-panel ul { margin: 0; padding-left: 18px; color: var(--foreground); }
.insight-panel li + li { margin-top: 8px; }
.lineage {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 16px;
  padding: 14px 16px;
  color: var(--muted-foreground);
  font-size: 12px;
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--foreground);
  overflow-wrap: anywhere;
}
@media (max-width: 760px) {
  .ka-dashboard { width: calc(100vw - 24px); padding: 16px 0; }
  .hero { display: block; }
  .toolbar { margin-top: 16px; flex-wrap: wrap; }
  .filter-bar { align-items: flex-start; flex-direction: column; }
  .kpi-grid { grid-template-columns: 1fr; }
  .bar-row summary { grid-template-columns: 96px minmax(0, 1fr) 56px; }
  .bar-row p { margin-left: 0; }
}
""".strip()


def _build_script() -> str:
    return r"""
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";

const root = resolve(".");
const src = resolve(root, "src");
const dist = resolve(root, "dist");
mkdirSync(dist, { recursive: true });
for (const name of ["index.html", "styles.css", "dashboard-data.json", "chart-config.json"]) {
  copyFileSync(resolve(src, name), resolve(dist, name));
}
const html = readFileSync(resolve(dist, "index.html"));
const digest = createHash("sha256").update(html).digest("hex");
writeFileSync(resolve(root, "build-result.json"), JSON.stringify({
  status: "succeeded",
  htmlDigest: digest,
  outputs: ["dist/index.html", "dist/styles.css", "dist/dashboard-data.json", "dist/chart-config.json"]
}, null, 2) + "\n");
""".strip()


def _serve_script() -> str:
    return r"""
import { createServer } from "node:http";
import { createReadStream, existsSync } from "node:fs";
import { extname, resolve } from "node:path";

const root = resolve("dist");
const port = Number(process.env.PORT || 4173);
const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json" };
const server = createServer((request, response) => {
  const pathname = request.url === "/" ? "/index.html" : request.url.split("?")[0];
  const file = resolve(root, "." + pathname);
  if (!file.startsWith(root) || !existsSync(file)) {
    response.writeHead(404);
    response.end("not found");
    return;
  }
  response.writeHead(200, { "content-type": types[extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(response);
});
server.listen(port, "127.0.0.1", () => {
  console.log(`dashboard artifact server listening on http://127.0.0.1:${port}`);
});
""".strip()


def _package_json(request: DashboardArtifactRequest) -> dict[str, object]:
    return {
        "name": _package_name(request.artifact_id),
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "description": "Generated Worker 3 publish-ready dashboard artifact.",
        "scripts": {
            "build": "node src/build.mjs",
            "serve": "node src/serve.mjs",
        },
        "dependencies": {},
        "devDependencies": {},
    }


def _package_lock(request: DashboardArtifactRequest) -> dict[str, object]:
    package = _package_json(request)
    return {
        "name": package["name"],
        "version": package["version"],
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": package,
        },
    }


def _package_name(artifact_id: str) -> str:
    normalized = "".join(
        character.lower() if character.isalnum() else "-" for character in artifact_id
    ).strip("-")
    return f"worker3-dashboard-{normalized or 'artifact'}"


def _artifact_manifest(
    request: DashboardArtifactRequest,
    *,
    workspace: Path,
    revision_id: str,
    html_ref: StorageRef,
    css_ref: StorageRef,
    data_ref: StorageRef,
    chart_config_ref: StorageRef,
    build_ref: StorageRef,
    lineage_ref: StorageRef,
    lineage_digest: str,
    generation_id: str,
    dist_digest: str,
) -> dict[str, object]:
    return {
        "schemaVersion": DASHBOARD_ARTIFACT_SCHEMA_VERSION,
        "artifactId": request.artifact_id,
        "revisionId": revision_id,
        "workspaceId": request.workspace_id,
        "callerId": request.caller_id,
        "createdAt": request.now,
        "designSystemVersion": DESIGN_SYSTEM_VERSION,
        "trustedTemplate": "worker3-dashboard-executive-overview",
        "entrypoint": "dist/index.html",
        "generationId": generation_id,
        "buildCommand": _build_command(workspace),
        "serveCommand": _serve_command(workspace),
        "inputs": {
            "w2BuildPlanId": request.build_plan.build_plan_id,
            "w1GoldenAssetRevisionId": request.golden_asset_revision.id,
            "w1GoldenAssetRevisionNumber": request.golden_asset_revision.revision,
            "w1GoldenAssetDigest": request.golden_asset_revision.storage_ref.sha256,
            "sourceRevisionRefs": request.golden_asset_revision.source_revision_refs,
            "dataQueryRef": request.build_plan.data_query_ref,
            "invocationRef": request.build_plan.invocation_ref,
        },
        "sourceFiles": [
            "src/index.html",
            "src/styles.css",
            "src/dashboard-data.json",
            "src/chart-config.json",
            "src/build.mjs",
            "src/serve.mjs",
        ],
        "configFiles": [
            "skill-manifest.json",
            "src/skill-manifest.json",
            "build-plan.json",
            "src/build-plan.json",
            "data/golden.json",
            "package.json",
            "package-lock.json",
            "revision.json",
            "lineage.json",
            "build.json",
            "artifact-manifest.json",
        ],
        "outputFiles": [
            "dist/index.html",
            "dist/styles.css",
            "dist/dashboard-data.json",
            "dist/chart-config.json",
        ],
        "dependencies": {
            "runtime": "node",
            "npm": "package-lock.json",
            "externalPackages": [],
        },
        "refs": {
            "html": html_ref.model_dump(mode="json", by_alias=True),
            "css": css_ref.model_dump(mode="json", by_alias=True),
            "data": data_ref.model_dump(mode="json", by_alias=True),
            "chartConfig": chart_config_ref.model_dump(mode="json", by_alias=True),
            "build": build_ref.model_dump(mode="json", by_alias=True),
            "lineage": lineage_ref.model_dump(mode="json", by_alias=True),
        },
        "lineageDigest": lineage_digest,
        "distDigest": dist_digest,
        "skillManifest": "skill-manifest.json",
        "invocationReference": request.build_plan.invocation_ref,
        "publish": {
            "ready": True,
            "mainPublishAction": "MAIN_PUBLISH_CHAIN_REQUIRED",
        },
        "forbiddenPatterns": {
            "businessScripts": False,
            "networkRequests": False,
            "externalIframes": False,
            "mockData": False,
            "fixedSalesContent": False,
            "jsonPreReplacementPage": False,
            "staticScreenshot": False,
            "selfPublishingRuntime": False,
        },
    }


def _browser_version(executable_path: str | None) -> str | None:
    command = [
        executable_path
        or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "--version",
    ]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        return None
    output = (process.stdout or process.stderr).strip()
    return output or None


def _visual_baseline_checks(page: object) -> list[str]:
    metrics = page.evaluate(
        """() => {
          const root = document.querySelector('.ka-dashboard');
          const hero = document.querySelector('.hero');
          const panel = document.querySelector('.panel');
          const h1 = document.querySelector('h1');
          const button = document.querySelector('button');
          const table = document.querySelector('table');
          const rootStyle = root ? getComputedStyle(root) : null;
          const heroStyle = hero ? getComputedStyle(hero) : null;
          const panelStyle = panel ? getComputedStyle(panel) : null;
          const h1Style = h1 ? getComputedStyle(h1) : null;
          const buttonStyle = button ? getComputedStyle(button) : null;
          return {
            hasRoot: Boolean(root),
            hasHero: Boolean(hero),
            hasPanel: Boolean(panel),
            hasTable: Boolean(table),
            rootWidth: root ? root.getBoundingClientRect().width : 0,
            bodyOverflowX: document.documentElement.scrollWidth > window.innerWidth,
            heroRadius: heroStyle ? parseFloat(heroStyle.borderRadius) : 0,
            heroBorderWidth: heroStyle ? parseFloat(heroStyle.borderTopWidth) : 0,
            panelRadius: panelStyle ? parseFloat(panelStyle.borderRadius) : 0,
            panelBorderWidth: panelStyle ? parseFloat(panelStyle.borderTopWidth) : 0,
            h1Size: h1Style ? parseFloat(h1Style.fontSize) : 0,
            h1Weight: h1Style ? Number(h1Style.fontWeight) : 0,
            buttonHeight: button ? button.getBoundingClientRect().height : 0,
            buttonRadius: buttonStyle ? parseFloat(buttonStyle.borderRadius) : 0,
          };
        }"""
    )
    failures: list[str] = []
    if not metrics["hasRoot"]:
        failures.append("missing dashboard root")
    if not metrics["hasHero"]:
        failures.append("missing hero region")
    if not metrics["hasPanel"]:
        failures.append("missing content panel")
    if not metrics["hasTable"]:
        failures.append("missing table")
    if not (0 < metrics["rootWidth"] <= 1180):
        failures.append("root width exceeds v2.13.1 readable max")
    if metrics["bodyOverflowX"]:
        failures.append("horizontal overflow")
    if not (10 <= metrics["heroRadius"] <= 14):
        failures.append("hero radius outside v2.13.1 panel range")
    if metrics["heroBorderWidth"] != 1:
        failures.append("hero border is not 1px")
    if not (10 <= metrics["panelRadius"] <= 14):
        failures.append("panel radius outside v2.13.1 panel range")
    if metrics["panelBorderWidth"] != 1:
        failures.append("panel border is not 1px")
    if not (20 <= metrics["h1Size"] <= 26):
        failures.append("title size outside v2.13.1 page-title range")
    if not (500 <= metrics["h1Weight"] <= 650):
        failures.append("title weight outside v2.13.1 range")
    if not (34 <= metrics["buttonHeight"] <= 36):
        failures.append("button height outside v2.13.1 control range")
    if metrics["buttonRadius"] < 16:
        failures.append("refresh button is not pill-shaped")
    if failures:
        raise AssertionError("; ".join(failures))
    return [
        "dashboard root rendered",
        "hero/content/table regions rendered",
        "no horizontal overflow",
        "panel radius and 1px border align with v2.13.1",
        "title typography aligns with v2.13.1",
        "refresh control size aligns with v2.13.1",
    ]


def _lineage(
    request: DashboardArtifactRequest,
    model: dict[str, object],
    status: DashboardArtifactStatus,
) -> dict[str, object]:
    payload = {
        "schemaVersion": "knowledge-assets.worker3.dashboard-lineage.v1",
        "artifactId": request.artifact_id,
        "workspaceId": request.workspace_id,
        "callerId": request.caller_id,
        "status": status,
        "skillId": request.skill_manifest.metadata.id,
        "skillVersion": request.skill_manifest.metadata.version,
        "buildPlanId": request.build_plan.build_plan_id,
        "userGoal": request.build_plan.user_goal,
        "dataQueryRef": request.build_plan.data_query_ref,
        "invocationRef": request.build_plan.invocation_ref,
        "goldenAssetRevisionId": request.golden_asset_revision.id,
        "goldenAssetRevisionNumber": request.golden_asset_revision.revision,
        "goldenAssetDigest": request.golden_asset_revision.storage_ref.sha256,
        "sourceRevisionRefs": request.golden_asset_revision.source_revision_refs,
        "freshnessAt": request.golden_asset_revision.freshness_at,
        "generatedAt": request.now,
        "modelDigest": _sha256_json(_jsonable(model)),
    }
    generation_id = f"{request.artifact_id}-{_sha256_json(payload)[:16]}"
    return {
        **payload,
        "generationId": generation_id,
        "lineageDigest": _sha256_json(payload),
    }


def _create_workspace_path(request: DashboardArtifactRequest) -> Path:
    base = _workspace_base_path(request)
    if not base.exists():
        return base
    for index in range(2, 10_000):
        candidate = base.with_name(f"{base.name}-{index:04d}")
        if not candidate.exists():
            return candidate
    return base.with_name(f"{base.name}-{uuid.uuid4().hex[:8]}")


def _workspace_base_path(request: DashboardArtifactRequest) -> Path:
    digest = _sha256_json(
        {
            "artifactId": request.artifact_id,
            "buildPlanId": request.build_plan.build_plan_id,
            "goldenAssetDigest": request.golden_asset_revision.storage_ref.sha256,
        }
    )
    return Path(request.workspace_root) / f"{request.artifact_id}-{digest[:12]}"


def _missing_fields(
    build_plan: DashboardBuildPlan, rows: list[dict[str, object]]
) -> list[str]:
    available = set(rows[0]) if rows else set()
    required = {
        *(kpi.field for kpi in build_plan.kpis),
        build_plan.chart.x_field,
        build_plan.chart.y_field,
        *build_plan.table.fields,
    }
    return sorted(field for field in required if field not in available)


def _aggregate(
    rows: list[dict[str, object]],
    *,
    dimension: str,
    metric: str,
    aggregation: str,
    limit: int,
) -> list[tuple[str, float]]:
    grouped: dict[str, list[float]] = {}
    order: list[str] = []
    for row in rows:
        label = str(row.get(dimension, "unknown"))
        value = row.get(metric)
        if aggregation == "count":
            numeric = 1.0
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
        else:
            continue
        if label not in grouped:
            order.append(label)
            grouped[label] = []
        grouped[label].append(numeric)
    return [
        (label, _apply_aggregation(grouped[label], aggregation))
        for label in order[:limit]
    ]


def _aggregate_scalar(
    rows: list[dict[str, object]], field: str, aggregation: str
) -> int | float:
    values = [
        float(row[field])
        for row in rows
        if isinstance(row.get(field), (int, float))
        and not isinstance(row.get(field), bool)
    ]
    if aggregation == "count":
        return len(rows)
    result = _apply_aggregation(values, aggregation)
    return int(result) if result.is_integer() else result


def _apply_aggregation(values: list[float], aggregation: str) -> float:
    if not values:
        return 0.0
    if aggregation == "avg":
        return sum(values) / len(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "max":
        return max(values)
    if aggregation == "count":
        return float(len(values))
    return sum(values)


def _trend(
    rows: list[dict[str, object]], field: str
) -> Literal["up", "down", "flat", "unknown"]:
    values = [
        float(row[field])
        for row in rows
        if isinstance(row.get(field), (int, float))
        and not isinstance(row.get(field), bool)
    ]
    if len(values) < 2:
        return "unknown"
    if values[-1] > values[0]:
        return "up"
    if values[-1] < values[0]:
        return "down"
    return "flat"


def _top_point(points: list[tuple[str, float]]) -> tuple[str, float]:
    if not points:
        return "暂无维度", 0.0
    return max(points, key=lambda item: item[1])


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if value is None:
        return ""
    return str(value)


def _denied(permission_ref: str) -> bool:
    return "deny" in permission_ref.lower() or "forbidden" in permission_ref.lower()


def _storage_ref(path: Path, media_type: str, kind: str) -> StorageRef:
    content = path.read_bytes()
    digest = _sha256_bytes(content)
    return StorageRef(
        uri=path.resolve().as_uri(),
        kind=kind,  # type: ignore[arg-type]
        sha256=digest,
        media_type=media_type,
        bytes=len(content),
    )


def _content_addressed_ref(
    workspace: Path,
    source: Path,
    media_type: str,
    kind: str,
    suffix: str,
) -> StorageRef:
    digest = _sha256_bytes(source.read_bytes())
    target = workspace / "objects" / f"{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(source, target)
    return _storage_ref(target, media_type, kind)


def _assert_safe_package(dist: Path) -> None:
    html_text = (dist / "index.html").read_text(encoding="utf-8").lower()
    css_text = (dist / "styles.css").read_text(encoding="utf-8").lower()
    forbidden = {
        "script": "<script",
        "iframe": "<iframe",
        "object": "<object",
        "embed": "<embed",
        "network URL": "http://",
        "secure network URL": "https://",
        "javascript URL": "javascript:",
        "CSS network import": "@import",
        "CSS network resource": "url(",
    }
    combined = f"{html_text}\n{css_text}"
    matches = [name for name, pattern in forbidden.items() if pattern in combined]
    if matches:
        raise ValueError(
            "dashboard package contains forbidden executable/network content: "
            + ", ".join(matches)
        )


def _free_port() -> int:
    with socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _jsonable(value: object) -> object:
    if isinstance(value, ContractModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _sha256_json(payload: object) -> str:
    return _sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _directory_digest(directory: Path) -> str:
    parts: list[str] = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        parts.append(
            f"{path.relative_to(directory).as_posix()}:{_sha256_bytes(path.read_bytes())}"
        )
    return _sha256_bytes("\n".join(parts).encode("utf-8"))


def _build_command(workspace: Path) -> list[str]:
    return ["npm", "run", "build", "--prefix", str(workspace)]


def _serve_command(workspace: Path) -> list[str]:
    return ["npm", "run", "serve", "--prefix", str(workspace)]


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("workspace")
    args = parser.parse_args(argv)
    if args.command == "build":
        run_dashboard_build(args.workspace)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
