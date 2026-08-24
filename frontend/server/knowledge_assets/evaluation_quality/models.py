from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseSource(str, Enum):
    MANUAL = "manual"
    HISTORICAL_CONVERSATION = "historical_conversation"
    HISTORICAL_RUN = "historical_run"
    CSV_IMPORT = "csv_import"
    JSON_IMPORT = "json_import"
    AGENT_CANDIDATE = "agent_candidate"


class CaseCategory(str, Enum):
    NORMAL = "normal"
    REFUSAL = "refusal"
    UNAUTHORIZED = "unauthorized"
    EMPTY_DATA = "empty_data"
    AMBIGUITY = "ambiguity"
    METRIC_DEFINITION = "metric_definition"
    CITATION = "citation"
    CHART_CONSISTENCY = "chart_consistency"
    INTERACTION = "interaction"
    PERFORMANCE_BUDGET = "performance_budget"


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    source: CaseSource
    category: CaseCategory
    input: dict[str, object]
    expected: dict[str, object]
    grading: dict[str, object] = Field(default_factory=dict)
    provenance_ref: str | None = None
    candidate_confirmed: bool = False
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def candidate_requires_confirmation(self) -> "EvaluationCase":
        if self.source != CaseSource.AGENT_CANDIDATE and self.candidate_confirmed:
            raise ValueError("only agent candidates may carry candidate_confirmed")
        return self

    @property
    def runnable(self) -> bool:
        return self.source != CaseSource.AGENT_CANDIDATE or self.candidate_confirmed


class EvaluationSuite(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    skill_id: str = Field(min_length=1, max_length=256)
    cases: tuple[EvaluationCase, ...]
    pass_threshold: float = Field(default=1.0, ge=0, le=1)
    created_at: str = Field(default_factory=utc_now)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RunProvenance(StrictModel):
    suite_id: str
    suite_version: int = Field(ge=1)
    environment: Literal["test", "staging", "production"]
    skill_draft_revision: str
    dependency_revision_refs: tuple[str, ...] = ()
    golden_revision_refs: tuple[str, ...] = ()
    executor_version: str
    renderer_version: str
    data_as_of: str


class EvaluationActual(StrictModel):
    output: dict[str, object]
    duration_ms: int = Field(ge=0)
    trace_ref: str
    evidence: tuple[str, ...] = ()


class EvaluationCaseResult(StrictModel):
    case_id: str
    status: Literal["passed", "failed", "cancelled"]
    score: float = Field(ge=0, le=1)
    input: dict[str, object]
    expected: dict[str, object]
    actual: dict[str, object] | None = None
    grading: dict[str, object] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
    trace_ref: str | None = None
    regression_diff: dict[str, object] = Field(default_factory=dict)
    duration_ms: int | None = Field(default=None, ge=0)


class EvaluationRun(StrictModel):
    id: str
    provenance: RunProvenance
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    selected_case_ids: tuple[str, ...]
    case_results: tuple[EvaluationCaseResult, ...] = ()
    attempt: int = Field(default=1, ge=1)
    retry_of: str | None = None
    created_at: str = Field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def score(self) -> float | None:
        if not self.case_results:
            return None
        return sum(result.score for result in self.case_results) / len(
            self.case_results
        )


class PolicyCheck(StrictModel):
    dimension: Literal[
        "schema",
        "data_quality",
        "freshness",
        "permission",
        "security",
        "evaluation",
        "visual_interaction",
        "compatibility",
        "budget",
    ]
    passed: bool
    machine_reason: str
    evidence_refs: tuple[str, ...] = ()


class PolicyGateInput(StrictModel):
    skill_draft_revision: str
    evaluation_run_id: str
    checks: tuple[PolicyCheck, ...]


class PolicyGateResult(StrictModel):
    id: str
    skill_draft_revision: str
    evaluation_run_id: str
    decision: Literal["publishable", "blocked"]
    checks: tuple[PolicyCheck, ...]
    machine_reasons: tuple[str, ...]
    checked_at: str = Field(default_factory=utc_now)


class PatchOperation(StrictModel):
    op: Literal[
        "replace_query",
        "replace_metric",
        "replace_retrieval_policy",
        "replace_view_binding",
        "replace_interaction",
        "replace_budget",
    ]
    path: str = Field(pattern=r"^/(query|metrics|retrieval|view|interaction|budget)/")
    before: object
    after: object


class TypedPatch(StrictModel):
    id: str
    base_draft_revision: str
    operations: tuple[PatchOperation, ...] = Field(min_length=1)


class FixPlan(StrictModel):
    id: str
    run_id: str
    issue_case_ids: tuple[str, ...] = Field(min_length=1)
    affected_case_ids: tuple[str, ...] = Field(min_length=1)
    conflicts: tuple[str, ...] = ()
    patch: TypedPatch
    status: Literal["proposed", "applied", "undone"] = "proposed"
    new_draft_revision: str | None = None
    rerun_id: str | None = None
    undo_token: str | None = None


EvaluationImport = Annotated[
    list[EvaluationCase], Field(min_length=1, max_length=1000)
]
