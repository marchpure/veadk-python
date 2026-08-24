"""Canonical typed contracts for the Knowledge Asset Skill Factory.

The Pydantic models in this module are the contract source of truth.  JSON
schemas and the TypeScript consumer types are generated from these models.
The narrow STEP 1 manifest is accepted only through the explicit legacy input
adapter below; repositories receive and persist only :class:`SkillManifest`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


RuntimeProfile = Literal["production", "demo", "test"]
SkillKind = Literal[
    "data_access",
    "semantic",
    "analysis",
    "knowledge",
    "graph_ontology",
    "monitoring",
]
StorageKind = Literal["object", "table", "vector", "bundle", "inline"]


class StorageRef(ContractModel):
    """Content or table reference; large values never live in metadata JSON."""

    uri: str = Field(min_length=1, max_length=2048)
    kind: StorageKind
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=256)
    bytes: int | None = Field(default=None, ge=0)


class SchemaRef(ContractModel):
    uri: str = Field(min_length=1, max_length=2048)
    version: str = Field(min_length=1, max_length=64)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SecretRef(ContractModel):
    uri: str = Field(pattern=r"^secret://.+", max_length=2048)
    version: str = Field(min_length=1, max_length=64)


class OwnerRef(ContractModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    principal_id: str = Field(min_length=1, max_length=256)


class PermissionRef(ContractModel):
    uri: str = Field(min_length=1, max_length=2048)
    version: str = Field(min_length=1, max_length=64)


class CompatibilityTargets(ContractModel):
    targets: list[Literal["agentkit", "mcp", "openapi", "codex"]] = Field(
        default_factory=list, max_length=8
    )


class SkillDependencies(ContractModel):
    skills: list[str] = Field(default_factory=list, max_length=100)
    golden_assets: list[str] = Field(default_factory=list, max_length=100)
    sources: list[str] = Field(default_factory=list, max_length=100)


class DataAccessKindSpec(ContractModel):
    kind: Literal["data_access"] = "data_access"
    connector_type: Literal[
        "oracle",
        "mysql",
        "postgresql",
        "csv",
        "excel",
        "web_api",
        "mcp",
        "local_file",
    ]
    endpoint_ref: str = Field(min_length=1, max_length=2048)
    secret_ref: SecretRef | None = None
    allowed_schemas: list[str] = Field(default_factory=list, max_length=100)
    allowed_tables: list[str] = Field(default_factory=list, max_length=100)
    allowed_operations: list[
        Literal["introspect", "query", "read", "subscribe", "search"]
    ] = Field(default_factory=list, max_length=16)
    row_policy_ref: PermissionRef | None = None
    column_policy_ref: PermissionRef | None = None


class SemanticKindSpec(ContractModel):
    kind: Literal["semantic"] = "semantic"
    metric_refs: list[str] = Field(default_factory=list, max_length=100)
    dimension_refs: list[str] = Field(default_factory=list, max_length=100)
    relationship_refs: list[str] = Field(default_factory=list, max_length=100)
    query_policy_ref: PermissionRef | None = None


class AnalysisKindSpec(ContractModel):
    kind: Literal["analysis"] = "analysis"
    question: str = Field(min_length=1, max_length=2048)
    query_plan_ref: str = Field(min_length=1, max_length=2048)
    refresh_policy_ref: str | None = Field(default=None, max_length=2048)
    alert_policy_ref: str | None = Field(default=None, max_length=2048)


class KnowledgeKindSpec(ContractModel):
    kind: Literal["knowledge"] = "knowledge"
    retrieval_mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    source_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    citation_policy_ref: PermissionRef | None = None
    refusal_policy_ref: str | None = Field(default=None, max_length=2048)


class GraphOntologyKindSpec(ContractModel):
    kind: Literal["graph_ontology"] = "graph_ontology"
    entity_schema_ref: SchemaRef
    relationship_schema_ref: SchemaRef
    constraint_refs: list[str] = Field(default_factory=list, max_length=100)
    evidence_policy_ref: PermissionRef | None = None


class MonitoringKindSpec(ContractModel):
    kind: Literal["monitoring"] = "monitoring"
    metric_refs: list[str] = Field(default_factory=list, max_length=100)
    refresh_schedule_ref: str = Field(min_length=1, max_length=2048)
    alert_policy_ref: str = Field(min_length=1, max_length=2048)
    action_policy_ref: PermissionRef | None = None


KindSpec = Annotated[
    DataAccessKindSpec
    | SemanticKindSpec
    | AnalysisKindSpec
    | KnowledgeKindSpec
    | GraphOntologyKindSpec
    | MonitoringKindSpec,
    Field(discriminator="kind"),
]


class SkillContract(ContractModel):
    input_schema_ref: SchemaRef
    output_schema_ref: SchemaRef
    examples_ref: StorageRef | None = None
    error_codes: list[str] = Field(default_factory=list, max_length=100)
    operations: list["SkillOperation"] = Field(default_factory=list, max_length=64)


class SkillOperation(ContractModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    input_schema_ref: SchemaRef
    output_schema_ref: SchemaRef
    risk: Literal["read_only", "external_write", "high_risk"] = "read_only"


class SkillSpec(ContractModel):
    kind: SkillKind
    contract: SkillContract
    dependencies: SkillDependencies = Field(default_factory=SkillDependencies)
    policy_ref: PermissionRef
    runtime_ref: str = Field(min_length=1, max_length=2048)
    evaluation_suite_ref: str | None = Field(default=None, max_length=2048)
    skill_view_ref: str | None = Field(default=None, max_length=2048)
    compatibility: CompatibilityTargets = Field(default_factory=CompatibilityTargets)
    kind_spec: KindSpec

    @model_validator(mode="after")
    def kind_matches_spec(self) -> "SkillSpec":
        if self.kind != self.kind_spec.kind:
            raise ValueError("spec.kind must match spec.kindSpec.kind")
        return self


class SkillMetadata(ContractModel):
    id: str = Field(min_length=1, max_length=256)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2048)
    owner: OwnerRef
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SkillManifest(ContractModel):
    api_version: Literal["knowledge.veadk.io/v1alpha1"] = (
        "knowledge.veadk.io/v1alpha1"
    )
    kind: Literal["Skill"] = "Skill"
    metadata: SkillMetadata
    spec: SkillSpec


class ManifestProperty(ContractModel):
    type: Literal["string", "number", "boolean", "object", "array"]
    description: str = Field(default="", max_length=512)


class ManifestInputSchema(ContractModel):
    type: Literal["object"] = "object"
    properties: dict[str, ManifestProperty] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list, max_length=100)
    additional_properties: bool = False


class SkillManifestAction(ContractModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)


class LegacySkillManifestInput(ContractModel):
    """The only accepted compatibility shape for the original M1 UI."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    description: str = Field(default="", max_length=1024)
    actions: list[SkillManifestAction] = Field(default_factory=list, max_length=64)
    schema: ManifestInputSchema = Field(default_factory=ManifestInputSchema)


