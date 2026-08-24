from __future__ import annotations

from .contract_base import *
from .contract_data import *
from .contract_views import *

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
    status: Literal["not_ready", "succeeded", "failed"] = "not_ready"
    draft_id: str
    golden_asset_revision: GoldenAssetRevision | None = None


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
