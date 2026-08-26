"""Typed contracts for Agent orchestration and SkillDraft authoring.

The models in this file are deliberately narrower than an arbitrary artifact
or HTML document.  A model can propose a plan or one of the typed mutations,
but cannot provide executable code, markup, secrets, or a persistence command.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal, Mapping, Union
from uuid import uuid4

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


_PUBLIC_REDACTED = "[REDACTED]"
_PUBLIC_TRUNCATED = "…"
_PUBLIC_SENSITIVE_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "connection",
    "connectionstring",
    "connectionuri",
    "connectionurl",
    "cookie",
    "credential",
    "credentials",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "secretkey",
    "secretref",
    "token",
}
_PUBLIC_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key|password|passwd|token)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_PUBLIC_BEARER_SECRET = re.compile(
    r"(?i)\b(authorization\s*:\s*)?(bearer)\s+[A-Za-z0-9._~+/=-]+"
)
_PUBLIC_URI_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/@\s]+)@")
_PUBLIC_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)


def _redact_public_text(value: str, *, limit: int) -> str:
    redacted = _PUBLIC_PRIVATE_KEY.sub(_PUBLIC_REDACTED, value)
    redacted = _PUBLIC_BEARER_SECRET.sub(
        lambda match: (f"{match.group(1) or ''}{match.group(2)} {_PUBLIC_REDACTED}"),
        redacted,
    )
    redacted = _PUBLIC_ASSIGNMENT_SECRET.sub(
        lambda match: f"{match.group(1)}={_PUBLIC_REDACTED}",
        redacted,
    )
    redacted = _PUBLIC_URI_USERINFO.sub(
        lambda match: f"{match.group(1)}{_PUBLIC_REDACTED}@",
        redacted,
    )
    if len(redacted) > limit:
        return redacted[:limit] + _PUBLIC_TRUNCATED
    return redacted


def _sanitize_public_value(
    value: object,
    *,
    key: str | None = None,
    depth: int = 0,
) -> object:
    """Return a JSON-safe, bounded value suitable for durable public replay."""

    normalized_key = re.sub(r"[^a-z0-9]", "", (key or "").casefold())
    if normalized_key in _PUBLIC_SENSITIVE_KEYS:
        return _PUBLIC_REDACTED
    if depth >= 5:
        return _PUBLIC_TRUNCATED
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _redact_public_text(
            value,
            limit=8_000 if normalized_key == "text" else 2_000,
        )
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for raw_key, item in list(value.items())[:32]:
            public_key = str(raw_key)[:160]
            sanitized[public_key] = _sanitize_public_value(
                item,
                key=public_key,
                depth=depth + 1,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_public_value(item, depth=depth + 1) for item in value[:32]]
    return "[UNSUPPORTED]"


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
    EXECUTION_BLOCKED = "execution_blocked"


class SkillAuthoringError(RuntimeError):
    """Typed domain failure suitable for conversion by the Main BFF."""

    def __init__(
        self, code: AuthoringErrorCode, message: str, *, operation_id: str | None = None
    ):
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

    kind: Literal[
        "golden_asset",
        "document",
        "knowledge",
        "semantic",
        "graph",
        "skill",
        "artifact",
        # Retained for existing callers while the explicit revision kinds
        # above become the canonical browser contract.
        "data_access_skill",
        "knowledge_asset",
    ]
    object_id: str = Field(
        min_length=1,
        max_length=160,
        validation_alias=AliasChoices("object_id", "objectId"),
        serialization_alias="objectId",
    )
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
    # A conversation-scoped key lets the service enforce one active
    # generation without serialising unrelated conversations in a workspace.
    # It is optional for older command clients that do not have conversations.
    conversation_id: str | None = Field(default=None, max_length=160)
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
        if any(
            token in lowered for token in ("access_token=", "api_key=", "secret_key=")
        ):
            raise ValueError(
                "secrets must be represented by server-side secretRef, not prompt text"
            )
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
                    "scope": resource.ref.scope.value,
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
            "context_binding": {
                "current_skill_id": self.envelope.current_skill_id,
                "current_view_id": self.envelope.current_view_id,
                "current_component_id": self.envelope.current_component_id,
                "comment_ids": self.envelope.comment_ids,
            },
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
    type: Literal[
        "string", "number", "boolean", "date", "dimension", "metric", "document_ref"
    ]
    required: bool = True


class OutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    type: Literal[
        "answer", "table", "metric", "chart", "schema", "graph", "observation"
    ]
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
    clarification_questions: tuple[str, ...] = Field(
        default_factory=tuple, max_length=5
    )
    data_refs: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    metrics: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    dimensions: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    layout_intent: Literal[
        "kpi", "trend", "table", "funnel", "breakdown", "graph", "document", "alert"
    ] = "table"
    refresh_policy: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    lineage: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    plan_digest: str

    @model_validator(mode="before")
    @classmethod
    def infer_structural_kind(cls, value: object) -> object:
        """Normalize only unambiguous Ark structured-output omissions.

        Some Responses API models omit the discriminant while returning the
        complete kind-specific shape. Infer only canonical structural markers
        so malformed, mixed, and conflicting plans remain rejected.
        """
        if not isinstance(value, dict):
            return value
        kind_spec = value.get("kind_spec")
        if not isinstance(kind_spec, dict) or "kind" in kind_spec:
            return value
        if value.get("intent") == SkillKind.ANALYSIS and isinstance(
            kind_spec.get("query_plan"), dict
        ):
            normalized = dict(value)
            normalized["kind_spec"] = {**kind_spec, "kind": SkillKind.ANALYSIS}
            return normalized
        citation_intent = kind_spec.get("citation_intent")
        retrieval_mode = kind_spec.get("retrieval_mode")
        if (
            value.get("intent") == SkillKind.KNOWLEDGE
            and isinstance(citation_intent, (list, tuple))
            and bool(citation_intent)
            and retrieval_mode in {None, "hybrid", "semantic", "exact"}
            and set(kind_spec).issubset({"citation_intent", "retrieval_mode"})
        ):
            normalized = dict(value)
            normalized["kind_spec"] = {**kind_spec, "kind": SkillKind.KNOWLEDGE}
            return normalized
        return value

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
    state: Literal[
        "draft", "awaiting_execution", "execution_requested", "conflicted"
    ] = "draft"
    scope: Scope
    owner_id: str
    workspace_id: str
    budget: Budget = Field(default_factory=Budget)
    authorized_permissions: tuple[str, ...] = Field(
        default_factory=tuple, max_length=64
    )
    lineage: tuple[ResourceRef, ...] = Field(default_factory=tuple)
    lineage_source_draft_id: str | None = None
    promotion_state: Literal["personal", "team_read_only", "pre_publish_evaluation"] = (
        "personal"
    )
    digest: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    undo_of_revision: int | None = Field(default=None, ge=1)
    dashboard_config: Mapping[str, Any] = Field(default_factory=dict, max_length=64)
    sop_steps: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple, max_length=128)
    graph_config: Mapping[str, Any] = Field(default_factory=dict, max_length=64)


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


class SetSemanticMetricPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_semantic_metric"] = "set_semantic_metric"
    metric: str = Field(min_length=1, max_length=128)
    definition: str = Field(min_length=1, max_length=512)


class SetSemanticDimensionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_semantic_dimension"] = "set_semantic_dimension"
    dimension: str = Field(min_length=1, max_length=128)
    field: str = Field(min_length=1, max_length=128)


class SetSemanticRelationshipPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_semantic_relationship"] = "set_semantic_relationship"
    relationship: str = Field(min_length=1, max_length=128)
    source_entity: str = Field(min_length=1, max_length=128)
    target_entity: str = Field(min_length=1, max_length=128)


class SetDashboardKpiPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_dashboard_kpi"] = "set_dashboard_kpi"
    key: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=160)
    value: float | int | str
    unit: str = Field(default="", max_length=32)


class SetDashboardChartPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_dashboard_chart"] = "set_dashboard_chart"
    x_field: str = Field(min_length=1, max_length=128)
    y_field: str = Field(min_length=1, max_length=128)
    chart_type: Literal["line", "bar", "area", "table"] = "line"


class SetDashboardFilterPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_dashboard_filter"] = "set_dashboard_filter"
    field: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=512)


class SetSopStepPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_sop_step"] = "set_sop_step"
    step_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=240)
    condition: str | None = Field(default=None, max_length=512)
    tool_ref: str | None = Field(default=None, max_length=240)


class SetSopConditionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_sop_condition"] = "set_sop_condition"
    step_id: str = Field(min_length=1, max_length=128)
    condition: str = Field(min_length=1, max_length=512)


class SetSopToolRefPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_sop_tool_ref"] = "set_sop_tool_ref"
    step_id: str = Field(min_length=1, max_length=128)
    tool_ref: str = Field(min_length=1, max_length=240)


class SetGraphEntityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_graph_entity"] = "set_graph_entity"
    entity_type: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=240)


class SetGraphRelationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_type: Literal["set_graph_relation"] = "set_graph_relation"
    relation: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=128)


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
        SetSemanticMetricPatch,
        SetSemanticDimensionPatch,
        SetSemanticRelationshipPatch,
        SetDashboardKpiPatch,
        SetDashboardChartPatch,
        SetDashboardFilterPatch,
        SetSopStepPatch,
        SetSopConditionPatch,
        SetSopToolRefPatch,
        SetGraphEntityPatch,
        SetGraphRelationPatch,
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
    operation_id: str | None = None
    draft_id: str
    base_revision: int = Field(ge=1)
    patch: TypedPatch
    impact: PatchImpact
    status: Literal["proposed", "accepted", "rejected", "undone", "conflicted"] = (
        "proposed"
    )
    proposed_by: str
    source_comment_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    before: Mapping[str, Any] = Field(default_factory=dict, max_length=32)
    after: Mapping[str, Any] = Field(default_factory=dict, max_length=32)
    base_digest: str | None = Field(default=None, max_length=128)
    new_digest: str | None = Field(default=None, max_length=128)
    new_revision: int | None = Field(default=None, ge=1)
    view_revision_id: str | None = Field(default=None, max_length=240)
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
    data_refs: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    metrics: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    dimensions: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    layout_intent: str = Field(default="table", min_length=1, max_length=64)
    lineage: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    budget: Budget
    freshness: FreshnessPolicy
    draft_manifest: DraftManifest | None = None
    build_plan: BuildPlan | None = None
    trace_id: str = Field(default="", max_length=160)


class Worker3ExecutionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str
    state: Literal["queued", "credential_blocked", "accepted", "failed"]
    reason: str | None = None
    artifact_result: dict[str, object] | None = None
    execution_result: dict[str, object] | None = None
    view_revision_id: str | None = Field(default=None, max_length=240)
    view_revision: Mapping[str, Any] | None = Field(default=None, max_length=64)


class AgentEventEvidence(BaseModel):
    """Safe, durable summary of one event emitted by the real Agent Runner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str = Field(min_length=1, max_length=160)
    author: str | None = Field(default=None, max_length=160)
    has_content: bool = False
    output_present: bool = False