def adapt_legacy_manifest(
    value: LegacySkillManifestInput,
    *,
    draft_id: str,
    workspace_id: str,
) -> SkillManifest:
    """Normalize the frozen M1 knowledge payload at the BFF boundary."""

    digest_source = f"schema://{draft_id}/input"
    digest = "0" * 64  # refs are identifiers until a schema artifact exists
    operation_refs = [
        SkillOperation(
            name=action.name,
            description=action.description,
            input_schema_ref=SchemaRef(
                uri=digest_source,
                version=value.version,
                sha256=digest,
            ),
            output_schema_ref=SchemaRef(
                uri=f"schema://{draft_id}/output",
                version=value.version,
                sha256=digest,
            ),
        )
        for action in value.actions
    ]
    return SkillManifest(
        metadata=SkillMetadata(
            id=draft_id,
            version=value.version,
            display_name=value.name,
            description=value.description,
            owner=OwnerRef(workspace_id=workspace_id, principal_id="local"),
        ),
        spec=SkillSpec(
            kind="knowledge",
            contract=SkillContract(
                input_schema_ref=SchemaRef(uri=digest_source, version=value.version, sha256=digest),
                output_schema_ref=SchemaRef(
                    uri=f"schema://{draft_id}/output",
                    version=value.version,
                    sha256=digest,
                ),
                error_codes=["VALIDATION_ERROR", "FORBIDDEN", "UNAVAILABLE"],
                operations=operation_refs,
            ),
            policy_ref=PermissionRef(
                uri=f"policy://workspace/{workspace_id}", version="1"
            ),
            runtime_ref="runtime://knowledge/v1",
            kind_spec=KnowledgeKindSpec(
                source_revision_refs=[],
                retrieval_mode="hybrid",
            ),
        ),
    )


