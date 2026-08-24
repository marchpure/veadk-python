from __future__ import annotations

from .contract_base import *
from .contract_data import *
from .contract_views import *
from .contract_commands import *
from .connector_contracts import ConnectorKindConfig

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
    connector_config: ConnectorKindConfig | None = None


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
