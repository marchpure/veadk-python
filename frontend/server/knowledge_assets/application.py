"""Application use cases behind the Studio BFF."""

from __future__ import annotations

import hashlib

from .contracts import (
    CommandResponse,
    CommandResult,
    DraftCommandResult,
    ErrorEnvelope,
    LegacySkillManifestInput,
    InvocationStartPayload,
    InvocationStartResult,
    OperationEvent,
    OperationResponse,
    PublicationPublishPayload,
    PublicationPublishResult,
    RefreshRunPayload,
    RefreshRunResult,
    SkillDraft,
    SkillDraftRunPayload,
    SkillDraftRunResult,
    SkillManifest,
    SourceCleanPayload,
    SourceCleanResult,
    SourceProfilePayload,
    SourceProfileResult,
    adapt_legacy_manifest,
    now_iso,
)
from .policies import validate_manifest_policy
from .ports import AuditRecorderPort
from .repository import (
    KnowledgeAssetRepositoryError,
    KnowledgeAssetRepository,
)


class KnowledgeAssetApplication:
    def __init__(
        self,
        repository: KnowledgeAssetRepository,
        *,
        audit_recorder: AuditRecorderPort | None = None,
    ) -> None:
        self.repository = repository
        self.audit_recorder = audit_recorder or repository

    def bootstrap(self, workspace_id: str, role: str):
        return self.repository.bootstrap(workspace_id, role)

    def create_skill_draft(
        self,
        payload: dict[str, object],
        *,
        request_id: str,
        idempotency_key: str,
    ) -> CommandResponse:
        workspace_id = str(payload["workspace_id"])
        name = str(payload["name"])
        description = str(payload.get("description", ""))
        source_refs = [str(item) for item in payload.get("source_refs", [])]
        try:
            draft, replayed = self.repository.create_skill_draft(
                workspace_id=workspace_id,
                name=name,
                description=description,
                source_refs=source_refs,
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
        except KnowledgeAssetRepositoryError:
            raise
        operation_id = self._operation_id(idempotency_key)
        self.repository.create_operation(operation_id, request_id)
        if replayed:
            existing_operation = self.repository.operation(operation_id)
            if existing_operation is not None:
                return CommandResponse(
                    accepted=True,
                    request_id=request_id,
                    operation_id=operation_id,
                    result=existing_operation.result,
                )
        return self._complete_operation(
            operation_id=operation_id,
            request_id=request_id,
            workspace_id=workspace_id,
            action="skill-draft.create",
            resource_id=draft.id,
            draft=draft,
            replayed=replayed,
        )

    def save_manifest(
        self,
        payload: dict[str, object],
        *,
        request_id: str,
        idempotency_key: str,
    ) -> CommandResponse:
        draft_id = str(payload["draft_id"])
        base_revision = int(payload["base_revision"])
        raw_manifest = payload["manifest"]
        if isinstance(raw_manifest, SkillManifest):
            manifest = raw_manifest
        else:
            legacy = LegacySkillManifestInput.model_validate(raw_manifest)
            draft = self.repository.draft(draft_id)
            if draft is None:
                raise KnowledgeAssetRepositoryError(
                    "DRAFT_NOT_FOUND",
                    "Skill 草稿不存在。",
                    details={"draftId": draft_id},
                )
            manifest = adapt_legacy_manifest(
                legacy,
                draft_id=draft.id,
                workspace_id=draft.workspace_id,
            )
        validate_manifest_policy(manifest)
        draft, replayed = self.repository.save_manifest(
            draft_id=draft_id,
            base_revision=base_revision,
            manifest=manifest,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        operation_id = self._operation_id(idempotency_key)
        self.repository.create_operation(operation_id, request_id)
        if replayed:
            existing_operation = self.repository.operation(operation_id)
            if existing_operation is not None:
                return CommandResponse(
                    accepted=True,
                    request_id=request_id,
                    operation_id=operation_id,
                    result=existing_operation.result,
                )
        return self._complete_operation(
            operation_id=operation_id,
            request_id=request_id,
            workspace_id=draft.workspace_id,
            action="skill-draft.save-manifest",
            resource_id=draft.id,
            draft=draft,
            replayed=replayed,
        )

    @staticmethod
    def _operation_id(idempotency_key: str) -> str:
        return "op-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]

    def _complete_operation(
        self,
        *,
        operation_id: str,
        request_id: str,
        workspace_id: str,
        action: str,
        resource_id: str,
        draft: SkillDraft,
        replayed: bool,
    ) -> CommandResponse:
        typed_result = DraftCommandResult(
            result_type=action,
            draft=draft,
            replayed=replayed,
        )
        accepted = OperationEvent(
            operation_id=operation_id,
            event_id=f"{operation_id}:accepted",
            sequence=1,
            occurred_at=now_iso(),
            type="accepted",
            terminal=False,
        )
        succeeded = OperationEvent(
            operation_id=operation_id,
            event_id=f"{operation_id}:succeeded",
            sequence=2,
            occurred_at=now_iso(),
            type="succeeded",
            terminal=True,
            result=typed_result,
        )
        self.repository.append_operation_event(operation_id, accepted, status="running")
        self.repository.append_operation_event(
            operation_id,
            succeeded,
            status="succeeded",
            result=typed_result.model_dump(mode="json", by_alias=True),
        )
        self.audit_recorder.record_audit(
            request_id=request_id,
            operation_id=operation_id,
            workspace_id=workspace_id,
            action=action,
            resource_id=resource_id,
            outcome="succeeded",
            details={"revision": str(draft.revision)},
        )
        return CommandResponse(
            accepted=True,
            request_id=request_id,
            operation_id=operation_id,
            result=typed_result,
        )

    def stream_events(self, operation_id: str, after: int = 0) -> list[OperationEvent]:
        operation = self.repository.operation(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        return [event for event in operation.events if event.sequence > after]

    def unsupported(
        self,
        command: str,
        request_id: str,
        payload: dict[str, object],
    ) -> CommandResponse:
        result: CommandResult
        if command == "source.profile":
            typed = SourceProfilePayload.model_validate(payload)
            result = SourceProfileResult(
                source_revision_id=typed.source_revision_id,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "source.clean":
            typed = SourceCleanPayload.model_validate(payload)
            result = SourceCleanResult(
                source_revision_id=typed.source_revision_id,
                recipe_id=typed.recipe_id,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "skill-draft.run":
            typed = SkillDraftRunPayload.model_validate(payload)
            result = SkillDraftRunResult(
                draft_id=typed.draft_id,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "publication.publish":
            typed = PublicationPublishPayload.model_validate(payload)
            result = PublicationPublishResult(
                draft_id=typed.draft_id,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "refresh.run":
            typed = RefreshRunPayload.model_validate(payload)
            result = RefreshRunResult(
                skill_id=typed.skill_id,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "invocation.start":
            typed = InvocationStartPayload.model_validate(payload)
            result = InvocationStartResult(
                skill_version_id=typed.skill_version_id,
                error=self._not_ready_error(command, request_id),
            )
        else:
            result = InvocationStartResult(
                skill_version_id="unsupported",
                error=self._not_ready_error(command, request_id),
            )
        return CommandResponse(
            accepted=False,
            request_id=request_id,
            result=result,
        )

    @staticmethod
    def _not_ready_error(command: str, request_id: str) -> ErrorEnvelope:
        return ErrorEnvelope(
            code="COMMAND_NOT_READY",
            message=f"命令 {command} 尚未在当前 STEP 1 应用波次开放。",
            retryable=False,
            request_id=request_id,
        )

    def operation(self, operation_id: str) -> OperationResponse | None:
        return self.repository.operation(operation_id)

    def cancel(self, operation_id: str, request_id: str) -> OperationResponse:
        return self.repository.cancel_operation(operation_id, request_id)
