"""Server-owned, immutable domain models for the Knowledge Workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class InvocationKind(StrEnum):
    GENERATE = "generate"
    UPDATE = "update"
    RUN = "run"


class InvocationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DraftStatus(StrEnum):
    EDITING = "editing"
    GENERATING = "generating"
    GENERATED = "generated"
    VALIDATING = "validating"
    READY_TO_PUBLISH = "ready_to_publish"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImmutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillDraft(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    draft_id: str = Field(min_length=1, max_length=160)
    created_by: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=8_000)
    trial_task: str | None = Field(default=None, max_length=20_000)
    connection_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    upload_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    status: DraftStatus = DraftStatus.EDITING
    current_revision_id: str | None = None
    etag: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuthoringSession(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    draft_id: str = Field(min_length=1, max_length=160)
    authoring_session_id: str = Field(min_length=1, max_length=160)
    autoskill_agent_id: str = Field(min_length=1, max_length=160)
    autoskill_session_id: str = Field(min_length=1, max_length=160)
    state_uri: str | None = Field(default=None, max_length=2_048)
    created_at: datetime = Field(default_factory=utc_now)


class Invocation(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    invocation_id: str = Field(min_length=1, max_length=160)
    draft_id: str = Field(min_length=1, max_length=160)
    revision_id: str | None = Field(default=None, max_length=160)
    connection_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    upload_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    lease_id: str | None = Field(default=None, max_length=256)
    authoring_session_id: str = Field(min_length=1, max_length=160)
    kind: InvocationKind
    status: InvocationStatus = InvocationStatus.QUEUED
    autoskill_agent_id: str = Field(min_length=1, max_length=160)
    autoskill_session_id: str = Field(min_length=1, max_length=160)
    autoskill_request_id: str = Field(min_length=1, max_length=160)
    autoskill_request_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    principal_id: str = Field(default="legacy", min_length=1, max_length=160)
    message: str = Field(default="", max_length=20_000)
    model: str | None = Field(default=None, max_length=256)
    request_summary: Mapping[str, Any] | None = None
    final_answer_observed: bool = False
    request_summary_observed: bool = False
    done_observed: bool = False
    error_observed: bool = False
    state_update_observed: bool = False
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class SkillRevision(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    revision_id: str = Field(min_length=1, max_length=160)
    draft_id: str = Field(min_length=1, max_length=160)
    number: int = Field(ge=1)
    skill_name: str = Field(min_length=1, max_length=256)
    zip_uri: str = Field(min_length=1, max_length=2_048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: Mapping[str, Any]
    created_from_invocation: str = Field(min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=utc_now)


class Artifact(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    artifact_id: str = Field(min_length=1, max_length=160)
    revision_id: str = Field(min_length=1, max_length=160)
    invocation_id: str = Field(min_length=1, max_length=160)
    uri: str = Field(min_length=1, max_length=2_048)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=256)
    encoding: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(ge=1)
    lineage: Mapping[str, Any]
    csp: str = Field(min_length=1, max_length=2_048)
    sandbox: str = Field(max_length=256)
    created_at: datetime = Field(default_factory=utc_now)


class Publication(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    publication_id: str = Field(min_length=1, max_length=160)
    revision_id: str = Field(min_length=1, max_length=160)
    target_space: str = Field(min_length=1, max_length=64)
    published_by: str = Field(min_length=1, max_length=160)
    policy_snapshot: Mapping[str, Any] = Field(default_factory=dict)
    status: str = Field(default="published", min_length=1, max_length=32)
    created_at: datetime = Field(default_factory=utc_now)


class WorkspaceUpload(ImmutableModel):
    tenant_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)
    upload_id: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1)
    media_type: str = Field(min_length=1, max_length=256)
    purpose: str = Field(pattern=r"^(context|skill_input)$")
    uri: str = Field(min_length=1, max_length=2_048)
    created_at: datetime = Field(default_factory=utc_now)