def empty_knowledge_manifest(
    *, draft_id: str, workspace_id: str, name: str, description: str
) -> SkillManifest:
    return adapt_legacy_manifest(
        LegacySkillManifestInput(
            name=name,
            version="1.0.0",
            description=description,
            actions=[],
        ),
        draft_id=draft_id,
        workspace_id=workspace_id,
    )


class SkillDraft(ContractModel):
    id: str
    workspace_id: str
    name: str
    description: str
    revision: int = Field(ge=1)
    lifecycle: Literal["draft"] = "draft"
    view_state: Literal["debug"] = "debug"
    created_at: str
    updated_at: str
    manifest: SkillManifest


class SourceRevision(ContractModel):
    id: str
    source_type: Literal[
        "local_file", "pdf", "document", "database", "excel", "web_api", "mcp"
    ]
    content_ref: StorageRef
    schema_ref: SchemaRef | None = None
    permission_ref: PermissionRef
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str


class ProfileRun(ContractModel):
    id: str
    source_revision_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    sample_ref: StorageRef | None = None
    report_ref: StorageRef | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    error_code: str | None = None
    started_at: str
    finished_at: str | None = None


class CleaningRecipe(ContractModel):
    id: str
    version: int = Field(ge=1)
    operations: list[
        Literal["trim", "deduplicate", "normalize", "split", "map", "redact"]
    ] = Field(default_factory=list, max_length=100)
    config_ref: StorageRef | None = None
    source_revision_id: str
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CleanRun(ContractModel):
    id: str
    source_revision_id: str
    recipe_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    output_ref: StorageRef | None = None
    quality_report_ref: StorageRef | None = None
    error_code: str | None = None
    started_at: str
    finished_at: str | None = None


class GoldenAssetRevision(ContractModel):
    id: str
    asset_kind: Literal["dataset", "knowledge", "semantic", "graph"]
    revision: int = Field(ge=1)
    schema_ref: SchemaRef
    storage_ref: StorageRef
    source_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    recipe_ref: str | None = None
    quality_run_ref: str | None = None
    owner: OwnerRef
    permissions_ref: PermissionRef
    lineage_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    freshness_at: str
    last_good: bool = True


class SkillDraftRevision(ContractModel):
    id: str
    skill_id: str
    revision: int = Field(ge=1)
    manifest: SkillManifest
    source_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    golden_asset_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    status: Literal[
        "draft",
        "planning",
        "awaiting_input",
        "running",
        "partially_succeeded",
        "failed",
        "ready_for_evaluation",
        "evaluating",
        "publishable",
        "publishing",
        "published",
    ] = "draft"
    created_at: str


class SkillResult(ContractModel):
    id: str
    skill_id: str
    skill_revision: int = Field(ge=1)
    kind: SkillKind
    output_schema_ref: SchemaRef
    result_ref: StorageRef
    source_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    golden_asset_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    trace_id: str
    freshness_at: str | None = None


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


class EvaluationSuite(ContractModel):
    id: str
    version: int = Field(ge=1)
    skill_id: str
    case_count: int = Field(ge=0)
    cases_ref: StorageRef
    pass_threshold: float = Field(ge=0, le=1)


class EvaluationRun(ContractModel):
    id: str
    suite_id: str
    suite_version: int = Field(ge=1)
    skill_revision_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    score: float | None = Field(default=None, ge=0, le=1)
    evidence_ref: StorageRef | None = None
    regression_ref: StorageRef | None = None
    started_at: str
    finished_at: str | None = None


