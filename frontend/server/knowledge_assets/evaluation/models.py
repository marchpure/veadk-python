"""Strict contracts for Knowledge Asset evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

KnowledgeAssetEvalTargetKind = Literal[
    "semantic_skill",
    "asktable_query",
    "asktable",
    "dashboard_skill",
]
KnowledgeAssetEvalRunStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "blocked",
]
KnowledgeAssetEvalResultStatus = Literal["passed", "failed", "blocked"]
KnowledgeAssetJudgeStatus = Literal[
    "not_configured",
    "skipped",
    "succeeded",
    "failed",
]
KnowledgeAssetOptimizationPriority = Literal["high", "medium", "low"]
KnowledgeAssetOptimizationModule = Literal[
    "semantic_model",
    "metric_definition",
    "relationship",
    "policy",
    "freshness",
    "query_tool",
    "dashboard_layout",
    "evidence",
    "other",
]


class KnowledgeAssetEvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class KnowledgeAssetEvaluationOutput(KnowledgeAssetEvalModel):
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)


class KnowledgeAssetOptimizationSuggestion(KnowledgeAssetEvalModel):
    suggestion: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)


class KnowledgeAssetOptimizationGroup(KnowledgeAssetEvalModel):
    priority: KnowledgeAssetOptimizationPriority
    module: KnowledgeAssetOptimizationModule
    custom_module: str | None = Field(
        default=None,
        alias="customModule",
        validation_alias=AliasChoices("customModule", "custom_module"),
        max_length=100,
    )
    items: list[KnowledgeAssetOptimizationSuggestion] = Field(
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_custom_module(self) -> KnowledgeAssetOptimizationGroup:
        custom = (self.custom_module or "").strip()
        if self.module == "other" and not custom:
            raise ValueError("customModule is required when module is other")
        if self.module != "other" and custom:
            raise ValueError("customModule must be null unless module is other")
        self.custom_module = custom or None
        return self


class KnowledgeAssetOptimizationOutput(KnowledgeAssetEvalModel):
    groups: list[KnowledgeAssetOptimizationGroup] = Field(max_length=30)


class CreateKnowledgeAssetEvalSuiteBody(KnowledgeAssetEvalModel):
    space_id: str = Field(alias="spaceId", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    target_kind: KnowledgeAssetEvalTargetKind = Field(alias="targetKind")
    target_asset_id: str = Field(alias="targetAssetId", min_length=1, max_length=256)


class KnowledgeAssetEvalSuite(CreateKnowledgeAssetEvalSuiteBody):
    id: str = Field(min_length=1, max_length=128)
    case_count: int = Field(default=0, alias="caseCount", ge=0)
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class CreateKnowledgeAssetEvalCaseBody(KnowledgeAssetEvalModel):
    target_kind: KnowledgeAssetEvalTargetKind | None = Field(
        default=None,
        alias="targetKind",
    )
    input: str = Field(default="", max_length=4000)
    question: str = Field(default="", max_length=2000)
    intent: str = Field(default="", max_length=2000)
    expected_metric: str = Field(default="", alias="expectedMetric", max_length=256)
    expected_dimensions: list[str] = Field(
        default_factory=list,
        alias="expectedDimensions",
        max_length=20,
    )
    expected_sql_contains: list[str] = Field(
        default_factory=list,
        alias="expectedSqlContains",
        max_length=20,
    )
    expected_policy_decision: str = Field(
        default="",
        alias="expectedPolicyDecision",
        max_length=80,
    )
    expected_dashboard_tiles: list[str] = Field(
        default_factory=list,
        alias="expectedDashboardTiles",
        max_length=50,
    )
    expected_evidence_keys: list[str] = Field(
        default_factory=list,
        alias="expectedEvidenceKeys",
        max_length=50,
    )
    tags: list[str] = Field(default_factory=list, max_length=30)

    @field_validator(
        "expected_dimensions",
        "expected_sql_contains",
        "expected_dashboard_tiles",
        "expected_evidence_keys",
        "tags",
    )
    @classmethod
    def _clean_string_list(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @model_validator(mode="after")
    def validate_prompt(self) -> CreateKnowledgeAssetEvalCaseBody:
        if not (self.input.strip() or self.question.strip() or self.intent.strip()):
            raise ValueError("input, question, or intent is required")
        return self


class ImportKnowledgeAssetEvalCasesBody(KnowledgeAssetEvalModel):
    cases: list[CreateKnowledgeAssetEvalCaseBody] = Field(min_length=1, max_length=200)


class KnowledgeAssetEvalCase(CreateKnowledgeAssetEvalCaseBody):
    id: str = Field(min_length=1, max_length=128)
    suite_id: str = Field(alias="suiteId", min_length=1, max_length=128)
    target_kind: KnowledgeAssetEvalTargetKind = Field(alias="targetKind")
    created_at: str = Field(alias="createdAt")


class RunKnowledgeAssetEvalBody(KnowledgeAssetEvalModel):
    suite_id: str = Field(alias="suiteId", min_length=1, max_length=128)
    target_asset_id: str | None = Field(
        default=None,
        alias="targetAssetId",
        max_length=256,
    )
    generation_mode: str = Field(
        default="deterministic",
        alias="generationMode",
        max_length=80,
    )


class KnowledgeAssetEvalRun(KnowledgeAssetEvalModel):
    id: str = Field(min_length=1, max_length=128)
    suite_id: str = Field(alias="suiteId", min_length=1, max_length=128)
    target_kind: KnowledgeAssetEvalTargetKind = Field(alias="targetKind")
    target_asset_id: str = Field(alias="targetAssetId", min_length=1, max_length=256)
    status: KnowledgeAssetEvalRunStatus
    score: float = Field(default=0, ge=0, le=1)
    started_at: str | None = Field(default=None, alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    model_status: KnowledgeAssetJudgeStatus = Field(alias="modelStatus")
    generation_mode: str = Field(default="deterministic", alias="generationMode")
    result_summary: dict[str, Any] = Field(
        default_factory=dict,
        alias="resultSummary",
    )
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class KnowledgeAssetEvalResult(KnowledgeAssetEvalModel):
    id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(alias="runId", min_length=1, max_length=128)
    case_id: str = Field(alias="caseId", min_length=1, max_length=128)
    status: KnowledgeAssetEvalResultStatus
    score: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=4000)
    actual_output: dict[str, Any] | str | list[Any] | None = Field(
        default=None,
        alias="actualOutput",
    )
    actual_sql: str = Field(default="", alias="actualSql")
    actual_rows_preview: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="actualRowsPreview",
    )
    actual_policy_decision: dict[str, Any] = Field(
        default_factory=dict,
        alias="actualPolicyDecision",
    )
    actual_freshness: dict[str, Any] = Field(
        default_factory=dict,
        alias="actualFreshness",
    )
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, alias="toolCalls")
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    dashboard_spec_diff: dict[str, Any] = Field(
        default_factory=dict,
        alias="dashboardSpecDiff",
    )
    created_at: str = Field(alias="createdAt")


class KnowledgeAssetOptimizationSnapshot(KnowledgeAssetEvalModel):
    target_kind: KnowledgeAssetEvalTargetKind = Field(alias="targetKind")
    target_asset_id: str = Field(alias="targetAssetId", min_length=1, max_length=256)
    generated_at: datetime = Field(
        alias="generatedAt",
        default_factory=lambda: datetime.now(timezone.utc),
    )
    source_run_ids: list[str] = Field(alias="sourceRunIds")
    groups: list[KnowledgeAssetOptimizationGroup] = Field(default_factory=list)


class KnowledgeAssetEvalRunDetail(KnowledgeAssetEvalModel):
    run: KnowledgeAssetEvalRun
    suite: KnowledgeAssetEvalSuite
    cases: list[KnowledgeAssetEvalCase]
    results: list[KnowledgeAssetEvalResult]
    mock: Literal[False] = False


class ImportKnowledgeAssetEvalCasesResult(KnowledgeAssetEvalModel):
    items: list[KnowledgeAssetEvalCase]
    imported: int = Field(ge=0)
    mock: Literal[False] = False