class AgentToolCallEvidence(BaseModel):
    """Safe, durable summary of a formal tool call observed in Runner events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    call_id: str | None = Field(default=None, max_length=160)
    status: Literal["requested", "succeeded", "failed"] = "succeeded"


class AgentExecutionEvidence(BaseModel):
    """Verifiable execution evidence; IDs are never fabricated on failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    status: Literal["running", "succeeded", "failed"]
    events: tuple[AgentEventEvidence, ...] = Field(
        default_factory=tuple, max_length=256
    )
    tool_calls: tuple[AgentToolCallEvidence, ...] = Field(
        default_factory=tuple, max_length=128
    )
    error_code: AuthoringErrorCode | None = None
    error_message: str | None = Field(default=None, max_length=500)


class AgentRuntimeEvent(BaseModel):
    """One bounded public event emitted while a gateway invocation is running."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal[
        "answer.delta",
        "tool.started",
        "tool.progress",
        "tool.completed",
        "tool.failed",
        "plan.step.started",
        "plan.step.completed",
        "plan.step.failed",
    ]
    public_summary: str = Field(min_length=1, max_length=500)
    payload: Mapping[str, Any] = Field(default_factory=dict, max_length=32)
    session_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=160)


class AgentAnswer(BaseModel):
    """Bounded ordinary-conversation output from the real Agent/Runner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["succeeded", "awaiting_input"]
    text: str | None = Field(default=None, min_length=1, max_length=8_000)
    citations: tuple[ResourceRef, ...] = Field(default_factory=tuple, max_length=32)
    clarification_questions: tuple[str, ...] = Field(
        default_factory=tuple, max_length=5
    )

    @model_validator(mode="after")
    def status_has_exact_payload(self) -> "AgentAnswer":
        if self.status == "succeeded":
            if not self.text or self.clarification_questions:
                raise ValueError("succeeded answer requires text and no clarification")
        elif self.text is not None or not self.clarification_questions:
            raise ValueError(
                "awaiting_input answer requires clarification and no answer text"
            )
        return self


