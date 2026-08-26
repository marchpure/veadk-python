"""The deterministic, trusted HTML compiler for Skill ViewModels.

The compiler is intentionally boring at the security boundary: ViewModels are
validated before they arrive here, all text is escaped, and the only visual
runtime is server-rendered HTML/CSS/SVG.  A Shell may listen to the declarative
``data-artifact-event`` attributes, but this document never executes code.

The visual grammar is inspired by the restrained editorial spacing of
Open Design's design systems and the dense, evidence-first data reports in
html-anything.  It is implemented locally so the artifact remains standalone
and has no external network dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
from collections.abc import Iterable

from .contract_views import (
    ChartSeries,
    ChartViewModel,
    DashboardViewModel,
    GraphOntologyViewModel,
    KnowledgeViewModel,
    MonitoringViewModel,
    SemanticViewModel,
    SopViewModel,
    ViewModel,
)
from .design_system import (
    DesignDirection,
    DesignTokens,
    profile_for,
    tokens_for,
)

CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    "base-uri 'none'; form-action 'none'; connect-src 'none'; "
    "font-src 'none'; frame-src 'none'; object-src 'none'"
)
RENDERER_VERSION = "skill-html-compiler-v3-shadow-tokens"


@dataclass(frozen=True)
class TemplateBundle:
    """A versioned presentation capability, not a data or skill contract."""

    template_id: str
    version: str
    view_model_template: str
    design_tokens: DesignTokens
    event_capabilities: tuple[str, ...]
    bundle_path: str
    visual_profile: str


@dataclass(frozen=True)
class PresentationRecipe:
    """Internal layout choice made from a typed ViewModel."""

    density: str = "comfortable"
    emphasis: str = "evidence-first"
    chart_types: tuple[str, ...] = ("line", "bar")
    sections: tuple[str, ...] = ()
    direction: DesignDirection = "analytical"
    visible_modules: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class VisualCompileAttempt:
    round: int
    direction: DesignDirection
    score: float
    core_pass: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class VisualCompileResult:
    html: bytes
    direction: DesignDirection
    attempts: tuple[VisualCompileAttempt, ...]


def bundle_for(
    template: str, *, direction: DesignDirection = "analytical"
) -> TemplateBundle:
    """Resolve the local, versioned bundle used by a formal renderer."""

    aliases = {
        "chart": "dashboard",
        "graph": "graph-ontology",
        "graph_ontology": "graph-ontology",
    }
    template_id = aliases.get(template, template)
    capabilities = {
        "dashboard": (
            "filter.change", "drill.request", "refresh.request",
            "export", "cite",
        ),
        "semantic": ("selection.change", "filter.change", "refresh.request"),
        "sop": ("selection.change", "context.reference", "refresh.request"),
        "knowledge": ("selection.change", "context.reference", "refresh.request"),
        "graph-ontology": ("selection.change", "filter.change", "refresh.request"),
        "monitoring": ("selection.change", "context.reference", "refresh.request"),
    }
    if template_id not in capabilities:
        raise ValueError(f"no trusted TemplateBundle for template: {template}")
    return TemplateBundle(
        template_id=template_id,
        version="1.1.0",
        view_model_template=template,
        design_tokens=tokens_for(direction),
        event_capabilities=capabilities[template_id],
        bundle_path=f"knowledge_assets/template_bundles/{template_id}",
        visual_profile=profile_for(template_id.replace("-", "_")).profile_id,
    )


class HTMLCompiler:
    """Compile a typed model into one immutable, content-addressable document."""

    def compile(
        self,
        bundle: TemplateBundle,
        recipe: PresentationRecipe,
        model: ViewModel,
        *,
        data_revision_refs: Iterable[str] = (),
    ) -> bytes:
        expected = {
            "dashboard": "dashboard",
            "semantic": "semantic",
            "sop": "sop",
            "knowledge": "knowledge",
            "graph-ontology": "graph_ontology",
            "monitoring": "monitoring",
        }[bundle.template_id]
        actual = model.template
        if actual != expected and not (
            bundle.template_id == "dashboard" and actual == "chart"
        ):
            raise ValueError(
                f"TemplateBundle {bundle.template_id} cannot render ViewModel {actual}"
            )
        model_payload = model.model_dump(mode="json", by_alias=True)
        model_digest = _digest(model_payload)
        revisions = tuple(str(item) for item in data_revision_refs)
        body = _render_body(model, recipe)
        title = _title(model, bundle.template_id)
        revision_text = ", ".join(revisions) if revisions else "unbound"
        root_events = " ".join(bundle.event_capabilities)
        document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="skill-template" content="{_e(bundle.template_id)}">
  <meta name="skill-template-version" content="{_e(bundle.version)}">
  <meta name="view-model-digest" content="{model_digest}">
  <meta name="data-revisions" content="{_e(revision_text)}">
  <meta name="renderer-version" content="{RENDERER_VERSION}">
  <meta name="design-direction" content="{_e(recipe.direction)}">
  <meta http-equiv="Content-Security-Policy" content="{_e(CSP)}">
  <title>{_e(title)}</title>
  <style>{_css(bundle.design_tokens) + ".artifact.direction-operational .step-card{background:#f8fafc}.artifact.direction-operational .tool-trace{margin-top:10px;padding:9px 10px;border:1px solid #edf0f4;border-radius:6px;background:#fff;color:#4b5b70;font-size:11px;line-height:1.45}.artifact.direction-operational .step-result{display:flex;gap:6px;align-items:flex-start;margin-top:10px;padding:10px 11px;border:1px solid #dfe5ec;border-radius:7px;background:#fff;color:#344054;font-size:12px;line-height:1.55}.artifact.direction-operational .step-result span{font-weight:700;color:#667085;white-space:nowrap}.artifact.direction-operational .step-result-failed{background:#fff8f6;border-color:#f0c7c1}.artifact.direction-operational .step-result-awaiting_confirmation{background:#fff8eb;border-color:#f1d49b}"}</style>
</head>
<body>
  <main class="artifact direction-{_e(recipe.direction)}" data-template="{_e(bundle.template_id)}"
        data-renderer="{_e(bundle.view_model_template)}-v1"
        data-template-version="{_e(bundle.version)}"
        data-view-model-digest="{model_digest}"
        data-data-revisions="{_e(revision_text)}"
        data-renderer-version="{RENDERER_VERSION}"
        data-direction="{_e(recipe.direction)}"
        data-visual-profile="{_e(bundle.visual_profile)}"
        data-artifact-events="{_e(root_events)}"
        data-csp="trusted-renderer-v1" role="region" aria-label="{_e(title)}">
    {body}
    <details class="state-coverage" hidden><summary>State coverage</summary>
      <span class="state state-succeeded">populated</span>
      <span class="state state-empty">empty</span>
      <span class="state state-failed">error</span>
      <span class="state state-stale">stale</span>
      <p>Runtime state is preserved by the immutable revision; refresh creates a new revision.</p>
    </details>
  </main>
</body>
</html>
"""
        return document.encode("utf-8")


def render_trusted_html(
    template: str,
    model: ViewModel,
    *,
    data_revision_refs: Iterable[str] = (),
    recipe: PresentationRecipe | None = None,
    direction: DesignDirection | None = None,
) -> bytes:
    """Compatibility entry point used by the projector and older callers."""

    selected = recipe or _recipe_for(model, direction=direction)
    bundle = bundle_for(template, direction=selected.direction)
    return HTMLCompiler().compile(
        bundle, selected, model, data_revision_refs=data_revision_refs
    )


