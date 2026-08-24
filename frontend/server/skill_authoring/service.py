"""Application service for safe SkillDraft orchestration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4

from .models import (
    AddCitationIntentPatch,
    AuthoringErrorCode,
    AuthoringEvent,
    AuthoringOperation,
    AuthoringReadModel,
    AuthoringStatus,
    BuildPlan,
    ContextEnvelope,
    DraftManifest,
    DraftRevision,
    PatchImpact,
    PatchProposal,
    QueryPlan,
    ResolvedContext,
    Scope,
    SetDescriptionPatch,
    SetPermissionScopePatch,
    SetQueryPlanPatch,
    SetRefreshPolicyPatch,
    SetSemanticMappingPatch,
    SetThresholdPolicyPatch,
    SetTitlePatch,
    SkillAuthoringError,
    SkillKind,
    TypedPatch,
    Worker3ExecutionRequest,
    ContextMutation,
    CommentRepairBatchRequest,
    CommentRepairBatchResult,
    CommentRepairRequest,
    CreateDraftRequest,
    TeamReuseRequest,
    TeamReviewRequest,
    digest,
    utc_now,
)
from .ports import (
    AuthoringRepository,
    ModelGateway,
    ResourceResolver,
    Worker3Executor,
)


class SkillAuthoringService:
    """Coordinates intent/context/plan/draft without persisting model output blindly."""

    def __init__(
        self,
        repository: AuthoringRepository,
        resolver: ResourceResolver,
        model_gateway: ModelGateway,
        worker3: Worker3Executor,
    ) -> None:
        self.repository = repository
        self.resolver = resolver
        self.model_gateway = model_gateway
        self.worker3 = worker3
        self._locks: dict[str, asyncio.Lock] = {}

    async def create_draft(
        self,
        envelope: ContextEnvelope,
        *,
        requested_kind: SkillKind | None = None,
        scope: Scope = Scope.PERSONAL,
        display_name: str | None = None,
    ) -> AuthoringReadModel:
        operation = AuthoringOperation(
            operation_id=f"op_{uuid4().hex}",
            operation_type="create_draft",
            status=AuthoringStatus.QUEUED,
            caller_id=envelope.caller_id,
            workspace_id=envelope.workspace_id,
            trace_id=f"trace_{uuid4().hex}",
        )
        await self.repository.save_operation(operation)
        await self.repository.save_create_request(
            operation.operation_id,
            CreateDraftRequest(
                envelope=envelope,
                requested_kind=requested_kind,
                scope=scope,
                display_name=display_name,
            ),
        )
        await self._event(operation, "operation_created", {})
        try:
            operation = operation.model_copy(update={"status": AuthoringStatus.PLANNING})
            await self.repository.save_operation(operation)
            context = await self.resolver.resolve(envelope, envelope.resource_refs)
            await self._event(
                operation,
                "context_resolved",
                {
                    "context_digest": context.context_digest,
                    "resource_count": str(len(context.resources)),
                },
            )
            if not context.resources:
                raise SkillAuthoringError(
                    AuthoringErrorCode.AMBIGUOUS,
                    "choose at least one resource before creating a skill",
                )
            try:
                plan = await asyncio.wait_for(
                    self.model_gateway.propose_plan(
                        context, requested_kind=requested_kind
                    ),
                    timeout=envelope.budget.timeout_ms / 1000,
                )
            except asyncio.TimeoutError as error:
                raise SkillAuthoringError(
                    AuthoringErrorCode.MODEL_TIMEOUT,
                    "model gateway timed out",
                    operation_id=operation.operation_id,
                ) from error
            await self._event(
                operation,
                "plan_proposed",
                {"plan_id": plan.plan_id, "plan_digest": plan.plan_digest},
            )
            if plan.clarification_questions:
                operation = operation.model_copy(
                    update={
                        "status": AuthoringStatus.AWAITING_INPUT,
                        "clarification_questions": plan.clarification_questions,
                    }
                )
                await self.repository.save_operation(operation)
                await self._event(
                    operation,
                    "clarification_required",
                    {"question_count": str(len(plan.clarification_questions))},
                )
                return AuthoringReadModel(
                    operation=operation,
                    draft=None,
                    events=await self.repository.list_events(operation.operation_id),
                )
            draft = self._make_draft(
                operation,
                envelope,
                context,
                plan,
                scope=scope,
                display_name=display_name,
            )
            await self.repository.save_draft(draft)
            operation = operation.model_copy(
                update={
                    "status": AuthoringStatus.READY_FOR_EXECUTION,
                    "draft_id": draft.draft_id,
                    "current_revision": draft.revision,
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "draft_created",
                {"draft_id": draft.draft_id, "revision": str(draft.revision)},
            )
            return await self.read_operation(operation.operation_id)
        except SkillAuthoringError as error:
            status = (
                AuthoringStatus.CREDENTIAL_BLOCKED
                if error.code == AuthoringErrorCode.CREDENTIAL_BLOCKED
                else AuthoringStatus.AWAITING_INPUT
                if error.code == AuthoringErrorCode.AMBIGUOUS
                else AuthoringStatus.FAILED
            )
            operation = operation.model_copy(
                update={
                    "status": status,
                    "error_code": error.code,
                    "error_message": error.message,
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_operation(operation)
            event_type = (
                "credential_blocked"
                if error.code == AuthoringErrorCode.CREDENTIAL_BLOCKED
                else "operation_failed"
            )
            await self._event(
                operation,
                event_type,
                {"code": error.code.value, "message": error.message[:240]},
            )
            return await self.read_operation(operation.operation_id)

    async def propose_patch(
        self,
        draft_id: str,
        *,
        base_revision: int,
        patch: TypedPatch,
        proposed_by: str,
    ) -> PatchProposal:
        draft = await self.repository.get_draft(draft_id, base_revision)
        if draft is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND,
                f"draft revision {draft_id}@{base_revision} was not found",
            )
        if draft.promotion_state == "team_read_only":
            raise SkillAuthoringError(
                AuthoringErrorCode.TEAM_READ_ONLY,
                "team-published objects are read-only; copy them to a personal draft",
            )
        if isinstance(patch, SetQueryPlanPatch):
            if patch.query_plan.source_revision not in {
                item.revision for item in draft.lineage
            }:
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    "query patch must reference a fixed draft lineage revision",
                )
        if isinstance(patch, SetPermissionScopePatch) and not set(
            patch.permissions
        ).issubset(set(draft.authorized_permissions)):
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "permission patch cannot exceed server-authorized capabilities",
            )
        impact = self._impact(patch)
        operation = await self._new_operation(
            operation_type="propose_patch",
            caller_id=proposed_by,
            draft_id=draft_id,
        )
        proposal = PatchProposal(
            operation_id=operation.operation_id,
            draft_id=draft_id,
            base_revision=base_revision,
            patch=patch,
            impact=impact,
            proposed_by=proposed_by,
        )
        operation = operation.model_copy(
            update={"status": AuthoringStatus.SUCCEEDED, "patch_id": proposal.patch_id}
        )
        await self.repository.save_patch(proposal)
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "patch_proposed",
            {
                "patch_id": proposal.patch_id,
                "base_revision": str(base_revision),
                "requires_rerun": str(impact.requires_rerun).lower(),
            },
        )
        return proposal

    async def accept_patch(
        self,
        proposal: PatchProposal,
        *,
        caller_id: str,
        operation_id: str | None = None,
    ) -> AuthoringReadModel:
        operation = await self._new_operation(
            operation_type="accept_patch",
            caller_id=caller_id,
            draft_id=proposal.draft_id,
            operation_id=operation_id,
        )
        lock = self._locks.setdefault(proposal.draft_id, asyncio.Lock())
        async with lock:
            current = await self.repository.get_draft(proposal.draft_id)
            if current is None:
                raise SkillAuthoringError(
                    AuthoringErrorCode.NOT_FOUND, "draft was not found"
                )
            if current.owner_id != caller_id and current.promotion_state != "team_read_only":
                raise SkillAuthoringError(
                    AuthoringErrorCode.PERMISSION_DENIED,
                    "caller does not own this personal draft",
                )
            if current.promotion_state == "team_read_only":
                raise SkillAuthoringError(
                    AuthoringErrorCode.TEAM_READ_ONLY,
                    "team-published objects are read-only",
                )
            if current.revision != proposal.base_revision:
                await self._save_patch_status(proposal, "conflicted")
                operation = operation.model_copy(
                    update={
                        "status": AuthoringStatus.FAILED,
                        "error_code": AuthoringErrorCode.CONFLICT,
                        "error_message": "draft changed since this proposal was created",
                        "patch_id": proposal.patch_id,
                    }
                )
                await self.repository.save_operation(operation)
                await self._event(
                    operation,
                    "operation_failed",
                    {"code": AuthoringErrorCode.CONFLICT.value},
                )
                return await self.read_operation(operation.operation_id)
            next_draft = self._apply_patch(current, proposal.patch)
            await self.repository.save_draft(next_draft)
            operation = operation.model_copy(
                update={
                    "status": AuthoringStatus.READY_FOR_EXECUTION
                    if proposal.impact.requires_rerun
                    else AuthoringStatus.SUCCEEDED,
                    "current_revision": next_draft.revision,
                    "patch_id": proposal.patch_id,
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "patch_accepted",
                {
                    "draft_id": next_draft.draft_id,
                    "revision": str(next_draft.revision),
                    "requires_rerun": str(proposal.impact.requires_rerun).lower(),
                },
            )
            await self._save_patch_status(proposal, "accepted")
            return await self.read_operation(operation.operation_id)

    async def reject_patch(
        self, proposal: PatchProposal, *, caller_id: str
    ) -> AuthoringReadModel:
        operation = await self._new_operation(
            operation_type="patch_reject",
            caller_id=caller_id,
            draft_id=proposal.draft_id,
        )
        operation = operation.model_copy(update={"patch_id": proposal.patch_id})
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "patch_rejected",
            {"patch_id": proposal.patch_id},
        )
        await self._save_patch_status(proposal, "rejected")
        operation = operation.model_copy(update={"status": AuthoringStatus.SUCCEEDED})
        await self.repository.save_operation(operation)
        return await self.read_operation(operation.operation_id)

    async def _save_patch_status(
        self, proposal: PatchProposal, status: str
    ) -> None:
        await self.repository.save_patch(proposal.model_copy(update={"status": status}))

    async def repair_comment(
        self, request: CommentRepairRequest
    ) -> PatchProposal:
        proposal = await self.propose_patch(
            request.draft_id,
            base_revision=request.base_revision,
            patch=request.patch,
            proposed_by=request.proposed_by,
        )
        proposal = proposal.model_copy(
            update={"source_comment_ids": (request.comment_id,)}
        )
        await self.repository.save_patch(proposal)
        return proposal

    async def repair_comments(
        self, request: CommentRepairBatchRequest
    ) -> CommentRepairBatchResult:
        if len({item.draft_id for item in request.requests}) != 1:
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "batch comment repair must target one draft",
            )
        proposals = tuple(
            [
                await self.repair_comment(item)
                for item in request.requests
            ]
        )
        operation = await self._new_operation(
            operation_type="comment_repair_batch",
            caller_id=request.requests[0].proposed_by,
            draft_id=request.requests[0].draft_id,
        )
        await self._event(
            operation,
            "patch_proposed",
            {"proposal_count": str(len(proposals)), "batch": "true"},
        )
        return CommentRepairBatchResult(
            operation_id=operation.operation_id,
            proposals=proposals,
        )

    async def undo(
        self,
        draft_id: str,
        *,
        target_revision: int,
        caller_id: str,
    ) -> AuthoringReadModel:
        current = await self.repository.get_draft(draft_id)
        target = await self.repository.get_draft(draft_id, target_revision)
        if current is None or target is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND, "draft revision was not found"
            )
        if current.owner_id != caller_id or current.promotion_state == "team_read_only":
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "only the personal draft owner may undo a revision",
            )
        operation = await self._new_operation(
            operation_type="undo",
            caller_id=caller_id,
            draft_id=draft_id,
        )
        restored = target.model_copy(
            update={
                "revision": current.revision + 1,
                "parent_revision": current.revision,
                "undo_of_revision": target_revision,
                "updated_at": utc_now(),
                "digest": digest(
                    {
                        "manifest": target.manifest.model_dump(mode="json"),
                        "plan": target.plan.model_dump(mode="json"),
                        "undo_of": target_revision,
                        "new_revision": current.revision + 1,
                    }
                ),
            }
        )
        await self.repository.save_draft(restored)
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.SUCCEEDED,
                "current_revision": restored.revision,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "undo_applied",
            {"target_revision": str(target_revision), "revision": str(restored.revision)},
        )
        return await self.read_operation(operation.operation_id)

    async def request_execution(
        self, draft_id: str, *, caller_id: str, revision: int | None = None
    ) -> AuthoringReadModel:
        draft = await self.repository.get_draft(draft_id, revision)
        if draft is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "draft not found")
        if draft.owner_id != caller_id and draft.promotion_state != "team_read_only":
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED, "caller cannot execute this draft"
            )
        await self.resolver.resolve(
            ContextEnvelope(
                caller_id=caller_id,
                workspace_id=draft.workspace_id,
                prompt="execute fixed SkillDraft revision",
                resource_refs=draft.lineage,
                permissions=draft.authorized_permissions,
                fixed_revisions=tuple(ref.revision for ref in draft.lineage),
                freshness=draft.manifest.freshness,
                current_skill_id=draft.draft_id,
            ),
            draft.lineage,
        )
        operation = await self._new_operation(
            operation_type="execute_draft",
            caller_id=caller_id,
            draft_id=draft_id,
        )
        request = Worker3ExecutionRequest(
            operation_id=operation.operation_id,
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            skill_kind=draft.manifest.kind,
            workspace_id=draft.workspace_id,
            caller_id=caller_id,
            dependencies=draft.lineage,
            budget=draft.budget,
            freshness=draft.manifest.freshness,
        )
        accepted = await self.worker3.request_execution(request)
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.RUNNING
                if getattr(accepted, "state", None) == "accepted"
                else AuthoringStatus.READY_FOR_EXECUTION,
                "current_revision": draft.revision,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "execution_requested",
            {"draft_id": draft_id, "revision": str(draft.revision)},
        )
        return await self.read_operation(operation.operation_id)

    async def submit_team_review(self, request: TeamReviewRequest) -> AuthoringReadModel:
        draft = await self.repository.get_draft(request.draft_id, request.base_revision)
        if draft is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "draft not found")
        if draft.scope != Scope.PERSONAL or draft.promotion_state != "personal":
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "only a personal draft can enter team review",
            )
        if draft.owner_id != request.caller_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "only the draft owner can submit team review",
            )
        operation = await self._new_operation(
            operation_type="submit_team_review",
            caller_id=request.caller_id,
            draft_id=request.draft_id,
        )
        next_revision = draft.revision + 1
        reviewed = draft.model_copy(
            update={
                "revision": next_revision,
                "parent_revision": draft.revision,
                "promotion_state": "pre_publish_evaluation",
                "updated_at": utc_now(),
                "digest": digest(
                    {
                        "parent": draft.digest,
                        "team": request.team_id,
                        "review_revision": request.base_revision,
                        "next_revision": next_revision,
                    }
                ),
            }
        )
        await self.repository.save_draft(reviewed)
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.SUCCEEDED,
                "current_revision": reviewed.revision,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "context_resolved",
            {
                "team_id": request.team_id,
                "state": "pre_publish_evaluation",
                "published": "false",
                "revision": str(reviewed.revision),
            },
        )
        return await self.read_operation(operation.operation_id)

    async def update_context(
        self,
        draft_id: str,
        *,
        caller_id: str,
        envelope: ContextEnvelope,
        mutation: ContextMutation,
    ) -> AuthoringReadModel:
        current = await self.repository.get_draft(draft_id)
        if current is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "draft not found")
        if current.owner_id != caller_id or current.promotion_state == "team_read_only":
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "only a personal draft owner can change context",
            )
        refs = list(current.lineage)
        if mutation.action == "add" and mutation.resource_ref not in refs:
            refs.append(mutation.resource_ref)
        elif mutation.action == "remove":
            refs = [ref for ref in refs if ref != mutation.resource_ref]
        resolved = await self.resolver.resolve(envelope, tuple(refs))
        operation = await self._new_operation(
            operation_type="update_context",
            caller_id=caller_id,
            draft_id=draft_id,
        )
        authorized_permissions = resolved.authorized_permissions
        resolved_refs = tuple(item.ref for item in resolved.resources)
        manifest = current.manifest.model_copy(
            update={
                "dependencies": resolved_refs,
                "permissions": authorized_permissions,
            }
        )
        plan = current.plan.model_copy(update={"dependencies": resolved_refs})
        next_revision = current.revision + 1
        updated = current.model_copy(
            update={
                "revision": next_revision,
                "parent_revision": current.revision,
                "manifest": manifest,
                "plan": plan,
                "lineage": resolved_refs,
                "authorized_permissions": authorized_permissions,
                "updated_at": utc_now(),
                "digest": digest(
                    {
                        "parent": current.digest,
                        "context": resolved.context_digest,
                        "revision": next_revision,
                    }
                ),
            }
        )
        await self.repository.save_draft(updated)
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.READY_FOR_EXECUTION,
                "current_revision": next_revision,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "context_resolved",
            {
                "action": mutation.action,
                "revision": str(next_revision),
                "context_digest": resolved.context_digest,
            },
        )
        return await self.read_operation(operation.operation_id)

    async def cancel(
        self, operation_id: str, *, caller_id: str
    ) -> AuthoringReadModel:
        operation = await self.repository.get_operation(operation_id)
        if operation is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "operation not found")
        if operation.caller_id != caller_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED, "caller cannot cancel this operation"
            )
        if operation.status in {
            AuthoringStatus.SUCCEEDED,
            AuthoringStatus.FAILED,
            AuthoringStatus.CANCELLED,
        }:
            return await self.read_operation(operation_id)
        cancelled = operation.model_copy(
            update={
                "status": AuthoringStatus.CANCELLED,
                "error_code": AuthoringErrorCode.CANCELLED,
                "error_message": "operation cancelled by caller",
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_operation(cancelled)
        await self._event(
            cancelled,
            "operation_cancelled",
            {"reason": "caller_requested"},
        )
        return await self.read_operation(operation_id)

    async def retry(
        self, operation_id: str, *, caller_id: str
    ) -> AuthoringReadModel:
        operation = await self.repository.get_operation(operation_id)
        if operation is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "operation not found")
        if operation.caller_id != caller_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED, "caller cannot retry this operation"
            )
        if operation.status not in {
            AuthoringStatus.FAILED,
            AuthoringStatus.CREDENTIAL_BLOCKED,
            AuthoringStatus.CANCELLED,
        }:
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "only failed, blocked, or cancelled operations can be retried",
            )
        if operation.operation_type != "create_draft":
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "only draft creation retries are supported",
            )
        draft = (
            await self.repository.get_draft(operation.draft_id)
            if operation.draft_id
            else None
        )
        if draft is not None:
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "a draft already exists; use a typed patch or execution retry",
            )
        request = await self.repository.get_create_request(operation_id)
        if request is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND,
                "durable create request is unavailable for retry",
            )
        retry_request = CreateDraftRequest.model_validate(request)
        retried = await self.create_draft(
            retry_request.envelope,
            requested_kind=retry_request.requested_kind,
            scope=retry_request.scope,
            display_name=retry_request.display_name,
        )
        replacement = retried.operation.model_copy(
            update={"retry_of_operation_id": operation_id}
        )
        await self.repository.save_operation(replacement)
        await self._event(replacement, "operation_retry", {"attempt": "next"})
        return await self.read_operation(replacement.operation_id)

    async def copy_team_draft(
        self,
        request: TeamReuseRequest,
        *,
        caller_id: str,
        workspace_id: str,
    ) -> AuthoringReadModel:
        source = await self.repository.get_draft(
            request.team_draft_id, request.team_revision
        )
        if source is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "team draft not found")
        if source.scope != Scope.TEAM or source.promotion_state != "team_read_only":
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "only a team read-only draft can be reused",
            )
        if source.workspace_id != workspace_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "team draft belongs to another workspace",
            )
        operation = await self._new_operation(
            operation_type="copy_team_draft",
            caller_id=caller_id,
            draft_id=None,
            workspace_id=workspace_id,
        )
        copied = source.model_copy(
            update={
                "draft_id": f"draft_{uuid4().hex}",
                "revision": 1,
                "parent_revision": None,
                "owner_id": caller_id,
                "scope": Scope.PERSONAL,
                "promotion_state": "personal",
                "lineage_source_draft_id": source.draft_id,
                "manifest": source.manifest.model_copy(
                    update={"name": request.personal_name}
                ),
                "lineage": source.lineage,
                "digest": digest(
                    {
                        "source_draft": source.draft_id,
                        "source_revision": source.revision,
                        "owner": caller_id,
                        "name": request.personal_name,
                    }
                ),
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_draft(copied)
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.SUCCEEDED,
                "draft_id": copied.draft_id,
                "current_revision": 1,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "draft_created",
            {
                "lineage_source": source.draft_id,
                "draft_id": copied.draft_id,
                "scope": Scope.PERSONAL.value,
            },
        )
        return await self.read_operation(operation.operation_id)

    async def read_operation(self, operation_id: str) -> AuthoringReadModel:
        operation = await self.repository.get_operation(operation_id)
        if operation is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "operation not found")
        draft = (
            await self.repository.get_draft(operation.draft_id)
            if getattr(operation, "draft_id", None)
            else None
        )
        return AuthoringReadModel(
            operation=operation,
            draft=draft,
            latest_patch=(
                await self.repository.get_patch(operation.patch_id)
                if operation.patch_id
                else None
            ),
            events=await self.repository.list_events(operation_id),
        )

    async def _new_operation(
        self,
        *,
        operation_type: str,
        caller_id: str,
        draft_id: str | None,
        operation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthoringOperation:
        draft = (
            await self.repository.get_draft(draft_id)
            if draft_id
            else None
        )
        operation = AuthoringOperation(
            operation_id=operation_id or f"op_{uuid4().hex}",
            operation_type=operation_type,  # type: ignore[arg-type]
            status=AuthoringStatus.QUEUED,
            caller_id=caller_id,
            workspace_id=workspace_id or (draft.workspace_id if draft else "unknown"),
            draft_id=draft_id,
            trace_id=f"trace_{uuid4().hex}",
        )
        await self.repository.save_operation(operation)
        await self._event(operation, "operation_created", {})
        return operation

    async def _event(
        self, operation: AuthoringOperation, event_type: str, data: dict[str, str]
    ) -> None:
        existing = await self.repository.list_events(operation.operation_id)
        await self.repository.save_event(
            AuthoringEvent(
                operation_id=operation.operation_id,
                event_type=event_type,  # type: ignore[arg-type]
                sequence=len(existing) + 1,
                data=data,
            )
        )

    @staticmethod
    def _make_draft(
        operation: AuthoringOperation,
        envelope: ContextEnvelope,
        context: ResolvedContext,
        plan: BuildPlan,
        *,
        scope: Scope,
        display_name: str | None,
    ) -> DraftRevision:
        name = display_name or f"{plan.intent.value} skill"
        manifest = DraftManifest(
            name=name,
            description=plan.purpose,
            kind=plan.intent,
            kind_spec=plan.kind_spec,
            inputs=plan.inputs,
            outputs=plan.outputs,
            dependencies=plan.dependencies,
            permissions=context.authorized_permissions,
            freshness=envelope.freshness,
        )
        draft_id = f"draft_{uuid4().hex}"
        draft_digest = digest(
            {
                "draft_id": draft_id,
                "manifest": manifest.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "context": context.context_digest,
            }
        )
        return DraftRevision(
            draft_id=draft_id,
            revision=1,
            manifest=manifest,
            plan=plan,
            scope=scope,
            owner_id=envelope.caller_id,
            workspace_id=envelope.workspace_id,
            budget=envelope.budget,
            authorized_permissions=context.authorized_permissions,
            lineage=plan.dependencies,
            promotion_state="team_read_only" if scope == Scope.TEAM else "personal",
            digest=draft_digest,
        )

    @staticmethod
    def _impact(patch: TypedPatch) -> PatchImpact:
        if isinstance(patch, (SetTitlePatch, SetDescriptionPatch)):
            return PatchImpact(
                summary="更新 Skill 草稿展示文本",
                affected_paths=("manifest.name" if isinstance(patch, SetTitlePatch) else "manifest.description",),
                requires_rerun=False,
                reason="presentation_only",
            )
        if isinstance(patch, SetQueryPlanPatch):
            return PatchImpact(
                summary="查询计划变化，需要重新执行",
                affected_paths=("kind_spec.query_plan", "query_plan"),
                requires_rerun=True,
                reason="query_changed",
            )
        if isinstance(patch, SetRefreshPolicyPatch):
            return PatchImpact(
                summary="刷新策略变化，需要重新执行",
                affected_paths=("manifest.freshness",),
                requires_rerun=True,
                reason="freshness_changed",
            )
        if isinstance(patch, SetPermissionScopePatch):
            if any(permission not in {"read", "profile", "query"} for permission in patch.permissions):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "permission patch contains an unsupported capability",
                )
            return PatchImpact(
                summary="权限范围变化，需要重新鉴权并执行",
                affected_paths=("manifest.permissions",),
                requires_rerun=True,
                reason="permission_changed",
            )
        if isinstance(patch, SetThresholdPolicyPatch):
            return PatchImpact(
                summary="告警阈值变化，需要重新执行",
                affected_paths=("kind_spec.threshold", "kind_spec.comparator"),
                requires_rerun=True,
                reason="alert_changed",
            )
        if isinstance(patch, SetSemanticMappingPatch):
            return PatchImpact(
                summary="语义映射变化，需要重新编译",
                affected_paths=("kind_spec.mapping_intent",),
                requires_rerun=True,
                reason="mapping_changed",
            )
        if isinstance(patch, AddCitationIntentPatch):
            return PatchImpact(
                summary="引用意图变化，需要重新检索",
                affected_paths=("kind_spec.citation_intent",),
                requires_rerun=True,
                reason="query_changed",
            )
        raise SkillAuthoringError(
            AuthoringErrorCode.VALIDATION_FAILED,
            "unsupported patch type",
        )

    @staticmethod
    def _apply_patch(draft: DraftRevision, patch: TypedPatch) -> DraftRevision:
        manifest = draft.manifest
        kind_spec = manifest.kind_spec
        if isinstance(patch, SetTitlePatch):
            manifest = manifest.model_copy(update={"name": patch.title})
        elif isinstance(patch, SetDescriptionPatch):
            manifest = manifest.model_copy(update={"description": patch.description})
        elif isinstance(patch, SetPermissionScopePatch):
            if not set(patch.permissions).issubset(set(draft.authorized_permissions)):
                raise SkillAuthoringError(
                    AuthoringErrorCode.PERMISSION_DENIED,
                    "permission patch cannot exceed server-authorized capabilities",
                )
            manifest = manifest.model_copy(update={"permissions": patch.permissions})
        elif isinstance(patch, SetRefreshPolicyPatch):
            manifest = manifest.model_copy(update={"freshness": patch.freshness})
        elif isinstance(patch, SetQueryPlanPatch):
            if draft.manifest.kind != SkillKind.ANALYSIS:
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "query plan patches apply only to analysis skills",
                )
            if patch.query_plan.source_revision not in {
                item.revision for item in draft.lineage
            }:
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    "query patch must reference a fixed draft lineage revision",
                )
            kind_spec = kind_spec.model_copy(update={"query_plan": patch.query_plan})
            plan = draft.plan.model_copy(
                update={"kind_spec": kind_spec, "query_plan": patch.query_plan}
            )
        elif isinstance(patch, SetThresholdPolicyPatch):
            if draft.manifest.kind != SkillKind.MONITORING:
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "threshold patches apply only to monitoring skills",
                )
            kind_spec = kind_spec.model_copy(
                update={"threshold": patch.threshold, "comparator": patch.comparator}
            )
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
        elif isinstance(patch, AddCitationIntentPatch):
            if draft.manifest.kind != SkillKind.KNOWLEDGE:
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "citation patches apply only to knowledge skills",
                )
            kind_spec = kind_spec.model_copy(
                update={"citation_intent": (*kind_spec.citation_intent, patch.intent)}
            )
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
        elif isinstance(patch, SetSemanticMappingPatch):
            if draft.manifest.kind != SkillKind.GRAPH_ONTOLOGY:
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "mapping patches apply only to graph ontology skills",
                )
            kind_spec = kind_spec.model_copy(
                update={
                    "mapping_intent": (
                        *kind_spec.mapping_intent,
                        f"{patch.field}->{patch.entity}",
                    )
                }
            )
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
        else:
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "unsupported patch",
            )
        if "plan" not in locals():
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
        revision = draft.revision + 1
        return draft.model_copy(
            update={
                "revision": revision,
                "parent_revision": draft.revision,
                "manifest": manifest.model_copy(update={"kind_spec": kind_spec}),
                "plan": plan,
                "updated_at": utc_now(),
                "digest": digest(
                    {
                        "manifest": manifest.model_dump(mode="json"),
                        "plan": plan.model_dump(mode="json"),
                        "parent": draft.digest,
                        "revision": revision,
                    }
                ),
            }
        )
