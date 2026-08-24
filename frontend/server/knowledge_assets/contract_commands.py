from __future__ import annotations

from .contract_base import *
from .contract_data import *
from .contract_views import *
from .evaluation_quality.models import (
    EvaluationCase as QualityEvaluationCase,
    EvaluationRun as QualityEvaluationRun,
    EvaluationSuite as QualityEvaluationSuite,
    FixPlan as QualityFixPlan,
    PolicyCheck as QualityPolicyCheck,
    PolicyGateResult as QualityPolicyGateResult,
    RunProvenance as QualityRunProvenance,
    TypedPatch as QualityTypedPatch,
)
from frontend.server.skill_authoring.models import (
    AuthoringEvent,
    AuthoringOperation,
    DraftRevision,
    ResourceRef as AuthoringResourceRef,
)
from .sources_golden.models import (
    ConnectorOperation,
    ConnectionInstance,
    GoldenAssetRevisionRecord,
    ProfileRunRecord,
    CleaningRecipeRecord,
    CleanRunRecord,
    SourceRevisionRecord,
)


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
    reason: str = Field(default="revoked", max_length=256)


class ConnectorPayload(ContractModel):
    connector_key: str = Field(min_length=1, max_length=128)


class SourceGoldenConnectionCreatePayload(ContractModel):
    connector_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    scope: Literal["personal", "team"] = "personal"
    configuration: dict[str, object] = Field(default_factory=dict)
    secret_ref: str | None = None


class SourceGoldenIngestPayload(ContractModel):
    connection_id: str = Field(min_length=1, max_length=256)
    resource_id: str | None = None
    recipe_operations: list[
        Literal["trim", "deduplicate", "normalize", "redact"]
    ] = Field(default_factory=lambda: ["trim"])
    tool_arguments: dict[str, object] = Field(default_factory=dict)


class SourceGoldenConnectionResult(ContractModel):
    result_type: Literal["source_golden.connection"] = "source_golden.connection"
    connection: ConnectionInstance
    validation: ConnectorOperation
    discovery: ConnectorOperation
    replayed: bool = False


class SourceGoldenIngestResult(ContractModel):
    result_type: Literal["source_golden.ingest"] = "source_golden.ingest"
    source_revision: SourceRevisionRecord
    profile_run: ProfileRunRecord
    cleaning_recipe: CleaningRecipeRecord
    clean_run: CleanRunRecord
    golden_asset_revision: GoldenAssetRevisionRecord
    replayed: bool = False


class ImportPayload(ContractModel):
    source_id: str = Field(min_length=1, max_length=128)


class AssistantTurnPayload(ContractModel):
    text: str = Field(min_length=1, max_length=16_384)
    context_ids: list[str] = Field(default_factory=list, max_length=100)
    context: "AssistantContextEnvelope | None" = None
    patch: "SkillPatch | None" = None


class AssistantContextEnvelope(ContractModel):
    skill_id: str = Field(min_length=1, max_length=256)
    view_revision_id: str = Field(min_length=1, max_length=256)
    selected_ids: list[str] = Field(default_factory=list, max_length=100)
    schema_ref: str = Field(min_length=1, max_length=2048)
    permission_scope: str = Field(min_length=1, max_length=256)


class SkillPatch(ContractModel):
    patch_id: str = Field(min_length=1, max_length=256)
    skill_id: str = Field(min_length=1, max_length=256)
    base_revision: int = Field(ge=1)
    operation: Literal["set_description", "set_runtime_ref", "set_evaluation_suite_ref"]
    value: str = Field(max_length=2048)
    undo_token: str | None = Field(default=None, min_length=1, max_length=256)


class AssistantDiff(ContractModel):
    patch_id: str
    skill_id: str
    base_revision: int
    next_revision: int
    operation: SkillPatch
    before: str
    after: str
    undo_token: str


class EvaluationPayload(ContractModel):
    target_id: str = Field(min_length=1, max_length=128)
    suite_id: str = Field(default="default-step3", min_length=1, max_length=128)
    environment: RuntimeProfile = "test"
    case_ids: list[str] = Field(default_factory=list, max_length=1000)
    cases: list[EvaluationCase] = Field(default_factory=list, max_length=1000)


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
    max_steps: int = Field(default=10, ge=1, le=100)
    budget: int = Field(default=10_000, ge=1, le=10_000_000)


class SkillDraftRetryPayload(SkillDraftRunPayload):
    retry_of_operation_id: str = Field(min_length=1, max_length=256)


class PublicationPublishPayload(ContractModel):
    draft_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1)
    semver: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class RefreshRunPayload(ContractModel):
    skill_id: str = Field(min_length=1, max_length=256)
    trigger: Literal["manual", "schedule", "event", "freshness_on_read"]