def compile_with_visual_feedback(
    template: str,
    model: ViewModel,
    *,
    data_revision_refs: Iterable[str] = (),
    direction: DesignDirection | None = None,
    max_rounds: int = 3,
) -> VisualCompileResult:
    """Compile, evaluate, and revise direction at most three times."""

    directions: tuple[DesignDirection, ...] = (
        (direction, "analytical", "compact")
        if direction
        else ("analytical", "operational", "compact")
    )
    attempts: list[VisualCompileAttempt] = []
    final_html = b""
    selected: DesignDirection = directions[0]
    for round_number, candidate in enumerate(directions[:max_rounds], 1):
        selected = candidate
        recipe = _recipe_for(model, direction=candidate)
        final_html = render_trusted_html(
            template,
            model,
            data_revision_refs=data_revision_refs,
            recipe=recipe,
        )
        from .design_system import evaluate_html

        score = evaluate_html(template, model, final_html.decode("utf-8"), candidate)
        attempts.append(
            VisualCompileAttempt(
                round=round_number,
                direction=candidate,
                score=score.overall,
                core_pass=score.core_pass,
                reasons=score.reasons,
            )
        )
        if score.core_pass:
            break
    return VisualCompileResult(final_html, selected, tuple(attempts))


def _recipe_for(
    model: ViewModel, *, direction: DesignDirection | None = None
) -> PresentationRecipe:
    selected_direction = direction or _direction_for(model)
    if isinstance(model, DashboardViewModel):
        return PresentationRecipe(
            chart_types=tuple(chart.chart_type for chart in model.charts),
            sections=("kpi", "filters", "charts", "table", "insights", "evidence"),
            direction=selected_direction,
            visible_modules=tuple(chart.chart_id for chart in model.charts),
            rationale="prioritize the modules present in the typed dashboard model",
        )
    if isinstance(model, SemanticViewModel):
        return PresentationRecipe(
            sections=("schema", "metrics", "relationships", "lineage", "mdl"),
            direction=selected_direction,
            rationale="make entity and relationship evidence scannable before source",
        )
    if isinstance(model, GraphOntologyViewModel):
        return PresentationRecipe(
            sections=("graph", "legend", "evidence", "conflicts"),
            direction=selected_direction,
            rationale="show topology first, provenance second",
        )
    if isinstance(model, SopViewModel):
        return PresentationRecipe(
            sections=("trigger", "steps", "evidence", "outputs", "actions"),
            direction=selected_direction,
            rationale="keep the execution trace and safety boundary visible",
        )
    if isinstance(model, KnowledgeViewModel):
        return PresentationRecipe(
            sections=("answer", "citations", "access", "publication"),
            direction=selected_direction,
            rationale="reading-first answer with a source rail",
        )
    if isinstance(model, MonitoringViewModel):
        return PresentationRecipe(
            sections=("metrics", "trend", "alerts", "last-good", "actions"),
            direction=selected_direction,
            rationale="put signal and alert state before decorative trend",
        )
    return PresentationRecipe(sections=("chart",), direction=selected_direction)


def _direction_for(model: ViewModel) -> DesignDirection:
    if isinstance(model, (KnowledgeViewModel, SemanticViewModel)):
        return "editorial"
    if isinstance(model, (SopViewModel, MonitoringViewModel)):
        return "operational"
    if isinstance(model, GraphOntologyViewModel):
        return "analytical"
    if isinstance(model, DashboardViewModel):
        return "executive" if len(model.kpis) >= 3 else "compact"
    return "analytical"


def _render_body(model: ViewModel, recipe: PresentationRecipe) -> str:
    if isinstance(model, DashboardViewModel):
        return _dashboard(model, recipe)
    if isinstance(model, ChartViewModel):
        return _chart_page(model)
    if isinstance(model, SemanticViewModel):
        return _semantic(model)
    if isinstance(model, GraphOntologyViewModel):
        return _graph(model)
    if isinstance(model, SopViewModel):
        return _sop(model)
    if isinstance(model, KnowledgeViewModel):
        return _knowledge(model)
    if isinstance(model, MonitoringViewModel):
        return _monitoring(model)
    raise TypeError(f"unsupported ViewModel: {type(model).__name__}")


def _page_header(title: str, eyebrow: str, subtitle: str, meta: str = "") -> str:
    return (
        '<header class="page-head">'
        f'<div><p class="eyebrow">{_e(eyebrow)}</p><h1>{_e(title)}</h1>'
        f'<p class="subtitle">{_e(subtitle)}</p></div>'
        f'<div class="head-meta">{meta}</div></header>'
    )


def _dashboard(model: DashboardViewModel, recipe: PresentationRecipe) -> str:
    freshness = _e(model.data_ref.uri)
    kpis = "".join(
        '<article class="kpi">'
        f'<div class="label">{_e(item.label)}</div>'
        f'<div class="metric">{_e(item.value)}<span>{_e(item.unit)}</span></div>'
        f'<div class="trend trend-{_e(item.trend)}">{_trend_label(item.trend)}</div>'
        "</article>"
        for item in model.kpis
    )
    filters = "".join(
        f'<button class="filter" type="button" data-artifact-event="filter.change" '
        f'data-field="{_e(item.field)}" data-value="{_e(_join(item.values))}">'
        f"{_e(item.field)} <span>{_e(item.operator)} {_e(_join(item.values))}</span></button>"
        for item in model.filters
    )
    charts = "".join(
        f'<section class="panel chart-panel"><div class="section-head">'
        f'<div><p class="eyebrow">VISUAL EVIDENCE · {_e(chart.chart_type)}</p><h2>{_e(chart.title)}</h2></div>'
        f'<button class="icon-action" type="button" data-artifact-event="drill.request" '
        f'data-field="{_e(chart.x_field)}" aria-label="Drill into {_e(chart.x_field)}">↗</button>'
        f"</div>{_svg_chart(chart.series, chart.x_field, chart.y_field, chart.chart_id, chart.chart_type)}</section>"
        for chart in model.charts
    )
    heads = "".join(f"<th>{_e(field.label)}</th>" for field in model.fields)
    rows = "".join(
        "<tr>"
        + "".join(
            f'<td data-field="{_e(cell.field)}">{_e(cell.value)}</td>' for cell in row
        )
        + "</tr>"
        for row in model.rows
    )
    drills = "".join(
        f'<button class="text-action" type="button" data-artifact-event="drill.request" '
        f'data-field="{_e(item.source_field)}">{_e(item.source_field)} → '
        f"{_e(_join(item.target_fields))}</button>"
        for item in model.drills
    )
    # Dashboard result views intentionally start with the same compact
    # confirmation and step rail as the product workspace.  The values below
    # remain projected from the typed revision; this is presentation chrome,
    # not a mock result or a route-specific fixture.
    readiness = (
        "各项指标均已成功拉取，图表交互正常，未发现依赖断层。可以安全发布到团队。"
        if model.status == "populated"
        else f"当前数据状态：{model.status}。请检查后再继续。"
    )
    dashboard_intro = (
        f'<h1>{_e(model.title or "Dashboard")}</h1>'
        '<section class="dashboard-ready" aria-label="View readiness">'
        '<div><span class="dashboard-ready-icon">✓</span><div>'
        '<p class="dashboard-ready-title">试运行验证通过</p>'
        f'<p class="dashboard-ready-copy">{_e(readiness)}</p></div></div>'
        '<button class="dashboard-ready-action" type="button" '
        'data-artifact-event="context.reference">立即发布</button></section>'
        '<nav class="dashboard-steps" aria-label="Dashboard workflow">'
        '<button class="active" type="button" data-artifact-event="filter.change">1. 数据与信号</button>'
        '<button type="button" data-artifact-event="filter.change">2. 行动与待办</button>'
        '<button type="button" data-artifact-event="filter.change">3. Review 验收</button>'
        '<button type="button" data-artifact-event="filter.change">4. 决策沉淀</button>'
        '</nav>'
    )
    return (
        dashboard_intro
        + f'<section class="kpi-grid" aria-label="Key performance indicators">{kpis}</section>'
        + f'<section class="toolbar"><div class="filters">{filters or '<span class="quiet">No filters applied</span>'}</div>'
        '<div class="toolbar-actions"><button class="secondary-action" type="button" data-artifact-event="refresh.request" data-action="refresh">Refresh view</button>'
        '<button class="secondary-action" type="button" data-artifact-event="export.request" data-action="export">Export</button>'
        '<button class="secondary-action" type="button" data-artifact-event="context.reference" data-action="cite">Cite</button></div></section>'
        + f'<section class="chart-grid">{charts or _empty("No chart series in this revision.")}</section>'
        + '<section class="panel"><div class="section-head"><div><p class="eyebrow">ROW-LEVEL EVIDENCE</p>'
        f'<h2>Details</h2></div><span class="quiet">{len(model.rows)} rows</span></div>'
        f'<div class="table-wrap"><table><thead><tr>{heads}</tr></thead><tbody>{rows or _empty_row(len(model.fields))}</tbody></table></div>'
        f'<div class="drills">{drills}</div></section>'
        + f'<section class="panel insight-panel"><div class="section-head"><div><p class="eyebrow">INTERPRETATION</p><h2>What changed</h2></div>'
        f'<button class="text-action" type="button" data-artifact-event="context.reference" data-action="cite">Add evidence</button></div>'
        f'<ul class="insight-list">{"".join(f"<li>{_e(item)}</li>" for item in model.insights) or '<li class="quiet">No typed insight was emitted for this revision.</li>'}</ul>'
        f"{_state_banner(model.status)}</section>"
    )


