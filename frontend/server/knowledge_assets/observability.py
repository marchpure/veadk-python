"""Typed observability contracts used by application write paths."""

from __future__ import annotations

from dataclasses import dataclass

from .ports import AuditRecorderPort


@dataclass(frozen=True)
class AuditEvent:
    request_id: str
    operation_id: str
    workspace_id: str
    action: str
    resource_id: str
    outcome: str
    details: dict[str, str]


class RepositoryAuditRecorder:
    def __init__(self, repository: AuditRecorderPort) -> None:
        self._repository = repository

    def record_audit(self, event: AuditEvent) -> None:
        self._repository.record_audit(
            request_id=event.request_id,
            operation_id=event.operation_id,
            workspace_id=event.workspace_id,
            action=event.action,
            resource_id=event.resource_id,
            outcome=event.outcome,
            details=event.details,
        )
