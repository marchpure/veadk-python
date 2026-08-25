"""Canonical typed contracts for the Knowledge Asset Skill Factory.

The Pydantic models in this module are the contract source of truth.  JSON
schemas and the TypeScript consumer types are generated from these models.
The narrow STEP 1 manifest is accepted only through the explicit legacy input
adapter below; repositories receive and persist only :class:`SkillManifest`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

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
    "sop",
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


class TemplateRef(ContractModel):
    """Immutable reference to the method used to build a Skill revision."""

    template_id: str = Field(min_length=1, max_length=256)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContextRevisionRef(ContractModel):
    """A pinned input context; mutable resource ids are intentionally rejected."""

    kind: Literal[
        "source",
        "golden_asset",
        "document",
        "semantic_skill",
        "published_skill",
        "tool",
    ]
    resource_id: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(min_length=1, max_length=256)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    permission_ref: PermissionRef | None = None


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
        "markdown",
        "pdf",
        "office",
        "lark_doc",
        "lark_minutes",
        "lark_group_chat",
        "web_api",
        "web_url",
        "rest_api",
        "graphql",
        "openapi",
        "mcp",
        "published_skill",
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


class DashboardPresentationSpec(ContractModel):
    title: str | None = Field(default=None, max_length=256)
    kpi_labels: dict[str, str] = Field(default_factory=dict)
    chart_title: str | None = Field(default=None, max_length=256)
    filter_fields: list[str] = Field(default_factory=list, max_length=100)
    drill_fields: list[str] = Field(default_factory=list, max_length=100)


class AnalysisKindSpec(ContractModel):
    kind: Literal["analysis"] = "analysis"
    question: str = Field(min_length=1, max_length=2048)
    query_plan_ref: str = Field(min_length=1, max_length=2048)
    refresh_policy_ref: str | None = Field(default=None, max_length=2048)
    alert_policy_ref: str | None = Field(default=None, max_length=2048)
    dashboard: DashboardPresentationSpec | None = None


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
    entities: list[str] = Field(default_factory=list, max_length=500)
    relationships: list["GraphRelationSpec"] = Field(
        default_factory=list, max_length=1000
    )
    evidence_policy_ref: PermissionRef | None = None


class GraphRelationSpec(ContractModel):
    source: str = Field(min_length=1, max_length=256)
    target: str = Field(min_length=1, max_length=256)
    relation: str = Field(min_length=1, max_length=256)
    evidence_locator: str = Field(min_length=1, max_length=2048)


class MonitoringKindSpec(ContractModel):
    kind: Literal["monitoring"] = "monitoring"
    metric_refs: list[str] = Field(default_factory=list, max_length=100)
    refresh_schedule_ref: str = Field(min_length=1, max_length=2048)
    alert_policy_ref: str = Field(min_length=1, max_length=2048)
    action_policy_ref: PermissionRef | None = None


class SopInputField(ContractModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=128)
    label: str = Field(min_length=1, max_length=256)
    value_type: Literal["string", "number", "boolean", "enum"]
    required: bool = True
    enum_values: list[str] = Field(default_factory=list, max_length=100)
    description: str = Field(default="", max_length=1024)

    @model_validator(mode="after")
    def enum_values_match_type(self) -> "SopInputField":
        if self.value_type == "enum" and not self.enum_values:
            raise ValueError("enum SOP input fields require enumValues")
        if self.value_type != "enum" and self.enum_values:
            raise ValueError("enumValues are only valid for enum SOP input fields")
        return self


class SopCondition(ContractModel):
    field: str = Field(min_length=1, max_length=128)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "exists"]
    value: str | int | float | bool | None = None


class SopToolRef(ContractModel):
    tool_id: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=128)
    risk: Literal["read_only", "external_write", "high_risk"] = "read_only"


class SopEvidenceRequirement(ContractModel):
    kind: Literal["tool_result", "source_citation", "input", "decision"]
    required: bool = True
    locator: str | None = Field(default=None, max_length=2048)


class SopStep(ContractModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    instruction: str = Field(min_length=1, max_length=4096)
    condition: SopCondition | None = None
    tool_ref: SopToolRef | None = None
    evidence_requirements: list[SopEvidenceRequirement] = Field(
        default_factory=list, max_length=32
    )
    on_true: str | None = Field(default=None, max_length=128)
    on_false: str | None = Field(default=None, max_length=128)
    failure_mode: Literal["stop", "continue", "request_input", "propose_action"] = (
        "stop"
    )


class SopOutputField(ContractModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    value_type: Literal["string", "number", "boolean", "object", "array"]


class SopKindSpec(ContractModel):
    kind: Literal["sop"] = "sop"
    trigger: str = Field(min_length=1, max_length=1024)
    scope: str = Field(min_length=1, max_length=1024)
    input_fields: list[SopInputField] = Field(min_length=1, max_length=100)
    steps: list[SopStep] = Field(min_length=1, max_length=200)
    outputs: list[SopOutputField] = Field(default_factory=list, max_length=100)
    failure_handling: str = Field(min_length=1, max_length=2048)
    action_proposal: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_step_graph(self) -> "SopKindSpec":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("SOP step ids must be unique")
        known = set(step_ids)
        for step in self.steps:
            for target in (step.on_true, step.on_false):
                if target is not None and target not in known:
                    raise ValueError(f"SOP branch target does not exist: {target}")
        return self


KindSpec = Annotated[
    DataAccessKindSpec
    | SemanticKindSpec
    | AnalysisKindSpec
    | KnowledgeKindSpec
    | GraphOntologyKindSpec
    | MonitoringKindSpec
    | SopKindSpec,
    Field(discriminator="kind"),
]

TemplateContextKind = Literal[
    "tabular",
    "document",
    "semantic_skill",
    "knowledge",
    "graph",
    "tool",
    "observation",
]
TemplateRenderer = Literal[
    "dashboard", "semantic", "sop", "knowledge", "graph_ontology", "monitoring"
]


class TemplateQualityGate(ContractModel):
    gate_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    required: bool = True


class TemplateEvidenceRule(ContractModel):
    evidence_kind: Literal[
        "data_revision", "source_citation", "tool_result", "schema", "trace"
    ]
    description: str = Field(min_length=1, max_length=1024)
    minimum_count: int = Field(default=1, ge=0, le=1000)


class TemplateSpec(ContractModel):
    """Versioned, validated build method. The generated artifact is always a Skill."""

    template_id: str = Field(min_length=1, max_length=256)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    display_name: str = Field(min_length=1, max_length=128)
    scenario: str = Field(min_length=1, max_length=2048)
    required_context_kinds: list[TemplateContextKind] = Field(
        min_length=1, max_length=32
    )
    input_schema: dict[str, Any]
    capability_intent: SkillKind
    execution_instructions: list[str] = Field(min_length=1, max_length=100)
    evidence_rules: list[TemplateEvidenceRule] = Field(min_length=1, max_length=100)
    quality_gates: list[TemplateQualityGate] = Field(min_length=1, max_length=100)
    default_renderer: TemplateRenderer
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    allowed_actions: list[str] = Field(default_factory=list, max_length=100)
    compatibility: CompatibilityTargets = Field(default_factory=CompatibilityTargets)
    builtin: bool = False
    owner_workspace_id: str | None = Field(default=None, max_length=128)
    copied_from: TemplateRef | None = None

    @model_validator(mode="after")
    def validate_template(self) -> "TemplateSpec":
        if self.input_schema.get("type") != "object":
            raise ValueError("TemplateSpec inputSchema must be a JSON object schema")
        if self.builtin and self.owner_workspace_id is not None:
            raise ValueError("built-in templates cannot have a workspace owner")
        if not self.builtin and not self.owner_workspace_id:
            raise ValueError("custom templates require ownerWorkspaceId")
        renderer_kind = {
            "dashboard": "analysis",
            "semantic": "semantic",
            "sop": "sop",
            "knowledge": "knowledge",
            "graph_ontology": "graph_ontology",
            "monitoring": "monitoring",
        }[self.default_renderer]
        if renderer_kind != self.capability_intent:
            raise ValueError("defaultRenderer must match capabilityIntent")
        return self


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
    template_ref: TemplateRef | None = None
    default_renderer: TemplateRenderer | None = None
    context_revision_refs: list[ContextRevisionRef] = Field(
        default_factory=list, max_length=100
    )
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
    api_version: Literal["knowledge.veadk.io/v1alpha1"] = "knowledge.veadk.io/v1alpha1"
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
                input_schema_ref=SchemaRef(
                    uri=digest_source, version=value.version, sha256=digest
                ),
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
