from __future__ import annotations

from .contract_base import *
from .contract_data import *

class ViewIntent(ContractModel):
    id: str
    skill_id: str
    skill_revision: int = Field(ge=1)
    template: Literal[
        "dashboard", "chart", "semantic", "knowledge", "graph_ontology", "monitoring"
    ]
    purpose: Literal[
        "overview", "compare", "schema", "answer", "explore", "monitor"
    ]
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


class DashboardViewModel(ContractModel):
    template: Literal["dashboard"] = "dashboard"
    fields: list[ViewField] = Field(default_factory=list)
    kpis: list[DashboardKpi] = Field(default_factory=list)
    rows: list[list[ViewCell]] = Field(default_factory=list)
    data_ref: StorageRef


class ChartViewModel(ContractModel):
    template: Literal["chart"] = "chart"
    title: str
    x_field: str
    y_field: str
    series: list[ChartSeries] = Field(default_factory=list)
    data_ref: StorageRef


class SemanticViewModel(ContractModel):
    template: Literal["semantic"] = "semantic"
    schema_ref: SchemaRef
    metric_refs: list[str] = Field(default_factory=list)
    dimension_refs: list[str] = Field(default_factory=list)
    relationship_refs: list[str] = Field(default_factory=list)
    data_ref: StorageRef | None = None


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


class GraphOntologyViewModel(ContractModel):
    template: Literal["graph_ontology"] = "graph_ontology"
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    evidence_ref: StorageRef | None = None


class MonitoringViewModel(ContractModel):
    template: Literal["monitoring"] = "monitoring"
    metric_refs: list[str] = Field(default_factory=list)
    values: list[tuple[str, float]] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    data_ref: StorageRef | None = None


ViewModel = Annotated[
    DashboardViewModel
    | ChartViewModel
    | SemanticViewModel
    | KnowledgeViewModel
    | GraphOntologyViewModel
    | MonitoringViewModel,
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
    case_results: list[EvaluationCaseResult] = Field(default_factory=list, max_length=1000)
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
