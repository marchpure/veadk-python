from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

# Contract modules intentionally re-export one canonical schema namespace.
# ruff: noqa: F405
from .contract_base import *  # noqa: F403
from .contract_data import *  # noqa: F403


class ViewIntent(ContractModel):
    id: str
    skill_id: str
    skill_revision: int = Field(ge=1)
    template: Literal[
        "dashboard",
        "chart",
        "semantic",
        "sop",
        "knowledge",
        "graph_ontology",
        "monitoring",
    ]
    purpose: Literal["overview", "compare", "schema", "answer", "explore", "monitor"]
    result_ref: str


class ViewField(ContractModel):
    name: str
    label: str
    data_type: Literal["string", "number", "boolean", "date", "json"]


class ViewCell(ContractModel):
    field: str
    value: str | int | float | bool | None


class DashboardKpi(ContractModel):
    key: str
    label: str
    value: str | int | float
    unit: str = ""
    trend: Literal["up", "down", "flat", "unknown"] = "unknown"


class ChartSeries(ContractModel):
    name: str
    points: list[tuple[str, float]] = Field(default_factory=list, max_length=10000)


class DashboardChart(ContractModel):
    chart_id: str
    title: str
    x_field: str
    y_field: str
    chart_type: Literal[
        "line", "bar", "stacked_bar", "area", "donut", "scatter", "table"
    ] = "line"
    series: list[ChartSeries] = Field(default_factory=list)


class DashboardFilter(ContractModel):
    field: str
    operator: Literal["eq", "in", "gte", "lte", "between"]
    values: list[str | int | float | bool] = Field(default_factory=list)


class DashboardDrill(ContractModel):
    source_field: str
    target_fields: list[str] = Field(default_factory=list)


class DashboardViewModel(ContractModel):
    template: Literal["dashboard"] = "dashboard"
    title: str = ""
    fields: list[ViewField] = Field(default_factory=list)
    kpis: list[DashboardKpi] = Field(default_factory=list)
    charts: list[DashboardChart] = Field(default_factory=list)
    rows: list[list[ViewCell]] = Field(default_factory=list)
    filters: list[DashboardFilter] = Field(default_factory=list)
    drills: list[DashboardDrill] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list, max_length=100)
    freshness_at: str | None = None
    status: Literal["populated", "partial", "stale", "empty", "error"] = "populated"
    data_ref: StorageRef


class ChartViewModel(ContractModel):
    template: Literal["chart"] = "chart"
    title: str
    x_field: str
    y_field: str
    chart_type: Literal[
        "line", "bar", "stacked_bar", "area", "donut", "scatter", "table"
    ] = "line"
    series: list[ChartSeries] = Field(default_factory=list)
    data_ref: StorageRef


class SemanticViewModel(ContractModel):
    template: Literal["semantic"] = "semantic"
    schema_ref: SchemaRef
    metric_refs: list[str] = Field(default_factory=list)
    dimension_refs: list[str] = Field(default_factory=list)
    relationship_refs: list[str] = Field(default_factory=list)
    data_ref: StorageRef | None = None
    entities: list[str] = Field(default_factory=list)
    fields: list["SemanticViewField"] = Field(default_factory=list)
    relationships: list["SemanticViewRelationship"] = Field(default_factory=list)
    mdl: str = ""
    ambiguities: list[str] = Field(default_factory=list)
    dependency_errors: list[str] = Field(default_factory=list)


class SemanticViewField(ContractModel):
    name: str
    role: Literal["entity", "dimension", "measure", "time"]
    aggregation: Literal["sum", "count", "avg", "min", "max", "none"] = "none"
    unit: str = ""
    source_field: str
    primary_key: bool = False


class SemanticViewRelationship(ContractModel):
    source: str
    target: str
    relation: str
    join_type: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    evidence_locator: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class KnowledgeCitation(ContractModel):
    citation_id: str
    source_revision_id: str
    title: str
    locator: str
    excerpt_ref: StorageRef | None = None


class KnowledgeViewModel(ContractModel):
    template: Literal["knowledge"] = "knowledge"
    answer: str
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    refusal: bool = False


class GraphNode(ContractModel):
    id: str
    label: str
    entity_type: str


class GraphEdge(ContractModel):
    source: str
    target: str
    relation: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_locator: str | None = None


class GraphOntologyViewModel(ContractModel):
    template: Literal["graph_ontology"] = "graph_ontology"
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    evidence_ref: StorageRef | None = None
    evidence_locators: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    selected_node_id: str | None = None


class MonitoringObservationView(ContractModel):
    metric: str
    latest: float
    previous: float | None = None
    change_rate: float | None = None
    duration_seconds: int = Field(ge=0)
    freshness_at: str
    last_good_revision_id: str | None = None


class MonitoringViewModel(ContractModel):
    template: Literal["monitoring"] = "monitoring"
    metric_refs: list[str] = Field(default_factory=list)
    values: list[tuple[str, float]] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    data_ref: StorageRef | None = None
    observations: list[MonitoringObservationView] = Field(default_factory=list)
    failure_trace: list[str] = Field(default_factory=list)
    call_volume: float | None = None
    success_rate: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float | None = None
    stale: bool = False
    status: Literal["healthy", "stale", "alert", "failed", "empty"] = "healthy"


class SopStepEvidence(ContractModel):
    kind: Literal["tool_result", "source_citation", "input", "decision"]
    locator: str
    summary: str


