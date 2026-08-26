"""Application service for safe SkillDraft orchestration."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from .models import (
    AddCitationIntentPatch,
    AgentTurnAccepted,
    AgentTurnRequest,
    AgentExecutionEvidence,
    AgentRuntimeEvent,
    AuthoringErrorCode,
    AuthoringEvent,
    AuthoringOperation,
    AuthoringReadModel,
    AuthoringStatus,
    BuildPlan,
    ContextEnvelope,
    DraftManifest,
    DraftRevision,
    GraphOntologyKindSpec,
    KnowledgeKindSpec,
    PatchImpact,
    PatchProposal,
    ResolvedContext,
    Scope,
    SemanticKindSpec,
    SetDescriptionPatch,
    SetPermissionScopePatch,
    SetQueryPlanPatch,
    SetRefreshPolicyPatch,
    SetSemanticMappingPatch,
    SetSemanticMetricPatch,
    SetSemanticDimensionPatch,
    SetSemanticRelationshipPatch,
    SetThresholdPolicyPatch,
    SetTitlePatch,
    SetDashboardKpiPatch,
    SetDashboardChartPatch,
    SetDashboardFilterPatch,
    SetSopStepPatch,
    SetSopConditionPatch,
    SetSopToolRefPatch,
    SetGraphEntityPatch,
    SetGraphRelationPatch,
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
        self._active_tasks: dict[str, asyncio.Task[object]] = {}
        self._generation_guard = asyncio.Lock()
        self._active_generations: dict[str, str] = {}

    @property
    def active_operation_ids(self) -> tuple[str, ...]:
        return tuple(self._active_tasks)

    @staticmethod
    def _generation_key(envelope: ContextEnvelope) -> str:
        """Return the durable conversation lane used for concurrency control."""

        return (
            f"{envelope.workspace_id}\0{envelope.caller_id}\0"
            f"{envelope.conversation_id or 'default'}"
        )

    async def _claim_generation(
        self,
        envelope: ContextEnvelope,
        operation: AuthoringOperation,
        *,
        idempotency_key: str | None,
    ) -> tuple[AuthoringOperation, bool]:
        """Atomically claim one conversation lane and optional idempotency key."""

        generation_key = self._generation_key(envelope)
        async with self._generation_guard:
            operation_id, claimed, reason = await self.repository.claim_generation(
                generation_key,
                operation,
                idempotency_key=idempotency_key,
            )
            if not claimed:
                existing = await self.repository.get_operation(operation_id)
                if existing is None:
                    raise SkillAuthoringError(
                        AuthoringErrorCode.NOT_FOUND,
                        "durable generation operation is unavailable",
                    )
                if (
                    existing.caller_id != envelope.caller_id
                    or existing.workspace_id != envelope.workspace_id
                    or existing.conversation_id != envelope.conversation_id
                ):
                    raise SkillAuthoringError(
                        AuthoringErrorCode.PERMISSION_DENIED,
                        "generation lane belongs to another caller",
                    )
                if reason == "active":
                    raise SkillAuthoringError(
                        AuthoringErrorCode.VALIDATION_FAILED,
                        "当前对话已有回答正在生成，请先停止后再发送。",
                        operation_id=operation_id,
                    )
                return existing, False
            operation = operation.model_copy(update={"operation_id": operation_id})
            self._active_generations[generation_key] = operation.operation_id
            return operation, True

    async def _release_generation(self, operation: AuthoringOperation) -> None:
        for candidate, operation_id in tuple(self._active_generations.items()):
            if operation_id == operation.operation_id:
                self._active_generations.pop(candidate, None)
        await self.repository.release_generation(operation.operation_id)

    def _schedule_release(self, operation: AuthoringOperation) -> None:
        asyncio.create_task(self._release_generation(operation))

    def _on_generation_done(
        self, completed: asyncio.Task[object], operation: AuthoringOperation
    ) -> None:
        """Finalize a detached turn without leaving an unhandled operation."""

        self._active_tasks.pop(operation.operation_id, None)
        asyncio.create_task(self._finalize_generation_task(completed, operation))

    async def _finalize_generation_task(
        self, completed: asyncio.Task[object], operation: AuthoringOperation
    ) -> None:
        try:
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                current = await self.repository.get_operation(operation.operation_id)
                if current is not None and current.status not in {
                    AuthoringStatus.SUCCEEDED,
                    AuthoringStatus.FAILED,
                    AuthoringStatus.CANCELLED,
                    AuthoringStatus.AWAITING_INPUT,
                    AuthoringStatus.CREDENTIAL_BLOCKED,
                }:
                    await self._finish_answer_failure(
                        current,
                        SkillAuthoringError(
                            AuthoringErrorCode.MODEL_UNAVAILABLE,
                            "Agent execution failed unexpectedly; you can retry this operation.",
                            operation_id=current.operation_id,
                        ),
                    )
        finally:
            await self._release_generation(operation)

    def _execution_evidence(self, request_id: str) -> AgentExecutionEvidence | None:
        lookup = getattr(self.model_gateway, "execution_evidence_for", None)
        if callable(lookup):
            evidence = lookup(request_id)
            if isinstance(evidence, AgentExecutionEvidence):
                return evidence
        evidence = getattr(self.model_gateway, "execution_evidence", None)
        return evidence if isinstance(evidence, AgentExecutionEvidence) else None

    async def create_draft(
        self,
        envelope: ContextEnvelope,
        *,
        requested_kind: SkillKind | None = None,
        scope: Scope = Scope.PERSONAL,
        display_name: str | None = None,
        _operation: AuthoringOperation | None = None,
        _context: ResolvedContext | None = None,
        _auto_execute: bool = False,
    ) -> AuthoringReadModel:
        operation = _operation or AuthoringOperation(
            operation_id=f"op_{uuid4().hex}",
            operation_type="create_draft",
            status=AuthoringStatus.QUEUED,
            caller_id=envelope.caller_id,
            workspace_id=envelope.workspace_id,
            conversation_id=envelope.conversation_id,
            trace_id=f"trace_{uuid4().hex}",
        )
        if _operation is not None:
            operation = operation.model_copy(
                update={"operation_type": "create_draft", "updated_at": utc_now()}
            )
        await self.repository.save_operation(operation)
        if _operation is None:
            await self.repository.save_authoring_request(
                operation.operation_id,
                CreateDraftRequest(
                    envelope=envelope,
                    requested_kind=requested_kind,
                    scope=scope,
                    display_name=display_name,
                ),
            )
        if _operation is None:
            await self._event(operation, "operation_created", {})
        try:
            operation = operation.model_copy(
                update={
                    "status": AuthoringStatus.PLANNING,
                    "stage": "planning",
                    "progress": 10,
                }
            )
            await self.repository.save_operation(operation)
            context = _context
            if context is None:
                context = await self.resolver.resolve(envelope, envelope.resource_refs)
                await self._event(
                    operation,
                    "context_resolved",
                    {
                        "context_digest": context.context_digest,
                        "resource_count": str(len(context.resources)),
                    },
                )
            operation = operation.model_copy(
                update={
                    "stage": "context_resolved",
                    "progress": 30,
                    "context_digest": context.context_digest,
                }
            )
            await self.repository.save_operation(operation)
            if not context.resources:
                raise SkillAuthoringError(
                    AuthoringErrorCode.AMBIGUOUS,
                    "choose at least one resource before creating a skill",
                )

            async def persist_runtime_event(event: AgentRuntimeEvent) -> None:
                await self._event(
                    operation,
                    event.type,
                    dict(event.payload),
                    summary=event.public_summary,
                    session_id=event.session_id,
                    trace_id=event.trace_id,
                )

            try:
                plan = await asyncio.wait_for(
                    self.model_gateway.propose_plan(
                        context,
                        requested_kind=requested_kind,
                        event_sink=persist_runtime_event,
                    ),
                    timeout=envelope.budget.timeout_ms / 1000,
                )
            except asyncio.TimeoutError as error:
                raise SkillAuthoringError(
                    AuthoringErrorCode.MODEL_TIMEOUT,
                    "model gateway timed out",
                    operation_id=operation.operation_id,
                ) from error
            execution_evidence = self._execution_evidence(envelope.request_id)
            if execution_evidence is not None:
                operation = operation.model_copy(
                    update={
                        "agent_execution": execution_evidence,
                        "trace_id": execution_evidence.trace_id,
                    }
                )
                await self.repository.save_operation(operation)
                await self._event(
                    operation,
                    "agent_execution",
                    {
                        "session_id": execution_evidence.session_id,
                        "trace_id": execution_evidence.trace_id,
                        "status": execution_evidence.status,
                        "event_count": str(len(execution_evidence.events)),
                        "tool_call_count": str(len(execution_evidence.tool_calls)),
                    },
                )
            plan = self._validate_plan(context, plan, requested_kind=requested_kind)
            operation = operation.model_copy(
                update={"stage": "plan_ready", "progress": 60, "plan": plan}
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "plan_proposed",
                {
                    "plan_id": plan.plan_id,
                    "plan_digest": plan.plan_digest,
                    "steps": [
                        {
                            "id": "resolve_context",
                            "label": "解析上下文",
                            "status": "completed",
                        },
                        {
                            "id": "build_plan",
                            "label": "生成 Skill 方案",
                            "status": "completed",
                        },
                        {
                            "id": "save_revision",
                            "label": "保存 Skill 修订",
                            "status": "running",
                        },
                    ],
                },
            )
            if plan.clarification_questions:
                operation = operation.model_copy(
                    update={
                        "status": AuthoringStatus.AWAITING_INPUT,
                        "stage": "clarification",
                        "progress": 60,
                        "clarification_questions": plan.clarification_questions,
                    }
                )
                await self.repository.save_operation(operation)
                await self._event(
                    operation,
                    "clarification_required",
                    {
                        "question_count": str(len(plan.clarification_questions)),
                        "clarification_questions": list(plan.clarification_questions),
                    },
                )
                await self._event(
                    operation,
                    "operation.completed",
                    {"status": operation.status.value},
                    summary="Waiting for clarification",
                    terminal=True,
                )
                return AuthoringReadModel(
                    operation=operation,
                    draft=None,
                    events=await self.repository.list_events(operation.operation_id),
                )
            if await self._is_cancelled(operation.operation_id):
                return await self.read_operation(operation.operation_id)
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
                    "stage": "draft_ready",
                    "progress": 100,
                    "plan": plan,
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "plan.step.completed",
                {"step_id": "save_revision"},
                summary="Skill revision saved",
            )
            inline_execution = _auto_execute and getattr(
                self.worker3, "supports_inline_execution", False
            )
            if not inline_execution:
                await self._event(
                    operation,
                    "draft_created",
                    {"draft_id": draft.draft_id, "revision": str(draft.revision)},
                )
            if inline_execution:
                return await self.request_execution(
                    draft.draft_id,
                    caller_id=envelope.caller_id,
                    revision=draft.revision,
                    _operation=operation,
                )
            await self._event(
                operation,
                "operation.completed",
                {
                    "status": operation.status.value,
                    "draft_id": draft.draft_id,
                    "revision": draft.revision,
                },
                summary="Skill draft ready",
                terminal=True,
            )
            return await self.read_operation(operation.operation_id)

        except SkillAuthoringError as error:
            execution_evidence = self._execution_evidence(envelope.request_id)
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
                    "stage": (
                        "credential_blocked"
                        if error.code == AuthoringErrorCode.CREDENTIAL_BLOCKED
                        else "clarification"
                        if error.code == AuthoringErrorCode.AMBIGUOUS
                        else "failed"
                    ),
                    "progress": 60
                    if error.code == AuthoringErrorCode.AMBIGUOUS
                    else 100,
                    "updated_at": utc_now(),
                    "agent_execution": execution_evidence,
                    "trace_id": (
                        execution_evidence.trace_id
                        if execution_evidence is not None
                        and execution_evidence.trace_id != "unavailable"
                        else operation.trace_id
                    ),
                }
            )
            if error.code == AuthoringErrorCode.AMBIGUOUS:
                questions = (
                    "请先选择一个已授权的数据资源（固定 revision），再创建 Skill。",
                )
                operation = operation.model_copy(
                    update={"clarification_questions": questions}
                )
            await self.repository.save_operation(operation)
            if error.code == AuthoringErrorCode.AMBIGUOUS:
                await self._event(
                    operation,
                    "answer.final",
                    {
                        "status": "awaiting_input",
                        "clarification_questions": list(questions),
                    },
                    summary="Clarification required",
                )
                await self._event(
                    operation,
                    "operation.completed",
                    {
                        "status": operation.status.value,
                        "clarification_questions": list(questions),
                    },
                    summary="Waiting for clarification",
                    terminal=True,
                )
            else:
                event_type = (
                    "credential_blocked"
                    if error.code == AuthoringErrorCode.CREDENTIAL_BLOCKED
                    else "operation_failed"
                )
                await self._event(
                    operation,
                    event_type,
                    {"code": error.code.value, "message": error.message[:240]},
                    terminal=True,
                )
            return await self.read_operation(operation.operation_id)

    async def start_turn(
        self,
        envelope: ContextEnvelope,
        *,
        requested_kind: SkillKind | None = None,
        scope: Scope = Scope.PERSONAL,
        display_name: str | None = None,
        idempotency_key: str | None = None,
    ) -> AgentTurnAccepted:
        """Start one routed Agent turn and return before model execution finishes."""

        operation = AuthoringOperation(
            operation_id=f"op_{uuid4().hex}",
            operation_type="answer",
            status=AuthoringStatus.QUEUED,
            caller_id=envelope.caller_id,
            workspace_id=envelope.workspace_id,
            conversation_id=envelope.conversation_id,
            trace_id=f"trace_{uuid4().hex}",
        )
        operation, claimed = await self._claim_generation(
            envelope,
            operation,
            idempotency_key=idempotency_key,
        )
        if not claimed:
            return AgentTurnAccepted(
                operation_id=operation.operation_id,
                action="routing",
                status=operation.status,
            )
        turn_request = AgentTurnRequest(
            envelope=envelope,
            requested_kind=requested_kind,
            scope=scope,
            display_name=display_name,
        )
        await self.repository.save_authoring_request(
            operation.operation_id, turn_request
        )
        await self._event(
            operation,
            "message.accepted",
            {"request_id": envelope.request_id},
            summary="Message accepted",
        )
        task = asyncio.create_task(
            self._run_turn(
                operation,
                envelope,
                requested_kind=requested_kind,
                scope=scope,
                display_name=display_name,
            )
        )
        self._active_tasks[operation.operation_id] = task
        task.add_done_callback(
            lambda completed: self._on_generation_done(completed, operation)
        )
        return AgentTurnAccepted(
            operation_id=operation.operation_id,
            action="routing",
            status=operation.status,
        )

    async def _run_turn(
        self,
        operation: AuthoringOperation,
        envelope: ContextEnvelope,
        *,
        requested_kind: SkillKind | None,
        scope: Scope,
        display_name: str | None,
    ) -> AuthoringReadModel:
        try:
            operation = operation.model_copy(
                update={
                    "status": AuthoringStatus.PLANNING,
                    "stage": "planning",
                    "progress": 10,
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "context.resolving",
                {"resource_count": len(envelope.resource_refs)},
                summary="Resolving authorized context",
            )
            context = await self.resolver.resolve(envelope, envelope.resource_refs)
            operation = operation.model_copy(
                update={
                    "context_digest": context.context_digest,
                    "stage": "context_resolved",
                    "progress": 20,
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "context.resolved",
                {
                    "context_digest": context.context_digest,
                    "resource_count": len(context.resources),
                },
                summary=f"Resolved {len(context.resources)} authorized context items",
            )
            await self._event(
                operation,
                "agent.started",
                {"role": "router"},
                summary="Routing request",
            )
            intent = await asyncio.wait_for(
                self.model_gateway.route(context),
                timeout=envelope.budget.timeout_ms / 1000,
            )
            # Routing is a real VEADK Agent/Runner invocation too. Persist its
            # bounded evidence before branching into answer/create/patch/
            # execute so every routed turn exposes the same durable execution
            # identity and keeps one operation/trace across the whole journey.
            execution_evidence = self._execution_evidence(envelope.request_id)
            if execution_evidence is not None:
                operation = operation.model_copy(
                    update={
                        "agent_execution": execution_evidence,
                        "trace_id": (
                            execution_evidence.trace_id
                            if execution_evidence.trace_id != "unavailable"
                            else operation.trace_id
                        ),
                        "updated_at": utc_now(),
                    }
                )
                await self.repository.save_operation(operation)
                await self._event(
                    operation,
                    "agent_execution",
                    {
                        "session_id": execution_evidence.session_id,
                        "trace_id": execution_evidence.trace_id,
                        "status": execution_evidence.status,
                        "event_count": str(len(execution_evidence.events)),
                        "tool_call_count": str(len(execution_evidence.tool_calls)),
                    },
                    summary="Agent routing completed",
                    session_id=execution_evidence.session_id,
                    trace_id=execution_evidence.trace_id,
                )
        except asyncio.CancelledError:
            stored = await self.repository.get_operation(operation.operation_id)
            if stored is not None and stored.status == AuthoringStatus.CANCELLED:
                return await self.read_operation(operation.operation_id)
            raise
        except asyncio.TimeoutError:
            return await self._finish_answer_failure(
                operation,
                SkillAuthoringError(
                    AuthoringErrorCode.MODEL_TIMEOUT, "VEADK Runner timed out"
                ),
            )
        except SkillAuthoringError as error:
            return await self._finish_answer_failure(operation, error)

        if intent.action == "patch":
            if not envelope.current_skill_id:
                return await self._finish_answer_failure(
                    operation,
                    SkillAuthoringError(
                        AuthoringErrorCode.INVALID_CONTEXT,
                        "请先选择一个可编辑的 Skill 草稿。",
                    ),
                )
            draft = await self.repository.get_draft(envelope.current_skill_id)
            if draft is None:
                return await self._finish_answer_failure(
                    operation,
                    SkillAuthoringError(
                        AuthoringErrorCode.NOT_FOUND,
                        "当前 Skill 草稿不存在或已不可用。",
                    ),
                )
            try:
                proposal = await self.propose_patch(
                    draft.draft_id,
                    base_revision=int(intent.base_revision or draft.revision),
                    patch=intent.patch,  # validated by AgentIntent
                    proposed_by=envelope.caller_id,
                    _operation=operation,
                )
                read = await self.accept_patch(
                    proposal,
                    caller_id=envelope.caller_id,
                    operation_id=operation.operation_id,
                )
                # A data/semantic/SOP/graph patch must produce a new
                # ViewRevision in the same durable operation.  Presentation
                # only patches intentionally stop after the draft revision.
                if proposal.impact.requires_rerun:
                    return await self.request_execution(
                        proposal.draft_id,
                        caller_id=envelope.caller_id,
                        revision=proposal.new_revision,
                        _operation=read.operation,
                    )
                return read
            except SkillAuthoringError as error:
                return await self._finish_answer_failure(operation, error)
        if intent.action == "execute":
            if not envelope.current_skill_id:
                return await self._finish_answer_failure(
                    operation,
                    SkillAuthoringError(
                        AuthoringErrorCode.INVALID_CONTEXT,
                        "请先选择一个可执行的 Skill 草稿。",
                    ),
                )
            draft = await self.repository.get_draft(envelope.current_skill_id)
            if draft is None:
                return await self._finish_answer_failure(
                    operation,
                    SkillAuthoringError(
                        AuthoringErrorCode.NOT_FOUND,
                        "当前 Skill 草稿不存在或已不可用。",
                    ),
                )
            try:
                # Keep routing, authorization, fixed-lineage resolution, and
                # Worker 3 execution on the same durable operation. The
                # execution service re-resolves the draft lineage under the
                # authenticated caller before handing it to Worker 3.
                return await self.request_execution(
                    draft.draft_id,
                    caller_id=envelope.caller_id,
                    revision=draft.revision,
                    _operation=operation,
                )
            except SkillAuthoringError as error:
                return await self._finish_answer_failure(operation, error)
        if intent.action == "awaiting_input":
            operation = operation.model_copy(
                update={
                    "status": AuthoringStatus.AWAITING_INPUT,
                    "clarification_questions": intent.clarification_questions,
                    "stage": "clarification",
                    "progress": 100,
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "answer.final",
                {
                    "status": "awaiting_input",
                    "clarification_questions": list(intent.clarification_questions),
                },
                summary="Clarification required",
                terminal=False,
            )
            await self._event(
                operation,
                "operation.completed",
                {"status": operation.status.value},
                summary="Waiting for clarification",
                terminal=True,
            )
            return await self.read_operation(operation.operation_id)

        if intent.action == "create_skill":
            return await self.create_draft(
                envelope,
                # An explicit kind supplied by the caller is part of the
                # authenticated command context. The router may classify the
                # action, but it must not silently change the requested
                # renderer/contract kind.
                requested_kind=requested_kind or intent.requested_kind,
                scope=scope,
                display_name=display_name,
                _operation=operation,
                _context=context,
                _auto_execute=True,
            )
        return await self.answer(
            envelope,
            _operation=operation,
            _context=context,
        )

    async def answer(
        self,
        envelope: ContextEnvelope,
        *,
        _operation: AuthoringOperation | None = None,
        _context: ResolvedContext | None = None,
    ) -> AuthoringReadModel:
        """Persist an ordinary Agent answer as a resumable public timeline."""

        operation = _operation
        owns_task_registration = operation is None
        if operation is None:
            operation = AuthoringOperation(
                operation_id=f"op_{uuid4().hex}",
                operation_type="answer",
                status=AuthoringStatus.QUEUED,
                caller_id=envelope.caller_id,
                workspace_id=envelope.workspace_id,
                conversation_id=envelope.conversation_id,
                trace_id=f"trace_{uuid4().hex}",
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "message.accepted",
                {"request_id": envelope.request_id},
                summary="Message accepted",
            )
        assert operation is not None
        active_operation = operation
        current_task = asyncio.current_task()
        if owns_task_registration and current_task is not None:
            self._active_tasks[active_operation.operation_id] = current_task
        emitted_answer_delta = False

        async def persist_runtime_event(event: AgentRuntimeEvent) -> None:
            nonlocal emitted_answer_delta
            if event.type == "answer.delta":
                emitted_answer_delta = True
            await self._event(
                active_operation,
                event.type,
                dict(event.payload),
                summary=event.public_summary,
                session_id=event.session_id,
                trace_id=event.trace_id,
            )

        try:
            operation = operation.model_copy(
                update={
                    "status": AuthoringStatus.PLANNING,
                    "stage": "planning",
                    "progress": 10,
                }
            )
            await self.repository.save_operation(operation)
            context = _context
            if context is None:
                await self._event(
                    operation,
                    "context.resolving",
                    {"resource_count": len(envelope.resource_refs)},
                    summary="Resolving authorized context",
                )
                context = await self.resolver.resolve(envelope, envelope.resource_refs)
                operation = operation.model_copy(
                    update={
                        "context_digest": context.context_digest,
                        "stage": "context_resolved",
                        "progress": 30,
                    }
                )
                await self.repository.save_operation(operation)
                await self._event(
                    operation,
                    "context.resolved",
                    {
                        "context_digest": context.context_digest,
                        "resource_count": len(context.resources),
                    },
                    summary=(
                        f"Resolved {len(context.resources)} authorized context items"
                    ),
                )
            await self._event(
                operation,
                "agent.started",
                {"role": "answer"},
                summary="Answering request",
            )
            answer = await asyncio.wait_for(
                self.model_gateway.answer(
                    context,
                    event_sink=persist_runtime_event,
                ),
                timeout=envelope.budget.timeout_ms / 1000,
            )
            execution = self._execution_evidence(envelope.request_id)
            if execution is not None:
                operation = operation.model_copy(
                    update={
                        "agent_execution": execution,
                        "trace_id": (
                            execution.trace_id
                            if execution.trace_id != "unavailable"
                            else operation.trace_id
                        ),
                    }
                )
                await self.repository.save_operation(operation)
            if answer.status == "succeeded":
                if not emitted_answer_delta:
                    await self._event(
                        operation,
                        "answer.delta",
                        {"text": answer.text or ""},
                        summary="Answer received",
                    )
                terminal_payload: dict[str, object] = {
                    "status": answer.status,
                    "text": answer.text or "",
                    "citations": [
                        item.model_dump(mode="json") for item in answer.citations
                    ],
                }
                status = AuthoringStatus.SUCCEEDED
            else:
                terminal_payload = {
                    "status": answer.status,
                    "clarification_questions": list(answer.clarification_questions),
                }
                status = AuthoringStatus.AWAITING_INPUT
            operation = operation.model_copy(
                update={
                    "status": status,
                    "stage": (
                        "clarification"
                        if status == AuthoringStatus.AWAITING_INPUT
                        else "draft_ready"
                    ),
                    "progress": 100,
                    "clarification_questions": answer.clarification_questions,
                    "updated_at": utc_now(),
                }
            )
            await self.repository.save_operation(operation)
            await self._event(
                operation,
                "answer.final",
                terminal_payload,
                summary=(
                    "Clarification required"
                    if status == AuthoringStatus.AWAITING_INPUT
                    else "Answer ready"
                ),
                terminal=False,
            )
            await self._event(
                operation,
                "operation.completed",
                {"status": status.value},
                summary=(
                    "Waiting for clarification"
                    if status == AuthoringStatus.AWAITING_INPUT
                    else "Answer completed"
                ),
                terminal=True,
            )
            return AuthoringReadModel(
                operation=operation,
                answer=answer,
                events=await self.repository.list_events(operation.operation_id),
            )
        except asyncio.TimeoutError:
            failure = SkillAuthoringError(
                AuthoringErrorCode.MODEL_TIMEOUT, "VEADK Runner timed out"
            )
            return await self._finish_answer_failure(operation, failure)
        except asyncio.CancelledError:
            stored = await self.repository.get_operation(operation.operation_id)
            if stored is not None and stored.status == AuthoringStatus.CANCELLED:
                return await self.read_operation(operation.operation_id)
            raise
        except SkillAuthoringError as error:
            return await self._finish_answer_failure(operation, error)
        finally:
            if (
                owns_task_registration
                and self._active_tasks.get(operation.operation_id) is current_task
            ):
                self._active_tasks.pop(operation.operation_id, None)

    async def _finish_answer_failure(
        self,
        operation: AuthoringOperation,
        error: SkillAuthoringError,
    ) -> AuthoringReadModel:
        request = await self.repository.get_authoring_request(operation.operation_id)
        request_id = (
            request.envelope.request_id
            if isinstance(request, (AgentTurnRequest, CreateDraftRequest))
            else ""
        )
        execution = self._execution_evidence(request_id)
        status = (
            AuthoringStatus.CREDENTIAL_BLOCKED
            if error.code == AuthoringErrorCode.CREDENTIAL_BLOCKED
            else AuthoringStatus.FAILED
        )
        failed = operation.model_copy(
            update={
                "status": status,
                "stage": (
                    "credential_blocked"
                    if status == AuthoringStatus.CREDENTIAL_BLOCKED
                    else "failed"
                ),
                "progress": 100,
                "error_code": error.code,
                "error_message": error.message,
                "agent_execution": execution,
                "trace_id": (
                    execution.trace_id
                    if execution is not None and execution.trace_id != "unavailable"
                    else operation.trace_id
                ),
                "updated_at": utc_now(),
            }
        )
        await self.repository.save_operation(failed)
        await self._event(
            failed,
            "operation.failed",
            {"code": error.code.value, "message": error.message[:240]},
            summary=error.message[:500],
            terminal=True,
        )
        return AuthoringReadModel(
            operation=failed,
            events=await self.repository.list_events(failed.operation_id),
        )

    async def propose_patch(
        self,
        draft_id: str,
        *,
        base_revision: int,
        patch: TypedPatch,
        proposed_by: str,
        _operation: AuthoringOperation | None = None,
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
        if draft.owner_id != proposed_by:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "only the personal draft owner may propose a patch",
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
        preview = self._apply_patch(draft, patch)
        before = self._patch_snapshot(draft, patch)
        after = self._patch_snapshot(preview, patch)
        operation = _operation or await self._new_operation(
            operation_type="propose_patch",
            caller_id=proposed_by,
            draft_id=draft_id,
        )
        if _operation is not None:
            operation = operation.model_copy(
                update={"draft_id": draft_id, "updated_at": utc_now()}
            )
        proposal = PatchProposal(
            operation_id=operation.operation_id,
            draft_id=draft_id,
            base_revision=base_revision,
            patch=patch,
            impact=impact,
            proposed_by=proposed_by,
            before=before,
            after=after,
            base_digest=draft.digest,
            new_digest=preview.digest,
            new_revision=preview.revision,
        )
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.SUCCEEDED,
                "patch_id": proposal.patch_id,
                "stage": "patch_ready",
                "progress": 100,
                "current_revision": base_revision,
            }
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
                "before": before,
                "after": after,
                "base_digest": draft.digest,
                "new_digest": preview.digest,
                "new_revision": preview.revision,
                "steps": [
                    {
                        "id": "patch_proposal",
                        "label": impact.summary,
                        "status": "completed",
                    }
                ],
            },
            summary=impact.summary,
        )
        return proposal

    async def accept_patch(
        self,
        proposal: PatchProposal,
        *,
        caller_id: str,
        operation_id: str | None = None,
    ) -> AuthoringReadModel:
        operation = (
            await self.repository.get_operation(operation_id) if operation_id else None
        )
        if operation is None:
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
            if (
                current.owner_id != caller_id
                and current.promotion_state != "team_read_only"
            ):
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
                        "stage": "failed",
                        "progress": 100,
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
                    "stage": "draft_ready",
                    "progress": 100,
                }
            )
            await self.repository.save_operation(operation)
            # For routed turns, the proposal already lives in this operation.
            # Emit the acceptance transition once; the following explicit
            # artifact event is the only revision card payload.
            await self._event(
                operation,
                "patch_accepted",
                {
                    "step_id": "patch_proposal",
                    "draft_id": next_draft.draft_id,
                    "revision": str(next_draft.revision),
                    "requires_rerun": str(proposal.impact.requires_rerun).lower(),
                    "before": dict(proposal.before),
                    "after": dict(proposal.after),
                    "base_revision": proposal.base_revision,
                    "new_revision": next_draft.revision,
                    "base_digest": proposal.base_digest or current.digest,
                    "new_digest": next_draft.digest,
                },
                summary="Patch accepted",
            )
            await self._event(
                operation,
                "artifact.revision.created",
                {
                    "artifact_id": next_draft.draft_id,
                    "draft_id": next_draft.draft_id,
                    "revision": next_draft.revision,
                    "base_revision": proposal.base_revision,
                    "new_revision": next_draft.revision,
                    "base_digest": proposal.base_digest or current.digest,
                    "new_digest": next_draft.digest,
                    "view_revision_id": proposal.view_revision_id,
                    "label": f"{next_draft.manifest.name} revision {next_draft.revision}",
                },
                summary="Skill revision created",
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
        operation = operation.model_copy(
            update={
                "patch_id": proposal.patch_id,
                "stage": "patch_ready",
                "progress": 100,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "patch_rejected",
            {"patch_id": proposal.patch_id},
        )
        await self._save_patch_status(proposal, "rejected")
        operation = operation.model_copy(
            update={
                "status": AuthoringStatus.SUCCEEDED,
                "stage": "patch_ready",
                "progress": 100,
            }
        )
        await self.repository.save_operation(operation)
        return await self.read_operation(operation.operation_id)

    async def _save_patch_status(self, proposal: PatchProposal, status: str) -> None:
        await self.repository.save_patch(proposal.model_copy(update={"status": status}))

    async def repair_comment(self, request: CommentRepairRequest) -> PatchProposal:
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
            [await self.repair_comment(item) for item in request.requests]
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
                "stage": "draft_ready",
                "progress": 100,
                "plan": restored.plan,
            }
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "undo_applied",
            {
                "target_revision": str(target_revision),
                "revision": str(restored.revision),
            },
        )
        return await self.read_operation(operation.operation_id)

    async def request_execution(
        self,
        draft_id: str,
        *,
        caller_id: str,
        revision: int | None = None,
        _operation: AuthoringOperation | None = None,
    ) -> AuthoringReadModel:
        draft = await self.repository.get_draft(draft_id, revision)
        if draft is None:
            raise SkillAuthoringError(AuthoringErrorCode.NOT_FOUND, "draft not found")
        if draft.owner_id != caller_id and draft.promotion_state != "team_read_only":
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED, "caller cannot execute this draft"
            )
        resolved = await self.resolver.resolve(
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
        operation = _operation or await self._new_operation(
            operation_type="execute_draft",
            caller_id=caller_id,
            draft_id=draft_id,
        )
        if _operation is not None:
            operation = operation.model_copy(
                update={
                    "operation_type": "execute_draft",
                    "draft_id": draft_id,
                    "current_revision": draft.revision,
                    "updated_at": utc_now(),
                }
            )
        request = Worker3ExecutionRequest(
            operation_id=operation.operation_id,
            draft_id=draft.draft_id,
            draft_revision=draft.revision,
            skill_kind=draft.manifest.kind,
            workspace_id=draft.workspace_id,
            caller_id=caller_id,
            dependencies=draft.lineage,
            data_refs=draft.plan.data_refs or draft.lineage,
            metrics=draft.plan.metrics,
            dimensions=draft.plan.dimensions,
            layout_intent=draft.plan.layout_intent,
            lineage=draft.plan.lineage or draft.lineage,
            budget=draft.budget,
            freshness=draft.manifest.freshness,
            draft_manifest=draft.manifest,
            build_plan=draft.plan,
            trace_id=operation.trace_id,
            selected_template=draft.selected_template,
            resolved_resources=resolved.resources,
        )
        accepted = await self.worker3.request_execution(request)
        accepted_state = getattr(accepted, "state", None)
        accepted_reason = getattr(accepted, "reason", None)
        operation = operation.model_copy(
            update={
                "status": (
                    AuthoringStatus.SUCCEEDED
                    if accepted_state == "accepted"
                    else AuthoringStatus.READY_FOR_EXECUTION
                    if accepted_state == "queued"
                    else AuthoringStatus.FAILED
                    if accepted_state == "failed"
                    else AuthoringStatus.CREDENTIAL_BLOCKED
                    if accepted_state == "credential_blocked"
                    else AuthoringStatus.READY_FOR_EXECUTION
                ),
                "current_revision": draft.revision,
                "stage": (
                    "execution_succeeded"
                    if accepted_state == "accepted"
                    else "execution_queued"
                ),
                "progress": 100 if accepted_state == "accepted" else 85,
                # Worker 3 owns the full result objects.  AuthoringOperation
                # is also exposed by the BFF read model, so persist only
                # bounded public summaries here; the event feed must never
                # become a raw artifact/result transport.
                "artifact_result": self._public_result_summary(
                    getattr(accepted, "artifact_result", None)
                ),
                "execution_result": self._public_result_summary(
                    getattr(accepted, "execution_result", None)
                ),
                "error_code": (
                    AuthoringErrorCode.EXECUTION_BLOCKED
                    if accepted_state in {"credential_blocked", "failed"}
                    else None
                ),
                "error_message": (
                    str(accepted_reason)
                    if accepted_state in {"credential_blocked", "failed"}
                    and accepted_reason
                    else None
                ),
            }
        )
        accepted_view_revision = getattr(accepted, "view_revision", None)
        accepted_view_revision_id = getattr(accepted, "view_revision_id", None)
        if accepted_view_revision_id or accepted_view_revision:
            public_view_revision = self._public_view_revision_summary(
                accepted_view_revision,
                view_revision_id=accepted_view_revision_id,
            )
            await self._event(
                operation,
                "artifact.revision.created",
                {
                    "artifact_id": (
                        f"{draft.draft_id}:view:{accepted_view_revision_id}"
                        if accepted_view_revision_id
                        else draft.draft_id
                    ),
                    "draft_id": draft.draft_id,
                    "revision": draft.revision,
                    "view_revision_id": accepted_view_revision_id,
                    "view_revision_summary": public_view_revision,
                    "label": f"{draft.manifest.name} ViewRevision",
                },
                summary="ViewRevision created",
            )
        await self._emit_execution_answer(
            operation,
            draft=draft,
            view_revision_id=accepted_view_revision_id,
        )
        await self.repository.save_operation(operation)
        await self._event(
            operation,
            "execution_requested",
            {
                "draft_id": draft_id,
                "revision": str(draft.revision),
                "state": str(accepted_state),
                "reason": str(accepted_reason or ""),
            },
        )
        if accepted_state == "accepted":
            await self._event(
                operation,
                "operation.completed",
                {
                    "status": operation.status.value,
                    "draft_id": draft_id,
                    "revision": draft.revision,
                    "view_revision_id": accepted_view_revision_id,
                },
                summary="Execution and ViewRevision completed",
                terminal=True,
            )
        return await self.read_operation(operation.operation_id)

    async def _emit_execution_answer(
        self,
        operation: AuthoringOperation,
        *,
        draft: DraftRevision,
        view_revision_id: str | None,
    ) -> None:
        """Publish a safe, readable completion summary for authoring actions.

        Creation and execution turns return typed plans/artifacts rather than a
        free-form model answer.  The summary is derived only from the
        already-authorized draft, fixed lineage, and bounded Worker 3 result;
        it never copies model reasoning or raw tool output into the timeline.
        """

        revision = draft.revision
        source_summary = (
            f"{len(draft.lineage)} 个固定 revision 授权资源"
            if draft.lineage
            else "已授权上下文"
        )
        view_summary = (
            f"已生成 ViewRevision {view_revision_id}。"
            if view_revision_id
            else "ViewRevision 将由执行器继续提供。"
        )
        evidence = operation.agent_execution
        session_id = evidence.session_id if evidence is not None else None
        trace_id = (
            evidence.trace_id
            if evidence is not None and evidence.trace_id != "unavailable"
            else operation.trace_id
        )
        text = (
            f"已完成 Skill revision {revision}，来源摘要：{source_summary}。"
            f"{view_summary} sessionId: {session_id or 'unavailable'}；"
            f"traceId: {trace_id}。"
        )
        midpoint = max(1, len(text) // 2)
        for chunk in (text[:midpoint], text[midpoint:]):
            await self._event(
                operation,
                "answer.delta",
                {"text": chunk},
                summary="执行结果已更新",
                session_id=session_id,
                trace_id=trace_id,
            )
        await self._event(
            operation,
            "answer.final",
            {
                "status": "succeeded",
                "text": text,
                "citations": [],
            },
            summary="执行结果已准备",
            session_id=session_id,
            trace_id=trace_id,
        )

    async def submit_team_review(
        self, request: TeamReviewRequest
    ) -> AuthoringReadModel:
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
                "stage": "draft_ready",
                "progress": 100,
                "plan": reviewed.plan,
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
                "stage": "draft_ready",
                "progress": 100,
                "context_digest": resolved.context_digest,
                "plan": plan,
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

    async def cancel(self, operation_id: str, *, caller_id: str) -> AuthoringReadModel:
        operation = await self.repository.get_operation(operation_id)
        if operation is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND, "operation not found"
            )
        if operation.caller_id != caller_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "caller cannot cancel this operation",
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
                "stage": "cancelled",
                "progress": 100,
                "updated_at": utc_now(),
            }
        )
        active = self._active_tasks.get(operation_id)
        if active is not None and not active.done():
            active.cancel()
        await self.repository.save_operation(cancelled)
        await self._event(
            cancelled,
            "operation.cancelled",
            {"reason": "caller_requested"},
            summary="Operation cancelled by caller",
            terminal=True,
        )
        # Cancellation is not complete merely because the task was marked
        # cancelled: VEADK closes its Runner in the gateway's finally block.
        # Wait for that cleanup before returning, so a subsequent retry cannot
        # overlap the previous Runner's tool/model work.
        cleanup_done = active is None or active.done()
        if active is not None and active is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(active), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                # The durable cancellation event above remains authoritative
                # if an upstream model refuses cancellation promptly.
                pass
            cleanup_done = active.done()
        if cleanup_done:
            await self._release_generation(operation)
        return await self.read_operation(operation_id)

    async def retry(self, operation_id: str, *, caller_id: str) -> AuthoringReadModel:
        operation = await self.repository.get_operation(operation_id)
        if operation is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND, "operation not found"
            )
        if operation.caller_id != caller_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "caller cannot retry this operation",
            )
        active = self._active_tasks.get(operation_id)
        if active is not None and not active.done():
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "上一轮仍在停止，请稍后再重试。",
                operation_id=operation_id,
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
        request = await self.repository.get_authoring_request(operation_id)
        if isinstance(request, AgentTurnRequest):
            replacement = AuthoringOperation(
                operation_id=f"op_{uuid4().hex}",
                operation_type="answer",
                status=AuthoringStatus.QUEUED,
                caller_id=operation.caller_id,
                workspace_id=operation.workspace_id,
                conversation_id=request.envelope.conversation_id,
                trace_id=f"trace_{uuid4().hex}",
                retry_of_operation_id=operation_id,
            )
            replacement, claimed = await self._claim_generation(
                request.envelope,
                replacement,
                idempotency_key=None,
            )
            if not claimed:
                return await self.read_operation(replacement.operation_id)
            await self.repository.save_authoring_request(
                replacement.operation_id, request
            )
            await self._event(
                replacement,
                "message.accepted",
                {
                    "request_id": request.envelope.request_id,
                    "retry_of_operation_id": operation_id,
                },
                summary="Retry accepted",
            )
            task = asyncio.create_task(
                self._run_turn(
                    replacement,
                    request.envelope,
                    requested_kind=request.requested_kind,
                    scope=request.scope,
                    display_name=request.display_name,
                )
            )
            self._active_tasks[replacement.operation_id] = task
            task.add_done_callback(
                lambda completed: self._on_generation_done(completed, replacement)
            )
            return await self.read_operation(replacement.operation_id)
        if operation.operation_type != "create_draft":
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "the durable authoring request is not retryable",
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
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND, "team draft not found"
            )
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
                "stage": "draft_ready",
                "progress": 100,
                "plan": copied.plan,
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
            raise SkillAuthoringError(
                AuthoringErrorCode.NOT_FOUND, "operation not found"
            )
        draft_id = operation.draft_id
        draft = await self.repository.get_draft(draft_id) if draft_id else None
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

    async def _is_cancelled(self, operation_id: str) -> bool:
        operation = await self.repository.get_operation(operation_id)
        return operation is not None and operation.status == AuthoringStatus.CANCELLED

    @staticmethod
    def _validate_plan(
        context: ResolvedContext,
        plan: BuildPlan,
        *,
        requested_kind: SkillKind | None,
    ) -> BuildPlan:
        """Validate model output against server-resolved context and contracts."""
        if requested_kind is not None and plan.intent != requested_kind:
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "model plan intent does not match the requested kind",
            )
        authorized = {
            (item.ref.scope, item.ref.kind, item.ref.object_id, item.ref.revision)
            for item in context.resources
        }
        dependencies = tuple(dict.fromkeys(plan.dependencies))
        plan_data_refs = tuple(dict.fromkeys(plan.data_refs or dependencies))
        plan_lineage = tuple(dict.fromkeys(plan.lineage or plan_data_refs))
        if any(
            (item.scope, item.kind, item.object_id, item.revision) not in authorized
            for item in dependencies
        ):
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "model plan contains an unauthorized resource dependency",
            )
        if any(
            (item.scope, item.kind, item.object_id, item.revision) not in authorized
            for item in (*plan_data_refs, *plan_lineage)
        ):
            raise SkillAuthoringError(
                AuthoringErrorCode.PERMISSION_DENIED,
                "model plan contains an unauthorized data reference or lineage",
            )
        if plan.intent == SkillKind.ANALYSIS and any(
            item.ref.kind not in {"golden_asset", "data_access_skill"}
            for item in context.resources
        ):
            raise SkillAuthoringError(
                AuthoringErrorCode.INVALID_CONTEXT,
                "analysis requires a GoldenAssetRevision or authorized data_access Skill",
            )
        pinned = set(context.envelope.fixed_revisions)
        if plan.query_plan is not None:
            if plan.query_plan.source_revision not in pinned:
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    "query plan source is not fixed in the Context Envelope",
                )
            available_fields = {
                field for item in context.resources for field in item.semantic_fields
            }
            if available_fields and not set(plan.query_plan.selected_fields).issubset(
                available_fields
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "query plan selects a field absent from the authorized schema",
                )
        node_ids = [node.node_id for node in plan.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "BuildPlan contains duplicate node IDs",
            )
        node_set = set(node_ids)
        if any(dep not in node_set for node in plan.nodes for dep in node.depends_on):
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "BuildPlan contains an unknown node dependency",
            )
        if not any(node.role == "worker3_execution" for node in plan.nodes):
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "BuildPlan must terminate at the Worker 3 execution boundary",
            )
        canonical = plan.model_copy(
            update={
                "dependencies": dependencies,
                "data_refs": plan_data_refs,
                "lineage": plan_lineage,
                "plan_digest": digest(
                    plan.model_dump(exclude={"plan_digest"}, mode="json")
                ),
            }
        )
        return canonical

    @staticmethod
    def _public_view_revision_summary(
        value: object,
        *,
        view_revision_id: str | None,
    ) -> dict[str, object]:
        """Expose only bounded ViewRevision metadata in the public timeline.

        Worker 3 owns the full typed view and artifact references.  The event
        feed only needs enough information for the UI to confirm that a
        revision was created; raw view models, result rows, local paths, and
        renderer payloads must not become durable public event data.
        """

        if not isinstance(value, dict):
            return {
                "view_revision_id": view_revision_id,
                "available": bool(view_revision_id),
            }
        intent = value.get("intent")
        manifest = value.get("manifest")
        view_model = value.get("viewModel") or value.get("view_model")
        summary: dict[str, object] = {
            "view_revision_id": view_revision_id or value.get("id"),
            "revision": value.get("revision"),
            "skill_revision_id": value.get("skillRevisionId")
            or value.get("skill_revision_id"),
        }
        if isinstance(intent, dict):
            template = intent.get("template")
            purpose = intent.get("purpose")
            if isinstance(template, str):
                summary["template"] = template[:80]
            if isinstance(purpose, str):
                summary["purpose"] = purpose[:240]
        if isinstance(manifest, dict):
            renderer = manifest.get("rendererRef") or manifest.get("renderer_ref")
            if isinstance(renderer, str):
                summary["renderer_ref"] = renderer[:160]
        if isinstance(view_model, dict):
            template = view_model.get("template")
            title = view_model.get("title")
            if isinstance(template, str):
                summary["view_model_template"] = template[:80]
            if isinstance(title, str):
                summary["view_model_title"] = title[:240]
        return {key: item for key, item in summary.items() if item is not None}

    @staticmethod
    def _public_result_summary(value: object) -> dict[str, object] | None:
        """Keep operation read models useful without exposing raw Worker data."""

        if not isinstance(value, dict):
            return None
        allowed = {
            "id",
            "artifactId",
            "artifact_id",
            "operationId",
            "operation_id",
            "status",
            "state",
            "kind",
            "handler",
            "message",
            "traceId",
            "trace_id",
            "skillId",
            "skill_id",
            "skillRevision",
            "skill_revision",
            "revisionId",
            "revision_id",
            "viewRevisionId",
            "view_revision_id",
            "template",
            "mediaType",
            "media_type",
            "bytes",
            "sha256",
        }
        result: dict[str, object] = {}
        for key in allowed:
            item = value.get(key)
            if item is None:
                continue
            if isinstance(item, (str, int, float, bool)):
                result[key] = str(item)[:500] if isinstance(item, str) else item
        return result or {"available": True}

    async def _new_operation(
        self,
        *,
        operation_type: str,
        caller_id: str,
        draft_id: str | None,
        operation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthoringOperation:
        draft = await self.repository.get_draft(draft_id) if draft_id else None
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
        self,
        operation: AuthoringOperation,
        event_type: str,
        data: dict[str, object],
        *,
        summary: str = "",
        terminal: bool | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        existing = await self.repository.list_events(operation.operation_id)
        execution = operation.agent_execution
        await self.repository.save_event(
            AuthoringEvent(
                operation_id=operation.operation_id,
                event_type=event_type,  # type: ignore[arg-type]
                sequence=len(existing) + 1,
                data=data,
                payload=data,
                session_id=(
                    session_id
                    if session_id is not None
                    else execution.session_id
                    if execution is not None
                    else None
                ),
                trace_id=trace_id or operation.trace_id,
                public_summary=summary,
                terminal=(
                    terminal
                    if terminal is not None
                    else event_type
                    in {
                        "operation.completed",
                        "operation.failed",
                        "operation.cancelled",
                    }
                ),
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
            selected_template=envelope.selected_template,
        )

    @staticmethod
    def _impact(patch: TypedPatch) -> PatchImpact:
        if isinstance(patch, (SetTitlePatch, SetDescriptionPatch)):
            return PatchImpact(
                summary="更新 Skill 草稿展示文本",
                affected_paths=(
                    "manifest.name"
                    if isinstance(patch, SetTitlePatch)
                    else "manifest.description",
                ),
                requires_rerun=False,
                reason="presentation_only",
            )
        if isinstance(patch, SetDashboardKpiPatch):
            return PatchImpact(
                summary="更新 Dashboard KPI，需要重新生成 ViewRevision",
                affected_paths=("dashboard_config.kpis",),
                requires_rerun=True,
                reason="metric_changed",
            )
        if isinstance(patch, SetDashboardChartPatch):
            return PatchImpact(
                summary="更新 Dashboard 图表，需要重新生成 ViewRevision",
                affected_paths=("dashboard_config.chart",),
                requires_rerun=True,
                reason="presentation_only",
            )
        if isinstance(patch, SetDashboardFilterPatch):
            return PatchImpact(
                summary="更新 Dashboard 筛选条件，需要重新查询",
                affected_paths=("dashboard_config.filters",),
                requires_rerun=True,
                reason="query_changed",
            )
        if isinstance(
            patch, (SetSopStepPatch, SetSopConditionPatch, SetSopToolRefPatch)
        ):
            path = (
                "sop_steps"
                if isinstance(patch, SetSopStepPatch)
                else "sop_steps.condition"
                if isinstance(patch, SetSopConditionPatch)
                else "sop_steps.tool_ref"
            )
            return PatchImpact(
                summary="更新 SOP 步骤，需要重新执行",
                affected_paths=(path,),
                requires_rerun=True,
                reason="query_changed",
            )
        if isinstance(
            patch,
            (
                SetSemanticMetricPatch,
                SetSemanticDimensionPatch,
                SetSemanticRelationshipPatch,
            ),
        ):
            return PatchImpact(
                summary="更新 Semantic 定义，需要重新编译",
                affected_paths=("kind_spec",),
                requires_rerun=True,
                reason="mapping_changed",
            )
        if isinstance(patch, (SetGraphEntityPatch, SetGraphRelationPatch)):
            return PatchImpact(
                summary="更新图谱映射，需要重新编译",
                affected_paths=("graph_config",),
                requires_rerun=True,
                reason="mapping_changed",
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
            if any(
                permission not in {"read", "profile", "query"}
                for permission in patch.permissions
            ):
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
    def _patch_snapshot(draft: DraftRevision, patch: TypedPatch) -> dict[str, object]:
        """Return a small, public before/after view; never expose whole drafts."""
        if isinstance(patch, SetDashboardKpiPatch):
            return {"kpis": draft.dashboard_config.get("kpis", [])}
        if isinstance(patch, (SetDashboardChartPatch, SetDashboardFilterPatch)):
            return {
                "chart": draft.dashboard_config.get("chart", {}),
                "filters": draft.dashboard_config.get("filters", {}),
            }
        if isinstance(
            patch, (SetSopStepPatch, SetSopConditionPatch, SetSopToolRefPatch)
        ):
            return {"steps": list(draft.sop_steps)}
        if isinstance(patch, (SetGraphEntityPatch, SetGraphRelationPatch)):
            return {"graph": dict(draft.graph_config)}
        if isinstance(
            patch,
            (
                SetSemanticMetricPatch,
                SetSemanticDimensionPatch,
                SetSemanticRelationshipPatch,
            ),
        ):
            return {"semantic": draft.plan.kind_spec.model_dump(mode="json")}
        return {
            "manifest": {
                "name": draft.manifest.name,
                "description": draft.manifest.description,
            },
            "digest": draft.digest,
        }

    @staticmethod
    def _apply_patch(draft: DraftRevision, patch: TypedPatch) -> DraftRevision:
        manifest = draft.manifest
        kind_spec = manifest.kind_spec
        plan = draft.plan
        dashboard_config = dict(draft.dashboard_config)
        sop_steps = [dict(item) for item in draft.sop_steps]
        graph_config = dict(draft.graph_config)
        if isinstance(patch, SetTitlePatch):
            manifest = manifest.model_copy(update={"name": patch.title})
        elif isinstance(patch, SetDashboardKpiPatch):
            kpis = [
                dict(item)
                for item in dashboard_config.get("kpis", [])
                if isinstance(item, dict)
            ]
            next_kpi = {
                "key": patch.key,
                "label": patch.label or patch.key,
                "value": patch.value,
                "unit": patch.unit,
            }
            dashboard_config["kpis"] = [
                next_kpi if item.get("key") == patch.key else item for item in kpis
            ]
            if not any(item.get("key") == patch.key for item in kpis):
                dashboard_config["kpis"].append(next_kpi)
        elif isinstance(patch, SetDashboardChartPatch):
            dashboard_config["chart"] = {
                "x_field": patch.x_field,
                "y_field": patch.y_field,
                "chart_type": patch.chart_type,
            }
        elif isinstance(patch, SetDashboardFilterPatch):
            filters = dict(dashboard_config.get("filters", {}))
            filters[patch.field] = patch.value
            dashboard_config["filters"] = filters
        elif isinstance(patch, SetSopStepPatch):
            next_step = {
                "step_id": patch.step_id,
                "label": patch.label,
                "condition": patch.condition,
                "tool_ref": patch.tool_ref,
            }
            sop_steps = [
                next_step if item.get("step_id") == patch.step_id else item
                for item in sop_steps
            ]
            if not any(
                item.get("step_id") == patch.step_id for item in draft.sop_steps
            ):
                sop_steps.append(next_step)
        elif isinstance(patch, SetSopConditionPatch):
            found = False
            for item in sop_steps:
                if item.get("step_id") == patch.step_id:
                    item["condition"] = patch.condition
                    found = True
            if not found:
                sop_steps.append(
                    {"step_id": patch.step_id, "condition": patch.condition}
                )
        elif isinstance(patch, SetSopToolRefPatch):
            found = False
            for item in sop_steps:
                if item.get("step_id") == patch.step_id:
                    item["tool_ref"] = patch.tool_ref
                    found = True
            if not found:
                sop_steps.append({"step_id": patch.step_id, "tool_ref": patch.tool_ref})
        elif isinstance(patch, SetGraphEntityPatch):
            entities = dict(graph_config.get("entities", {}))
            entities[patch.entity_type] = patch.label
            graph_config["entities"] = entities
        elif isinstance(patch, SetGraphRelationPatch):
            relations = [
                item
                for item in graph_config.get("relations", [])
                if isinstance(item, dict)
                and not (
                    item.get("source_type") == patch.source_type
                    and item.get("target_type") == patch.target_type
                )
            ]
            relations.append(
                {
                    "relation": patch.relation,
                    "source_type": patch.source_type,
                    "target_type": patch.target_type,
                }
            )
            graph_config["relations"] = relations
        elif isinstance(patch, SetSemanticMetricPatch):
            if draft.manifest.kind != SkillKind.SEMANTIC or not isinstance(
                kind_spec, SemanticKindSpec
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "semantic metric patches apply only to semantic skills",
                )
            kind_spec = kind_spec.model_copy(
                update={"measures": (*kind_spec.measures, patch.metric)}
            )
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
        elif isinstance(patch, SetSemanticDimensionPatch):
            if draft.manifest.kind != SkillKind.SEMANTIC or not isinstance(
                kind_spec, SemanticKindSpec
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "semantic dimension patches apply only to semantic skills",
                )
            kind_spec = kind_spec.model_copy(
                update={"dimensions": (*kind_spec.dimensions, patch.dimension)}
            )
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
        elif isinstance(patch, SetSemanticRelationshipPatch):
            if draft.manifest.kind != SkillKind.SEMANTIC or not isinstance(
                kind_spec, SemanticKindSpec
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "semantic relationship patches apply only to semantic skills",
                )
            kind_spec = kind_spec.model_copy(
                update={
                    "relationships": (
                        *kind_spec.relationships,
                        f"{patch.source_entity}->{patch.relationship}->{patch.target_entity}",
                    )
                }
            )
            plan = draft.plan.model_copy(update={"kind_spec": kind_spec})
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
            if not isinstance(kind_spec, KnowledgeKindSpec):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "knowledge draft has an invalid kind spec",
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
            if not isinstance(kind_spec, GraphOntologyKindSpec):
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "graph ontology draft has an invalid kind spec",
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
        plan = plan.model_copy(update={"kind_spec": kind_spec})
        revision = draft.revision + 1
        return draft.model_copy(
            update={
                "revision": revision,
                "parent_revision": draft.revision,
                "manifest": manifest.model_copy(update={"kind_spec": kind_spec}),
                "plan": plan,
                "dashboard_config": dashboard_config,
                "sop_steps": tuple(sop_steps),
                "graph_config": graph_config,
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
