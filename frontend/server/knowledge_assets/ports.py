"""Application ports for external Knowledge Asset capabilities."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class ArtifactStorePort(Protocol):
    def put(self, *, key: str, content: bytes, content_type: str) -> str: ...
    def signed_read_url(self, *, key: str) -> str: ...


class SecretStorePort(Protocol):
    def get(self, *, key: str) -> str | None: ...


class QueuePort(Protocol):
    def enqueue(
        self, *, job_type: str, idempotency_key: str, payload: dict[str, object]
    ) -> str: ...


class RuntimePort(Protocol):
    def invoke(
        self, *, skill_id: str, version: str, input_payload: dict[str, object]
    ) -> Iterable[dict[str, object]]: ...


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
