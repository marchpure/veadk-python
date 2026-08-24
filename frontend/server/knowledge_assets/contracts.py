"""Typed application contracts for the Knowledge Asset Studio BFF."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ErrorEnvelope(ContractModel):
    code: str
    message: str
    retryable: bool
    request_id: str
    details: dict[str, str] | None = None


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


class SkillManifest(ContractModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$", max_length=32)
    description: str = Field(default="", max_length=1024)
    actions: list[SkillManifestAction] = Field(default_factory=list, max_length=64)
    schema: ManifestInputSchema = Field(default_factory=ManifestInputSchema)


class SkillDraft(ContractModel):
    id: str
    workspace_id: str
    name: str
    description: str
    revision: int
    lifecycle: Literal["draft"] = "draft"
    view_state: Literal["debug"] = "debug"
    created_at: str
    updated_at: str
    manifest: SkillManifest


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
    manifest: SkillManifest


class EmptyPayload(ContractModel):
    pass


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


class EmptyCommand(ContractModel):
    command: Literal[
        "source.profile",
        "source.clean",
        "skill-draft.run",
        "publication.publish",
        "refresh.run",
        "invocation.start",
    ]
    payload: EmptyPayload


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
    | EmptyCommand,
    Field(discriminator="command"),
]


class CommandResponse(ContractModel):
    accepted: bool
    request_id: str
    operation_id: str | None = None
    result: dict[str, object] | None = None


class OperationEvent(ContractModel):
    schema_version: Literal["knowledge-assets.event.v1"] = (
        "knowledge-assets.event.v1"
    )
    operation_id: str
    event_id: str
    sequence: int
    occurred_at: str
    type: Literal["accepted", "progress", "succeeded", "failed", "cancelled"]
    terminal: bool
    result: dict[str, object] | None = None
    error: ErrorEnvelope | None = None


class OperationResponse(ContractModel):
    operation_id: str
    status: Literal["accepted", "running", "succeeded", "failed", "cancelled"]
    version: int
    events: list[OperationEvent]
    result: dict[str, object] | None = None
    error: ErrorEnvelope | None = None
    next_actions: list[str] = Field(default_factory=list)
    audit: list["AuditItem"] = Field(default_factory=list)


class AuditItem(ContractModel):
    request_id: str
    operation_id: str
    workspace_id: str
    action: str
    resource_id: str
    outcome: str
    details: dict[str, object] = Field(default_factory=dict)
    occurred_at: str


class OperationAuditResponse(ContractModel):
    operation_id: str
    items: list[AuditItem] = Field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