class PolicyGateResult(ContractModel):
    id: str
    skill_revision_id: str
    evaluation_run_id: str
    decision: Literal["publishable", "blocked"]
    reasons: list[str] = Field(default_factory=list)
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


class ErrorEnvelope(ContractModel):
    code: str
    message: str
    retryable: bool
    request_id: str
    details: dict[str, str] | None = None


class ResourceSummary(ContractModel):
    id: str
    display_name: str
    resource_kind: Literal["skill_draft"] = "skill_draft"
    subtype: Literal["skill"] = "skill"
    space: Literal["personal", "team"]
    lifecycle: Literal["draft"] = "draft"
    version: str = "DRAFT"
    revision: int = Field(default=1, ge=1)
    permission: bool = True


class BootstrapResponse(ContractModel):
    resources: list[ResourceSummary]
    connections: list[dict[str, str]]
    publications: list[dict[str, str]]
    routes: list[str]
    workspace_data: dict[str, object]
    action_loop: dict[str, list[object]]
    access: dict[str, object]
    server_time: str


class CreateSkillDraftPayload(ContractModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class SaveManifestPayload(ContractModel):
    draft_id: str = Field(min_length=1, max_length=128)
    base_revision: int = Field(ge=1)
    manifest: SkillManifest | LegacySkillManifestInput


class ResourcePayload(ContractModel):
    resource_id: str = Field(min_length=1, max_length=128)


class ConnectorPayload(ContractModel):
    connector_key: str = Field(min_length=1, max_length=128)


class ImportPayload(ContractModel):
    source_id: str = Field(min_length=1, max_length=128)


class AssistantTurnPayload(ContractModel):
    text: str = Field(min_length=1, max_length=16_384)
    context_ids: list[str] = Field(default_factory=list, max_length=100)


class EvaluationPayload(ContractModel):
    target_id: str = Field(min_length=1, max_length=128)


class ActionUpdatePayload(ContractModel):
    action_id: str = Field(min_length=1, max_length=512)


class ArtifactExportPayload(ContractModel):
    resource_id: str = Field(min_length=1, max_length=128)
    format: Literal["json", "csv", "html"]


class StreamCancelPayload(ContractModel):
    stream_id: str = Field(min_length=1, max_length=128)
    source_command: Literal["import.start", "assistant.turn"]


class SourceProfilePayload(ContractModel):
    source_revision_id: str = Field(min_length=1, max_length=256)
    sample_limit: int = Field(default=100, ge=1, le=10_000)


class SourceCleanPayload(ContractModel):
    source_revision_id: str = Field(min_length=1, max_length=256)
    recipe_id: str = Field(min_length=1, max_length=256)


class SkillDraftRunPayload(ContractModel):
    draft_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1)
    trace_id: str = Field(min_length=1, max_length=256)


class PublicationPublishPayload(ContractModel):
    draft_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1)
    semver: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class RefreshRunPayload(ContractModel):
    skill_id: str = Field(min_length=1, max_length=256)
    trigger: Literal["manual", "schedule", "event", "freshness_on_read"]


class InvocationStartPayload(ContractModel):
    skill_version_id: str = Field(min_length=1, max_length=256)
    input_ref: StorageRef
    caller_id: str = Field(min_length=1, max_length=256)


class CommandResultBase(ContractModel):
    result_type: str
    error: ErrorEnvelope | None = None


class DraftCommandResult(CommandResultBase):
    result_type: Literal["skill-draft.create", "skill-draft.save-manifest"]
    draft: SkillDraft
    replayed: bool = False


class NotReadyCommandResult(CommandResultBase):
    result_type: Literal["command.not-ready"] = "command.not-ready"
    command: str
    error: ErrorEnvelope


class SourceProfileResult(CommandResultBase):
    result_type: Literal["source.profile"] = "source.profile"
    status: Literal["not_ready"] = "not_ready"
    source_revision_id: str


class SourceCleanResult(CommandResultBase):
    result_type: Literal["source.clean"] = "source.clean"
    status: Literal["not_ready"] = "not_ready"
    source_revision_id: str
    recipe_id: str


