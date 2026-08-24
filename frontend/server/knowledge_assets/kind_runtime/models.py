"""Typed Worker 3 execution records.

This module is intentionally independent from the shared BFF command surface.
Main can adapt these records into `skill-draft.run` without Worker 3 editing
shared routes, generated contracts, or repository internals.
"""

from __future__ import annotations

from typing import Literal

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


class ExecutionEvidence(ContractModel):
    evidence_id: str = Field(min_length=1, max_length=256)
    source_revision_id: str = Field(min_length=1, max_length=256)
    golden_asset_revision_id: str = Field(min_length=1, max_length=256)
    locator: str = Field(min_length=1, max_length=2048)
    permission_ref: str = Field(min_length=1, max_length=2048)
    evidence_ref: StorageRef | None = None


class KindExecutionRequest(ContractModel):
    draft_revision: SkillDraftRevision
    caller_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)
    golden_asset_revisions: list[GoldenAssetRevision] = Field(
        default_factory=list, max_length=100
    )
    golden_asset_contents: dict[str, str] = Field(default_factory=dict)
    data_access_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    downstream_skill_revision_refs: list[str] = Field(default_factory=list, max_length=100)
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    freshness_at: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=256)
    trace_id: str = Field(min_length=1, max_length=256)
    cancel_requested: bool = False
    rerun_scope: dict[str, str] = Field(default_factory=dict)
    now: str


class KindHandlerOutput(ContractModel):
    state: KindExecutionState
    template: Literal[
        "dashboard", "chart", "semantic", "knowledge", "graph_ontology", "monitoring"
    ]
    purpose: Literal["overview", "compare", "schema", "answer", "explore", "monitor"]
    view_model: ViewModel | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    evidence: list[ExecutionEvidence] = Field(default_factory=list, max_length=1000)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    error_code: str | None = Field(default=None, max_length=128)
    message: str | None = Field(default=None, max_length=2048)


class SkillKindExecutionRecord(ContractModel):
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
    message: str | None = None