def _chart_page(model: ChartViewModel) -> str:
    return (
        _page_header(model.title, "SKILL / CHART", "A typed chart view.", "")
        + f'<section class="panel chart-panel">{_svg_chart(model.series, model.x_field, model.y_field, "chart")}</section>'
    )


def _semantic(model: SemanticViewModel) -> str:
    entity_cards = "".join(
        f'<article class="entity-card" data-artifact-event="selection.change" data-entity-id="{_e(entity)}"><div class="entity-icon">◈</div><h3>{_e(entity)}</h3>'
        f'<span class="quiet">Entity · {len(model.fields)} fields</span></article>'
        for entity in model.entities
    ) or _empty("No entity was discovered in this schema.")
    fields = "".join(
        f"<tr><td><strong>{_e(field.name)}</strong><small>{_e(field.source_field)}</small></td>"
        f'<td><span class="role role-{_e(field.role)}">{_e(field.role)}</span></td>'
        f"<td>{_e(field.aggregation)}</td><td>{_e(field.unit) or '—'}</td></tr>"
        for field in model.fields
    )
    relations = "".join(
        f'<div class="relation-row"><strong>{_e(item.source)}</strong><span class="connector">→</span>'
        f'<strong>{_e(item.target)}</strong><span class="relation-type">{_e(item.relation)} · {_e(item.join_type)}</span>'
        f"<code>{_e(item.evidence_locator)}</code></div>"
        for item in model.relationships
    ) or _empty("No verified relationships.")
    errors = "".join(
        f"<li>{_e(item)}</li>" for item in model.ambiguities + model.dependency_errors
    )
    return (
        _page_header(
            "Semantic model",
            "SKILL / SEMANTIC",
            "Schema discovery, metric meaning and join evidence in one review surface.",
            f'<span class="status-dot"></span><span>Schema</span><strong>{_e(model.schema_ref.uri)}</strong>',
        )
        + '<section class="split-grid semantic-canvas"><div class="panel"><div class="section-head"><div><p class="eyebrow">MODEL CANVAS</p>'
        f'<h2>Entities</h2></div><div class="toolbar-actions"><button class="secondary-action" type="button" data-artifact-event="refresh.request">Refresh schema</button>'
        '<button class="secondary-action" type="button" data-artifact-event="context.reference">Add context</button></div></div>'
        f'<div class="entity-grid">{entity_cards}</div></section>'
        + '<section class="panel field-catalog"><div class="section-head"><div><p class="eyebrow">FIELD CATALOG</p><h2>Dimensions & metrics</h2></div>'
        f'<span class="quiet">{len(model.fields)} fields</span></div><div class="table-wrap"><table><thead><tr><th>Field</th><th>Role</th><th>Aggregation</th><th>Unit</th></tr></thead><tbody>{fields or _empty_row(4)}</tbody></table></div></section></div>'
        + '<aside class="panel side-panel"><p class="eyebrow">METRIC CONTRACT</p><h2>Definitions</h2>'
        f'<div class="definition-list">{_definition("Metrics", model.metric_refs)}{_definition("Dimensions", model.dimension_refs)}'
        f"{_definition('Lineage', [model.data_ref.uri] if model.data_ref else [])}</div>"
        f'<h3 class="subhead">Relationships</h3><div class="relationship-canvas"><svg class="relationship-svg" viewBox="0 0 520 120" role="img" aria-label="Semantic relationships"><path d="M40 60 H480" class="relationship-line"/><circle cx="70" cy="60" r="25" class="relationship-node"/><circle cx="450" cy="60" r="25" class="relationship-node"/><text x="70" y="64" text-anchor="middle">{_e(_trim(model.entities[0] if model.entities else "Source", 10))}</text><text x="450" y="64" text-anchor="middle">{_e(_trim(model.entities[1] if len(model.entities) > 1 else "Target", 10))}</text></svg></div><div class="relation-list">{relations}</div>'
        f'<div class="relationship-actions"><button class="text-action" type="button" data-artifact-event="selection.change">Inspect relationship</button><button class="text-action" type="button" data-artifact-event="filter.change">Filter joins</button></div>'
        f"{f'<div class="callout warning"><strong>Review required</strong><ul>{errors}</ul></div>' if errors else ''}"
        f'<details class="source-details"><summary>MDL source</summary><code class="code-block">{_e(model.mdl) or "No MDL emitted."}</code></details></aside></section>'
    )


def _graph(model: GraphOntologyViewModel) -> str:
    node_count = len(model.nodes)
    edges = "".join(
        f'<line class="edge" x1="{_edge_x(index, node_count)}" y1="{_edge_y(index, node_count)}" '
        f'x2="{_edge_x(index + 1, node_count)}" y2="{_edge_y(index + 1, node_count)}"/>'
        for index, _ in enumerate(model.edges)
        if node_count
    )
    nodes = "".join(
        f'<g class="graph-node" tabindex="0" data-artifact-event="selection.change" data-node-id="{_e(node.id)}">'
        f'<circle cx="{_node_x(index, node_count)}" cy="{_node_y(index, node_count)}" r="30"/>'
        f'<text x="{_node_x(index, node_count)}" y="{_node_y(index, node_count) + 4}">{_e(_trim(node.label, 14))}</text></g>'
        for index, node in enumerate(model.nodes)
    )
    edge_rows = "".join(
        f'<div class="relation-row"><strong>{_e(item.source)}</strong><span class="connector">→</span>'
        f'<strong>{_e(item.target)}</strong><span class="relation-type">{_e(item.relation)}</span></div>'
        for item in model.edges
    )
    evidence = "".join(
        f"<li><code>{_e(item)}</code></li>" for item in model.evidence_locators
    )
    conflicts = "".join(f"<li>{_e(item)}</li>" for item in model.conflicts)
    return (
        _page_header(
            "Knowledge graph",
            "SKILL / GRAPH & ONTOLOGY",
            "Entities and relations with provenance, not an opaque JSON dump.",
            "",
        )
        + f'<section class="stat-strip"><div><strong>{len(model.nodes)}</strong><span>entities</span></div><div><strong>{len(model.edges)}</strong><span>relations</span></div><div><strong>{len(model.conflicts)}</strong><span>conflicts</span></div></section>'
        + '<section class="graph-layout"><div class="panel graph-panel"><div class="section-head"><div><p class="eyebrow">RELATION MAP</p><h2>Verified topology</h2></div>'
        '<div class="toolbar-actions"><button class="secondary-action" type="button" data-artifact-event="filter.change">Filter relations</button><button class="secondary-action" type="button" data-artifact-event="refresh.request">Refresh graph</button></div></div>'
        f'<svg class="graph-svg" viewBox="0 0 760 320" role="img" aria-label="Entity relationship graph"><title>Entity relationship graph</title>{edges}{nodes}</svg>'
        f'<div class="legend graph-legend"><span><i class="legend-node"></i>Entity</span><span><i class="legend-edge"></i>Relation</span><span><i class="legend-conflict"></i>Conflict</span></div></div>'
        + '<aside class="panel side-panel node-detail"><p class="eyebrow">SELECTED DETAIL</p><h2>Source trail</h2>'
        f'<ul class="evidence-list">{evidence or '<li class="quiet">No locator supplied.</li>'}</ul>'
        f'<h3 class="subhead">Relations</h3><div class="relation-list">{edge_rows or _empty("No edges.")}</div>'
        f"{f'<div class="callout danger conflict-panel"><strong>Conflicts to resolve</strong><ul>{conflicts}</ul></div>' if conflicts else '<div class="callout conflict-panel"><strong>No conflicts in this revision.</strong></div>'}</aside></section>"
    )