class SkillDraftRunResult(CommandResultBase):
    result_type: Literal["skill-draft.run"] = "skill-draft.run"
    status: Literal["not_ready"] = "not_ready"
    draft_id: str


class PublicationPublishResult(CommandResultBase):
    result_type: Literal["publication.publish"] = "publication.publish"
    status: Literal["not_ready"] = "not_ready"
    draft_id: str


class RefreshRunResult(CommandResultBase):
    result_type: Literal["refresh.run"] = "refresh.run"
    status: Literal["not_ready"] = "not_ready"
    skill_id: str


class InvocationStartResult(CommandResultBase):
    result_type: Literal["invocation.start"] = "invocation.start"
    status: Literal["not_ready"] = "not_ready"
    skill_version_id: str


CommandResult = Annotated[
    DraftCommandResult
    | NotReadyCommandResult
    | SourceProfileResult
    | SourceCleanResult
    | SkillDraftRunResult
    | PublicationPublishResult
    | RefreshRunResult
    | InvocationStartResult,
    Field(discriminator="result_type"),
]


class CreateSkillDraftCommand(ContractModel):
    command: Literal["skill-draft.create"]
    payload: CreateSkillDraftPayload


class SaveManifestCommand(ContractModel):
    command: Literal["skill-draft.save-manifest"]
    payload: SaveManifestPayload


class ResourceCommand(ContractModel):
    command: Literal[
        "resource.create",
        "resource.update",
        "resource.publish",
        "resource.share",
        "resource.revoke",
    ]
    payload: ResourcePayload


class ConnectorCommand(ContractModel):
    command: Literal["connector.create", "connector.test"]
    payload: ConnectorPayload


class ImportCommand(ContractModel):
    command: Literal["import.start", "import.cancel"]
    payload: ImportPayload


class StreamCancelCommand(ContractModel):
    command: Literal["stream.cancel"]
    payload: StreamCancelPayload


class AssistantCommand(ContractModel):
    command: Literal["assistant.turn"]
    payload: AssistantTurnPayload


class EvaluationCommand(ContractModel):
    command: Literal["evaluation.run", "evaluation.apply"]
    payload: EvaluationPayload


class ActionCommand(ContractModel):
    command: Literal["action.update"]
    payload: ActionUpdatePayload


class ArtifactExportCommand(ContractModel):
    command: Literal["artifact.export"]
    payload: ArtifactExportPayload


class SourceProfileCommand(ContractModel):
    command: Literal["source.profile"]
    payload: SourceProfilePayload


class SourceCleanCommand(ContractModel):
    command: Literal["source.clean"]
    payload: SourceCleanPayload


class SkillDraftRunCommand(ContractModel):
    command: Literal["skill-draft.run"]
    payload: SkillDraftRunPayload


class PublicationPublishCommand(ContractModel):
    command: Literal["publication.publish"]
    payload: PublicationPublishPayload


class RefreshRunCommand(ContractModel):
    command: Literal["refresh.run"]
    payload: RefreshRunPayload


class InvocationStartCommand(ContractModel):
    command: Literal["invocation.start"]
    payload: InvocationStartPayload


CommandRequest = Annotated[
    CreateSkillDraftCommand
    | SaveManifestCommand
    | ResourceCommand
    | ConnectorCommand
    | ImportCommand
    | StreamCancelCommand
    | AssistantCommand
    | EvaluationCommand
    | ActionCommand
    | ArtifactExportCommand
    | SourceProfileCommand
    | SourceCleanCommand
    | SkillDraftRunCommand
    | PublicationPublishCommand
    | RefreshRunCommand
    | InvocationStartCommand,
    Field(discriminator="command"),
]


class CommandResponse(ContractModel):
    accepted: bool
    request_id: str
    operation_id: str | None = None
    result: CommandResult | None = None


class Event(ContractModel):
    schema_version: Literal["knowledge-assets.event.v1"] = (
        "knowledge-assets.event.v1"
    )
    operation_id: str
    event_id: str
    sequence: int = Field(ge=1)
    occurred_at: str
    type: Literal["accepted", "progress", "succeeded", "failed", "cancelled"]
    terminal: bool
    result: CommandResult | None = None
    error: ErrorEnvelope | None = None