class InvocationStartPayload(ContractModel):
    skill_version_id: str = Field(min_length=1, max_length=256)
    skill_view_revision_id: str = Field(default="unbound", min_length=1, max_length=256)
    input_ref: StorageRef
    caller_id: str = Field(min_length=1, max_length=256)


class SkillAuthoringStartPayload(ContractModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    resource_refs: list[AuthoringResourceRef] = Field(default_factory=list, max_length=32)
    permissions: list[str] = Field(default_factory=list, max_length=64)
    fixed_revisions: list[str] = Field(default_factory=list, max_length=64)
    requested_kind: Literal[
        "knowledge", "semantic", "analysis", "graph_ontology", "monitoring"
    ] | None = None
    scope: Literal["personal", "team"] = "personal"
    display_name: str | None = Field(default=None, max_length=160)
    current_skill_id: str | None = Field(default=None, max_length=160)
    current_view_id: str | None = Field(default=None, max_length=160)
    current_component_id: str | None = Field(default=None, max_length=160)
    comment_ids: list[str] = Field(default_factory=list, max_length=64)


class EvaluationSuiteCreatePayload(ContractModel):
    suite_id: str = Field(min_length=1, max_length=128)
    skill_id: str = Field(min_length=1, max_length=256)
    cases: list[QualityEvaluationCase] = Field(min_length=1, max_length=1000)
    pass_threshold: float = Field(default=1.0, ge=0, le=1)


class EvaluationSuiteRevisePayload(ContractModel):
    suite_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    additions: list[QualityEvaluationCase] = Field(min_length=1, max_length=1000)


class EvaluationCaseImportPayload(ContractModel):
    content: str = Field(min_length=1, max_length=10_000_000)
    media_type: Literal["application/json", "text/csv"]


class EvaluationCaseAdoptHistoryPayload(ContractModel):
    case_id: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    input: dict[str, object]
    expected: dict[str, object]
    provenance_ref: str = Field(min_length=1, max_length=2048)
    source: Literal["historical_conversation", "historical_run"]


class EvaluationCaseGenerateCandidatePayload(ContractModel):
    case_id: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    input: dict[str, object]
    expected: dict[str, object]
    provenance_ref: str = Field(min_length=1, max_length=2048)


class EvaluationCaseConfirmPayload(ContractModel):
    suite_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    case_ids: list[str] = Field(min_length=1, max_length=1000)


class EvaluationRunStartPayload(ContractModel):
    suite_id: str = Field(min_length=1, max_length=128)
    suite_version: int = Field(ge=1)
    provenance: QualityRunProvenance
    selected_case_ids: list[str] = Field(default_factory=list, max_length=1000)


class EvaluationRunActionPayload(ContractModel):
    run_id: str = Field(min_length=1, max_length=256)


class EvaluationRunRetryPayload(ContractModel):
    run_id: str = Field(min_length=1, max_length=256)


class EvaluationFixProposePayload(ContractModel):
    run_id: str = Field(min_length=1, max_length=256)
    issue_case_ids: list[str] = Field(min_length=1, max_length=1000)
    affected_case_ids: list[str] = Field(min_length=1, max_length=1000)
    conflicts: list[str] = Field(default_factory=list, max_length=1000)
    patch: QualityTypedPatch


class EvaluationFixProposeAllPayload(ContractModel):
    run_id: str = Field(min_length=1, max_length=256)
    affected_case_ids: list[str] = Field(min_length=1, max_length=1000)
    conflicts: list[str] = Field(default_factory=list, max_length=1000)
    patch: QualityTypedPatch


class EvaluationFixActionPayload(ContractModel):
    plan_id: str = Field(min_length=1, max_length=256)


class PolicyGateEvaluatePayload(ContractModel):
    run_id: str = Field(min_length=1, max_length=256)
    checks: list[QualityPolicyCheck] = Field(default_factory=list, max_length=32)


class CommandResultBase(ContractModel):
    result_type: str
    error: ErrorEnvelope | None = None


class SkillAuthoringStartResult(CommandResultBase):
    result_type: Literal["skill-authoring.start"] = "skill-authoring.start"
    status: Literal[
        "queued", "planning", "awaiting_input", "ready_for_execution",
        "credential_blocked", "failed", "cancelled"
    ] = "failed"
    operation: AuthoringOperation | None = None
    draft: DraftRevision | None = None
    events: list[AuthoringEvent] = Field(default_factory=list, max_length=128)


class DraftCommandResult(CommandResultBase):
    result_type: Literal["skill-draft.create", "skill-draft.save-manifest"]
    draft: SkillDraft
    replayed: bool = False


class NotReadyCommandResult(CommandResultBase):
    result_type: Literal["command.not-ready"] = "command.not-ready"
    command: str
    error: ErrorEnvelope


class ArtifactExportResult(CommandResultBase):
    result_type: Literal["artifact.export"] = "artifact.export"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    resource_id: str
    artifact_ref: StorageRef | None = None


class ResourceShareResult(CommandResultBase):
    result_type: Literal["resource.share"] = "resource.share"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    resource_id: str
    share_grant: SkillViewShareGrant | None = None


class SourceProfileResult(CommandResultBase):
    result_type: Literal["source.profile"] = "source.profile"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    source_revision_id: str
    profile_run: ProfileRun | None = None


class SourceCleanResult(CommandResultBase):
    result_type: Literal["source.clean"] = "source.clean"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    source_revision_id: str
    recipe_id: str
    clean_run: CleanRun | None = None
    golden_asset_revision: GoldenAssetRevision | None = None


class SkillDraftRunResult(CommandResultBase):
    result_type: Literal["skill-draft.run"] = "skill-draft.run"
    status: Literal[
        "not_ready",
        "planning",
        "awaiting_input",
        "running",
        "partially_succeeded",
        "failed",
        "cancelled",
        "ready_for_evaluation",
    ] = "not_ready"
    draft_id: str
    golden_asset_revision: GoldenAssetRevision | None = None
    skill_result: SkillResult | None = None
    view_intent: ViewIntent | None = None
    skill_view_revision: SkillViewRevision | None = None
    execution_state: (
        Literal[
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
            "awaiting_input",
        ]
        | None
    ) = None
    trace_ref: StorageRef | None = None
    evidence_ref: StorageRef | None = None


class AssistantTurnResult(CommandResultBase):
    result_type: Literal["assistant.turn"] = "assistant.turn"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    skill_id: str
    diff: AssistantDiff | None = None
    rerun: SkillDraftRunResult | None = None


class PublicationPublishResult(CommandResultBase):
    result_type: Literal["publication.publish"] = "publication.publish"
    status: Literal["not_ready"] = "not_ready"
    draft_id: str


class RefreshRunResult(CommandResultBase):
    result_type: Literal["refresh.run"] = "refresh.run"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    skill_id: str
    refresh_run: RefreshRun | None = None


class InvocationStartResult(CommandResultBase):
    result_type: Literal["invocation.start"] = "invocation.start"
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    skill_version_id: str
    invocation: Invocation | None = None
    skill_result: SkillResult | None = None
    data_revision_refs: list[str] = Field(default_factory=list, max_length=100)


class EvaluationRunResult(CommandResultBase):
    result_type: Literal["evaluation.run", "evaluation.apply"]
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    target_id: str
    evaluation_suite: EvaluationSuite | None = None
    evaluation_run: EvaluationRun | None = None
    policy_gate_result: PolicyGateResult | None = None


class EvaluationQualityCommandResult(CommandResultBase):
    result_type: Literal[
        "evaluation-suite.create",
        "evaluation-suite.revise",
        "evaluation-case.import",
        "evaluation-case.adopt-history",
        "evaluation-case.generate-candidates",
        "evaluation-case.confirm-candidates",
        "evaluation-run.start",
        "evaluation-run.cancel",
        "evaluation-run.resume",
        "evaluation-run.retry",
        "evaluation-fix.propose",
        "evaluation-fix.propose-all-unresolved",
        "evaluation-fix.apply",
        "evaluation-fix.undo",
        "policy-gate.evaluate",
    ]
    status: Literal["not_ready", "succeeded", "failed", "blocked"] = "not_ready"
    suite: QualityEvaluationSuite | None = None
    run: QualityEvaluationRun | None = None
    fix_plan: QualityFixPlan | None = None
    gate: QualityPolicyGateResult | None = None
    cases: list[QualityEvaluationCase] = Field(default_factory=list, max_length=1000)
    message: str | None = None


CommandResult = Annotated[
    DraftCommandResult
    | NotReadyCommandResult
    | SourceProfileResult
    | SourceCleanResult
    | SkillDraftRunResult
    | AssistantTurnResult
    | ArtifactExportResult
    | ResourceShareResult
    | PublicationPublishResult
    | RefreshRunResult
    | InvocationStartResult
    | EvaluationRunResult
    | EvaluationQualityCommandResult
    | SkillAuthoringStartResult
    | SourceGoldenConnectionResult
    | SourceGoldenIngestResult,
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


class EvaluationSuiteCreateCommand(ContractModel):
    command: Literal["evaluation-suite.create"]
    payload: EvaluationSuiteCreatePayload


class EvaluationSuiteReviseCommand(ContractModel):
    command: Literal["evaluation-suite.revise"]
    payload: EvaluationSuiteRevisePayload


class EvaluationCaseImportCommand(ContractModel):
    command: Literal["evaluation-case.import"]
    payload: EvaluationCaseImportPayload


class EvaluationCaseAdoptHistoryCommand(ContractModel):
    command: Literal["evaluation-case.adopt-history"]
    payload: EvaluationCaseAdoptHistoryPayload


class EvaluationCaseGenerateCandidateCommand(ContractModel):
    command: Literal["evaluation-case.generate-candidates"]
    payload: EvaluationCaseGenerateCandidatePayload


class EvaluationCaseConfirmCommand(ContractModel):
    command: Literal["evaluation-case.confirm-candidates"]
    payload: EvaluationCaseConfirmPayload


class EvaluationRunStartCommand(ContractModel):
    command: Literal["evaluation-run.start"]
    payload: EvaluationRunStartPayload


class EvaluationRunCancelCommand(ContractModel):
    command: Literal["evaluation-run.cancel"]
    payload: EvaluationRunActionPayload


class EvaluationRunResumeCommand(ContractModel):
    command: Literal["evaluation-run.resume"]
    payload: EvaluationRunActionPayload


class EvaluationRunRetryCommand(ContractModel):
    command: Literal["evaluation-run.retry"]
    payload: EvaluationRunRetryPayload


class EvaluationFixProposeCommand(ContractModel):
    command: Literal["evaluation-fix.propose"]
    payload: EvaluationFixProposePayload


class EvaluationFixProposeAllCommand(ContractModel):
    command: Literal["evaluation-fix.propose-all-unresolved"]
    payload: EvaluationFixProposeAllPayload


class EvaluationFixApplyCommand(ContractModel):
    command: Literal["evaluation-fix.apply"]
    payload: EvaluationFixActionPayload


class EvaluationFixUndoCommand(ContractModel):
    command: Literal["evaluation-fix.undo"]
    payload: EvaluationFixActionPayload


class PolicyGateEvaluateCommand(ContractModel):
    command: Literal["policy-gate.evaluate"]
    payload: PolicyGateEvaluatePayload


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


class SkillDraftRetryCommand(ContractModel):
    command: Literal["skill-draft.retry"]
    payload: SkillDraftRetryPayload


class PublicationPublishCommand(ContractModel):
    command: Literal["publication.publish"]
    payload: PublicationPublishPayload


class RefreshRunCommand(ContractModel):
    command: Literal["refresh.run"]
    payload: RefreshRunPayload


class InvocationStartCommand(ContractModel):
    command: Literal["invocation.start"]
    payload: InvocationStartPayload


class SkillAuthoringStartCommand(ContractModel):
    command: Literal["skill-authoring.start"]
    payload: SkillAuthoringStartPayload


class SourceGoldenConnectionCreateCommand(ContractModel):
    command: Literal["source-golden.connection.create"]
    payload: SourceGoldenConnectionCreatePayload


class SourceGoldenIngestCommand(ContractModel):
    command: Literal["source-golden.ingest"]
    payload: SourceGoldenIngestPayload


CommandRequest = Annotated[
    CreateSkillDraftCommand
    | SaveManifestCommand
    | ResourceCommand
    | ConnectorCommand
    | ImportCommand
    | StreamCancelCommand
    | AssistantCommand
    | EvaluationCommand
    | EvaluationSuiteCreateCommand
    | EvaluationSuiteReviseCommand
    | EvaluationCaseImportCommand
    | EvaluationCaseAdoptHistoryCommand
    | EvaluationCaseGenerateCandidateCommand
    | EvaluationCaseConfirmCommand
    | EvaluationRunStartCommand
    | EvaluationRunCancelCommand
    | EvaluationRunResumeCommand
    | EvaluationRunRetryCommand
    | EvaluationFixProposeCommand
    | EvaluationFixProposeAllCommand
    | EvaluationFixApplyCommand
    | EvaluationFixUndoCommand
    | PolicyGateEvaluateCommand
    | ActionCommand
    | ArtifactExportCommand
    | SourceProfileCommand
    | SourceCleanCommand
    | SkillDraftRunCommand
    | SkillDraftRetryCommand
    | PublicationPublishCommand
    | RefreshRunCommand
    | InvocationStartCommand
    | SkillAuthoringStartCommand
    | SourceGoldenConnectionCreateCommand
    | SourceGoldenIngestCommand,
    Field(discriminator="command"),
]


class CommandResponse(ContractModel):
    accepted: bool
    request_id: str
    operation_id: str | None = None
    result: CommandResult | None = None


class Event(ContractModel):
    schema_version: Literal["knowledge-assets.event.v1"] = "knowledge-assets.event.v1"
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
