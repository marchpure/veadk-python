"""Business domain for managed Data Workshop MCP publications."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ManagedPublicationStatus(StrEnum):
    DRAFT = "draft"
    PROVISIONING = "provisioning"
    VERIFYING = "verifying"
    ACTIVE = "active"
    FAILED = "failed"
    RETRYING = "retrying"
    UPDATING = "updating"
    DISABLING = "disabling"
    DISABLED = "disabled"
    EXTERNAL_MANAGED = "external-managed"


class RevisionState(StrEnum):
    DRAFT = "draft"
    PROVISIONING = "provisioning"
    VERIFYING = "verifying"
    ACTIVE = "active"
    FAILED = "failed"
    RETIRED = "retired"
    DISABLED = "disabled"


class OperationStage(StrEnum):
    DRAFT_SAVED = "draft_saved"
    VALIDATED = "validated"
    RUNTIME_TOKEN_CREATED = "runtime_token_created"
    CREDENTIAL_MANAGED = "credential_managed"
    GATEWAY_CREATED = "gateway_created"
    AUDIENCE_BOUND = "audience_bound"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    FAILED = "failed"
    DISABLING = "disabling"
    DISABLED = "disabled"


class ActionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    preset: Literal["read_only", "read_write", "custom"]
    action_ids: tuple[str, ...] = Field(
        default_factory=tuple, alias="actionIds", max_length=256
    )

    @field_validator("action_ids")
    @classmethod
    def normalize_actions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def custom_must_be_explicit(self) -> "ActionPolicy":
        if self.preset == "custom" and not self.action_ids:
            raise ValueError("custom action policy requires actionIds")
        return self


class PublicationAudience(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["applications", "users_and_groups"]
    client_ids: tuple[str, ...] = Field(
        default_factory=tuple, alias="clientIds", max_length=64
    )
    user_ids: tuple[str, ...] = Field(
        default_factory=tuple, alias="userIds", max_length=256
    )
    group_ids: tuple[str, ...] = Field(
        default_factory=tuple, alias="groupIds", max_length=256
    )

    @field_validator("client_ids", "user_ids", "group_ids")
    @classmethod
    def normalize_subjects(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def require_matching_subjects(self) -> "PublicationAudience":
        if self.type == "applications":
            if not self.client_ids or self.user_ids or self.group_ids:
                raise ValueError("applications audience requires only clientIds")
        elif not (self.user_ids or self.group_ids) or self.client_ids:
            raise ValueError(
                "users_and_groups audience requires userIds or groupIds only"
            )
        return self


class ManagedPublicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=128)
    connection_ids: tuple[str, ...] = Field(
        alias="connectionIds", min_length=1, max_length=32
    )
    action_policy: ActionPolicy = Field(alias="actionPolicy")
    audience: PublicationAudience
    idempotency_key: str = Field(alias="idempotencyKey", min_length=16, max_length=256)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("connection_ids")
    @classmethod
    def normalize_connections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            dict.fromkeys(value.strip() for value in values if value.strip())
        )
        if not normalized:
            raise ValueError("connectionIds must not be empty")
        return normalized


class ManagedRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    connection_ids: tuple[str, ...] = Field(
        alias="connectionIds", min_length=1, max_length=32
    )
    action_policy: ActionPolicy = Field(alias="actionPolicy")
    audience: PublicationAudience
    idempotency_key: str = Field(alias="idempotencyKey", min_length=16, max_length=256)


class ManagedPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    workspace_id: str
    name: str
    status: ManagedPublicationStatus
    active_revision_id: str | None = None
    created_by: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ManagedRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    publication_id: str
    version: int = Field(ge=1)
    endpoint_ref: str | None = None
    connection_scope: tuple[str, ...]
    resolved_action_scope: tuple[str, ...] = ()
    action_policy_source: ActionPolicy
    audience_type: Literal["applications", "users_and_groups"]
    runtime_token_record_id: str | None = None
    credential_provider_ref: str | None = None
    mcp_service_id: str | None = None
    toolset_id: str | None = None
    identity_binding_ref: str | None = None
    gateway_endpoint: str | None = None
    state: RevisionState = RevisionState.DRAFT
    verification_summary: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class PublicationSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_id: str
    revision_id: str
    subject_type: Literal["user", "group", "application"]
    subject_ref: str


class PublicationOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    publication_id: str
    revision_id: str
    idempotency_key: str
    request_digest: str
    stage: OperationStage
    attempt: int = Field(default=1, ge=1)
    last_error: dict[str, object] | None = None
    external_request_ids: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class PublicationAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    publication_id: str
    revision_id: str | None = None
    actor: str
    event_type: str
    before_digest: str | None = None
    after_digest: str | None = None
    request_id: str
    created_at: datetime = Field(default_factory=now_utc)


class ResolvedConnectionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_ref: str
    connection_ids: tuple[str, ...]
    available_action_ids: tuple[str, ...]


class RuntimeTokenMaterial(BaseModel):
    """Transient only. Callers must never persist or serialize this model."""

    model_config = ConfigDict(extra="forbid")

    record_id: str
    plaintext: str = Field(repr=False)


class ManagedPublicationView(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    publication: ManagedPublication
    active_revision: ManagedRevision | None = Field(alias="activeRevision")
    revisions: tuple[ManagedRevision, ...]
    subjects: tuple[PublicationSubject, ...]
    operations: tuple[PublicationOperation, ...]
    audit_events: tuple[PublicationAuditEvent, ...] = Field(alias="auditEvents")
    capabilities: dict[str, object]

    def public_dump(self) -> dict[str, object]:
        def revision(value: ManagedRevision) -> dict[str, object]:
            return {
                "id": value.id,
                "publication_id": value.publication_id,
                "version": value.version,
                "connection_scope": list(value.connection_scope),
                "resolved_action_scope": list(value.resolved_action_scope),
                "action_policy_source": value.action_policy_source.model_dump(
                    mode="json", by_alias=True
                ),
                "audience_type": value.audience_type,
                "gateway_endpoint": value.gateway_endpoint,
                "state": value.state,
                "verification_summary": value.verification_summary,
                "created_at": value.created_at.isoformat(),
            }

        return {
            "publication": {
                "id": self.publication.id,
                "name": self.publication.name,
                "status": self.publication.status,
                "active_revision_id": self.publication.active_revision_id,
                "created_at": self.publication.created_at.isoformat(),
                "updated_at": self.publication.updated_at.isoformat(),
            },
            "activeRevision": (
                revision(self.active_revision) if self.active_revision else None
            ),
            "revisions": [revision(item) for item in self.revisions],
            "subjects": [item.model_dump(mode="json") for item in self.subjects],
            "operations": [
                item.model_dump(
                    mode="json",
                    exclude={"request_digest", "external_request_ids"},
                )
                for item in self.operations
            ],
            "auditEvents": [
                item.model_dump(mode="json", exclude={"before_digest", "after_digest"})
                for item in self.audit_events
            ],
            "capabilities": self.capabilities,
        }


_PUBLICATION_TRANSITIONS: dict[
    ManagedPublicationStatus, frozenset[ManagedPublicationStatus]
] = {
    ManagedPublicationStatus.DRAFT: frozenset({ManagedPublicationStatus.PROVISIONING}),
    ManagedPublicationStatus.PROVISIONING: frozenset(
        {ManagedPublicationStatus.VERIFYING, ManagedPublicationStatus.FAILED}
    ),
    ManagedPublicationStatus.VERIFYING: frozenset(
        {ManagedPublicationStatus.ACTIVE, ManagedPublicationStatus.FAILED}
    ),
    ManagedPublicationStatus.ACTIVE: frozenset(
        {ManagedPublicationStatus.UPDATING, ManagedPublicationStatus.DISABLING}
    ),
    ManagedPublicationStatus.FAILED: frozenset(
        {ManagedPublicationStatus.RETRYING, ManagedPublicationStatus.DISABLING}
    ),
    ManagedPublicationStatus.RETRYING: frozenset(
        {
            ManagedPublicationStatus.PROVISIONING,
            ManagedPublicationStatus.VERIFYING,
            ManagedPublicationStatus.ACTIVE,
            ManagedPublicationStatus.FAILED,
        }
    ),
    ManagedPublicationStatus.UPDATING: frozenset(
        {
            ManagedPublicationStatus.VERIFYING,
            ManagedPublicationStatus.ACTIVE,
            ManagedPublicationStatus.FAILED,
        }
    ),
    ManagedPublicationStatus.DISABLING: frozenset(
        {ManagedPublicationStatus.DISABLED, ManagedPublicationStatus.FAILED}
    ),
    ManagedPublicationStatus.DISABLED: frozenset(),
    ManagedPublicationStatus.EXTERNAL_MANAGED: frozenset(),
}


def assert_publication_transition(
    current: ManagedPublicationStatus, target: ManagedPublicationStatus
) -> None:
    if current == target:
        return
    if target not in _PUBLICATION_TRANSITIONS[current]:
        raise ValueError(f"illegal publication transition: {current} -> {target}")
