from __future__ import annotations

"""Canonical typed contracts for the Knowledge Asset Skill Factory.

The Pydantic models in this module are the contract source of truth.  JSON
schemas and the TypeScript consumer types are generated from these models.
The narrow STEP 1 manifest is accepted only through the explicit legacy input
adapter below; repositories receive and persist only :class:`SkillManifest`.
"""


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

