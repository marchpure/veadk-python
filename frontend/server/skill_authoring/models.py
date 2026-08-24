"""Typed contracts for Agent orchestration and SkillDraft authoring.

The models in this file are deliberately narrower than an arbitrary artifact
or HTML document.  A model can propose a plan or one of the typed mutations,
but cannot provide executable code, markup, secrets, or a persistence command.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal, Mapping, Sequence, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


class AuthoringErrorCode(StrEnum):
    INVALID_CONTEXT = "invalid_context"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_NOT_FOUND = "resource_not_found"
    AMBIGUOUS = "awaiting_input"
    CREDENTIAL_BLOCKED = "credential_blocked"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_UNAVAILABLE = "model_unavailable"
    VALIDATION_FAILED = "validation_failed"
    CONFLICT = "optimistic_conflict"
    TEAM_READ_ONLY = "team_read_only"
    EVALUATION_REQUIRED = "evaluation_required"
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"


class SkillAuthoringError(RuntimeError):
    """Typed domain failure suitable for conversion by the Main BFF."""

    def __init__(self, code: AuthoringErrorCode, message: str, *, operation_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.operation_id = operation_id


class AuthoringStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_INPUT = "awaiting_input"
    CREDENTIAL_BLOCKED = "credential_blocked"
    RUNNING = "running"
    READY_FOR_EXECUTION = "ready_for_execution"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SkillKind(StrEnum):
    KNOWLEDGE = "knowledge"
    SEMANTIC = "semantic"
    ANALYSIS = "analysis"
    GRAPH_ONTOLOGY = "graph_ontology"
    MONITORING = "monitoring"


class Scope(StrEnum):
    PERSONAL = "personal"
    TEAM = "team"


class ResourceRef(BaseModel):
    """A browser-safe reference; it is not a resource snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["golden_asset", "data_access_skill", "knowledge_asset", "skill"]
    object_id: str = Field(min_length=1, max_length=160)
    revision: str = Field(min_length=1, max_length=160)
    scope: Scope


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(default=8, ge=1, le=32)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    timeout_ms: int = Field(default=30_000, ge=100, le=120_000)


class FreshnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: datetime | None = None
    max_age_seconds: int = Field(default=86_400, ge=0, le=31_536_000)
    require_fixed_revision: bool = True


class ContextEnvelope(BaseModel):
    """Minimum caller/workspace context sent to the orchestration boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex}", min_length=1)
    caller_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=8_000)
    resource_refs: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    permissions: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    fixed_revisions: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    budget: Budget = Field(default_factory=Budget)
    freshness: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    current_skill_id: str | None = Field(default=None, max_length=160)
    current_view_id: str | None = Field(default=None, max_length=160)
    current_component_id: str | None = Field(default=None, max_length=160)
    comment_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)

    @field_validator("prompt")
    @classmethod
    def prompt_is_not_a_secret(cls, value: str) -> str:
        lowered = value.casefold()
        if any(token in lowered for token in ("access_token=", "api_key=", "secret_key=")):
            raise ValueError("secrets must be represented by server-side secretRef, not prompt text")
        return value

    @model_validator(mode="after")
    def fixed_revisions_are_unique(self) -> "ContextEnvelope":
        if len(set(self.fixed_revisions)) != len(self.fixed_revisions):
            raise ValueError("fixed revisions must be deduplicated")
        return self


class ResolvedResource(BaseModel):
    """Server-resolved, authorized metadata; raw provider content is excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: ResourceRef
    display_name: str = Field(min_length=1, max_length=240)
    provider_revision: str = Field(min_length=1, max_length=160)
    schema_digest: str = Field(min_length=1, max_length=128)
    capabilities: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    semantic_fields: tuple[str, ...] = Field(default_factory=tuple, max_length=256)
    authorized: bool = True


class ResolvedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope: ContextEnvelope
    resources: tuple[ResolvedResource, ...]
    authorized_permissions: tuple[str, ...] = Field(default_factory=tuple)
    context_digest: str

    @property
    def model_input(self) -> Mapping[str, object]:
        """Safe model input; no browser object, raw document, secret, or token."""
        return {
            "request_id": self.envelope.request_id,
            "workspace_id": self.envelope.workspace_id,
            "caller_id": self.envelope.caller_id,
            "prompt": self.envelope.prompt,
            "resources": [
                {
                    "kind": resource.ref.kind,
                    "object_id": resource.ref.object_id,
                    "revision": resource.ref.revision,
                    "provider_revision": resource.provider_revision,
                    "schema_digest": resource.schema_digest,
                    "capabilities": resource.capabilities,
                    "semantic_fields": resource.semantic_fields,
                }
                for resource in self.resources
            ],
            "permissions": self.authorized_permissions,
            "fixed_revisions": self.envelope.fixed_revisions,
            "budget": self.envelope.budget.model_dump(mode="json"),
            "freshness": self.envelope.freshness.model_dump(mode="json"),
        }


class PlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    role: Literal[
        "intent_resolution",
        "context_resolution",
        "query_plan",
        "retrieval",
        "schema_mapping",
        "threshold_policy",
        "worker3_execution",
    ]
    depends_on: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    input_names: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    output_names: tuple[str, ...] = Field(default_factory=tuple, max_length=32)


class InputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["string", "number", "boolean", "date", "dimension", "metric", "document_ref"]
    required: bool = True


class OutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal["answer", "table", "metric", "chart", "schema", "graph", "observation"]
    required: bool = True


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_revision: str = Field(min_length=1, max_length=160)
    selected_fields: tuple[str, ...] = Field(min_length=1, max_length=64)
    filters: Mapping[str, str] = Field(default_factory=dict, max_length=32)
    limit: int = Field(default=100, ge=1, le=10_000)
    read_only: Literal[True] = True

    @field_validator("filters")
    @classmethod
    def filter_values_are_bounded(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        if any(len(key) > 128 or len(item) > 512 for key, item in value.items()):
            raise ValueError("query filter is too large")
        return dict(value)


class KnowledgeKindSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[SkillKind.KNOWLEDGE] = SkillKind.KNOWLEDGE
    citation_intent: tuple[str, ...] = Field(min_length=1, max_length=32)
    retrieval_mode: Literal["hybrid", "semantic", "exact"] = "hybrid"


class SemanticKindSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[SkillKind.SEMANTIC] = SkillKind.SEMANTIC
    entities: tuple[str, ...] = Field(min_length=1, max_length=128)
    relationships: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    dimensions: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    measures: tuple[str, ...] = Field(default_factory=tuple, max_length=128)


class AnalysisKindSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[SkillKind.ANALYSIS] = SkillKind.ANALYSIS
    query_plan: QueryPlan
    analysis_shape: Literal["kpi", "trend", "table", "funnel", "breakdown"] = "table"
    unit: str | None = Field(default=None, max_length=64)


class GraphOntologyKindSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[SkillKind.GRAPH_ONTOLOGY] = SkillKind.GRAPH_ONTOLOGY
    entity_types: tuple[str, ...] = Field(min_length=1, max_length=128)
    relation_types: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    mapping_intent: tuple[str, ...] = Field(default_factory=tuple, max_length=64)


class MonitoringKindSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[SkillKind.MONITORING] = SkillKind.MONITORING
    metric: str = Field(min_length=1, max_length=128)
    threshold: float
    comparator: Literal["gt", "gte", "lt", "lte", "change_rate"]
    duration_minutes: int = Field(default=5, ge=1, le=43_200)
    refresh_seconds: int = Field(default=900, ge=60, le=86_400)


KindSpec = Annotated[
    Union[
        KnowledgeKindSpec,
        SemanticKindSpec,
        AnalysisKindSpec,
        GraphOntologyKindSpec,
        MonitoringKindSpec,
    ],
    Field(discriminator="kind"),
]


class BuildPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    intent: SkillKind
    purpose: str = Field(min_length=1, max_length=1_000)
    nodes: tuple[PlanNode, ...] = Field(min_length=3, max_length=12)
    inputs: tuple[InputContract, ...] = Field(default_factory=tuple, max_length=32)
    outputs: tuple[OutputContract, ...] = Field(min_length=1, max_length=16)
    dependencies: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    kind_spec: KindSpec
    query_plan: QueryPlan | None = None
    clarification_questions: tuple[str, ...] = Field(default_factory=tuple, max_length=5)
    plan_digest: str

    @model_validator(mode="after")
    def plan_kind_matches_spec(self) -> "BuildPlan":
        if self.kind_spec.kind != self.intent:
            raise ValueError("kind-specific plan spec does not match intent")
        if self.intent == SkillKind.ANALYSIS and self.query_plan is None:
            raise ValueError("analysis plan requires a query plan")
        if any(node.node_id in node.depends_on for node in self.nodes):
            raise ValueError("plan cannot contain a self dependency")
        return self


class DraftManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_000)
    kind: SkillKind
    kind_spec: KindSpec
    inputs: tuple[InputContract, ...]
    outputs: tuple[OutputContract, ...]
    dependencies: tuple[ResourceRef, ...]
    permissions: tuple[str, ...]
    freshness: FreshnessPolicy


class DraftRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    manifest: DraftManifest
    plan: BuildPlan
    state: Literal["draft", "awaiting_execution", "execution_requested", "conflicted"] = "draft"
    scope: Scope
    owner_id: str
    workspace_id: str
    budget: Budget
    lineage: tuple[ResourceRef, ...] = Field(default_factory=tuple)
    lineage_source_draft_id: str | None = None
    promotion_state: Literal["personal", "team_read_only", "pre_publish_evaluation"] = "personal"
    digest: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    undo_of_revision: int | None = Field(default=None, ge=1)


class SetTitlePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_title"] = "set_title"
    title: str = Field(min_length=1, max_length=160)


class SetDescriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_description"] = "set_description"
    description: str = Field(min_length=1, max_length=1_000)


class SetQueryPlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_query_plan"] = "set_query_plan"
    query_plan: QueryPlan


class SetRefreshPolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_refresh_policy"] = "set_refresh_policy"
    freshness: FreshnessPolicy


class SetThresholdPolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_threshold_policy"] = "set_threshold_policy"
    threshold: float
    comparator: Literal["gt", "gte", "lt", "lte", "change_rate"]


class SetPermissionScopePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_permission_scope"] = "set_permission_scope"
    permissions: tuple[str, ...] = Field(min_length=1, max_length=64)


class AddCitationIntentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["add_citation_intent"] = "add_citation_intent"
    intent: str = Field(min_length=1, max_length=240)


class SetSemanticMappingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_semantic_mapping"] = "set_semantic_mapping"
    field: str = Field(min_length=1, max_length=128)
    entity: str = Field(min_length=1, max_length=128)


TypedPatch = Annotated[
    Union[
        SetTitlePatch,
        SetDescriptionPatch,
        SetQueryPlanPatch,
        SetRefreshPolicyPatch,
        SetThresholdPolicyPatch,
        SetPermissionScopePatch,
        AddCitationIntentPatch,
        SetSemanticMappingPatch,
    ],
    Field(discriminator="patch_type"),
]


class PatchImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=500)
    affected_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    requires_rerun: bool
    reason: Literal[
        "presentation_only",
        "query_changed",
        "metric_changed",
        "permission_changed",
        "freshness_changed",
        "alert_changed",
        "mapping_changed",
    ]


class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_id: str = Field(default_factory=lambda: f"patch_{uuid4().hex}")
    draft_id: str
    base_revision: int = Field(ge=1)
    patch: TypedPatch
    impact: PatchImpact
    status: Literal["proposed", "accepted", "rejected", "undone", "conflicted"] = "proposed"
    proposed_by: str
    created_at: datetime = Field(default_factory=utc_now)


class Worker3ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    draft_id: str
    draft_revision: int
    skill_kind: SkillKind
    workspace_id: str
    caller_id: str
    dependencies: tuple[ResourceRef, ...]
    budget: Budget
    freshness: FreshnessPolicy


class Worker3ExecutionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str
    state: Literal["queued", "credential_blocked", "accepted"]
    reason: str | None = None


class AuthoringEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    operation_id: str
    event_type: Literal[
        "operation_created",
        "context_resolved",
        "plan_proposed",
        "clarification_required",
        "credential_blocked",
        "draft_created",
        "patch_proposed",
        "patch_accepted",
        "patch_rejected",
        "undo_applied",
        "execution_requested",
        "operation_retry",
        "operation_cancelled",
        "operation_failed",
    ]
    sequence: int = Field(ge=1)
    data: Mapping[str, str] = Field(default_factory=dict, max_length=16)
    occurred_at: datetime = Field(default_factory=utc_now)


class AuthoringOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    operation_type: Literal[
        "create_draft",
        "accept_patch",
        "undo",
        "comment_repair",
        "retry",
        "cancel",
        "copy_team_draft",
        "update_context",
    ]
    status: AuthoringStatus
    caller_id: str
    workspace_id: str
    draft_id: str | None = None
    current_revision: int | None = None
    error_code: AuthoringErrorCode | None = None
    error_message: str | None = None
    trace_id: str
    retry_of_operation_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuthoringReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: AuthoringOperation
    draft: DraftRevision | None = None
    latest_patch: PatchProposal | None = None
    events: tuple[AuthoringEvent, ...] = Field(default_factory=tuple)


class CreateDraftRequest(BaseModel):
    """Durable, secret-free replay input for Composer create."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope: ContextEnvelope
    requested_kind: SkillKind | None = None
    scope: Scope = Scope.PERSONAL
    display_name: str | None = Field(default=None, max_length=160)


class ContextMutation(BaseModel):
    """Typed Composer context operation; the browser sends refs, never objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["add", "remove"]
    resource_ref: ResourceRef


class TeamReuseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_draft_id: str
    team_revision: int
    personal_name: str = Field(min_length=1, max_length=160)