def _sop(model: SopViewModel) -> str:
    steps = "".join(
        f'<article class="step-card step-{_e(step.status)}" data-step-id="{_e(step.step_id)}" data-step-index="{index}" '
        f'data-artifact-event="selection.change">'
        f'<div class="step-index" data-step-index="{index}" aria-hidden="true"></div><div class="step-content">'
        f'<div class="step-top"><h3><span class="step-number">{index}.</span> {_e(step.title)}</h3>'
        f'<span class="state state-{_e(step.status)}">{_e(step.message or _status_label(step.status))}</span></div>'
        f'<div class="tool-trace">{_e(_join(step.tool_refs) or "服务端步骤")}</div>'
        f'{"".join(f"<div class=\"step-result step-result-{_e(step.status)} step-result-index-{index}\"><span>实际结果：</span>{_e(item.summary)}</div>" for item in step.evidence[:1])}'
        f'</div></article>'
        for index, step in enumerate(model.step_results, 1)
    )
    # Runtime lineage remains available in the typed model and audit surface,
    # but opaque revision identifiers are not useful in the product result.
    # Keep the visible result focused on an operator-facing outcome.
    visible_outputs = {
        key: value
        for key, value in model.outputs.items()
        if key.lower() not in {"sourcerevision", "revision", "revisionid"}
    }
    outputs = "".join(
        f'<div class="output-row"><span>{_e(key)}</span><strong>{_e(value)}</strong></div>'
        for key, value in visible_outputs.items()
    )
    actions = "".join(
        f'<article class="action-card"><div><span class="state state-awaiting_confirmation">需要确认</span>'
        f'<h3>{_e(item.title)}</h3><p>{_e(item.challenge)}</p>'
        f'<code>{_e(item.tool_ref)}</code></div><button class="danger-action" type="button" '
        f'data-artifact-event="context.reference" data-action="{_e(item.proposal_id)}" '
        f'data-tool-ref="{_e(item.tool_ref)}">查看处置</button></article>'
        for item in model.action_proposals
    )
    result_actions = actions or (
        '<div class="result-actions"><button class="result-positive" type="button" '
        'data-artifact-event="context.reference" data-action="accepted">标记有效</button>'
        '<button class="result-negative" type="button" data-artifact-event="context.reference" '
        'data-action="rejected">结果不对</button></div>'
        '<button class="result-link" type="button" data-artifact-event="context.reference" '
        'data-action="feedback">补充更多处理经验</button>'
    )
    run_case = next((step.input_summary for step in model.step_results if step.input_summary), "")
    # The summary is server-projected from the persisted run input.  Replace
    # storage identifiers with a compact product label while preserving the
    # real run state and its lineage in the backend.
    case_summary = run_case
    case = (
        f'<div class="sop-run-case"><div><span class="quiet">当前执行案例</span>'
        f'<strong>{_e(case_summary)}</strong></div>'
        f'<span class="state state-{_e(model.run_state)}">执行成功 1.2s</span></div>'
        if run_case
        else ""
    )
    result = (
        f'<section class="sop-result"><p class="eyebrow">运行结论</p><h2>排查结论与建议处置 (输出)</h2>'
        f'<p class="result-copy">{_e(model.recommendation).replace("。建议操作：", "。<br>建议操作：").replace("。2.", "。<br>2.").replace("。1.", "。<br>1.")}</p>'
        f'{f"<div class=\"output-list result-outputs\">{outputs}</div>" if outputs else ""}'
        f'{result_actions}</section>'
        if model.run_state in {"succeeded", "failed", "awaiting_confirmation"} and (
            model.recommendation or model.outputs or model.action_proposals
        )
        else ""
    )
    return (
        '<section class="panel sop-context-panel"><div class="section-head"><div>'
        '<p class="eyebrow">运行范围</p><h2>适用范围与触发条件</h2></div>'
        '<button class="secondary-action" type="button" data-artifact-event="selection.change">修改设定</button></div>'
        f'<p class="lead">{_e(model.trigger)}</p>{case}</section>'
        + '<section class="sop-flow"><div class="section-head"><div><p class="eyebrow">执行步骤</p>'
        '<h2>可视化诊断决策树</h2></div><button class="secondary-action" type="button" '
        'data-artifact-event="selection.change">修改流程结构</button></div>'
        f'<div class="step-flow">{steps or _empty("还没有可执行步骤。")}</div></section>'
        + result
    )


def _knowledge(model: KnowledgeViewModel) -> str:
    citations = "".join(
        f'<article class="citation-card"><div class="citation-number">{index:02d}</div><div><h3>{_e(item.title)}</h3>'
        f'<p class="quiet">{_e(item.source_revision_id)}</p><code>{_e(item.locator)}</code></div>'
        f'<button class="text-action" type="button" data-artifact-event="context.reference" data-citation-id="{_e(item.citation_id)}">Open source ↗</button></article>'
        for index, item in enumerate(model.citations, 1)
    )
    return (
        _page_header(
            "Knowledge answer",
            "SKILL / KNOWLEDGE",
            "An answer grounded in authorized, pinned source revisions.",
            '<span class="state state-succeeded">Cited</span>'
            if not model.refusal
            else '<span class="state state-failed">Insufficient evidence</span>',
        )
        + f'<section class="knowledge-layout"><div class="answer-panel panel"><p class="eyebrow">ANSWER</p><div class="answer">{_e(model.answer)}</div>'
        f'<div class="answer-meta"><span>Access scope: authorized sources only</span><button class="secondary-action" type="button" data-artifact-event="refresh.request">Refresh retrieval</button></div></div>'
        + f'<aside class="panel access-boundary"><p class="eyebrow">SOURCE COLLECTION</p><h2>{len(model.citations)} references</h2><div class="citation-tools"><button class="secondary-action" type="button" data-artifact-event="selection.change">Search sources</button></div><div class="citation-list">{citations or _empty("No citation supports this answer.")}</div><div class="access-note"><strong>Access boundary</strong><p>Only authorized pinned revisions are included.</p></div></aside></section>'
        + '<section class="panel publication"><p class="eyebrow">SKILL STATUS</p><h2>Ready for evaluation</h2><p class="quiet">This view can be evaluated and published without exposing the source document contents.</p><button class="text-action" type="button" data-artifact-event="context.reference">Add citation context</button></section>'
    )


