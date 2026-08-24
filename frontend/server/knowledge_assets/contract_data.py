from __future__ import annotations

from .contract_base import *

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
        "local_file", "markdown", "csv", "pdf", "document", "database", "excel",
        "web_api", "mcp"
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
    structure_ref: StorageRef | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    sensitive_classification: list[str] = Field(default_factory=list, max_length=100)
    estimated_cost_ref: StorageRef | None = None
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
