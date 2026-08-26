"""Typed Worker 3 execution records.

This module is intentionally independent from the shared BFF command surface.
Main can adapt these records into `skill-draft.run` without Worker 3 editing
shared routes, generated contracts, or repository internals.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from frontend.server.knowledge_assets.contracts import (
    ContractModel,
    GoldenAssetRevision,
    SkillDraftRevision,
    SkillResult,
    SkillViewRevision,
    StorageRef,
    ViewIntent,
    ViewModel,
)

OperationLifecycleState = Literal[
    "queued",
    "running",
    "awaiting_input",
    "succeeded",
    "failed",
    "cancelled",
]

KindExecutionStatus = Literal[
    "queued",
    "running",
    "awaiting_input",
    "succeeded",
    "failed",
    "cancelled",
]

KindExecutionState = Literal[
    "ok",
    "no_data",
    "unable_to_answer",
    "permission_denied",
    "schema_drift",
    "validation_failed",
    "awaiting_input",
    "timeout",
    "over_budget",
    "cancelled",
    "credential_blocked",
]


class ExecutionBudget(ContractModel):
    """Hard execution limits enforced before projection."""

    max_steps: int = Field(default=16, ge=1, le=100)
    max_rows: int = Field(default=1_000, ge=1, le=100_000)
    max_bytes: int = Field(default=1_000_000, ge=1, le=100_000_000)
    timeout_ms: int = Field(default=10_000, ge=1, le=300_000)
    freshness_seconds: int | None = Field(default=None, ge=1)


class ExecutionTrace(ContractModel):
    trace_id: str = Field(min_length=1, max_length=256)
    steps: list[str] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    started_at: str | None = None
    finished_at: str | None = None


class ExecutionEvidence(ContractModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    source_revision_id: str = Field(min_length=1, max_length=256)
    golden_asset_revision_id: str = Field(min_length=1, max_length=256)
    locator: str = Field(min_length=1, max_length=2048)
    permission_ref: str = Field(min_length=1, max_length=2048)
    evidence_ref: StorageRef | None = None


class SemanticDependencySnapshot(ContractModel):
    skill_revision_id: str = Field(min_length=1, max_length=256)
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    metric_refs: list[str] = Field(default_factory=list, max_length=100)
    dimension_refs: list[str] = Field(default_factory=list, max_length=100)
    relationship_refs: list[str] = Field(default_factory=list, max_length=100)


class KindExecutionRequest(ContractModel):
    draft_revision: SkillDraftRevision
    caller_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)
    golden_asset_revisions: list[GoldenAssetRevision] = Field(
        default_factory=list, max_length=100
    )
    golden_asset_contents: dict[str, str] = Field(default_factory=dict)
    data_access_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    downstream_skill_revision_refs: list[str] = Field(
        default_factory=list, max_length=100
    )
    inputs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    tool_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    semantic_dependencies: list["SemanticDependencySnapshot"] = Field(
        default_factory=list, max_length=100
    )
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    freshness_at: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=256)
    trace_id: str = Field(min_length=1, max_length=256)
    cancel_requested: bool = False
    rerun_scope: dict[str, str] = Field(default_factory=dict)
    now: str


class RetrievalHit(ContractModel):
    source_revision_id: str = Field(min_length=1, max_length=256)
    chunk_locator: str = Field(min_length=1, max_length=2048)
    text: str = Field(min_length=1, max_length=16_384)
    score: float = Field(ge=0, le=1)
    permission_ref: str = Field(min_length=1, max_length=2048)


class QueryPlan(ContractModel):
    plan_id: str = Field(min_length=1, max_length=256)
    metric: str = Field(min_length=1, max_length=256)
    dimension: str | None = Field(default=None, max_length=256)
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    limit: int = Field(default=1_000, ge=1, le=100_000)
    read_only: bool = True
    timeout_ms: int | None = Field(default=None, ge=1, le=300_000)


class SemanticField(ContractModel):
    name: str
    role: Literal["entity", "dimension", "measure", "time"]
    aggregation: Literal["sum", "count", "avg", "min", "max", "none"] = "none"
    unit: str = ""
    source_field: str
    permission_ref: str


class SemanticRelationship(ContractModel):
    source: str
    target: str
    relation: str
    join_type: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"] = (
        "many_to_one"
    )
    evidence_locator: str


class SemanticModelProjection(ContractModel):
    entities: list[str] = Field(default_factory=list)
    fields: list[SemanticField] = Field(default_factory=list)
    relationships: list[SemanticRelationship] = Field(default_factory=list)
    mdl: str
    ambiguities: list[str] = Field(default_factory=list)
    dependency_errors: list[str] = Field(default_factory=list)


class GraphMapping(ContractModel):
    entities: list[str] = Field(default_factory=list)
    relationships: list[SemanticRelationship] = Field(default_factory=list)
    evidence_locators: list[str] = Field(default_factory=list)


class MonitoringObservation(ContractModel):
    id: str
    metric: str
    value: float
    previous_value: float | None = None
    change_rate: float | None = None
    duration_seconds: int = Field(ge=0)
    freshness_at: str
    last_good_revision_id: str | None = None
    evidence_locator: str


class MonitoringAlert(ContractModel):
    id: str
    observation_id: str
    status: Literal["open", "acknowledged", "resolved"] = "open"
    severity: Literal["info", "warning", "critical"] = "warning"
    reason: str
    opened_at: str
    resolved_at: str | None = None


class MonitoringActionCandidate(ContractModel):
    id: str
    alert_id: str
    status: Literal["preview", "approved", "rejected", "superseded"] = "preview"
    title: str
    preview_only: bool = True
    evidence_locator: str


class MonitoringLifecycle(ContractModel):
    operation_id: str
    observations: list[MonitoringObservation] = Field(default_factory=list)
    alerts: list[MonitoringAlert] = Field(default_factory=list)
    action_candidates: list[MonitoringActionCandidate] = Field(default_factory=list)
    external_actions_executed: bool = False


class KindHandlerOutput(ContractModel):
    state: KindExecutionState
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
    view_model: ViewModel | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    evidence: list[ExecutionEvidence] = Field(default_factory=list, max_length=1000)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    error_code: str | None = Field(default=None, max_length=128)
    message: str | None = Field(default=None, max_length=2048)


class SkillKindExecutionRecord(ContractModel):
    operation_id: str
    status: KindExecutionStatus
    state: KindExecutionState
    draft_revision_id: str
    skill_result: SkillResult | None = None
    view_intent: ViewIntent | None = None
    skill_view_revision: SkillViewRevision | None = None
    result_payload_ref: StorageRef | None = None
    trace_ref: StorageRef | None = None
    evidence_ref: StorageRef | None = None
    trace: ExecutionTrace
    handler: str
    idempotency_key: str
    retry_of_operation_id: str | None = None
    monitoring_lifecycle: MonitoringLifecycle | None = None
    message: str | None = None