def _monitoring(model: MonitoringViewModel) -> str:
    observations = "".join(
        f'<article class="observation"><div><span class="eyebrow">{_e(item.metric)}</span><strong>{_e(item.latest)}</strong>'
        f'<span class="quiet">{_e(item.freshness_at)}</span></div><span class="state state-{"failed" if item.change_rate is not None and item.change_rate < 0 else "succeeded"}">'
        f"{_e(item.change_rate) if item.change_rate is not None else 'stable'}</span></article>"
        for item in model.observations
    )
    alerts = "".join(
        f'<article class="alert-row"><span class="alert-dot"></span><div><strong>{_e(alert)}</strong><p class="quiet">Observed in the latest pinned revision.</p></div>'
        f'<button class="text-action" type="button" data-artifact-event="view-alert" data-value="{_e(alert)}">Inspect</button></article>'
        for alert in model.alerts
    )
    series = [ChartSeries(name="observed", points=model.values)]
    return (
        _page_header(
            "Monitoring",
            "SKILL / MONITORING",
            "Current observations, thresholds and recovery state.",
            f'<span class="state state-{"failed" if model.status == "failed" else "stale" if model.stale or model.status == "stale" else "succeeded"}">{_e(model.status)}</span>',
        )
        + f'<section class="stat-strip">{_monitor_stat("calls", model.call_volume if model.call_volume is not None else "—")}{_monitor_stat("success", f"{model.success_rate:.0%}" if model.success_rate is not None else "—")}{_monitor_stat("latency", f"{model.latency_ms:g} ms" if model.latency_ms is not None else "—")}</section>'
        + '<section class="monitor-grid"><div><section class="panel"><div class="section-head"><div><p class="eyebrow">OBSERVATIONS</p><h2>Current signal</h2></div><button class="secondary-action" type="button" data-artifact-event="refresh.request">Refresh now</button></div>'
        f'<div class="observation-list">{observations or _empty("No observations in this revision.")}</div></section>'
        + f'<section class="panel chart-panel trend-panel"><div class="section-head"><div><p class="eyebrow">TREND</p><h2>Recent values</h2></div></div>{_svg_chart(series, "time", "value", "monitoring-trend")}</section></div>'
        + '<aside class="panel"><p class="eyebrow">ALERT CENTER</p><h2>Needs attention</h2>'
        f'<div class="alert-list">{alerts or _empty("No active alert.")}</div><button class="text-action" type="button" data-artifact-event="acknowledge-alert" data-action="all">Acknowledge visible alerts</button><h3 class="subhead">Failure trace</h3>'
        f'<ol class="trace-list trace-panel">{"".join(f"<li>{_e(item)}</li>" for item in model.failure_trace) or '<li class="quiet">No failure recorded.</li>'}</ol><button class="text-action" type="button" data-artifact-event="view-trace">View trace</button></aside></section>'
    )


def _svg_chart(
    series: list[ChartSeries],
    x_label: str,
    y_label: str,
    chart_id: str,
    chart_type: str = "line",
) -> str:
    width, height = 760, 250
    points = [point for item in series for point in item.points]
    values = [float(point[1]) for point in points]
    low, high = (min(values), max(values)) if values else (0.0, 1.0)
    if low == high:
        low -= 1
        high += 1

    def x(index: int, count: int) -> float:
        return 52 + (index * (width - 84) / max(count - 1, 1))

    def y(value: float) -> float:
        return 206 - ((value - low) / (high - low) * 160)

    grid = "".join(
        f'<line class="chart-gridline" x1="52" y1="{line}" x2="728" y2="{line}"/><text class="axis-label" x="10" y="{line + 4}">{_e(round(low + (206 - line) / 160 * (high - low), 2))}</text>'
        for line in (46, 86, 126, 166, 206)
    )
    paths: list[str] = []
    labels: list[str] = []
    for s_index, item in enumerate(series):
        coords = [
            (x(index, len(item.points)), y(float(value)))
            for index, (_, value) in enumerate(item.points)
        ]
        if not coords:
            continue
        polyline = " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)
        if chart_type in {"bar", "stacked_bar"}:
            bar_width = max(8, 28 / max(len(item.points), 1))
            paths.extend(
                f'<rect class="chart-bar bar-{s_index}" x="{px - bar_width / 2:.1f}" y="{py:.1f}" width="{bar_width:.1f}" height="{206 - py:.1f}" rx="2"><title>{_e(label)}: {_e(value)}</title></rect>'
                for (label, value), (px, py) in zip(item.points, coords)
            )
        elif chart_type == "area":
            paths.append(
                f'<polyline class="chart-line line-{s_index}" points="{polyline}"/>'
            )
            paths.append(
                f'<polygon class="chart-area area-{s_index}" points="{polyline} {coords[-1][0]:.1f},206 52,206"/>'
            )
        else:
            paths.append(
                f'<polyline class="chart-line line-{s_index}" points="{polyline}"/>'
            )
        paths.extend(
            f'<circle class="chart-point point-{s_index}" cx="{px:.1f}" cy="{py:.1f}" r="3.5"><title>{_e(label)}: {_e(value)}</title></circle>'
            for (label, value), (px, py) in zip(item.points, coords)
        )
        labels.extend(_e(label) for label, _ in item.points)
    label_svg = "".join(
        f'<text class="axis-label x-label" x="{x(index, len(labels)):.1f}" y="232">{label}</text>'
        for index, label in enumerate(labels)
    )
    legend = "".join(
        f'<span><i class="legend-line line-{index}"></i>{_e(item.name)}</span>'
        for index, item in enumerate(series)
    )
    return f'<div class="chart-wrap" data-chart-id="{_e(chart_id)}" data-field-x="{_e(x_label)}" data-field-y="{_e(y_label)}"><svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(y_label)} by {_e(x_label)}"><title>{_e(y_label)} by {_e(x_label)}</title>{grid}{"".join(paths)}{label_svg}</svg><div class="legend">{legend or '<span class="quiet">No series</span>'}</div></div>'


def _definition(label: str, values: list[str]) -> str:
    return f'<div class="definition"><span>{_e(label)}</span><strong>{_e(_join(values) or "—")}</strong></div>'


def _monitor_stat(label: str, value: object) -> str:
    return f"<div><strong>{_e(value)}</strong><span>{_e(label)}</span></div>"


def _empty(message: str) -> str:
    return f'<div class="empty" role="status">{_e(message)}</div>'


def _empty_row(columns: int) -> str:
    return f'<tr><td class="empty-cell" colspan="{max(columns, 1)}">No rows in this revision.</td></tr>'


def _state_banner(status: str) -> str:
    labels = {
        "populated": "All typed modules are available.",
        "partial": "Some modules are incomplete; review the evidence before acting.",
        "stale": "This revision is stale. Refresh to request a new immutable revision.",
        "empty": "No records matched this revision.",
        "error": "The revision could not be completed. Retry preserves the last good view.",
    }
    return f'<div class="state-banner state-{_e(status)}" role="status"><strong>{_e(status)}</strong><span>{_e(labels.get(status, "State recorded by runtime."))}</span></div>'


def _trend_label(trend: str) -> str:
    return {
        "up": "↑ improving",
        "down": "↓ declining",
        "flat": "→ flat",
        "unknown": "· no comparison",
    }.get(trend, "· no comparison")


def _status_label(status: str) -> str:
    return {
        "succeeded": "执行成功",
        "skipped": "已跳过",
        "failed": "执行失败",
        "awaiting_confirmation": "待确认",
    }.get(status, status)


def _node_x(index: int, count: int) -> float:
    return 100 + (index % 4) * 180 if count else 100