class AgentIntent(BaseModel):
    """Structured router output produced by a real Agent/Runner invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["answer", "create_skill", "patch", "execute", "awaiting_input"]
    requested_kind: SkillKind | None = None
    # Patch proposals are model output, but the union below only permits the
    # bounded mutations understood by the authoring service.  The service
    # still checks the bound draft revision and caller permissions before any
    # persistence.
    patch: TypedPatch | None = None
    base_revision: int | None = Field(default=None, ge=1)
    clarification_questions: tuple[str, ...] = Field(
        default_factory=tuple, max_length=5
    )

    @model_validator(mode="after")
    def validate_action_payload(self) -> "AgentIntent":
        if self.action == "create_skill" and self.requested_kind is None:
            raise ValueError("create_skill intent requires requested_kind")
        if self.action == "awaiting_input" and not self.clarification_questions:
            raise ValueError("awaiting_input intent requires clarification questions")
        if self.action != "awaiting_input" and self.clarification_questions:
            raise ValueError("only awaiting_input may include clarification questions")
        if self.action == "patch" and self.patch is None:
            raise ValueError("patch intent requires a typed patch")
        if self.action != "patch" and (self.patch is not None or self.base_revision is not None):
            raise ValueError("only patch intent may include patch payload")
        return self


class AgentTurnRequest(BaseModel):
    """One typed message submitted through the streaming authoring boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope: ContextEnvelope
    requested_kind: SkillKind | None = None
    scope: Scope = Scope.PERSONAL
    display_name: str | None = Field(default=None, max_length=160)


class AgentTurnAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    action: Literal[
        "routing", "answer", "create_skill", "patch", "execute", "awaiting_input"
    ]
    status: AuthoringStatus


class AuthoringEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    operation_id: str
    event_type: Literal[
        "operation_created",
        "context_resolved",
        "agent_execution",
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
        "message.accepted",
        "context.resolving",
        "context.resolved",
        "agent.started",
        "answer.delta",
        "answer.final",
        "tool.started",
        "tool.progress",
        "tool.completed",
        "tool.failed",
        "plan.created",
        "plan.step.started",
        "plan.step.completed",
        "plan.step.failed",
        "artifact.revision.created",
        "operation.completed",
        "operation.failed",
        "operation.cancelled",
    ]
    sequence: int = Field(ge=1)
    # ``data`` is retained for existing command-response readers. New stream
    # clients consume the same bounded public values through ``payload``.
    data: Mapping[str, Any] = Field(default_factory=dict, max_length=32)
    payload: Mapping[str, Any] = Field(default_factory=dict, max_length=32)
    type: (
        Literal[
            "message.accepted",
            "context.resolving",
            "context.resolved",
            "agent.started",
            "answer.delta",
            "answer.final",
            "tool.started",
            "tool.progress",
            "tool.completed",
            "tool.failed",
            "plan.created",
            "plan.step.started",
            "plan.step.completed",
            "plan.step.failed",
            "artifact.revision.created",
            "operation.completed",
            "operation.failed",
            "operation.cancelled",
        ]
        | None
    ) = None
    session_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=160)
    public_summary: str = Field(default="", max_length=500)
    terminal: bool = False
    occurred_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def populate_public_stream_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        event_type = str(normalized.get("event_type") or "")
        canonical = {
            "operation_created": "message.accepted",
            "context_resolved": "context.resolved",
            "agent_execution": "agent.started",
            "plan_proposed": "plan.created",
            "clarification_required": "answer.final",
            "credential_blocked": "operation.failed",
            "draft_created": "artifact.revision.created",
            "patch_proposed": "plan.created",
            # The explicit artifact event below carries the revision payload.
            # Keep acceptance as a plan-step transition so the UI cannot
            # render the same revision twice.
            "patch_accepted": "plan.step.completed",
            "patch_rejected": "operation.completed",
            "undo_applied": "artifact.revision.created",
            # This legacy internal marker is not itself terminal. The service
            # emits the canonical operation.completed event after Worker 3
            # accepts execution.
            "execution_requested": "plan.step.started",
            "operation_retry": "message.accepted",
            "operation_cancelled": "operation.cancelled",
            "operation_failed": "operation.failed",
        }.get(event_type, event_type)
        if not normalized.get("type"):
            normalized["type"] = canonical
        if "payload" not in normalized:
            normalized["payload"] = normalized.get("data") or {}
        if "data" not in normalized:
            normalized["data"] = normalized.get("payload") or {}
        if "terminal" not in normalized:
            normalized["terminal"] = canonical in {
                "operation.completed",
                "operation.failed",
                "operation.cancelled",
            }
        if not normalized.get("public_summary"):
            normalized["public_summary"] = {
                "message.accepted": "Request accepted",
                "context.resolving": "Resolving authorized context",
                "context.resolved": "Authorized context resolved",
                "agent.started": "Agent started",
                "answer.delta": "Answer updated",
                "answer.final": "Answer ready",
                "tool.started": "Tool call started",
                "tool.progress": "Tool call in progress",
                "tool.completed": "Tool call completed",
                "tool.failed": "Tool call failed",
                "plan.created": "Plan created",
                "plan.step.started": "Plan step started",
                "plan.step.completed": "Plan step completed",
                "plan.step.failed": "Plan step failed",
                "artifact.revision.created": "Artifact revision created",
                "operation.completed": "Operation completed",
                "operation.failed": "Operation failed",
                "operation.cancelled": "Operation cancelled",
            }.get(canonical, "Agent activity")
        normalized["public_summary"] = _redact_public_text(
            str(normalized["public_summary"]),
            limit=500,
        )
        for field in ("data", "payload"):
            sanitized = _sanitize_public_value(normalized.get(field) or {})
            normalized[field] = sanitized if isinstance(sanitized, dict) else {}
        for field in ("session_id", "trace_id"):
            if normalized.get(field) is not None:
                normalized[field] = _redact_public_text(
                    str(normalized[field]),
                    limit=160,
                )
        return normalized


class AuthoringOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    operation_type: Literal[
        "answer",
        "create_draft",
        "propose_patch",
        "accept_patch",
        "patch_reject",
        "undo",
        "comment_repair",
        "comment_repair_batch",
        "execute_draft",
        "retry",
        "cancel",
        "copy_team_draft",
        "submit_team_review",
        "update_context",
    ]
    status: AuthoringStatus
    caller_id: str
    workspace_id: str
    conversation_id: str | None = Field(default=None, max_length=160)
    draft_id: str | None = None
    current_revision: int | None = None
    error_code: AuthoringErrorCode | None = None
    error_message: str | None = None
    trace_id: str
    patch_id: str | None = None
    retry_of_operation_id: str | None = None
    clarification_questions: tuple[str, ...] = Field(
        default_factory=tuple, max_length=8
    )
    stage: Literal[
        "received",
        "planning",
        "context_resolved",
        "plan_ready",
        "clarification",
        "draft_ready",
        "patch_ready",
        "execution_queued",
        "execution_succeeded",
        "credential_blocked",
        "cancelled",
        "failed",
    ] = "received"
    progress: int = Field(default=0, ge=0, le=100)
    context_digest: str | None = None
    plan: BuildPlan | None = None
    agent_execution: AgentExecutionEvidence | None = None
    artifact_result: dict[str, object] | None = None
    execution_result: dict[str, object] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuthoringReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: AuthoringOperation
    draft: DraftRevision | None = None
    latest_patch: PatchProposal | None = None
    answer: AgentAnswer | None = None
    events: tuple[AuthoringEvent, ...] = Field(default_factory=tuple)


class CommentRepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: str
    base_revision: int = Field(ge=1)
    comment_id: str = Field(min_length=1, max_length=160)
    patch: TypedPatch
    proposed_by: str = Field(min_length=1, max_length=160)


class CommentRepairBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requests: tuple[CommentRepairRequest, ...] = Field(min_length=1, max_length=32)


class CommentRepairBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    proposals: tuple[PatchProposal, ...]


class TeamReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: str
    base_revision: int = Field(ge=1)
    team_id: str = Field(min_length=1, max_length=160)
    caller_id: str = Field(min_length=1, max_length=160)


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
