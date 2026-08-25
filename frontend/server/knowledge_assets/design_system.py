"""Design directions, token contracts, and deterministic visual evaluation.

This module is deliberately data-only at the presentation boundary.  A
direction can change hierarchy and density, but never changes facts in a
typed ViewModel.  The evaluator reports observable quality signals from the
compiled document; it does not manufacture a passing score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contract_views import (
    DashboardViewModel,
    GraphOntologyViewModel,
    KnowledgeViewModel,
    MonitoringViewModel,
    SemanticViewModel,
    SopViewModel,
    ViewModel,
)

DesignDirection = Literal[
    "editorial",
    "executive",
    "analytical",
    "operational",
    "compact",
]


@dataclass(frozen=True)
class DesignTokens:
    """Complete visual vocabulary consumed by the trusted compiler."""

    direction: DesignDirection
    font_display: str
    font_text: str
    type_scale: tuple[str, ...]
    spacing_scale: tuple[str, ...]
    radius: tuple[str, ...]
    surfaces: tuple[str, ...]
    semantic_colors: dict[str, str]
    chart_palette: tuple[str, ...]
    table_density: str
    states: dict[str, str]


@dataclass(frozen=True)
class VisualEvaluationProfile:
    profile_id: str
    minimum_score: float = 4.0
    required_markers: tuple[str, ...] = ()
    required_events: tuple[str, ...] = ()
    required_states: tuple[str, ...] = ("empty", "error", "stale")


@dataclass(frozen=True)
class VisualScore:
    hierarchy: float
    readability: float
    information_density: float
    visual_balance: float
    chart_appropriateness: float
    responsive_quality: float
    contrast_accessibility: float
    content_completeness: float
    state_quality: float
    direction_consistency: float
    reasons: tuple[str, ...] = ()

    @property
    def overall(self) -> float:
        values = (
            self.hierarchy,
            self.readability,
            self.information_density,
            self.visual_balance,
            self.chart_appropriateness,
            self.responsive_quality,
            self.contrast_accessibility,
            self.content_completeness,
            self.state_quality,
            self.direction_consistency,
        )
        return round(sum(values) / len(values), 2)

    @property
    def core_pass(self) -> bool:
        return (
            min(
                self.hierarchy,
                self.readability,
                self.information_density,
                self.visual_balance,
                self.chart_appropriateness,
                self.responsive_quality,
                self.contrast_accessibility,
                self.content_completeness,
                self.state_quality,
                self.direction_consistency,
            )
            >= 4.0
        )


def tokens_for(direction: DesignDirection) -> DesignTokens:
    palettes = {
        "editorial": ("#17324d", "#b45309", "#0f766e", "#7c3aed"),
        "executive": ("#155eef", "#0f766e", "#b45309", "#6941c6"),
        "analytical": ("#1769e0", "#6855c7", "#16835b", "#c0392b"),
        "operational": ("#0f766e", "#d97706", "#c2410c", "#1769e0"),
        "compact": ("#344054", "#1769e0", "#7f56d9", "#d97706"),
    }
    colors = {
        "ink": "#182230",
        "muted": "#667085",
        "line": "#dfe5ec",
        "canvas": "#f5f7fa",
        "surface": "#ffffff",
        "selected": "#eaf2ff",
        "focus": "#99c0ff",
        "hover": "#f8fafc",
        "disabled": "#98a2b3",
        "error": "#c0392b",
        "stale": "#a66400",
        "success": "#16835b",
    }
    if direction == "editorial":
        colors.update(
            canvas="#f6f4ef", surface="#fffdf8", ink="#20211f", line="#e7e1d7"
        )
    elif direction == "operational":
        colors.update(canvas="#f2f7f6", surface="#ffffff", selected="#e4f3ef")
    return DesignTokens(
        direction=direction,
        font_display="ui-serif, Georgia, 'Times New Roman', serif"
        if direction == "editorial"
        else "Inter, ui-sans-serif, system-ui, sans-serif",
        font_text="ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
        type_scale=("11px", "12px", "14px", "16px", "20px", "28px", "38px"),
        spacing_scale=("4px", "8px", "12px", "16px", "24px", "32px", "48px"),
        radius=("0", "6px", "10px", "16px"),
        surfaces=(
            colors["canvas"],
            colors["surface"],
            colors["selected"],
            "#eef2f6",
        ),
        semantic_colors=colors,
        chart_palette=palettes[direction],
        table_density="tight" if direction == "compact" else "comfortable",
        states={
            "focus": colors["focus"],
            "hover": colors["hover"],
            "selected": colors["selected"],
            "disabled": colors["disabled"],
            "error": colors["error"],
            "stale": colors["stale"],
        },
    )


def profile_for(template: str) -> VisualEvaluationProfile:
    # Bundle ids use kebab-case while ViewModel/template internals use
    # snake_case.  Normalize at this boundary so the evaluator scores the
    # same formal profile that the compiler advertises.
    template = template.replace("-", "_")
    profiles = {
        "dashboard": VisualEvaluationProfile(
            "dashboard-data-report",
            required_markers=("kpi-grid", "chart-svg", "table-wrap", "insight-panel"),
            required_events=("filter", "drill", "refresh", "export", "cite"),
        ),
        "semantic": VisualEvaluationProfile(
            "semantic-workbench",
            required_markers=(
                "semantic-canvas",
                "field-catalog",
                "relationship-canvas",
                "source-details",
            ),
            required_events=(
                "select-entity",
                "select-relationship",
                "add-context",
                "refresh",
            ),
        ),
        "sop": VisualEvaluationProfile(
            "sop-runbook",
            required_markers=(
                "step-flow",
                "run-state",
                "tool-trace",
                "safety-boundary",
            ),
            required_events=(
                "run-step",
                "retry-step",
                "inspect-evidence",
                "confirm-action",
                "refresh",
            ),
        ),
        "knowledge": VisualEvaluationProfile(
            "knowledge-reader",
            required_markers=("answer-panel", "citation-list", "access-boundary"),
            required_events=("search", "open-citation", "add-context", "refresh"),
        ),
        "graph_ontology": VisualEvaluationProfile(
            "graph-explorer",
            required_markers=(
                "graph-svg",
                "graph-legend",
                "node-detail",
                "conflict-panel",
            ),
            required_events=("select-node", "filter-relation", "refresh"),
        ),
        "monitoring": VisualEvaluationProfile(
            "monitoring-ops",
            required_markers=(
                "observation-list",
                "trend-panel",
                "alert-list",
                "trace-panel",
            ),
            required_events=(
                "view-alert",
                "acknowledge-alert",
                "view-trace",
                "refresh",
            ),
        ),
    }
    return profiles.get(template, VisualEvaluationProfile(template))


def evaluate_html(
    template: str,
    model: ViewModel,
    html: str,
    direction: DesignDirection,
) -> VisualScore:
    """Score visible, inspectable quality signals without lowering thresholds."""

    profile = profile_for(template)
    reasons: list[str] = []
    marker_score = sum(marker in html for marker in profile.required_markers)
    event_score = sum(
        f'data-artifact-event="{event}"' in html for event in profile.required_events
    )
    marker_ratio = marker_score / max(len(profile.required_markers), 1)
    event_ratio = event_score / max(len(profile.required_events), 1)
    hierarchy = 4.6 if "<h1>" in html and html.count("<h2>") >= 2 else 3.4
    readability = 4.7 if "font-family" in html and "line-height" in html else 3.5
    density = 4.6 if len(html) > 3500 and marker_ratio >= 0.75 else 3.6
    balance = 4.5 if "grid-template-columns" in html and "@media" in html else 3.5
    charts = (
        4.6
        if (
            template not in {"dashboard", "monitoring"}
            or ("<svg" in html and ("chart-svg" in html or "graph-svg" in html))
        )
        else 3.2
    )
    responsive = 4.8 if "@media" in html and "max-width:520px" in html else 3.5
    contrast = 4.6 if "focus-visible" in html and "role=" in html else 3.7
    completeness = round(3.4 + 1.2 * marker_ratio + 0.4 * event_ratio, 2)
    state_quality = (
        4.6
        if all(
            marker in html
            for marker in (
                "state-coverage",
                "state-empty",
                "state-failed",
                "state-stale",
            )
        )
        else 3.4
    )
    direction_consistency = 4.7 if f'data-direction="{direction}"' in html else 3.3
    if marker_ratio < 1:
        reasons.append(
            f"missing visual markers: {len(profile.required_markers) - marker_score}"
        )
    if event_ratio < 1:
        reasons.append(
            f"missing event affordances: {len(profile.required_events) - event_score}"
        )
    if template == "dashboard" and isinstance(model, DashboardViewModel):
        if len(model.charts) < 2 or len(model.kpis) < 2:
            reasons.append("fixture has insufficient report modules")
    if template == "semantic" and isinstance(model, SemanticViewModel):
        if len(model.entities) < 2 or len(model.relationships) < 2:
            reasons.append("fixture has insufficient modeling relationships")
    if template == "graph_ontology" and isinstance(model, GraphOntologyViewModel):
        if len(model.nodes) < 8 or len(model.edges) < 8:
            reasons.append("fixture has insufficient topology density")
    if template == "knowledge" and isinstance(model, KnowledgeViewModel):
        if len(model.citations) < 3:
            reasons.append("fixture has insufficient source breadth")
    if template == "monitoring" and isinstance(model, MonitoringViewModel):
        if len(model.observations) < 2:
            reasons.append("fixture has insufficient observation breadth")
    if template == "sop" and isinstance(model, SopViewModel):
        if len(model.step_results) < 3:
            reasons.append("fixture has insufficient execution trace")
    return VisualScore(
        hierarchy,
        readability,
        density,
        balance,
        charts,
        responsive,
        contrast,
        completeness,
        state_quality,
        direction_consistency,
        tuple(reasons),
    )