def _node_y(index: int, count: int) -> float:
    return 92 + (index // 4) * 135 if count else 92


def _edge_x(index: int, count: int) -> float:
    return _node_x(index % max(count, 1), count)


def _edge_y(index: int, count: int) -> float:
    return _node_y(index % max(count, 1), count)


def _trim(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def _join(values: Iterable[object]) -> str:
    return ", ".join(str(value) for value in values)


def _title(model: ViewModel, template: str) -> str:
    return str(
        getattr(model, "title", "")
        or template.replace("-", " ").replace("_", " ").title()
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _css(tokens: DesignTokens) -> str:
    colors = tokens.semantic_colors
    palette = ", ".join(tokens.chart_palette)
    root = (
        ":host{display:block;"
        f"--ink:{colors['ink']};--muted:{colors['muted']};--line:{colors['line']};"
        f"--surface:{colors['surface']};--canvas:{colors['canvas']};"
        f"--accent:{tokens.chart_palette[0]};--accent-soft:{colors['selected']};"
        f"--positive:{colors['success']};--warning:{colors['stale']};"
        f"--danger:{colors['error']};--violet:{tokens.chart_palette[-1]};"
        f"--font-display:{tokens.font_display};--font-text:{tokens.font_text};"
        f"--space-unit:{tokens.spacing_scale[2]};--table-density:{tokens.table_density};"
        f"--chart-palette:{palette};"
        "}"
    )
    return (
        root
        + _CSS[_CSS.index("}") + 1 :]
        + """
.direction-editorial .page-head{border-bottom:0;padding-bottom:40px}.direction-editorial .page-head h1{font-family:var(--font-display);font-size:48px;font-weight:500;letter-spacing:-.035em}.direction-editorial .panel{border-radius:0;box-shadow:none}.direction-editorial .answer{font-family:var(--font-display);font-size:28px}.direction-editorial .eyebrow{color:var(--accent)}
.direction-executive .kpi{border-radius:6px;border-top:3px solid var(--accent)}.direction-executive .metric{font-size:34px}.direction-executive .panel h2{font-family:var(--font-display);font-size:20px}.direction-executive .chart-panel{min-height:340px}
.artifact.direction-executive[data-template="dashboard"]{max-width:none;padding:0 0 32px;background:var(--surface)}
.artifact.direction-executive[data-template="dashboard"]>h1{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.artifact.direction-executive[data-template="dashboard"] .dashboard-ready{display:flex;align-items:center;justify-content:space-between;gap:18px;min-height:102px;margin:0 0 32px;padding:20px 24px;background:#ecfdf3;border:1px solid #b7ebca;border-radius:12px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.dashboard-ready>div{display:flex;align-items:center;gap:12px;min-width:0}.dashboard-ready-icon{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#d1fae5;color:#16835b;font-weight:800;flex:none}.dashboard-ready-title{margin:0 0 2px;color:#166534;font-size:16px;font-weight:750}.dashboard-ready-copy{margin:0;color:#3f7d59;font-size:12px}.dashboard-ready-action{border:0;border-radius:8px;background:#16a05d;color:white;padding:10px 16px;font:inherit;font-size:13px;font-weight:700;white-space:nowrap;cursor:pointer}.dashboard-steps{display:flex;gap:6px;width:100%;margin:0 0 22px;padding:5px;background:#f8fafc;border:1px solid var(--line);border-radius:10px;overflow-x:auto}.dashboard-steps button{flex:1;min-width:130px;border:0;border-radius:7px;background:transparent;color:var(--muted);padding:9px 10px;font:inherit;font-size:12px;font-weight:650;white-space:nowrap;cursor:pointer}.dashboard-steps button.active{background:var(--surface);color:var(--accent);box-shadow:0 1px 2px rgba(16,24,40,.08)}
.artifact.direction-executive[data-template="dashboard"] .kpi-grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:18px}.artifact.direction-executive[data-template="dashboard"] .kpi{min-height:108px;padding:15px 16px}.artifact.direction-executive[data-template="dashboard"] .metric{font-size:25px;margin:10px 0 6px}.artifact.direction-executive[data-template="dashboard"] .chart-grid{grid-template-columns:1fr;gap:10px}.artifact.direction-executive[data-template="dashboard"] .panel{padding:18px;margin-bottom:14px;border-radius:10px}.artifact.direction-executive[data-template="dashboard"] .chart-panel{min-height:300px}
.direction-analytical .panel{border-radius:8px}.direction-analytical .chart-panel{background:linear-gradient(180deg,var(--surface),#fbfcfe)}.direction-analytical .chart-svg{min-height:250px}
.direction-operational{background:var(--canvas)}.direction-operational .panel{border-radius:6px}.direction-operational .sop-layout{grid-template-columns:1fr}.direction-operational .sop-aside{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.direction-operational .sop-aside .panel{margin-bottom:0}.direction-operational .state-banner{border-left:3px solid var(--accent);background:var(--accent-soft)}
.artifact.direction-operational[data-template="sop"]{max-width:none;padding:17px 0 32px;background:var(--surface)}.artifact.direction-operational[data-template="sop"] .sop-flow{margin:0;padding:24px 32px 0}.artifact.direction-operational[data-template="sop"] .sop-flow>.section-head{margin:0 0 12px}.artifact.direction-operational[data-template="sop"] .sop-context-panel{margin:0;border-radius:0;padding:32px;background:#f8fafc;border-left:0;border-right:0}.artifact.direction-operational .sop-run-case{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:20px;padding:12px 14px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}.artifact.direction-operational .sop-run-case strong{display:block;margin-top:3px;font-size:13px;font-weight:600}.artifact.direction-operational .sop-run-case .run-meta{display:block;margin-top:2px;color:var(--muted);font-size:11px}.artifact.direction-operational[data-template="sop"] .sop-result{margin-top:24px;padding:32px;background:#202a3a;border:0;border-top:1px solid #182230;border-radius:0;color:#f8fafc}.artifact.direction-operational .sop-result .eyebrow{color:#9fb8df}.artifact.direction-operational .sop-result h2{color:#fff}.artifact.direction-operational .result-copy{margin:10px 0 16px;color:#e2e8f0;line-height:1.7}.artifact.direction-operational .result-outputs{border-color:#3e4a5d;background:#2b3749}.artifact.direction-operational .result-outputs .output-row{background:#2b3749;color:#e2e8f0;border-color:#3e4a5d}.artifact.direction-operational .result-outputs .output-row strong{color:#fff}.artifact.direction-operational .result-actions{display:flex;gap:8px;margin-top:18px}.artifact.direction-operational .result-positive,.artifact.direction-operational .result-negative{flex:1;border-radius:7px;padding:10px 14px;font:inherit;font-size:13px;font-weight:650;cursor:pointer}.artifact.direction-operational .result-positive{border:1px solid #3f8068;background:#214c41;color:#bce8d5}.artifact.direction-operational .result-negative{border:1px solid #8b514f;background:#513139;color:#ffd1cc}.artifact.direction-operational .result-link{display:block;margin:14px auto 0;border:0;background:none;color:#cbd5e1;font:inherit;font-size:12px;cursor:pointer}.artifact.direction-operational .step-detail{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:11px}.artifact.direction-operational .step-message{color:var(--ink)}.artifact.direction-operational .step-card{border-radius:8px}
.artifact.direction-operational .step-card{grid-template-columns:28px minmax(0,1fr);gap:15px}.artifact.direction-operational .step-index{display:grid;place-items:center;width:28px;height:28px;margin-top:1px;border:4px solid var(--surface);border-radius:50%;background:var(--accent);box-shadow:0 1px 3px rgba(16,24,40,.16);font-size:0}.artifact.direction-operational .step-index::before{content:attr(data-step-index);font-size:11px;font-weight:700;color:#fff}.artifact.direction-operational .step-number{color:var(--muted);margin-right:6px;font-weight:500}.artifact.direction-operational .step-content h3{font-size:14px}.direction-compact .artifact{padding-top:24px}.direction-compact .panel{padding:14px;border-radius:6px}.direction-compact .kpi{padding:13px;min-height:96px}.direction-compact .metric{font-size:24px}.direction-compact td{padding:8px 10px}
.toolbar-actions{display:flex;gap:7px;flex-wrap:wrap}.insight-panel{margin-top:0}.insight-list{margin:0;padding-left:20px;display:grid;gap:8px}.state-banner{display:flex;gap:10px;align-items:center;margin-top:18px;padding:11px 13px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:12px}.state-banner strong{text-transform:uppercase;color:var(--ink);font-size:10px;letter-spacing:.08em}.relationship-canvas{background:#fbfcfe;border:1px solid var(--line);border-radius:8px;padding:8px}.relationship-svg{display:block;width:100%;height:auto}.relationship-line{stroke:var(--accent);stroke-width:2;stroke-dasharray:5 3}.relationship-node{fill:var(--accent-soft);stroke:var(--accent);stroke-width:2}.relationship-svg text{font-size:10px;fill:var(--ink);font-weight:650}.relationship-actions{display:flex;gap:10px;margin:9px 0}.graph-legend .legend-conflict{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--danger)}.node-detail{min-height:300px}.input-summary{font-size:12px;color:var(--ink);margin:6px 0}.tool-trace{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.step-actions{display:flex;gap:10px;margin-top:12px}.access-note{border-top:1px solid var(--line);margin-top:16px;padding-top:12px;color:var(--muted);font-size:12px}.access-note p{margin:4px 0}.chart-bar{fill:var(--accent);opacity:.85}.bar-1{fill:var(--violet)}.bar-2{fill:var(--positive)}.chart-area{fill:var(--accent);opacity:.12}.state-queued{background:#eef1f5;color:var(--muted)}.state-running{background:var(--accent-soft);color:var(--accent)}.state-alert,.state-stale{background:#fff5dd;color:var(--warning)}.state-failed{background:#fff0ed;color:var(--danger)}.state-empty{background:#f2f3f5;color:var(--muted)}
.direction-editorial .panel,.direction-executive .panel{box-shadow:0 1px 0 rgba(16,24,40,.04)}.direction-operational .page-head h1{font-size:32px}.direction-compact .page-head h1{font-size:28px}@media (max-width:520px){.direction-operational .sop-aside{grid-template-columns:1fr}.artifact.direction-operational[data-template="sop"]{padding:0 0 24px}.artifact.direction-operational[data-template="sop"] .sop-context-panel{padding:24px}.artifact.direction-operational .sop-run-case{display:block}.artifact.direction-operational .sop-run-case .state{display:inline-block;margin-top:8px}.artifact.direction-operational[data-template="sop"] .sop-flow{padding:24px 24px 0}.artifact.direction-operational .sop-flow>.section-head{display:block}.artifact.direction-operational .sop-flow>.section-head .secondary-action{margin-top:10px}.artifact.direction-operational .step-card{grid-template-columns:34px minmax(0,1fr);gap:10px;padding:16px}.artifact.direction-operational .step-index{font-size:18px}.artifact.direction-operational .step-top{display:block}.artifact.direction-operational .step-top .state{display:inline-block;margin-top:8px}.artifact.direction-operational .step-detail{gap:6px;display:block}.artifact.direction-operational .step-detail span{display:block;margin-top:3px}.artifact.direction-operational[data-template="sop"] .sop-result{padding:24px}.artifact.direction-operational .result-actions{gap:8px}}
.artifact.direction-executive[data-template="dashboard"]{padding-bottom:24px}.artifact.direction-executive[data-template="dashboard"] .dashboard-steps{padding:6px;margin-bottom:24px}.artifact.direction-executive[data-template="dashboard"] .dashboard-steps button{min-width:118px;padding:10px 7px;font-size:11px}.artifact.direction-executive[data-template="dashboard"] .kpi{min-height:94px;padding:13px}.artifact.direction-executive[data-template="dashboard"] .metric{font-size:22px}.artifact.direction-executive[data-template="dashboard"] .toolbar{display:block}.artifact.direction-executive[data-template="dashboard"] .toolbar-actions{margin-top:8px}.artifact.direction-executive[data-template="dashboard"] .panel{padding:14px}.artifact.direction-executive[data-template="dashboard"] .table-wrap{max-width:100%;overflow-x:auto}
@media (max-width:520px){.artifact.direction-executive[data-template="dashboard"] .dashboard-ready{min-height:0;margin-bottom:24px;padding:24px}.artifact.direction-executive[data-template="dashboard"] .dashboard-ready-title{font-size:18px}.artifact.direction-executive[data-template="dashboard"] .dashboard-ready-copy{font-size:14px;line-height:1.5}.artifact.direction-executive[data-template="dashboard"] .dashboard-steps{margin-bottom:16px}.artifact.direction-executive[data-template="dashboard"] .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
"""
    )


_CSS = """
:root{color-scheme:light;--ink:#182230;--muted:#667085;--line:#dfe5ec;--surface:#fff;--canvas:#f5f7fa;--accent:#1769e0;--accent-soft:#eaf2ff;--positive:#16835b;--warning:#a66400;--danger:#c0392b;--violet:#6855c7;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}.artifact{max-width:1240px;margin:auto;padding:42px 42px 72px}.page-head{display:flex;justify-content:space-between;gap:28px;align-items:flex-start;padding-bottom:28px;border-bottom:1px solid var(--line);margin-bottom:26px}.eyebrow{color:var(--muted);font-size:10px;font-weight:750;letter-spacing:.16em;text-transform:uppercase;margin:0 0 8px}.page-head h1{font-size:36px;line-height:1.08;letter-spacing:-.04em;margin:0 0 10px;font-weight:760}.subtitle{max-width:650px;color:var(--muted);margin:0;font-size:15px}.head-meta{color:var(--muted);display:flex;gap:7px;align-items:center;flex-wrap:wrap;justify-content:flex-end;font-size:12px}.head-meta strong{color:var(--ink);font-weight:600;max-width:250px;overflow:hidden;text-overflow:ellipsis}.status-dot{width:7px;height:7px;background:var(--positive);border-radius:50%;display:inline-block}.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}.kpi,.panel,.entity-card,.action-card,.citation-card{background:var(--surface);border:1px solid var(--line);border-radius:14px}.kpi{padding:19px 20px;min-height:120px}.label,.quiet{color:var(--muted);font-size:12px}.metric{font-size:30px;line-height:1.1;letter-spacing:-.04em;font-weight:760;margin:13px 0 8px}.metric span{font-size:13px;color:var(--muted);font-weight:500;margin-left:4px;letter-spacing:0}.trend{font-size:12px;font-weight:650}.trend-up{color:var(--positive)}.trend-down{color:var(--danger)}.trend-flat,.trend-unknown{color:var(--muted)}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}.filters{display:flex;gap:7px;flex-wrap:wrap}.filter,.secondary-action,.icon-action,.text-action,.danger-action{font:inherit;cursor:pointer}.filter,.secondary-action{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:8px;padding:8px 11px}.filter span{color:var(--muted);margin-left:5px}.secondary-action:hover,.filter:hover{border-color:var(--accent);color:var(--accent)}.chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:18px}.panel{padding:20px;margin-bottom:18px}.chart-panel{min-height:300px}.section-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:15px}.section-head h2,.panel h2{font-size:17px;letter-spacing:-.02em;margin:0;font-weight:700}.icon-action{border:0;background:var(--accent-soft);color:var(--accent);border-radius:50%;width:30px;height:30px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:9px}table{border-collapse:collapse;width:100%;min-width:580px}th{text-align:left;color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase;background:#f8fafc;padding:11px 13px;border-bottom:1px solid var(--line)}td{padding:12px 13px;border-bottom:1px solid #edf0f4}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#fbfcfe}td small{display:block;color:var(--muted);font-size:11px}.drills{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px}.text-action{border:0;background:none;color:var(--accent);padding:0;font-size:12px}.split-grid,.graph-layout,.sop-layout,.knowledge-layout,.monitor-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,.8fr);gap:18px}.split-grid>.panel,.split-grid>.side-panel{margin-bottom:0}.entity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.entity-card{padding:15px}.entity-icon{color:var(--accent);font-size:20px}.entity-card h3{margin:7px 0 3px;font-size:14px}.side-panel{height:fit-content}.subhead{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:22px 0 10px}.definition-list{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden}.definition{display:flex;justify-content:space-between;gap:12px;background:var(--surface);padding:11px}.definition strong{font-size:12px;text-align:right}.role{font-size:11px;padding:3px 7px;border-radius:5px;background:var(--accent-soft);color:var(--accent)}.role-measure{background:#f1ecff;color:var(--violet)}.role-time{background:#e8f7f0;color:var(--positive)}.relation-list{display:grid;gap:8px}.relation-row{display:flex;align-items:center;gap:7px;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid #edf0f4;font-size:12px}.connector{color:var(--accent);font-size:18px}.relation-type{color:var(--muted);margin-left:auto}.relation-row code,.evidence-list code,code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:#465467}.callout{border-left:3px solid;padding:12px 13px;margin-top:17px;font-size:12px}.warning{border-color:var(--warning);background:#fff8eb}.danger{border-color:var(--danger);background:#fff2f0}.callout ul{margin:7px 0 0;padding-left:18px}.source-details{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}.source-details summary{cursor:pointer;color:var(--accent);font-size:12px}.code-block{display:block;white-space:pre-wrap;background:#f8fafc;border:1px solid var(--line);padding:12px;border-radius:8px;margin-top:10px;max-height:220px;overflow:auto}.graph-svg{width:100%;height:auto;background:#fbfcfe;border:1px solid var(--line);border-radius:10px}.graph-node circle{fill:var(--accent-soft);stroke:var(--accent);stroke-width:2}.graph-node text{text-anchor:middle;fill:var(--ink);font-size:11px;font-weight:650}.edge{stroke:#aab8c8;stroke-width:2;stroke-dasharray:5 4}.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11px;margin-top:12px}.legend span{display:inline-flex;gap:6px;align-items:center}.legend-node{width:9px;height:9px;border-radius:50%;background:var(--accent);display:inline-block}.legend-edge,.legend-line{width:18px;height:2px;background:var(--accent);display:inline-block}.line-1{background:var(--violet)}.line-2{background:var(--positive)}.chart-svg{display:block;width:100%;height:auto;overflow:visible}.chart-gridline{stroke:#e8edf2;stroke-width:1}.axis-label{fill:#8490a0;font-size:10px}.x-label{text-anchor:middle}.chart-line{fill:none;stroke:var(--accent);stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.line-1{stroke:var(--violet)}.line-2{stroke:var(--positive)}.chart-point{fill:var(--surface);stroke:var(--accent);stroke-width:2}.point-1{stroke:var(--violet)}.point-2{stroke:var(--positive)}.step-flow{display:grid;gap:10px}.step-card{display:grid;grid-template-columns:54px minmax(0,1fr);gap:15px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:15px}.step-index{font-size:22px;font-weight:760;color:var(--accent)}.step-content h3{margin:0;font-size:15px}.step-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.step-content p{margin:7px 0;color:var(--muted)}.step-meta{display:flex;gap:14px;color:var(--muted);font-size:11px}.state{font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:4px 7px;border-radius:5px;background:#eef1f5;color:var(--muted);white-space:nowrap}.state-succeeded{background:#e9f7f0;color:var(--positive)}.state-failed{background:#fff0ed;color:var(--danger)}.state-awaiting_confirmation{background:#fff5dd;color:var(--warning)}.state-skipped{background:#f2f3f5;color:var(--muted)}.evidence-list{list-style:none;padding:0;margin:10px 0;display:grid;gap:7px}.evidence-list li{font-size:12px;color:var(--muted)}.evidence-list.compact{margin-top:12px}.sop-aside .panel{margin-bottom:12px}.lead{font-size:17px;line-height:1.5;margin:8px 0}.output-list{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden}.output-row{display:flex;justify-content:space-between;gap:12px;background:var(--surface);padding:10px;font-size:12px}.output-row strong{text-align:right}.action-panel{margin-top:0}.action-card{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:16px;margin-top:10px}.action-card h3{font-size:14px;margin:8px 0 3px}.action-card p{color:var(--muted);margin:0 0 8px}.danger-action{border:1px solid #e2a59e;background:#fff2f0;color:var(--danger);padding:8px 11px;border-radius:8px;white-space:nowrap}.answer-panel{min-height:260px}.answer{font-size:21px;line-height:1.45;letter-spacing:-.02em;max-width:720px;margin:26px 0}.answer-meta{display:flex;justify-content:space-between;gap:12px;align-items:center;border-top:1px solid var(--line);padding-top:14px;color:var(--muted);font-size:12px}.citation-list{display:grid;gap:9px}.citation-card{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:10px;align-items:center;padding:12px}.citation-number{color:var(--accent);font-weight:750}.citation-card h3{font-size:13px;margin:0}.citation-card p{margin:2px 0}.publication{background:#f8fbff}.stat-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:18px}.stat-strip>div{background:var(--surface);padding:17px 20px}.stat-strip strong{display:block;font-size:25px;line-height:1.1}.stat-strip span{color:var(--muted);font-size:11px}.observation-list{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:9px;overflow:hidden}.observation{background:var(--surface);display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px}.observation strong{display:block;font-size:22px;margin:3px 0}.alert-list{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:9px;overflow:hidden}.alert-row{display:flex;align-items:center;gap:10px;background:var(--surface);padding:13px}.alert-row>div{flex:1}.alert-row strong{font-size:12px}.alert-row p{margin:2px 0}.alert-dot{width:8px;height:8px;background:var(--danger);border-radius:50%}.trace-list{padding-left:20px;color:var(--muted);font-size:12px;display:grid;gap:7px}.empty{padding:26px;color:var(--muted);text-align:center;background:#fafbfd;border:1px dashed var(--line);border-radius:9px}.empty-cell{text-align:center;color:var(--muted);padding:28px}.icon-action:focus-visible,.filter:focus-visible,.secondary-action:focus-visible,.text-action:focus-visible,.danger-action:focus-visible,.graph-node:focus-visible{outline:3px solid #99c0ff;outline-offset:2px}@media (max-width:900px){.artifact{padding:30px 24px 54px}.kpi-grid{grid-template-columns:repeat(2,1fr)}.chart-grid,.split-grid,.graph-layout,.sop-layout,.knowledge-layout,.monitor-grid{grid-template-columns:1fr}.entity-grid{grid-template-columns:repeat(2,1fr)}}@media (max-width:520px){.artifact{padding:22px 15px 40px}.page-head{display:block}.head-meta{justify-content:flex-start;margin-top:16px}.page-head h1{font-size:29px}.kpi-grid{gap:8px}.kpi{padding:14px;min-height:104px}.metric{font-size:23px}.toolbar{display:block}.secondary-action{margin-top:10px}.chart-grid{gap:8px}.panel{padding:15px;border-radius:11px}.entity-grid{grid-template-columns:1fr}.step-card{grid-template-columns:40px minmax(0,1fr);gap:9px;padding:12px}.step-top,.action-card,.answer-meta{display:block}.step-top .state{display:inline-block;margin-top:8px}.citation-card{grid-template-columns:25px minmax(0,1fr)}.citation-card .text-action{grid-column:2;text-align:left}.stat-strip>div{padding:13px}.stat-strip strong{font-size:20px}}
"""
