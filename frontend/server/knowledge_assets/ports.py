"""Typed application ports for external Knowledge Asset capabilities.

Production adapters are intentionally fail-closed until a real provider is
configured.  Demo and test implementations must be injected explicitly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    BootstrapResponse,
    ErrorEnvelope,
    JobState,
    OperationEvent,
    OperationResponse,
    RuntimeProfile,
    SkillDraft,
    SkillManifest,
    SkillResult,
    StorageRef,
)


class KnowledgeAssetAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotConfiguredAdapterError(KnowledgeAssetAdapterError):
    def __init__(self, adapter: str) -> None:
        super().__init__(
            "NOT_CONFIGURED",
            f"生产适配器 {adapter} 尚未配置，拒绝回退到 mock。",
        )


@dataclass(frozen=True)
class ArtifactPutRequest:
    key: str
    content: bytes
    content_type: str
    profile: RuntimeProfile


@dataclass(frozen=True)
class SecretLeaseRequest:
    secret_ref: str
    profile: RuntimeProfile
    ttl_seconds: int


@dataclass(frozen=True)
class QueueEnqueueRequest:
    job_type: str
    idempotency_key: str
    payload_ref: StorageRef | None
    profile: RuntimeProfile


@dataclass(frozen=True)
class RuntimeInvocationRequest:
    skill_version_id: str
    input_ref: StorageRef
    caller_id: str
    workspace_id: str
    profile: RuntimeProfile


class ArtifactStorePort(Protocol):
    def put(self, request: ArtifactPutRequest) -> StorageRef: ...
    def signed_read_url(self, ref: StorageRef) -> str: ...


class SecretStorePort(Protocol):
    def lease(self, request: SecretLeaseRequest) -> str: ...


class QueuePort(Protocol):
    def enqueue(self, request: QueueEnqueueRequest) -> JobState: ...

class RuntimePort(Protocol):
    def invoke(self, request: RuntimeInvocationRequest) -> Iterable[SkillResult]: ...


class RepositoryPort(Protocol):
    def bootstrap(self, workspace_id: str, role: str) -> BootstrapResponse: ...
    def draft(self, draft_id: str) -> SkillDraft | None: ...

    def create_skill_draft(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str,
        source_refs: list[str],
        request_id: str,
        idempotency_key: str,
    ) -> tuple[SkillDraft, bool]: ...

    def save_manifest(
        self,
        *,
        draft_id: str,
        base_revision: int,
        manifest: SkillManifest,
        request_id: str,
        idempotency_key: str,
    ) -> tuple[SkillDraft, bool]: ...

    def current_pointer(self, *, object_type: str, object_id: str) -> int | None: ...
    def last_good_pointer(self, *, object_type: str, object_id: str) -> int | None: ...
    def operation(self, operation_id: str) -> OperationResponse | None: ...
    def append_operation_event(
        self,
        operation_id: str,
        event: OperationEvent,
        *,
        status: str,
        result: dict[str, object] | None = None,
        error: ErrorEnvelope | None = None,
    ) -> None: ...


class FailClosedArtifactStore:
    def put(self, request: ArtifactPutRequest) -> StorageRef:
        del request
        raise NotConfiguredAdapterError("ArtifactStore")

    def signed_read_url(self, ref: StorageRef) -> str:
        del ref
        raise NotConfiguredAdapterError("ArtifactStore")


class FailClosedSecretStore:
    def lease(self, request: SecretLeaseRequest) -> str:
        del request
        raise NotConfiguredAdapterError("SecretStore")


class FailClosedQueue:
    def enqueue(self, request: QueueEnqueueRequest) -> JobState:
        del request
        raise NotConfiguredAdapterError("Queue")


class FailClosedRuntime:
    def invoke(self, request: RuntimeInvocationRequest) -> Iterable[SkillResult]:
        del request
        raise NotConfiguredAdapterError("Runtime")


class AuditRecorderPort(Protocol):
    def record_audit(
        self,
        *,
        request_id: str,
        operation_id: str,
        workspace_id: str,
        action: str,
        resource_id: str,
        outcome: str,
        details: dict[str, str] | None = None,
    ) -> None: ...