OperationEvent = Event


class Audit(ContractModel):
    request_id: str
    operation_id: str
    workspace_id: str
    action: str
    resource_id: str
    outcome: str
    details: dict[str, object] = Field(default_factory=dict)
    occurred_at: str


AuditItem = Audit


class Operation(ContractModel):
    operation_id: str
    status: Literal["accepted", "running", "succeeded", "failed", "cancelled"]
    version: int
    events: list[Event]
    result: CommandResult | None = None
    error: ErrorEnvelope | None = None
    next_actions: list[str] = Field(default_factory=list)
    audit: list[Audit] = Field(default_factory=list)


OperationResponse = Operation


class OperationAuditResponse(ContractModel):
    operation_id: str
    items: list[Audit] = Field(default_factory=list)


def validate_state_transition(
    current: str, target: str, *, cancelled: bool = False
) -> None:
    """Validate the shared draft/job lifecycle without executing STEP 2+."""

    transitions: dict[str, set[str]] = {
        "draft": {"planning", "running", "failed"},
        "planning": {"awaiting_input", "running", "failed", "cancelled"},
        "awaiting_input": {"running", "cancelled"},
        "running": {"partially_succeeded", "failed", "ready_for_evaluation", "cancelled"},
        "partially_succeeded": {"running", "failed", "ready_for_evaluation"},
        "ready_for_evaluation": {"evaluating", "failed"},
        "evaluating": {"publishable", "failed"},
        "publishable": {"publishing", "failed"},
        "publishing": {"published", "failed"},
        "published": set(),
        "failed": {"planning", "running"},
        "cancelled": set(),
    }
    if cancelled and target != "cancelled":
        raise ValueError("cancelled jobs can only transition to cancelled")
    if target not in transitions.get(current, set()):
        raise ValueError(f"invalid state transition: {current} -> {target}")


class CoreContractBundle(ContractModel):
    """Schema-only registry that keeps every STEP 1 core contract generated."""

    source_revision: SourceRevision | None = None
    profile_run: ProfileRun | None = None
    cleaning_recipe: CleaningRecipe | None = None
    clean_run: CleanRun | None = None
    golden_asset_revision: GoldenAssetRevision | None = None
    skill_draft_revision: SkillDraftRevision | None = None
    skill_result: SkillResult | None = None
    view_intent: ViewIntent | None = None
    view_model: ViewModel | None = None
    skill_view_manifest: SkillViewManifest | None = None
    skill_view_revision: SkillViewRevision | None = None
    evaluation_suite: EvaluationSuite | None = None
    evaluation_run: EvaluationRun | None = None
    policy_gate_result: PolicyGateResult | None = None
    published_skill_version: PublishedSkillVersion | None = None
    agent_binding: AgentBinding | None = None
    invocation: Invocation | None = None
    refresh_run: RefreshRun | None = None
    alert_event: AlertEvent | None = None
    legacy_skill_manifest_input: LegacySkillManifestInput | None = None
    command_request: CommandRequest | None = None
    command_result: CommandResult | None = None
    command_response: CommandResponse | None = None
    operation: Operation | None = None
    event: Event | None = None
    audit: Audit | None = None
    job_state: JobState | None = None
    job_event: JobEvent | None = None


class JobState(ContractModel):
    job_id: str
    job_type: str
    profile: RuntimeProfile
    idempotency_key: str
    status: Literal[
        "queued",
        "leased",
        "running",
        "cancelling",
        "succeeded",
        "failed",
        "cancelled",
        "dead_letter",
    ]
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    next_attempt_at: str | None = None
    cancel_requested: bool = False
    outbox_sequence: int = Field(default=0, ge=0)


class JobEvent(ContractModel):
    job_id: str
    sequence: int = Field(ge=1)
    event_type: Literal[
        "enqueued",
        "leased",
        "heartbeat",
        "retry_scheduled",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
        "dead_letter",
    ]
    occurred_at: str
    payload_ref: StorageRef | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