class SopStepResult(ContractModel):
    step_id: str
    title: str
    status: Literal["succeeded", "skipped", "failed", "awaiting_confirmation"]
    branch: Literal["true", "false", "unconditional"] = "unconditional"
    evidence: list[SopStepEvidence] = Field(default_factory=list)
    message: str = ""
    tool_refs: list[str] = Field(default_factory=list, max_length=20)
    input_summary: str = ""


class SopActionProposal(ContractModel):
    proposal_id: str
    title: str
    risk: Literal["external_write", "high_risk"]
    confirmation_required: Literal[True] = True
    challenge: str
    tool_ref: str


class SopViewModel(ContractModel):
    template: Literal["sop"] = "sop"
    title: str
    trigger: str
    scope: str
    step_results: list[SopStepResult] = Field(default_factory=list)
    recommendation: str
    outputs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    action_proposals: list[SopActionProposal] = Field(default_factory=list)
    run_state: Literal[
        "queued", "running", "succeeded", "failed", "awaiting_confirmation"
    ] = "succeeded"


ViewModel = Annotated[
    DashboardViewModel
    | ChartViewModel
    | SemanticViewModel
    | KnowledgeViewModel
    | GraphOntologyViewModel
    | MonitoringViewModel
    | SopViewModel,
    Field(discriminator="template"),
]


class SkillViewManifest(ContractModel):
    id: str
    skill_revision_id: str
    renderer_ref: str
    view_model_schema_ref: SchemaRef
    allowed_components: list[str] = Field(default_factory=list, max_length=100)
    csp_profile: Literal["trusted-renderer-v1"] = "trusted-renderer-v1"


class SkillViewRevision(ContractModel):
    id: str
    skill_revision_id: str
    revision: int = Field(ge=1)
    manifest: SkillViewManifest
    intent: ViewIntent
    view_model: ViewModel
    invocation_id: str | None = None
    result_ref: StorageRef | None = None
    html_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    etag: str | None = Field(default=None, max_length=80)
    csp: str = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    data_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    trace_id: str | None = None
    created_at: str


class SkillViewShareGrant(ContractModel):
    id: str
    resource_id: str
    skill_view_revision_id: str
    workspace_id: str
    permission: Literal["read"] = "read"
    expires_at: str | None = None
    created_at: str


class EvaluationSuite(ContractModel):
    id: str
    version: int = Field(ge=1)
    skill_id: str
    case_count: int = Field(ge=0)
    cases_ref: StorageRef
    pass_threshold: float = Field(ge=0, le=1)
    environment: RuntimeProfile = "test"
    case_ids: list[str] = Field(default_factory=list, max_length=1000)


class EvaluationCase(ContractModel):
    id: str
    input_ref: StorageRef
    expected_output_ref: StorageRef | None = None
    source: Literal["manual", "historical", "batch", "agent_candidate"] = "manual"


class EvaluationCaseResult(ContractModel):
    case_id: str
    status: Literal["passed", "failed", "skipped"]
    score: float = Field(ge=0, le=1)
    evidence_ref: StorageRef | None = None
    regression_diff_ref: StorageRef | None = None


class EvaluationRun(ContractModel):
    id: str
    suite_id: str
    suite_version: int = Field(ge=1)
    skill_revision_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    score: float | None = Field(default=None, ge=0, le=1)
    evidence_ref: StorageRef | None = None
    regression_ref: StorageRef | None = None
    environment: RuntimeProfile = "test"
    dependency_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    data_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    case_results: list[EvaluationCaseResult] = Field(
        default_factory=list, max_length=1000
    )
    started_at: str
    finished_at: str | None = None


class PolicyGateResult(ContractModel):
    id: str
    skill_revision_id: str
    evaluation_run_id: str
    decision: Literal["publishable", "blocked"]
    reasons: list[str] = Field(default_factory=list)
    machine_reasons: list[str] = Field(default_factory=list)
    checked_at: str


class PublishedSkillVersion(ContractModel):
    id: str
    skill_id: str
    semver: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    manifest: SkillManifest
    skill_revision_id: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["published", "deprecated", "revoked"] = "published"
    evaluation_run_id: str
    policy_gate_result_id: str
    skill_view_ref: str | None = None
    published_at: str


class AgentBinding(ContractModel):
    id: str
    skill_version_id: str
    agent_id: str
    workspace_id: str
    version_selector: str
    status: Literal["active", "revoked"] = "active"
    created_at: str


class Invocation(ContractModel):
    id: str
    skill_version_id: str
    skill_view_revision_id: str
    caller_id: str
    workspace_id: str
    status: Literal[
        "accepted",
        "resolving",
        "running",
        "awaiting_confirmation",
        "succeeded",
        "failed",
        "cancelled",
    ]
    input_ref: StorageRef | None = None
    result_ref: StorageRef | None = None
    trace_id: str
    actual_data_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    started_at: str
    finished_at: str | None = None


class RefreshRun(ContractModel):
    id: str
    skill_id: str
    trigger: Literal["manual", "schedule", "event", "freshness_on_read"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    staging_ref: StorageRef | None = None
    current_revision: int | None = Field(default=None, ge=1)
    last_good_revision: int | None = Field(default=None, ge=1)
    error_code: str | None = None
    started_at: str
    finished_at: str | None = None


class AlertEvent(ContractModel):
    id: str
    skill_id: str
    severity: Literal["info", "warning", "critical"]
    status: Literal["open", "acknowledged", "resolved"]
    rule_ref: str
    fingerprint: str
    observed_at: str
    payload_ref: StorageRef | None = None
