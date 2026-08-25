"""Application use cases behind the Studio BFF."""

from __future__ import annotations

import asyncio
import hashlib
import csv
import html
import io
import json
import os
import sqlite3
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from .contracts import (
    CommandResponse,
    CommandResult,
    DraftCommandResult,
    ErrorEnvelope,
    EvaluationPayload,
    EvaluationRunResult,
    ArtifactExportPayload,
    ArtifactExportResult,
    ResourceShareResult,
    LegacySkillManifestInput,
    InvocationStartPayload,
    InvocationStartResult,
    AssistantDiff,
    AssistantTurnPayload,
    AssistantTurnResult,
    OperationEvent,
    OperationResponse,
    PublicationPublishPayload,
    PublicationPublishResult,
    RefreshRunPayload,
    RefreshRunResult,
    RefreshRun,
    SkillDraft,
    SkillDraftRunPayload,
    SkillDraftRetryPayload,
    SkillDraftRunResult,
    SkillManifest,
    SourceCleanPayload,
    SourceCleanResult,
    SourceProfilePayload,
    SourceProfileResult,
    SourceRevision,
    NotReadyCommandResult,
    ProfileRun,
    CleaningRecipe,
    CleanRun,
    GoldenAssetRevision,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    StorageRef,
    KnowledgeViewModel,
    KnowledgeCitation,
    SemanticViewModel,
    DashboardViewModel,
    ChartViewModel,
    ChartSeries,
    GraphOntologyViewModel,
    GraphNode,
    GraphEdge,
    MonitoringViewModel,
    SkillResult,
    SkillViewManifest,
    SkillViewRevision,
    SkillViewShareGrant,
    PublishedSkillVersion,
    ViewIntent,
    Invocation,
    EvaluationSuite,
    EvaluationCase,
    EvaluationRun,
    EvaluationCaseResult,
    PolicyGateResult,
    EvaluationQualityCommandResult,
    SourceGoldenConnectionCreatePayload,
    SourceGoldenIngestPayload,
    SourceGoldenConnectionResult,
    ConnectionViewModel,
    SourceGoldenIngestResult,
    EvaluationSuiteCreatePayload,
    EvaluationSuiteRevisePayload,
    EvaluationCaseImportPayload,
    EvaluationCaseAdoptHistoryPayload,
    EvaluationCaseGenerateCandidatePayload,
    EvaluationCaseConfirmPayload,
    EvaluationRunStartPayload,
    EvaluationRunActionPayload,
    EvaluationRunRetryPayload,
    EvaluationFixProposePayload,
    EvaluationFixProposeAllPayload,
    EvaluationFixActionPayload,
    PolicyGateEvaluatePayload,
    BootstrapConnection,
    adapt_legacy_manifest,
    now_iso,
)
from .policies import validate_manifest_policy
from .ports import AuditRecorderPort
from .workers import JobFramework, JobLeaseError, PostgresJobFramework
from .kind_runtime import (
    ContentAddressedStore,
    ExecutionBudget,
    KindExecutionRequest,
    KindRuntime,
)
from .kind_runtime.adapters import LocalGoldenAssetContentAdapter
from .contract_data import SkillDraftRevision
from .postgres_repository import PostgresKnowledgeAssetRepository
from .repository import (
    KnowledgeAssetRepositoryError,
    KnowledgeAssetRepository,
)
from .sources_golden import AccessContext, SourceGoldenApplication, SourcesGoldenError
from .evaluation_quality import EvaluationQualityService
from .evaluation_quality.main_repository import MainEvaluationRepository
from .evaluation_quality.models import (
    CaseCategory,
    CaseSource,
)
from frontend.server.skill_authoring.models import (
    AuthoringErrorCode,
    AuthoringReadModel,
    Budget,
    ContextEnvelope,
    FreshnessPolicy,
    ResourceRef as AuthoringResourceRef,
    Scope as AuthoringScope,
    SkillAuthoringError,
    SkillKind as AuthoringSkillKind,
    ResolvedContext,
    ResolvedResource,
    digest as authoring_digest,
)
from frontend.server.skill_authoring.ports import (
    CredentialBlockedGateway,
    NoopWorker3Executor,
)
from .authoring_repository import (
    PostgresAuthoringRepository,
    SqliteAuthoringRepository,
)


class _ImmutableResourceResolver:
    """Resolve exact, authorized revisions from server-owned stores."""

    def __init__(
        self,
        source_golden: SourceGoldenApplication,
        repository: KnowledgeAssetRepository,
        domain_resolver: object | None = None,
        authoring_repository: object | None = None,
    ) -> None:
        self.source_golden = source_golden
        self.repository = repository
        self.domain_resolver = domain_resolver
        self.authoring_repository = authoring_repository

    async def resolve(self, envelope, refs):
        context = AccessContext(
            workspace_id=envelope.workspace_id,
            principal_id=envelope.caller_id,
            role="editor",
        )
        resources: list[ResolvedResource] = []
        for ref in refs:
            if (
                envelope.freshness.require_fixed_revision
                and ref.revision not in envelope.fixed_revisions
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    f"resource {ref.object_id} is not pinned to a fixed revision",
                )
            if ref.revision.casefold() in {"latest", "current", "head", "draft"}:
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    "mutable revision aliases are forbidden",
                )
            if ref.kind == "golden_asset" or ref.kind == "knowledge_asset":
                binding = self.source_golden.golden_resource_binding(
                    context, ref.revision
                )
                if binding.object_id != ref.object_id:
                    raise SkillAuthoringError(
                        AuthoringErrorCode.INVALID_CONTEXT,
                        f"resource {ref.object_id}@{ref.revision} does not match the pinned Golden Asset",
                    )
                resources.append(
                    ResolvedResource(
                        ref=ref,
                        display_name=binding.display_name,
                        provider_revision=binding.provider_revision,
                        schema_digest=binding.schema_digest,
                        capabilities=tuple(binding.capabilities),
                        semantic_fields=tuple(binding.semantic_fields),
                        authorized=binding.authorized,
                    )
                )
                continue
            if ref.kind == "document":
                domain_resolve = getattr(
                    self.domain_resolver, "resolve_authoring_resource", None
                )
                if callable(domain_resolve):
                    try:
                        value = domain_resolve(
                            workspace_id=envelope.workspace_id,
                            caller_id=envelope.caller_id,
                            ref=ref,
                        )
                        if hasattr(value, "__await__"):
                            value = await value
                        resources.append(ResolvedResource.model_validate(value))
                        continue
                    except KeyError:
                        pass
                    except PermissionError as error:
                        raise SkillAuthoringError(
                            AuthoringErrorCode.PERMISSION_DENIED,
                            "Document revision is not authorized.",
                        ) from error
                source = self.source_golden.source_revision(context, ref.revision)
                if source.resource_id != ref.object_id:
                    raise SkillAuthoringError(
                        AuthoringErrorCode.INVALID_CONTEXT,
                        "Document object and revision do not match.",
                    )
                resources.append(
                    ResolvedResource(
                        ref=ref,
                        display_name=source.source_locator,
                        provider_revision=source.id,
                        schema_digest=source.schema_digest,
                        capabilities=("source.read", "lineage.read"),
                        authorized=True,
                    )
                )
                continue
            if ref.kind in {"skill", "data_access_skill"}:
                revision_number = self._skill_revision_number(ref)
                draft = self.repository.draft(ref.object_id)
                revision = self.repository.skill_draft_revision(
                    ref.object_id, revision_number
                )
                if (
                    draft is None
                    or draft.workspace_id != envelope.workspace_id
                    or revision is None
                    or revision.id != ref.revision
                ):
                    raise SkillAuthoringError(
                        AuthoringErrorCode.RESOURCE_NOT_FOUND,
                        "Skill revision does not exist in the authenticated workspace.",
                    )
                manifest = revision.manifest
                schema_digest = hashlib.sha256(
                    manifest.model_dump_json(by_alias=True).encode("utf-8")
                ).hexdigest()
                resources.append(
                    ResolvedResource(
                        ref=ref,
                        display_name=manifest.metadata.display_name,
                        provider_revision=revision.id,
                        schema_digest=schema_digest,
                        capabilities=("skill.read",),
                        authorized=True,
                    )
                )
                continue
            if ref.kind == "artifact":
                view = self.repository.skill_view_revision(ref.revision)
                if (
                    view is None
                    or view.id != ref.object_id
                    or not self._view_in_workspace(view, envelope.workspace_id)
                ):
                    raise SkillAuthoringError(
                        AuthoringErrorCode.RESOURCE_NOT_FOUND,
                        "Artifact revision does not exist in the authenticated workspace.",
                    )
                resources.append(
                    ResolvedResource(
                        ref=ref,
                        display_name=view.intent.template,
                        provider_revision=view.id,
                        schema_digest=(
                            view.result_ref.sha256
                            if view.result_ref is not None
                            else view.manifest.view_model_schema_ref.sha256
                        ),
                        capabilities=("artifact.read",),
                        authorized=True,
                    )
                )
                continue
            resolve = getattr(self.domain_resolver, "resolve_authoring_resource", None)
            if ref.kind in {"knowledge", "semantic", "graph"} and callable(resolve):
                try:
                    value = resolve(
                        workspace_id=envelope.workspace_id,
                        caller_id=envelope.caller_id,
                        ref=ref,
                    )
                    if hasattr(value, "__await__"):
                        value = await value
                    resources.append(ResolvedResource.model_validate(value))
                    continue
                except KeyError as error:
                    raise SkillAuthoringError(
                        AuthoringErrorCode.RESOURCE_NOT_FOUND,
                        f"{ref.kind.title()} revision does not exist.",
                    ) from error
                except PermissionError as error:
                    raise SkillAuthoringError(
                        AuthoringErrorCode.PERMISSION_DENIED,
                        f"{ref.kind.title()} revision is not authorized.",
                    ) from error
            raise SkillAuthoringError(
                AuthoringErrorCode.RESOURCE_NOT_FOUND,
                f"unsupported immutable resource kind: {ref.kind}",
            )
        await self._validate_bindings(envelope)
        authorized_permissions = tuple(
            sorted(
                {
                    capability
                    for resource in resources
                    for capability in resource.capabilities
                }
            )
        )
        return ResolvedContext(
            envelope=envelope,
            resources=tuple(resources),
            authorized_permissions=authorized_permissions,
            context_digest=authoring_digest(
                {
                    "caller": envelope.caller_id,
                    "workspace": envelope.workspace_id,
                    "prompt": envelope.prompt,
                    "refs": [item.model_dump(mode="json") for item in resources],
                    "permissions": authorized_permissions,
                    "fixed_revisions": envelope.fixed_revisions,
                    "current_skill_id": envelope.current_skill_id,
                    "current_view_id": envelope.current_view_id,
                    "current_component_id": envelope.current_component_id,
                    "comment_ids": envelope.comment_ids,
                }
            ),
        )

    @staticmethod
    def _skill_revision_number(ref: AuthoringResourceRef) -> int:
        prefix = f"{ref.object_id}:"
        if not ref.revision.startswith(prefix):
            raise SkillAuthoringError(
                AuthoringErrorCode.INVALID_CONTEXT,
                "Skill revision must be the exact immutable draft revision ID.",
            )
        try:
            revision = int(ref.revision.removeprefix(prefix))
        except ValueError as error:
            raise SkillAuthoringError(
                AuthoringErrorCode.INVALID_CONTEXT,
                "Skill revision ID is invalid.",
            ) from error
        if revision < 1:
            raise SkillAuthoringError(
                AuthoringErrorCode.INVALID_CONTEXT, "Skill revision ID is invalid."
            )
        return revision

    def _view_in_workspace(self, view: SkillViewRevision, workspace_id: str) -> bool:
        skill_id = view.skill_revision_id.rsplit(":", 1)[0]
        draft = self.repository.draft(skill_id)
        return draft is not None and draft.workspace_id == workspace_id

    async def _validate_bindings(self, envelope: ContextEnvelope) -> None:
        if envelope.current_skill_id:
            draft = self.repository.draft(envelope.current_skill_id)
            if draft is None and self.authoring_repository is not None:
                draft = await self.authoring_repository.get_draft(
                    envelope.current_skill_id
                )
                authorized = (
                    draft is not None
                    and draft.workspace_id == envelope.workspace_id
                    and (
                        draft.owner_id == envelope.caller_id
                        or draft.promotion_state == "team_read_only"
                    )
                )
            else:
                authorized = (
                    draft is not None and draft.workspace_id == envelope.workspace_id
                )
            if not authorized:
                raise SkillAuthoringError(
                    AuthoringErrorCode.PERMISSION_DENIED,
                    "current Skill binding is not authorized.",
                )
        if envelope.current_view_id:
            view = self.repository.skill_view_revision(envelope.current_view_id)
            if view is None or not self._view_in_workspace(view, envelope.workspace_id):
                raise SkillAuthoringError(
                    AuthoringErrorCode.PERMISSION_DENIED,
                    "current ViewRevision binding is not authorized.",
                )
            if envelope.current_skill_id and not view.skill_revision_id.startswith(
                f"{envelope.current_skill_id}:"
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    "current Skill and ViewRevision bindings do not match.",
                )
        if (
            envelope.current_component_id or envelope.comment_ids
        ) and not envelope.current_view_id:
            raise SkillAuthoringError(
                AuthoringErrorCode.INVALID_CONTEXT,
                "component and comment bindings require an authorized ViewRevision.",
            )


class _W1NotConfiguredResolver:
    async def resolve(self, envelope, refs):
        del envelope, refs
        raise SkillAuthoringError(
            AuthoringErrorCode.CREDENTIAL_BLOCKED,
            "W1 Source/Golden Data resolver and MCP lifecycle are not configured",
        )


class _UnavailableEvaluationExecutor:
    def evaluate(self, case, provenance):
        raise RuntimeError(
            "EVALUATION_EXECUTOR_NOT_CONFIGURED: a real evaluator port is required"
        )


class _UnavailableEvaluationGrader:
    def grade(self, case, actual):
        raise RuntimeError(
            "EVALUATION_GRADER_NOT_CONFIGURED: a real grader port is required"
        )


class KnowledgeAssetApplication:
    def __init__(
        self,
        repository: KnowledgeAssetRepository,
        *,
        audit_recorder: AuditRecorderPort | None = None,
        authoring_resolver: object | None = None,
        authoring_model_gateway: object | None = None,
        authoring_worker3: object | None = None,
        sources_golden: SourceGoldenApplication | None = None,
        domain_resolver: object | None = None,
        artifact_roots: tuple[str | Path, ...] = (),
        public_api_prefix: str = "/api/knowledge-assets/v1",
    ) -> None:
        self.repository = repository
        self.audit_recorder = audit_recorder or repository
        self._builder_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="knowledge-builder"
        )
        self._execution_checkpoint = lambda: None
        repository_connection = getattr(repository, "_connection", None)
        sqlite_connection = (
            repository_connection
            if isinstance(repository_connection, sqlite3.Connection)
            else None
        )
        if sqlite_connection is not None:
            self._builder_jobs = JobFramework(
                connection=sqlite_connection,
                lock=getattr(repository, "_lock", None),
            )
        elif isinstance(repository, PostgresKnowledgeAssetRepository):
            self._builder_jobs = PostgresJobFramework(
                connection=repository_connection,
                lock=getattr(repository, "_lock", None),
            )
        else:
            self._builder_jobs = JobFramework()
        self._builder_profile = (
            "production"
            if isinstance(repository, PostgresKnowledgeAssetRepository)
            else "test"
        )
        self._builder_job_ids: dict[str, str] = {}
        self._sources_golden = sources_golden
        self._artifact_roots = tuple(Path(root).resolve() for root in artifact_roots)
        self._public_api_prefix = public_api_prefix.rstrip("/")
        self._kind_runtime = KindRuntime(
            ContentAddressedStore(".veadk/knowledge-assets/kind-runtime")
        )
        self._golden_content = LocalGoldenAssetContentAdapter(
            ".veadk/knowledge-assets/artifacts"
        )
        self._evaluation_quality = None
        if sqlite_connection is not None or isinstance(
            repository, PostgresKnowledgeAssetRepository
        ):
            self._evaluation_quality = EvaluationQualityService(
                MainEvaluationRepository(
                    sqlite_connection
                    if sqlite_connection is not None
                    else repository_connection
                ),
                _UnavailableEvaluationExecutor(),
                _UnavailableEvaluationGrader(),
            )
        self._authoring = None
        if sqlite_connection is not None or isinstance(
            repository, PostgresKnowledgeAssetRepository
        ):
            from frontend.server.skill_authoring.service import SkillAuthoringService

            authoring_repository = (
                SqliteAuthoringRepository(
                    sqlite_connection, getattr(repository, "_lock", None)
                )
                if sqlite_connection is not None
                else PostgresAuthoringRepository(
                    repository_connection, getattr(repository, "_lock", None)
                )
            )
            self._authoring = SkillAuthoringService(
                authoring_repository,
                authoring_resolver
                or (
                    _ImmutableResourceResolver(
                        sources_golden,
                        repository,
                        domain_resolver,
                        authoring_repository,
                    )
                    if sources_golden is not None
                    else _W1NotConfiguredResolver()
                ),
                authoring_model_gateway or CredentialBlockedGateway(),
                authoring_worker3 or NoopWorker3Executor(),
            )

    def _authoring_envelope(
        self,
        payload: dict[str, object],
        *,
        caller_id: str,
        workspace_id: str,
        request_id: str,
    ) -> ContextEnvelope:
        refs = tuple(
            AuthoringResourceRef.model_validate(item)
            for item in payload.get("resource_refs", [])
        )
        return ContextEnvelope(
            request_id=request_id,
            caller_id=caller_id,
            workspace_id=workspace_id,
            prompt=str(payload["prompt"]),
            resource_refs=refs,
            permissions=tuple(str(item) for item in payload.get("permissions", [])),
            fixed_revisions=tuple(
                str(item) for item in payload.get("fixed_revisions", [])
            ),
            budget=Budget(
                timeout_ms=min(
                    max(int(os.getenv("MODEL_AGENT_TIMEOUT_MS", "30000")), 100),
                    120000,
                )
            ),
            freshness=FreshnessPolicy(),
            current_skill_id=payload.get("current_skill_id"),
            current_view_id=payload.get("current_view_id"),
            current_component_id=payload.get("current_component_id"),
            comment_ids=tuple(str(item) for item in payload.get("comment_ids", [])),
        )

    async def answer_skill_authoring(
        self,
        payload: dict[str, object],
        *,
        caller_id: str,
        workspace_id: str,
        request_id: str,
    ) -> CommandResponse:
        from .contracts import SkillAuthoringAnswerResult

        if self._authoring is None:
            result = SkillAuthoringAnswerResult(
                status="credential_blocked",
                error=ErrorEnvelope(
                    code="AUTHORING_NOT_CONFIGURED",
                    message="生产 authoring repository 尚未配置。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        try:
            envelope = self._authoring_envelope(
                payload,
                caller_id=caller_id,
                workspace_id=workspace_id,
                request_id=request_id,
            )
            context = await self._authoring.resolver.resolve(
                envelope, envelope.resource_refs
            )
            answer = await asyncio.wait_for(
                self._authoring.model_gateway.answer(context),
                timeout=envelope.budget.timeout_ms / 1000,
            )
            execution = self._authoring.model_gateway.execution_evidence
            result = SkillAuthoringAnswerResult(
                status=answer.status,
                answer=answer,
                agent_execution=execution,
                context_digest=context.context_digest,
            )
            return CommandResponse(
                accepted=True,
                request_id=request_id,
                result=result,
            )
        except asyncio.TimeoutError:
            error = SkillAuthoringError(
                AuthoringErrorCode.MODEL_TIMEOUT, "VEADK Runner timed out"
            )
        except SkillAuthoringError as caught:
            error = caught
        execution = self._authoring.model_gateway.execution_evidence
        status = (
            "credential_blocked"
            if error.code == AuthoringErrorCode.CREDENTIAL_BLOCKED
            else "failed"
        )
        return CommandResponse(
            accepted=False,
            request_id=request_id,
            result=SkillAuthoringAnswerResult(
                status=status,
                agent_execution=execution,
                error=ErrorEnvelope(
                    code=error.code.value.upper(),
                    message=error.message,
                    retryable=error.code
                    in {
                        AuthoringErrorCode.MODEL_TIMEOUT,
                        AuthoringErrorCode.MODEL_UNAVAILABLE,
                        AuthoringErrorCode.CREDENTIAL_BLOCKED,
                    },
                    request_id=request_id,
                ),
            ),
        )

    async def start_skill_authoring(
        self,
        payload: dict[str, object],
        *,
        caller_id: str,
        workspace_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> CommandResponse:
        from .contracts import SkillAuthoringStartResult

        if self._authoring is None:
            result = SkillAuthoringStartResult(
                status="credential_blocked",
                error=ErrorEnvelope(
                    code="AUTHORING_NOT_CONFIGURED",
                    message="生产 authoring repository 尚未配置。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        authoring_repo = self._authoring.repository
        previous_id = await authoring_repo.get_idempotency(idempotency_key)
        if previous_id:
            read = await self._authoring.read_operation(previous_id)
            return self._authoring_response(read, request_id)
        envelope = self._authoring_envelope(
            payload,
            caller_id=caller_id,
            workspace_id=workspace_id,
            request_id=request_id,
        )
        kind = payload.get("requested_kind")
        try:
            read = await self._authoring.create_draft(
                envelope,
                requested_kind=AuthoringSkillKind(kind) if kind else None,
                scope=AuthoringScope(str(payload.get("scope", "personal"))),
                display_name=payload.get("display_name"),
            )
        except (SourcesGoldenError, SkillAuthoringError) as error:
            result = SkillAuthoringStartResult(
                status="failed",
                error=ErrorEnvelope(
                    code=(
                        error.code.value
                        if isinstance(error.code, AuthoringErrorCode)
                        else error.code
                    ),
                    message=error.message,
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        operation_id = read.operation.operation_id
        await authoring_repo.save_idempotency(idempotency_key, operation_id)
        return self._authoring_response(read, request_id)

    async def execute_skill_authoring(
        self,
        payload: dict[str, object],
        *,
        caller_id: str,
        request_id: str,
    ) -> CommandResponse:
        from .contracts import SkillAuthoringExecuteResult

        if self._authoring is None:
            result = SkillAuthoringExecuteResult(
                status="credential_blocked",
                error=ErrorEnvelope(
                    code="AUTHORING_NOT_CONFIGURED",
                    message="生产 authoring repository 尚未配置。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        try:
            read = await self._authoring.request_execution(
                str(payload["draft_id"]),
                caller_id=caller_id,
                revision=(
                    int(payload["revision"])
                    if payload.get("revision") is not None
                    else None
                ),
            )
        except SkillAuthoringError as error:
            result = SkillAuthoringExecuteResult(
                status="failed",
                error=ErrorEnvelope(
                    code=error.code.value,
                    message=error.message,
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        return self._authoring_execute_response(read, request_id)

    async def patch_skill_authoring(
        self,
        payload: dict[str, object],
        *,
        caller_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> CommandResponse:
        from pydantic import TypeAdapter
        from frontend.server.skill_authoring.models import TypedPatch
        from .contracts import SkillAuthoringPatchResult

        if self._authoring is None:
            result = SkillAuthoringPatchResult(
                status="failed",
                error=ErrorEnvelope(
                    code="AUTHORING_NOT_CONFIGURED",
                    message="生产 authoring repository 尚未配置。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        authoring_repo = self._authoring.repository
        previous_id = await authoring_repo.get_idempotency(idempotency_key)
        if previous_id:
            read = await self._authoring.read_operation(previous_id)
            return self._authoring_patch_response(read, request_id)
        try:
            proposal = await self._authoring.propose_patch(
                str(payload["draft_id"]),
                base_revision=int(payload["base_revision"]),
                patch=TypeAdapter(TypedPatch).validate_python(payload["patch"]),
                proposed_by=caller_id,
            )
            read = await self._authoring.accept_patch(proposal, caller_id=caller_id)
        except SkillAuthoringError as error:
            result = SkillAuthoringPatchResult(
                status="failed",
                error=ErrorEnvelope(
                    code=error.code.value,
                    message=error.message,
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        await authoring_repo.save_idempotency(
            idempotency_key, read.operation.operation_id
        )
        return self._authoring_patch_response(read, request_id)

    @staticmethod
    def _authoring_response(
        read: AuthoringReadModel, request_id: str
    ) -> CommandResponse:
        from .contracts import SkillAuthoringStartResult

        operation_error = None
        if read.operation.error_code is not None and read.operation.error_message:
            operation_error = ErrorEnvelope(
                code=read.operation.error_code.value,
                message=read.operation.error_message,
                retryable=read.operation.error_code.value
                in {
                    "model_timeout",
                    "model_unavailable",
                    "credential_blocked",
                },
                request_id=request_id,
            )
        result = SkillAuthoringStartResult(
            status=read.operation.status.value,
            error=operation_error,
            operation=read.operation,
            draft=read.draft,
            events=list(read.events),
        )
        accepted = read.operation.status.value in {
            "queued",
            "planning",
            "awaiting_input",
            "ready_for_execution",
        }
        return CommandResponse(
            accepted=accepted,
            request_id=request_id,
            operation_id=read.operation.operation_id,
            result=result,
        )

    @staticmethod
    def _authoring_execute_response(
        read: AuthoringReadModel, request_id: str
    ) -> CommandResponse:
        from .contracts import SkillAuthoringExecuteResult

        operation_error = None
        if read.operation.error_code is not None and read.operation.error_message:
            operation_error = ErrorEnvelope(
                code=read.operation.error_code.value,
                message=read.operation.error_message,
                retryable=read.operation.error_code.value
                in {
                    "model_timeout",
                    "model_unavailable",
                    "credential_blocked",
                },
                request_id=request_id,
            )

        result = SkillAuthoringExecuteResult(
            status=read.operation.status.value,
            error=operation_error,
            operation=read.operation,
            draft=read.draft,
            events=list(read.events),
        )
        return CommandResponse(
            accepted=read.operation.status.value in {"running", "queued", "succeeded"},
            request_id=request_id,
            operation_id=read.operation.operation_id,
            result=result,
        )

    @staticmethod
    def _authoring_patch_response(
        read: AuthoringReadModel, request_id: str
    ) -> CommandResponse:
        from .contracts import SkillAuthoringPatchResult

        operation_error = None
        if read.operation.error_code is not None and read.operation.error_message:
            operation_error = ErrorEnvelope(
                code=read.operation.error_code.value,
                message=read.operation.error_message,
                retryable=False,
                request_id=request_id,
            )
        result = SkillAuthoringPatchResult(
            status=read.operation.status.value,
            error=operation_error,
            operation=read.operation,
            draft=read.draft,
            patch=read.latest_patch,
            events=list(read.events),
        )
        return CommandResponse(
            accepted=read.operation.status.value
            in {"succeeded", "ready_for_execution"},
            request_id=request_id,
            operation_id=read.operation.operation_id,
            result=result,
        )

    def bootstrap(self, workspace_id: str, role: str):
        base = self.repository.bootstrap(workspace_id, role)
        if self._sources_golden is None:
            return base
        projection = self._sources_golden.bootstrap_projection(
            AccessContext(
                workspace_id=workspace_id,
                principal_id=workspace_id,
                role=role if role in {"viewer", "editor", "admin"} else "viewer",
            )
        )
        value = base.model_dump(mode="python", by_alias=True)
        value["workspaceData"] = {
            **value.get("workspaceData", {}),
            **projection.get("workspaceData", {}),
        }
        # Keep W1's lifecycle authoritative while exposing its immutable
        # Golden revisions through the shared bootstrap resource read model.
        # The UI needs these server-owned references to pin authoring context;
        # it must never infer an asset or revision from a local label.
        golden_resources = [
            {
                "id": asset["goldenRevisionId"],
                "displayName": asset["displayName"],
                "resourceKind": "golden_asset",
                "subtype": asset["assetKind"],
                "space": asset["permissions"]["scope"],
                "lifecycle": "ready",
                "version": str(asset["revision"]),
                "revision": asset["revision"],
                "permission": asset["permissions"]["canRead"],
                "assetId": asset["assetId"],
                "goldenRevisionId": asset["goldenRevisionId"],
                "traceId": asset["traceId"],
            }
            for asset in projection.get("resources", [])
        ]
        value["resources"] = [
            *value.get("resources", []),
            *golden_resources,
        ]
        value["connections"] = [
            BootstrapConnection(
                id=connection["id"],
                workspace_id=connection["workspaceId"],
                connector_key=connection["connectorKey"],
                display_name=connection["displayName"],
                scope=connection["scope"],
                owner_id=connection["ownerId"],
                status=connection["status"],
                sync_mode=connection["syncMode"],
                created_at=connection["createdAt"],
                updated_at=connection["updatedAt"],
                last_success_at=connection.get("lastSuccessAt"),
                last_error=connection.get("lastError"),
                discovered_resources=connection.get("discoveredResources", []),
                golden_revision_ids=connection.get("goldenRevisionIds", []),
            )
            for connection in projection["connections"]
        ]
        value["routes"] = sorted(
            set(value.get("routes", [])) | set(projection["routes"])
        )
        return type(base).model_validate(value)

    def immutable_html_artifact(
        self,
        *,
        workspace_id: str,
        view_revision_id: str,
        sha256: str,
    ) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise KnowledgeAssetRepositoryError(
                "ARTIFACT_NOT_FOUND", "HTML revision does not exist."
            )
        revision = self.repository.skill_view_revision(view_revision_id)
        if revision is None or revision.result_ref is None:
            raise KnowledgeAssetRepositoryError(
                "ARTIFACT_NOT_FOUND", "HTML revision does not exist."
            )
        skill_id = revision.skill_revision_id.rsplit(":", 1)[0]
        draft = self.repository.draft(skill_id)
        if draft is None or draft.workspace_id != workspace_id:
            raise KnowledgeAssetRepositoryError(
                "ARTIFACT_NOT_FOUND", "HTML revision does not exist."
            )
        ref = revision.result_ref
        if (
            ref.media_type != "text/html"
            or ref.sha256 != sha256
            or ref.bytes is None
            or ref.bytes <= 0
            or ref.bytes > 5 * 1024 * 1024
        ):
            raise KnowledgeAssetRepositoryError(
                "ARTIFACT_REF_MISMATCH",
                "HTML revision metadata does not match the requested digest.",
            )
        candidates: list[Path] = []
        for root in self._artifact_roots:
            candidates.extend(
                (
                    root / "views" / f"{sha256}.html",
                    root / f"{sha256}.html",
                )
            )
            candidates.extend(root.glob(f"*/objects/{sha256}.html"))
        path = None
        for candidate in candidates:
            resolved = candidate.resolve()
            if candidate.is_file() and any(
                resolved.is_relative_to(root) for root in self._artifact_roots
            ):
                path = resolved
                break
        if path is None:
            raise KnowledgeAssetRepositoryError(
                "ARTIFACT_NOT_FOUND", "HTML revision bytes do not exist."
            )
        content = path.read_bytes()
        if len(content) != ref.bytes or hashlib.sha256(content).hexdigest() != sha256:
            raise KnowledgeAssetRepositoryError(
                "ARTIFACT_INTEGRITY_FAILED",
                "Stored HTML revision failed integrity verification.",
                retryable=False,
            )
        return content

    def source_golden_connection(
        self,
        payload: SourceGoldenConnectionCreatePayload,
        *,
        workspace_id: str,
        principal_id: str,
        role: str,
        idempotency_key: str,
        trace_id: str,
    ) -> CommandResponse:
        if self._sources_golden is None:
            raise SourcesGoldenError(
                "SOURCE_GOLDEN_NOT_CONFIGURED", "Source/Golden adapter 未配置。"
            )
        configuration = dict(payload.configuration)
        if payload.connector_key == "mcp_custom":
            if not payload.mcp_profile_id:
                raise SourcesGoldenError(
                    "MCP_PROFILE_REQUIRED",
                    "custom MCP 必须选择服务端注册的 profile。",
                )
            if any(key in configuration for key in {"command", "args", "cwd", "env"}):
                raise SourcesGoldenError(
                    "MCP_CLIENT_EXECUTION_FIELDS_FORBIDDEN",
                    "浏览器不得提交 MCP command、args、cwd 或 env。",
                )
            configuration = self._sources_golden.mcp_profile_configuration(
                payload.mcp_profile_id, payload.tool_allowlist
            )
        result = self._sources_golden.create_connection(
            AccessContext(
                workspace_id=workspace_id,
                principal_id=principal_id,
                role=role if role in {"viewer", "editor", "admin"} else "viewer",
            ),
            connector_key=payload.connector_key,
            display_name=payload.display_name,
            scope=payload.scope,
            configuration=configuration,
            secret_ref=payload.secret_ref,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
        return CommandResponse(
            accepted=result.connection.status == "ready",
            request_id=trace_id,
            result=SourceGoldenConnectionResult(
                connection=ConnectionViewModel.model_validate(
                    result.connection.model_dump(
                        mode="json",
                        exclude={"configuration", "secret_ref"},
                    )
                ),
                validation=result.validation,
                discovery=result.discovery,
                replayed=result.replayed,
            ),
        )

    def source_golden_ingest(
        self,
        payload: SourceGoldenIngestPayload,
        *,
        workspace_id: str,
        principal_id: str,
        role: str,
        idempotency_key: str,
        trace_id: str,
    ) -> CommandResponse:
        if self._sources_golden is None:
            raise SourcesGoldenError(
                "SOURCE_GOLDEN_NOT_CONFIGURED", "Source/Golden adapter 未配置。"
            )
        result = self._sources_golden.ingest(
            AccessContext(
                workspace_id=workspace_id,
                principal_id=principal_id,
                role=role if role in {"viewer", "editor", "admin"} else "viewer",
            ),
            connection_id=payload.connection_id,
            resource_id=payload.resource_id,
            recipe_operations=payload.recipe_operations,
            tool_arguments=payload.tool_arguments,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
        )
        return CommandResponse(
            accepted=True,
            request_id=trace_id,
            result=SourceGoldenIngestResult(
                source_revision=result.source_revision,
                profile_run=result.profile_run,
                cleaning_recipe=result.cleaning_recipe,
                clean_run=result.clean_run,
                golden_asset_revision=result.golden_asset_revision,
                replayed=result.replayed,
            ),
        )

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
        for source_ref in source_refs:
            self._register_local_source(
                source_ref, workspace_id=workspace_id, request_id=request_id
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
            workspace_id=workspace_id,
            action="skill-draft.create",
            resource_id=draft.id,
            draft=draft,
            replayed=replayed,
        )

    def _register_local_source(
        self, source_ref: str, *, workspace_id: str, request_id: str
    ) -> SourceRevision | None:
        path = self._local_path(source_ref)
        if path is None or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix not in {".md", ".markdown", ".csv"}:
            return None
        content = path.read_bytes()
        if len(content) > 10 * 1024 * 1024:
            raise KnowledgeAssetRepositoryError(
                "SOURCE_TOO_LARGE", "本地来源超过 10 MiB 限制。"
            )
        if b"\x00" in content:
            raise KnowledgeAssetRepositoryError(
                "SOURCE_UNSAFE_CONTENT", "本地来源包含不允许的二进制内容。"
            )
        digest = hashlib.sha256(content).hexdigest()
        source_type = "csv" if suffix == ".csv" else "markdown"
        schema_digest = self._schema_digest(content, source_type)
        revision = SourceRevision(
            id=f"source-{digest[:24]}",
            source_type=source_type,
            content_ref=StorageRef(
                uri=f"local://{digest}",
                kind="object",
                sha256=digest,
                media_type="text/csv" if source_type == "csv" else "text/markdown",
                bytes=len(content),
            ),
            schema_ref=SchemaRef(
                uri=f"local://schema/source/{schema_digest}",
                version="1",
                sha256=schema_digest,
            ),
            permission_ref=PermissionRef(
                uri=f"permission://workspace/{workspace_id}",
                version="1",
            ),
            source_digest=digest,
            created_at=now_iso(),
        )
        self.repository.save_source_revision(revision, workspace_id, str(path))
        return revision

    @staticmethod
    def _schema_digest(content: bytes, source_type: str) -> str:
        if source_type == "csv":
            first_line = content.decode("utf-8").splitlines()[0] if content else ""
            schema = {"format": "csv", "columns": next(csv.reader([first_line]), [])}
        else:
            schema = {"format": "markdown", "columns": ["text"]}
        return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _local_path(source_ref: str) -> Path | None:
        parsed = urlparse(source_ref)
        if parsed.scheme in {"http", "https", "secret"}:
            return None
        raw = Path(parsed.path if parsed.scheme == "file" else source_ref).expanduser()
        if raw.is_symlink():
            raise KnowledgeAssetRepositoryError(
                "SOURCE_UNSAFE_PATH", "本地来源不得通过符号链接读取。"
            )
        return raw.resolve()

    def _source_path(self, source_revision_id: str) -> Path:
        path = getattr(self.repository, "source_path", lambda _id: None)(
            source_revision_id
        )
        if path is None:
            raise KnowledgeAssetRepositoryError(
                "SOURCE_NOT_FOUND",
                "本地来源不存在。",
                details={"sourceRevisionId": source_revision_id},
            )
        return Path(path)

    def _run_profile(
        self, payload: SourceProfilePayload, request_id: str
    ) -> SourceProfileResult:
        source = self.repository.source_revision(payload.source_revision_id)
        if source is None:
            raise KnowledgeAssetRepositoryError("SOURCE_NOT_FOUND", "来源不存在。")
        path = self._source_path(source.id)
        content = path.read_text(encoding="utf-8")
        columns: list[str] = []
        rows: list[dict[str, str]] = []
        lines: list[str] = []
        if source.source_type == "csv":
            rows = list(csv.DictReader(content.splitlines()))
            sample = rows[: payload.sample_limit]
            columns = list(rows[0].keys()) if rows else []
            nonempty = sum(bool(value) for row in sample for value in row.values())
            total = max(len(sample) * max(len(columns), 1), 1)
            report = {
                "format": "csv",
                "rows": len(rows),
                "columns": columns,
                "sample": sample,
            }
        else:
            lines = [line for line in content.splitlines() if line.strip()]
            sample = lines[: payload.sample_limit]
            nonempty = len(sample)
            total = max(len(sample), 1)
            report = {"format": "markdown", "lines": len(lines), "sample": sample}
        report_digest = hashlib.sha256(
            json.dumps(report, sort_keys=True).encode()
        ).hexdigest()
        structure = {
            "format": source.source_type,
            "columns": columns if source.source_type == "csv" else ["text"],
            "rowCount": len(rows) if source.source_type == "csv" else len(lines),
        }
        structure_digest = hashlib.sha256(
            json.dumps(structure, sort_keys=True).encode()
        ).hexdigest()
        cost = {"bytesRead": path.stat().st_size, "sampleRows": len(sample)}
        cost_digest = hashlib.sha256(
            json.dumps(cost, sort_keys=True).encode()
        ).hexdigest()
        sensitive = [
            column
            for column in columns
            if any(
                token in column.lower()
                for token in ("email", "phone", "token", "secret")
            )
        ]
        run = ProfileRun(
            id=f"profile-{source.id}",
            source_revision_id=source.id,
            status="succeeded",
            report_ref=StorageRef(
                uri=f"local://profile/{report_digest}",
                kind="inline",
                sha256=report_digest,
                media_type="application/json",
            ),
            structure_ref=StorageRef(
                uri=f"local://structure/{structure_digest}",
                kind="inline",
                sha256=structure_digest,
                media_type="application/json",
            ),
            quality_score=nonempty / total,
            started_at=now_iso(),
            finished_at=now_iso(),
            sensitive_classification=sensitive,
            estimated_cost_ref=StorageRef(
                uri=f"local://cost/{cost_digest}",
                kind="inline",
                sha256=cost_digest,
                media_type="application/json",
            ),
        )
        self.repository.save_profile_run(run)
        return SourceProfileResult(
            source_revision_id=source.id,
            status="succeeded",
            profile_run=run,
            error=None,
        )

    def _run_clean(
        self, payload: SourceCleanPayload, workspace_id: str
    ) -> SourceCleanResult:
        source = self.repository.source_revision(payload.source_revision_id)
        if source is None:
            raise KnowledgeAssetRepositoryError("SOURCE_NOT_FOUND", "来源不存在。")
        source_workspace = getattr(
            self.repository, "source_workspace", lambda _id: None
        )(source.id)
        if source_workspace:
            workspace_id = source_workspace
        path = self._source_path(source.id)
        raw = path.read_text(encoding="utf-8")
        operations = ["trim", "deduplicate"]
        recipe_digest = hashlib.sha256(
            json.dumps(
                {"source": source.id, "operations": operations}, sort_keys=True
            ).encode()
        ).hexdigest()
        recipe = CleaningRecipe(
            id=payload.recipe_id,
            version=1,
            operations=operations,
            source_revision_id=source.id,
            recipe_digest=recipe_digest,
        )
        self.repository.save_cleaning_recipe(recipe)
        if source.source_type == "csv":
            rows = list(csv.DictReader(raw.splitlines()))
            seen = set()
            cleaned = []
            for row in rows:
                item = {key: value.strip() for key, value in row.items()}
                marker = json.dumps(item, sort_keys=True)
                if marker not in seen:
                    seen.add(marker)
                    cleaned.append(item)
            output = (
                "\n".join(
                    json.dumps(row, ensure_ascii=False, sort_keys=True)
                    for row in cleaned
                )
                + "\n"
            )
            media_type = "application/x-ndjson"
        else:
            lines = []
            seen = set()
            for line in raw.splitlines():
                value = line.strip()
                if value and value not in seen:
                    seen.add(value)
                    lines.append(value)
            output = "\n".join(lines) + "\n"
            media_type = "text/plain"
        digest = hashlib.sha256(output.encode()).hexdigest()
        artifact = self._artifact_path(digest)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(output, encoding="utf-8")
        storage = StorageRef(
            uri=f"local://golden/{digest}",
            kind="object",
            sha256=digest,
            media_type=media_type,
            bytes=len(output.encode()),
        )
        clean = CleanRun(
            id=f"clean-{source.id}-{recipe.version}",
            source_revision_id=source.id,
            recipe_id=recipe.id,
            status="succeeded",
            output_ref=storage,
            started_at=now_iso(),
            finished_at=now_iso(),
        )
        self.repository.save_clean_run(clean)
        lineage = hashlib.sha256(
            f"{source.source_digest}:{recipe.recipe_digest}:{digest}".encode()
        ).hexdigest()
        golden = GoldenAssetRevision(
            id=f"golden-{digest[:24]}",
            asset_kind="dataset" if source.source_type == "csv" else "knowledge",
            revision=1,
            schema_ref=SchemaRef(
                uri=f"local://schema/{digest}", version="1", sha256=digest
            ),
            storage_ref=storage,
            source_revision_refs=[source.id],
            recipe_ref=recipe.id,
            quality_run_ref=clean.id,
            owner=OwnerRef(workspace_id=workspace_id, principal_id="local"),
            permissions_ref=source.permission_ref,
            lineage_digest=lineage,
            freshness_at=now_iso(),
            last_good=True,
        )
        golden = self.repository.save_golden_asset_revision(golden)
        return SourceCleanResult(
            source_revision_id=source.id,
            recipe_id=recipe.id,
            status="succeeded",
            clean_run=clean,
            golden_asset_revision=golden,
        )

    @staticmethod
    def _artifact_path(digest: str) -> Path:
        return Path(".veadk/knowledge-assets/artifacts") / f"{digest}.jsonl"

    @staticmethod
    def _golden_rows(source: str) -> tuple[list[str], list[dict[str, object]]]:
        """Read the content-addressed Golden Asset into a bounded typed shape.

        CSV assets are persisted as NDJSON by the clean run. Markdown assets
        remain ordered text lines so the Knowledge executor preserves its
        citation-friendly answer semantics.
        """
        lines = [line for line in source.splitlines() if line.strip()]
        rows: list[dict[str, object]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                normalized: dict[str, object] = {}
                for key, item in value.items():
                    if isinstance(item, str):
                        stripped = item.strip()
                        try:
                            normalized[key] = (
                                float(stripped) if "." in stripped else int(stripped)
                            )
                            continue
                        except ValueError:
                            pass
                    normalized[key] = item
                rows.append(normalized)
        return lines, rows

    @staticmethod
    def _numeric_fields(rows: list[dict[str, object]]) -> list[str]:
        if not rows:
            return []
        fields = list(rows[0])
        return [
            field
            for field in fields
            if any(
                isinstance(row.get(field), (int, float))
                and not isinstance(row.get(field), bool)
                for row in rows
            )
        ]

    @staticmethod
    def _text_fields(rows: list[dict[str, object]]) -> list[str]:
        if not rows:
            return []
        return [
            field
            for field in rows[0]
            if not any(
                isinstance(row.get(field), (int, float))
                and not isinstance(row.get(field), bool)
                for row in rows
            )
        ]

    @staticmethod
    def _trusted_html(template: str, view_model: object) -> bytes:
        """Render only server-owned static templates; no executable output."""
        if isinstance(view_model, KnowledgeViewModel):
            body = f"<p>{html.escape(view_model.answer)}</p>"
        elif isinstance(view_model, SemanticViewModel):
            body = (
                f"<p>Metrics: {html.escape(', '.join(view_model.metric_refs))}</p>"
                f"<p>Dimensions: {html.escape(', '.join(view_model.dimension_refs))}</p>"
            )
        elif isinstance(view_model, DashboardViewModel):
            body = "".join(
                f'<div data-row="{index}">{html.escape(str(cell.value or ""))}</div>'
                for index, row in enumerate(view_model.rows)
                for cell in row
            )
        elif isinstance(view_model, ChartViewModel):
            body = f"<h2>{html.escape(view_model.title)}</h2>" + "".join(
                f'<div data-series="{html.escape(series.name)}">'
                f"{len(series.points)} points</div>"
                for series in view_model.series
            )
        elif isinstance(view_model, GraphOntologyViewModel):
            body = "".join(
                f'<div data-node="{html.escape(node.id)}">{html.escape(node.label)}</div>'
                for node in view_model.nodes
            )
        elif isinstance(view_model, MonitoringViewModel):
            body = "".join(
                f'<div data-point="{html.escape(label)}">{value}</div>'
                for label, value in view_model.values
            )
        else:
            raise ValueError(f"unsupported trusted renderer template: {template}")
        output = (
            f'<article data-renderer="{html.escape(template)}-v1">{body}</article>'
        ).encode("utf-8")
        lowered = output.lower()
        if b"<script" in lowered or b"<iframe" in lowered or b"javascript:" in lowered:
            raise ValueError("trusted renderer produced executable markup")
        return output

    def _run_skill_draft(
        self,
        payload: SkillDraftRunPayload,
        *,
        request_id: str,
        operation_id: str | None = None,
    ) -> SkillDraftRunResult:
        self._execution_checkpoint()

        def cancelled() -> bool:
            if operation_id is None:
                return False
            operation = self.repository.operation(operation_id)
            return operation is not None and operation.status == "cancelled"

        def cancelled_result(
            golden: GoldenAssetRevision | None = None,
        ) -> SkillDraftRunResult:
            if golden is not None:
                self.repository.update_skill_draft_revision_status(
                    payload.draft_id, payload.revision, "failed"
                )
            return SkillDraftRunResult(
                draft_id=payload.draft_id,
                status="cancelled",
                golden_asset_revision=golden,
                error=ErrorEnvelope(
                    code="EXECUTION_CANCELLED",
                    message="执行已取消，未提交新的 Skill ViewRevision。",
                    retryable=True,
                    request_id=request_id,
                ),
            )

        draft = self.repository.draft(payload.draft_id)
        if draft is None:
            return SkillDraftRunResult(
                draft_id=payload.draft_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_DRAFT_NOT_FOUND",
                    message="Builder 找不到要执行的 Skill 草稿。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if draft.revision != payload.revision:
            return SkillDraftRunResult(
                draft_id=payload.draft_id,
                status="failed",
                error=ErrorEnvelope(
                    code="CONFLICT",
                    message="Skill 草稿版本已变化，请刷新后重试。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if cancelled():
            return cancelled_result()
        self._execution_checkpoint()
        self.repository.update_skill_draft_revision_status(
            draft.id, payload.revision, "planning"
        )
        golden = self.repository.latest_golden_asset_revision(draft.workspace_id)
        if golden is None:
            self.repository.update_skill_draft_revision_status(
                draft.id, payload.revision, "failed"
            )
            return SkillDraftRunResult(
                draft_id=draft.id,
                status="failed",
                error=ErrorEnvelope(
                    code="GOLDEN_ASSET_NOT_FOUND",
                    message="当前工作区没有可执行的 Golden Asset Revision。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if cancelled():
            return cancelled_result(golden)
        self._execution_checkpoint()
        dependencies = draft.manifest.spec.dependencies.golden_assets
        if dependencies and golden.id not in dependencies:
            self.repository.update_skill_draft_revision_status(
                draft.id, payload.revision, "failed"
            )
            return SkillDraftRunResult(
                draft_id=draft.id,
                status="failed",
                golden_asset_revision=golden,
                error=ErrorEnvelope(
                    code="GOLDEN_ASSET_NOT_BOUND",
                    message="Skill Manifest 未绑定当前可用的 Golden Asset Revision。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        self.repository.update_skill_draft_revision_status(
            draft.id, payload.revision, "running"
        )
        if cancelled():
            return cancelled_result(golden)
        self._execution_checkpoint()
        if payload.max_steps < 2 or payload.budget < 128:
            self.repository.update_skill_draft_revision_status(
                draft.id, payload.revision, "partially_succeeded"
            )
            return SkillDraftRunResult(
                draft_id=draft.id,
                status="partially_succeeded",
                golden_asset_revision=golden,
                error=ErrorEnvelope(
                    code="EXECUTION_BUDGET_EXHAUSTED",
                    message="执行预算不足以完成查询、绑定和渲染。",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        return self._run_kind_runtime(
            draft=draft,
            golden=golden,
            payload=payload,
            request_id=request_id,
            cancelled=cancelled,
            cancelled_result=cancelled_result,
        )

    def _run_kind_runtime(
        self,
        *,
        draft: SkillDraft,
        golden: GoldenAssetRevision,
        payload: SkillDraftRunPayload,
        request_id: str,
        cancelled,
        cancelled_result,
    ) -> SkillDraftRunResult:
        """Execute the five typed kinds through Worker 3's explicit runtime."""
        if draft.manifest.spec.kind not in KindRuntime.supported_kinds:
            self.repository.update_skill_draft_revision_status(
                draft.id, payload.revision, "failed"
            )
            return SkillDraftRunResult(
                draft_id=draft.id,
                status="failed",
                golden_asset_revision=golden,
                error=ErrorEnvelope(
                    code="KIND_EXECUTOR_NOT_READY",
                    message=f"当前执行器尚未开放 {draft.manifest.spec.kind}。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if cancelled():
            return cancelled_result(golden)
        content = self._golden_content.read_many([golden])
        draft_revision = SkillDraftRevision(
            id=f"{draft.id}:{payload.revision}",
            skill_id=draft.id,
            revision=payload.revision,
            manifest=draft.manifest,
            source_revision_refs=golden.source_revision_refs,
            golden_asset_revision_refs=[golden.id],
            status="running",
            created_at=draft.updated_at,
        )
        execution = self._kind_runtime.execute(
            KindExecutionRequest(
                draft_revision=draft_revision,
                caller_id="studio-build",
                workspace_id=draft.workspace_id,
                golden_asset_revisions=[golden],
                golden_asset_contents=content,
                data_access_revision_refs=golden.source_revision_refs,
                budget=ExecutionBudget(
                    max_steps=payload.max_steps,
                    max_bytes=payload.budget,
                ),
                freshness_at=golden.freshness_at,
                idempotency_key=f"{draft.id}:{payload.revision}:{payload.trace_id}",
                trace_id=payload.trace_id,
                cancel_requested=cancelled(),
                now=now_iso(),
            )
        )
        if execution.status == "cancelled":
            return cancelled_result(golden)
        if (
            execution.skill_result is None
            or execution.view_intent is None
            or execution.skill_view_revision is None
        ):
            status = (
                "partially_succeeded"
                if execution.state == "over_budget"
                else "failed"
                if execution.status == "failed"
                else "awaiting_input"
            )
            self.repository.update_skill_draft_revision_status(
                draft.id, payload.revision, status
            )
            return SkillDraftRunResult(
                draft_id=draft.id,
                status=status,
                execution_state=execution.state,
                trace_ref=execution.trace_ref,
                evidence_ref=execution.evidence_ref,
                golden_asset_revision=golden,
                error=ErrorEnvelope(
                    code=execution.state.upper(),
                    message=execution.message
                    or "Typed Skill execution did not produce a view.",
                    retryable=execution.state in {"over_budget", "timeout", "no_data"},
                    request_id=request_id,
                ),
            )
        view = execution.skill_view_revision
        invocation_id = f"invocation-{hashlib.sha256(f'{draft.id}:{payload.revision}:{payload.trace_id}'.encode()).hexdigest()[:24]}"
        view = view.model_copy(update={"invocation_id": invocation_id})
        invocation = Invocation(
            id=invocation_id,
            skill_version_id=f"draft://{draft.id}:{payload.revision}",
            skill_view_revision_id=view.id,
            caller_id="studio-build",
            workspace_id=draft.workspace_id,
            status="succeeded",
            input_ref=golden.storage_ref,
            result_ref=execution.skill_result.result_ref,
            trace_id=payload.trace_id,
            actual_data_revision_refs=[golden.id],
            started_at=now_iso(),
            finished_at=now_iso(),
        )
        self.repository.save_skill_result(execution.skill_result)
        self.repository.save_skill_view_revision(view)
        self.repository.save_invocation(invocation)
        self.repository.update_skill_draft_revision_status(
            draft.id, payload.revision, "ready_for_evaluation"
        )
        return SkillDraftRunResult(
            draft_id=draft.id,
            status="ready_for_evaluation",
            execution_state=execution.state,
            trace_ref=execution.trace_ref,
            evidence_ref=execution.evidence_ref,
            golden_asset_revision=golden,
            skill_result=execution.skill_result,
            view_intent=execution.view_intent,
            skill_view_revision=view,
        )
        try:
            artifact = self._artifact_path(golden.storage_ref.sha256)
            source = artifact.read_text(encoding="utf-8").rstrip()
        except (OSError, UnicodeError) as error:
            self.repository.update_skill_draft_revision_status(
                draft.id, payload.revision, "failed"
            )
            return SkillDraftRunResult(
                draft_id=draft.id,
                status="failed",
                golden_asset_revision=golden,
                error=ErrorEnvelope(
                    code="RESULT_READ_FAILED",
                    message=f"无法读取 Golden Asset 内容：{error}",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        if cancelled():
            return cancelled_result(golden)
        self._execution_checkpoint()
        kind = draft.manifest.spec.kind
        lines, rows = self._golden_rows(source)
        numeric_fields = self._numeric_fields(rows)
        text_fields = self._text_fields(rows)
        answer = source
        result_payload = {
            "output": source,
            "kind": kind,
            "goldenAssetRevisionId": golden.id,
            "traceId": payload.trace_id,
            "steps": [
                "resolve-golden-asset",
                "read-content",
                f"execute-{kind}",
                "validate-typed-result",
                "render-trusted-view",
            ],
        }
        if kind == "semantic":
            result_payload["typedOutput"] = {
                "schemaRef": golden.schema_ref.model_dump(mode="json"),
                "metricRefs": draft.manifest.spec.kind_spec.metric_refs
                or numeric_fields,
                "dimensionRefs": draft.manifest.spec.kind_spec.dimension_refs
                or text_fields,
                "relationshipRefs": draft.manifest.spec.kind_spec.relationship_refs,
            }
        elif kind == "analysis":
            result_payload["typedOutput"] = {
                "recordCount": len(rows),
                "numericFields": numeric_fields,
                "dimensionFields": text_fields,
            }
        elif kind == "graph_ontology":
            result_payload["typedOutput"] = {
                "recordCount": len(rows) if rows else len(lines),
                "entityField": text_fields[0] if text_fields else None,
            }
        elif kind == "monitoring":
            result_payload["typedOutput"] = {
                "recordCount": len(rows) if rows else len(lines),
                "metricField": numeric_fields[0] if numeric_fields else None,
            }
        result_bytes = json.dumps(
            result_payload, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        result_digest = hashlib.sha256(result_bytes).hexdigest()
        result_path = Path(".veadk/knowledge-assets/results") / f"{result_digest}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_bytes(result_bytes)
        result_ref = StorageRef(
            uri=f"local://result/{result_digest}",
            kind="object",
            sha256=result_digest,
            media_type="application/json",
            bytes=len(result_bytes),
        )
        skill_result = SkillResult(
            id=f"result-{result_digest[:24]}",
            skill_id=draft.id,
            skill_revision=payload.revision,
            kind=kind,
            output_schema_ref=draft.manifest.spec.contract.output_schema_ref,
            result_ref=result_ref,
            source_revision_refs=golden.source_revision_refs,
            golden_asset_revision_refs=[golden.id],
            trace_id=payload.trace_id,
            freshness_at=golden.freshness_at,
        )
        if kind == "knowledge":
            view_model = KnowledgeViewModel(
                answer=answer,
                citations=[
                    KnowledgeCitation(
                        citation_id=f"citation-{golden.id}",
                        source_revision_id=source_id,
                        title="Golden Asset Revision",
                        locator=f"local://golden/{golden.storage_ref.sha256}",
                    )
                    for source_id in golden.source_revision_refs
                ],
            )
            template = "knowledge"
            purpose = "answer"
        elif kind == "semantic":
            view_model = SemanticViewModel(
                schema_ref=golden.schema_ref,
                metric_refs=(
                    draft.manifest.spec.kind_spec.metric_refs or numeric_fields
                ),
                dimension_refs=(
                    draft.manifest.spec.kind_spec.dimension_refs or text_fields
                ),
                relationship_refs=draft.manifest.spec.kind_spec.relationship_refs,
                data_ref=golden.storage_ref,
            )
            template = "semantic"
            purpose = "schema"
        elif kind == "analysis":
            x_field = text_fields[0] if text_fields else "row"
            y_field = numeric_fields[0] if numeric_fields else "value"
            points = [
                (
                    str(row.get(x_field, index + 1)),
                    float(row[y_field]) if numeric_fields else float(len(lines[index])),
                )
                for index, row in enumerate(rows[:1000])
            ]
            if not points:
                points = [
                    (str(index + 1), float(len(line)))
                    for index, line in enumerate(lines[:1000])
                ]
            view_model = ChartViewModel(
                title=draft.manifest.metadata.display_name,
                x_field=x_field,
                y_field=y_field,
                series=[
                    ChartSeries(
                        name="analysis",
                        points=points,
                    )
                ],
                data_ref=golden.storage_ref,
            )
            template = "chart"
            purpose = "compare"
        elif kind == "graph_ontology":
            if rows:
                nodes = [
                    GraphNode(
                        id=f"node-{index}",
                        label=str(row.get(text_fields[0], index)),
                        entity_type="record",
                    )
                    for index, row in enumerate(rows[:1000])
                ]
            else:
                nodes = [
                    GraphNode(id=f"node-{index}", label=line[:128], entity_type="line")
                    for index, line in enumerate(lines[:1000])
                ]
            view_model = GraphOntologyViewModel(
                nodes=nodes,
                edges=[
                    GraphEdge(
                        source=nodes[index - 1].id,
                        target=node.id,
                        relation="next",
                    )
                    for index, node in enumerate(nodes)
                    if index
                ],
                evidence_ref=golden.storage_ref,
            )
            template = "graph_ontology"
            purpose = "explore"
        else:
            metric = numeric_fields[0] if numeric_fields else None
            values = [
                (
                    str(row.get(text_fields[0], index + 1))
                    if text_fields
                    else str(index + 1),
                    float(row[metric]) if metric else float(len(lines[index])),
                )
                for index, row in enumerate(rows[:1000])
            ]
            if not values:
                values = [
                    (str(index + 1), float(len(line)))
                    for index, line in enumerate(lines[:1000])
                ]
            view_model = MonitoringViewModel(
                metric_refs=(
                    draft.manifest.spec.kind_spec.metric_refs
                    or ([metric] if metric else [])
                ),
                values=values,
                alerts=[],
                data_ref=golden.storage_ref,
            )
            template = "monitoring"
            purpose = "monitor"
        view_intent = ViewIntent(
            id=f"view-intent-{result_digest[:24]}",
            skill_id=draft.id,
            skill_revision=payload.revision,
            template=template,
            purpose=purpose,
            result_ref=result_ref.uri,
        )
        view_schema_bytes = view_model.model_dump_json(by_alias=True).encode("utf-8")
        view_schema_digest = hashlib.sha256(view_schema_bytes).hexdigest()
        html_bytes = self._trusted_html(template, view_model)
        html_digest = hashlib.sha256(html_bytes).hexdigest()
        html_path = Path(".veadk/knowledge-assets/bundles") / f"{html_digest}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_bytes(html_bytes)
        view_identity = hashlib.sha256(
            f"{draft.id}:{payload.revision}:{html_digest}:{request_id}".encode()
        ).hexdigest()
        view_revision = SkillViewRevision(
            id=f"view-{view_identity[:24]}",
            skill_revision_id=f"{draft.id}:{payload.revision}",
            revision=1,
            manifest=SkillViewManifest(
                id=f"view-manifest-{view_identity[:24]}",
                skill_revision_id=f"{draft.id}:{payload.revision}",
                renderer_ref=f"renderer://{template}/v1",
                view_model_schema_ref=SchemaRef(
                    uri=f"local://view-model/{view_schema_digest}",
                    version="1",
                    sha256=view_schema_digest,
                ),
                allowed_components=[
                    "SkillViewShell",
                    f"{template.title().replace('_', '')}View",
                ],
            ),
            intent=view_intent,
            view_model=view_model,
            result_ref=StorageRef(
                uri=f"local://bundle/{html_digest}",
                kind="bundle",
                sha256=html_digest,
                media_type="text/html",
                bytes=len(html_bytes),
            ),
            created_at=now_iso(),
        )
        invocation_id = f"invocation-{view_identity[:24]}"
        execution_time = now_iso()
        execution_invocation = Invocation(
            id=invocation_id,
            skill_version_id=f"draft://{draft.id}:{payload.revision}",
            skill_view_revision_id=view_revision.id,
            caller_id="studio-build",
            workspace_id=draft.workspace_id,
            status="succeeded",
            input_ref=golden.storage_ref,
            result_ref=skill_result.result_ref,
            trace_id=payload.trace_id,
            actual_data_revision_refs=skill_result.golden_asset_revision_refs,
            started_at=execution_time,
            finished_at=execution_time,
        )
        view_revision = view_revision.model_copy(
            update={"invocation_id": execution_invocation.id}
        )
        if cancelled():
            return cancelled_result(golden)
        self.repository.save_skill_result(skill_result)
        self.repository.save_skill_view_revision(view_revision)
        self.repository.save_invocation(execution_invocation)
        self.repository.update_skill_draft_revision_status(
            draft.id, payload.revision, "ready_for_evaluation"
        )
        return SkillDraftRunResult(
            draft_id=draft.id,
            status="ready_for_evaluation",
            golden_asset_revision=golden,
            skill_result=skill_result,
            view_intent=view_intent,
            skill_view_revision=view_revision,
        )

    def _run_evaluation(
        self,
        payload: EvaluationPayload,
        *,
        request_id: str,
        result_type: str = "evaluation.run",
    ) -> EvaluationRunResult:
        draft = self.repository.draft(payload.target_id)
        if draft is None:
            return EvaluationRunResult(
                result_type=result_type,
                target_id=payload.target_id,
                status="failed",
                error=self._not_ready_error("evaluation.run", request_id),
            )
        golden = self.repository.latest_golden_asset_revision(draft.workspace_id)
        if golden is None:
            return EvaluationRunResult(
                result_type="evaluation.run",
                target_id=draft.id,
                status="failed",
                error=ErrorEnvelope(
                    code="GOLDEN_ASSET_NOT_FOUND",
                    message="评测需要可用的 Golden Asset Revision。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        executed_result = self.repository.latest_skill_result(draft.id, draft.revision)
        if executed_result is None:
            run_id = f"evaluation-{hashlib.sha256((draft.id + request_id).encode()).hexdigest()[:24]}"
            gate = PolicyGateResult(
                id=f"gate-{run_id}",
                skill_revision_id=f"{draft.id}:{draft.revision}",
                evaluation_run_id=run_id,
                decision="blocked",
                reasons=["当前 Skill revision 没有可重放的真实 SkillResult。"],
                machine_reasons=["SKILL_RESULT_REQUIRED_BEFORE_EVALUATION"],
                checked_at=now_iso(),
            )
            self.repository.save_policy_gate_result(gate)
            return EvaluationRunResult(
                result_type=result_type,
                target_id=draft.id,
                status="failed",
                policy_gate_result=gate,
                error=ErrorEnvelope(
                    code="SKILL_RESULT_REQUIRED",
                    message="评测必须绑定当前 Skill revision 的真实执行结果。",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        executed_view = self.repository.latest_skill_view_revision(
            f"{draft.id}:{draft.revision}"
        )
        if executed_view is None:
            run_id = f"evaluation-{hashlib.sha256((draft.id + request_id + 'view').encode()).hexdigest()[:24]}"
            gate = PolicyGateResult(
                id=f"gate-{run_id}",
                skill_revision_id=f"{draft.id}:{draft.revision}",
                evaluation_run_id=run_id,
                decision="blocked",
                reasons=["当前 Skill revision 没有可重放的持久化 SkillViewRevision。"],
                machine_reasons=["SKILL_VIEW_REVISION_REQUIRED_BEFORE_EVALUATION"],
                checked_at=now_iso(),
            )
            self.repository.save_policy_gate_result(gate)
            return EvaluationRunResult(
                result_type=result_type,
                target_id=draft.id,
                status="failed",
                policy_gate_result=gate,
                error=ErrorEnvelope(
                    code="SKILL_VIEW_REVISION_REQUIRED",
                    message="评测必须绑定当前 Skill revision 的真实 Skill View。",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        cases = payload.cases or [
            EvaluationCase(
                id=case_id,
                input_ref=golden.storage_ref,
                source="manual",
            )
            for case_id in (payload.case_ids or ["default"])
        ]
        cases_bytes = json.dumps(
            [case.model_dump(mode="json", by_alias=True) for case in cases],
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        cases_digest = hashlib.sha256(cases_bytes).hexdigest()
        cases_path = (
            Path(".veadk/knowledge-assets/evaluations") / f"{cases_digest}.json"
        )
        cases_path.parent.mkdir(parents=True, exist_ok=True)
        cases_path.write_bytes(cases_bytes)
        cases_ref = StorageRef(
            uri=f"local://evaluation-cases/{cases_digest}",
            kind="object",
            sha256=cases_digest,
            media_type="application/json",
            bytes=len(cases_bytes),
        )
        suite = EvaluationSuite(
            id=payload.suite_id,
            version=1,
            skill_id=draft.id,
            case_count=len(cases),
            cases_ref=cases_ref,
            pass_threshold=1.0,
            environment=payload.environment,
            case_ids=[case.id for case in cases],
        )
        case_results = []
        for case in cases:
            candidate = case.source == "agent_candidate"
            actual_ref = executed_result.result_ref
            expected_matches = (
                case.expected_output_ref is None
                or case.expected_output_ref.sha256 == actual_ref.sha256
            )
            bound_to_current_revision = (
                executed_result.skill_id == draft.id
                and executed_result.skill_revision == draft.revision
                and executed_view.skill_revision_id == f"{draft.id}:{draft.revision}"
            )
            structural_pass = bound_to_current_revision and expected_matches
            evidence_bytes = json.dumps(
                {
                    "caseId": case.id,
                    "source": case.source,
                    "skillRevisionId": f"{draft.id}:{draft.revision}",
                    "dataRevisionId": golden.id,
                    "skillResultId": executed_result.id,
                    "resultDigest": executed_result.result_ref.sha256,
                    "skillViewRevisionId": executed_view.id,
                    "viewModelDigest": executed_view.manifest.view_model_schema_ref.sha256,
                    "actualResultRef": actual_ref.model_dump(mode="json"),
                    "expectedOutputRef": (
                        case.expected_output_ref.model_dump(mode="json")
                        if case.expected_output_ref
                        else None
                    ),
                    "boundToCurrentRevision": bound_to_current_revision,
                    "expectedMatches": expected_matches,
                    "status": "skipped"
                    if candidate
                    else ("passed" if structural_pass else "failed"),
                },
                sort_keys=True,
            ).encode("utf-8")
            evidence_digest = hashlib.sha256(evidence_bytes).hexdigest()
            evidence_path = (
                Path(".veadk/knowledge-assets/evaluations") / f"{evidence_digest}.json"
            )
            evidence_path.write_bytes(evidence_bytes)
            evidence_ref = StorageRef(
                uri=f"local://evaluation-evidence/{evidence_digest}",
                kind="object",
                sha256=evidence_digest,
                media_type="application/json",
                bytes=len(evidence_bytes),
            )
            regression_ref = StorageRef(
                uri=f"local://evaluation-regression/{evidence_digest}",
                kind="object",
                sha256=evidence_digest,
                media_type="application/json",
                bytes=len(evidence_bytes),
            )
            case_results.append(
                EvaluationCaseResult(
                    case_id=case.id,
                    status="skipped"
                    if candidate
                    else ("passed" if structural_pass else "failed"),
                    score=0.0 if candidate else (1.0 if structural_pass else 0.0),
                    evidence_ref=evidence_ref,
                    regression_diff_ref=regression_ref,
                )
            )
        runnable_results = [item for item in case_results if item.status != "skipped"]
        score = (
            sum(item.score for item in runnable_results) / len(runnable_results)
            if runnable_results
            else 0.0
        )
        candidate_blocked = any(case.source == "agent_candidate" for case in cases)
        run_id = f"evaluation-{hashlib.sha256((draft.id + request_id).encode()).hexdigest()[:24]}"
        run = EvaluationRun(
            id=run_id,
            suite_id=suite.id,
            suite_version=suite.version,
            skill_revision_id=f"{draft.id}:{draft.revision}",
            status=(
                "failed"
                if candidate_blocked or score < suite.pass_threshold
                else "succeeded"
            ),
            score=score,
            environment=payload.environment,
            dependency_revision_refs=draft.manifest.spec.dependencies.golden_assets,
            data_revision_refs=[golden.id],
            case_results=case_results,
            evidence_ref=StorageRef(
                uri=f"local://evaluation-evidence/{cases_digest}",
                kind="object",
                sha256=cases_digest,
                media_type="application/json",
                bytes=len(cases_bytes),
            ),
            regression_ref=StorageRef(
                uri=f"local://evaluation-regression/{cases_digest}",
                kind="object",
                sha256=cases_digest,
                media_type="application/json",
                bytes=len(cases_bytes),
            ),
            started_at=now_iso(),
            finished_at=now_iso(),
        )
        gate = PolicyGateResult(
            id=f"gate-{run_id}",
            skill_revision_id=run.skill_revision_id,
            evaluation_run_id=run.id,
            decision=(
                "publishable"
                if not candidate_blocked and score >= suite.pass_threshold
                else "blocked"
            ),
            reasons=(
                ["all runnable evaluation cases bound to the current result"]
                if not candidate_blocked and score >= suite.pass_threshold
                else (
                    ["agent candidate cases require explicit confirmation"]
                    if candidate_blocked
                    else [
                        "one or more evaluation cases did not bind to the current result"
                    ]
                )
            ),
            machine_reasons=(
                [
                    "EVAL_SCORE_AT_OR_ABOVE_THRESHOLD",
                    "SKILL_RESULT_BOUND_TO_CURRENT_REVISION",
                    "SKILL_VIEW_BOUND_TO_CURRENT_REVISION",
                ]
                if not candidate_blocked and score >= suite.pass_threshold
                else (
                    ["AGENT_CANDIDATE_CONFIRMATION_REQUIRED"]
                    if candidate_blocked
                    else ["EVAL_FACT_BINDING_FAILED"]
                )
            ),
            checked_at=now_iso(),
        )
        self.repository.save_evaluation_suite(suite)
        self.repository.save_evaluation_run(run)
        self.repository.save_policy_gate_result(gate)
        if not candidate_blocked and score >= suite.pass_threshold:
            self.repository.update_skill_draft_revision_status(
                draft.id, draft.revision, "publishable"
            )
        return EvaluationRunResult(
            result_type=result_type,
            target_id=draft.id,
            status=(
                "succeeded"
                if not candidate_blocked and score >= suite.pass_threshold
                else "failed"
            ),
            evaluation_suite=suite,
            evaluation_run=run,
            policy_gate_result=gate,
        )

    def _start_invocation(
        self,
        payload: InvocationStartPayload,
        *,
        request_id: str,
        workspace_id: str,
    ) -> InvocationStartResult:
        published = None
        effective_skill_version_id = payload.skill_version_id
        if payload.skill_version_id.startswith("published://"):
            published = self.repository.published_skill_version(
                payload.skill_version_id
            )
            if published is None:
                return InvocationStartResult(
                    skill_version_id=payload.skill_version_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="PUBLISHED_SKILL_NOT_FOUND",
                        message="已发布 Skill 版本不存在或已被撤销。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            draft = self.repository.draft(published.skill_id)
            if (
                draft is None
                or draft.workspace_id != workspace_id
                or published.status != "published"
            ):
                return InvocationStartResult(
                    skill_version_id=payload.skill_version_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="PUBLISHED_SKILL_FORBIDDEN",
                        message="已发布 Skill 不属于当前工作区。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            effective_skill_version_id = f"draft://{published.skill_revision_id}"
        if not effective_skill_version_id.startswith(("draft://", "test://")):
            return InvocationStartResult(
                skill_version_id=payload.skill_version_id,
                status="not_ready",
                error=self._not_ready_error("invocation.start", request_id),
            )
        view = self.repository.skill_view_revision(payload.skill_view_revision_id)
        if view is None:
            return InvocationStartResult(
                skill_version_id=payload.skill_version_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_VIEW_REVISION_NOT_FOUND",
                    message="Invocation 必须绑定已持久化的 SkillViewRevision。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        expected_skill_revision = effective_skill_version_id.rsplit(":", 1)[-1]
        if view.id != payload.skill_view_revision_id:
            return InvocationStartResult(
                skill_version_id=payload.skill_version_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_VIEW_REVISION_MISMATCH",
                    message="Invocation 的 Skill 版本与 SkillViewRevision 不匹配。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if not expected_skill_revision.isdigit() or int(expected_skill_revision) != int(
            view.skill_revision_id.rsplit(":", 1)[-1]
        ):
            return InvocationStartResult(
                skill_version_id=payload.skill_version_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_REVISION_MISMATCH",
                    message="Invocation 的草稿 revision 与 SkillViewRevision 不匹配。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        skill_id = view.skill_revision_id.rsplit(":", 1)[0]
        skill_revision = int(expected_skill_revision)
        if published is not None:
            if published.skill_revision_id != view.skill_revision_id:
                return InvocationStartResult(
                    skill_version_id=payload.skill_version_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="PUBLISHED_SKILL_REVISION_MISMATCH",
                        message="Published Skill revision 与 View revision 不匹配。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            if published.skill_view_ref and published.skill_view_ref != view.id:
                return InvocationStartResult(
                    skill_version_id=payload.skill_version_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="PUBLISHED_SKILL_VIEW_MISMATCH",
                        message="Published Skill 未绑定当前 SkillViewRevision。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
        skill_result = self.repository.latest_skill_result(skill_id, skill_revision)
        if skill_result is None:
            return InvocationStartResult(
                skill_version_id=payload.skill_version_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_RESULT_NOT_FOUND",
                    message="Invocation 必须绑定当前 SkillViewRevision 对应的真实 SkillResult。",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        invocation_id = (
            "invocation-"
            + hashlib.sha256(
                f"{payload.skill_version_id}:{payload.skill_view_revision_id}:{request_id}".encode()
            ).hexdigest()[:24]
        )
        now = now_iso()
        invocation = Invocation(
            id=invocation_id,
            skill_version_id=payload.skill_version_id,
            skill_view_revision_id=payload.skill_view_revision_id,
            caller_id=payload.caller_id,
            workspace_id=workspace_id,
            status="succeeded",
            input_ref=payload.input_ref,
            result_ref=skill_result.result_ref,
            trace_id=f"trace-{invocation_id}",
            actual_data_revision_refs=skill_result.golden_asset_revision_refs,
            started_at=now,
            finished_at=now,
        )
        self.repository.save_invocation(invocation)
        return InvocationStartResult(
            skill_version_id=payload.skill_version_id,
            status="succeeded",
            invocation=invocation,
            skill_result=skill_result,
            data_revision_refs=skill_result.golden_asset_revision_refs,
        )

    def _export_artifact(
        self,
        payload: ArtifactExportPayload,
        *,
        request_id: str,
        workspace_id: str,
    ) -> ArtifactExportResult:
        draft = self.repository.draft(payload.resource_id)
        if draft is None or draft.workspace_id != workspace_id:
            return ArtifactExportResult(
                resource_id=payload.resource_id,
                status="failed",
                error=ErrorEnvelope(
                    code="RESOURCE_NOT_FOUND",
                    message="只能导出当前工作区的 Skill View 资源。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        view = self.repository.latest_skill_view_revision(
            f"{draft.id}:{draft.revision}"
        )
        if view is None:
            return ArtifactExportResult(
                resource_id=payload.resource_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_VIEW_REVISION_REQUIRED",
                    message="导出需要已持久化的 SkillViewRevision。",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        if payload.format == "html":
            source = (
                Path(".veadk/knowledge-assets/bundles")
                / f"{view.result_ref.sha256}.html"
            )
            media_type = "text/html"
            suffix = "html"
        else:
            result = self.repository.latest_skill_result(draft.id, draft.revision)
            if result is None:
                return ArtifactExportResult(
                    resource_id=payload.resource_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="SKILL_RESULT_REQUIRED",
                        message="导出需要当前 revision 的真实 SkillResult。",
                        retryable=True,
                        request_id=request_id,
                    ),
                )
            source = (
                Path(".veadk/knowledge-assets/results")
                / f"{result.result_ref.sha256}.json"
            )
            if not source.exists() and result.result_ref.uri.startswith(
                "local://kind-runtime/results/"
            ):
                # Worker 3 owns the content-addressed result store. Keep the
                # export command's shared BFF contract able to consume that
                # real result without copying or reimplementing the runtime.
                source = (
                    Path(".veadk/knowledge-assets/kind-runtime/results")
                    / f"{result.result_ref.sha256}.json"
                )
            media_type = "text/csv" if payload.format == "csv" else "application/json"
            suffix = "csv" if payload.format == "csv" else "json"
        try:
            data = source.read_bytes()
        except OSError as error:
            return ArtifactExportResult(
                resource_id=payload.resource_id,
                status="failed",
                error=ErrorEnvelope(
                    code="ARTIFACT_NOT_FOUND",
                    message=f"导出产物不存在：{error}",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        if payload.format == "csv":
            try:
                result_payload = json.loads(data.decode("utf-8"))
                output = result_payload.get("output", "")
                csv_buffer = io.StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(["output"])
                writer.writerow([output])
                data = csv_buffer.getvalue().encode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                return ArtifactExportResult(
                    resource_id=payload.resource_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="ARTIFACT_FORMAT_FAILED",
                        message="当前结果无法转换为 CSV。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
        digest = hashlib.sha256(data).hexdigest()
        destination = Path(".veadk/knowledge-assets/exports") / f"{digest}.{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(data)
        return ArtifactExportResult(
            resource_id=payload.resource_id,
            status="succeeded",
            artifact_ref=StorageRef(
                uri=f"local://export/{digest}.{suffix}",
                kind="object",
                sha256=digest,
                media_type=media_type,
                bytes=len(data),
            ),
        )

    def _share_view(
        self, resource_id: str, *, request_id: str, workspace_id: str
    ) -> ResourceShareResult:
        draft = self.repository.draft(resource_id)
        if draft is None or draft.workspace_id != workspace_id:
            return ResourceShareResult(
                resource_id=resource_id,
                status="failed",
                error=ErrorEnvelope(
                    code="RESOURCE_NOT_FOUND",
                    message="只能分享当前工作区的 Skill View。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        view = self.repository.latest_skill_view_revision(
            f"{draft.id}:{draft.revision}"
        )
        if view is None:
            return ResourceShareResult(
                resource_id=resource_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_VIEW_REVISION_REQUIRED",
                    message="分享需要已持久化的 SkillViewRevision。",
                    retryable=True,
                    request_id=request_id,
                ),
            )
        grant_id = (
            "share-"
            + hashlib.sha256(
                f"{resource_id}:{view.id}:{workspace_id}".encode()
            ).hexdigest()[:24]
        )
        grant = SkillViewShareGrant(
            id=grant_id,
            resource_id=resource_id,
            skill_view_revision_id=view.id,
            workspace_id=workspace_id,
            created_at=now_iso(),
        )
        self.repository.save_skill_view_share(grant)
        return ResourceShareResult(
            resource_id=resource_id,
            status="succeeded",
            share_grant=grant,
        )

    def _assistant_turn(
        self,
        payload: AssistantTurnPayload,
        *,
        request_id: str,
        workspace_id: str,
    ) -> AssistantTurnResult:
        patch = payload.patch
        if patch is None:
            return AssistantTurnResult(
                skill_id=payload.context.skill_id if payload.context else "unknown",
                error=ErrorEnvelope(
                    code="PATCH_REQUIRED",
                    message="assistant.turn 必须携带服务端可校验的 typed patch。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        draft = self.repository.draft(patch.skill_id)
        if draft is None or draft.workspace_id != workspace_id:
            return AssistantTurnResult(
                skill_id=patch.skill_id,
                status="failed",
                error=ErrorEnvelope(
                    code="SKILL_NOT_FOUND",
                    message="patch 目标 Skill 不存在或不属于当前工作区。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if payload.context is None or payload.context.skill_id != patch.skill_id:
            return AssistantTurnResult(
                skill_id=patch.skill_id,
                status="failed",
                error=ErrorEnvelope(
                    code="PATCH_CONTEXT_MISMATCH",
                    message="Context Envelope 必须绑定当前 Skill。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        if patch.undo_token is not None:
            history = self.repository.patch_history(patch.undo_token)
            if history is None or history["skill_id"] != patch.skill_id:
                return AssistantTurnResult(
                    skill_id=patch.skill_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="UNDO_TOKEN_INVALID",
                        message="撤销令牌不存在或不属于当前 Skill。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            if patch.operation != history["operation"]:
                return AssistantTurnResult(
                    skill_id=patch.skill_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="UNDO_PATCH_MISMATCH",
                        message="撤销操作必须复用原 patch 的操作类型。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            patch = patch.model_copy(update={"value": str(history["before_value"])})
        if patch.base_revision != draft.revision:
            return AssistantTurnResult(
                skill_id=patch.skill_id,
                status="failed",
                error=ErrorEnvelope(
                    code="CONFLICT",
                    message="Skill 草稿版本已变化，请刷新后重试。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
        metadata = draft.manifest.metadata
        spec = draft.manifest.spec
        before: str
        if patch.operation == "set_description":
            before = metadata.description
            manifest = draft.manifest.model_copy(
                update={
                    "metadata": metadata.model_copy(update={"description": patch.value})
                }
            )
        elif patch.operation == "set_runtime_ref":
            before = spec.runtime_ref
            manifest = draft.manifest.model_copy(
                update={"spec": spec.model_copy(update={"runtime_ref": patch.value})}
            )
        else:
            before = spec.evaluation_suite_ref or ""
            manifest = draft.manifest.model_copy(
                update={
                    "spec": spec.model_copy(
                        update={"evaluation_suite_ref": patch.value or None}
                    )
                }
            )
        validate_manifest_policy(manifest)
        updated, _ = self.repository.save_manifest(
            draft_id=draft.id,
            base_revision=patch.base_revision,
            manifest=manifest,
            request_id=request_id,
            idempotency_key=f"assistant:{patch.patch_id}",
        )
        undo_token = hashlib.sha256(
            f"{patch.patch_id}:{draft.id}:{updated.revision}:{before}".encode()
        ).hexdigest()
        self.repository.save_patch_history(
            patch.patch_id,
            undo_token,
            draft.id,
            patch.base_revision,
            patch.operation,
            before,
            patch.value,
        )
        diff = AssistantDiff(
            patch_id=patch.patch_id,
            skill_id=draft.id,
            base_revision=patch.base_revision,
            next_revision=updated.revision,
            operation=patch,
            before=before,
            after=patch.value,
            undo_token=undo_token,
        )
        rerun = self._run_skill_draft(
            SkillDraftRunPayload(
                draft_id=draft.id,
                revision=updated.revision,
                trace_id=f"assistant-{request_id}",
            ),
            request_id=request_id,
        )
        return AssistantTurnResult(
            skill_id=draft.id,
            status="succeeded" if rerun.status == "ready_for_evaluation" else "failed",
            diff=diff,
            rerun=rerun,
            error=rerun.error,
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
        elif isinstance(raw_manifest, dict) and (
            raw_manifest.get("kind") == "Skill"
            or "apiVersion" in raw_manifest
            or "api_version" in raw_manifest
        ):
            manifest = SkillManifest.model_validate(raw_manifest)
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

    def _complete_builder_operation(
        self,
        typed: SkillDraftRunPayload,
        request_id: str,
        operation_id: str,
        workspace_id: str,
        job_id: str | None = None,
    ) -> None:
        """Run one durable Builder operation outside the HTTP request."""
        job = (
            self._builder_jobs.get(job_id)
            if job_id is not None
            else self._builder_jobs.enqueue(
                job_type="skill-draft.run",
                idempotency_key=operation_id,
                profile=self._builder_profile,
                max_attempts=3,
            )
        )
        self._builder_job_ids[operation_id] = job.job_id
        owner = f"builder:{operation_id}"
        try:
            self._builder_jobs.lease(job_id=job.job_id, owner=owner, ttl_seconds=30)
            self._builder_jobs.heartbeat(job_id=job.job_id, owner=owner, ttl_seconds=30)
        except JobLeaseError:
            return
        try:
            result = self._run_skill_draft(
                typed, request_id=request_id, operation_id=operation_id
            )
        except Exception as error:  # worker boundary must always close the Operation
            result = SkillDraftRunResult(
                draft_id=typed.draft_id,
                status="failed",
                error=ErrorEnvelope(
                    code="BUILDER_WORKER_FAILED",
                    message=str(error),
                    retryable=True,
                    request_id=request_id,
                ),
            )
            failed_job = self._builder_jobs.fail(
                job_id=job.job_id,
                owner=owner,
                reason="builder-worker-failed",
            )
            if failed_job.status == "queued":
                self._builder_executor.submit(
                    self._complete_builder_operation,
                    typed,
                    request_id,
                    operation_id,
                    workspace_id,
                    job.job_id,
                )
                return
        else:
            if result.status == "cancelled":
                self._builder_jobs.complete(job_id=job.job_id, owner=owner)
            elif result.status != "ready_for_evaluation":
                failed_job = self._builder_jobs.fail(
                    job_id=job.job_id,
                    owner=owner,
                    reason=result.error.code if result.error else "builder-incomplete",
                )
                if failed_job.status == "queued":
                    self._builder_executor.submit(
                        self._complete_builder_operation,
                        typed,
                        request_id,
                        operation_id,
                        workspace_id,
                        job.job_id,
                    )
                    return
            else:
                self._builder_jobs.complete(job_id=job.job_id, owner=owner)
        terminal_type = (
            "cancelled"
            if result.status == "cancelled"
            else "succeeded"
            if result.status == "ready_for_evaluation"
            else "failed"
        )
        terminal_event = OperationEvent(
            operation_id=operation_id,
            event_id=f"{operation_id}:{terminal_type}",
            sequence=3,
            occurred_at=now_iso(),
            type=terminal_type,
            terminal=True,
            result=result,
            error=result.error,
        )
        self.repository.append_operation_event(
            operation_id,
            terminal_event,
            status=terminal_type,
            result=result.model_dump(mode="json", by_alias=True),
            error=result.error,
        )
        self.audit_recorder.record_audit(
            request_id=request_id,
            operation_id=operation_id,
            workspace_id=workspace_id,
            action="skill-draft.run",
            resource_id=typed.draft_id,
            outcome=terminal_type,
        )

    def _run_evaluation_quality_command(
        self,
        command: str,
        payload: dict[str, object],
        *,
        request_id: str,
    ) -> CommandResponse:
        """Expose W4's typed domain through Main's public command seam."""
        if self._evaluation_quality is None:
            result = EvaluationQualityCommandResult(
                result_type=command,
                status="failed",
                message="Evaluation persistence is not configured.",
                error=ErrorEnvelope(
                    code="EVALUATION_PERSISTENCE_NOT_CONFIGURED",
                    message="当前仓库未配置 Evaluation 持久化。",
                    retryable=False,
                    request_id=request_id,
                ),
            )
            return CommandResponse(accepted=False, request_id=request_id, result=result)
        try:
            if command == "evaluation-suite.create":
                typed = EvaluationSuiteCreatePayload.model_validate(payload)
                value = self._evaluation_quality.create_suite(
                    suite_id=typed.suite_id,
                    skill_id=typed.skill_id,
                    cases=typed.cases,
                    pass_threshold=typed.pass_threshold,
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", suite=value
                )
            elif command == "evaluation-suite.revise":
                typed = EvaluationSuiteRevisePayload.model_validate(payload)
                value = self._evaluation_quality.revise_suite(
                    typed.suite_id, typed.version, typed.additions
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", suite=value
                )
            elif command == "evaluation-case.import":
                typed = EvaluationCaseImportPayload.model_validate(payload)
                value = self._evaluation_quality.import_cases(
                    typed.content, media_type=typed.media_type
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", cases=list(value)
                )
            elif command == "evaluation-case.adopt-history":
                typed = EvaluationCaseAdoptHistoryPayload.model_validate(payload)
                value = self._evaluation_quality.adopt_historical_case(
                    case_id=typed.case_id,
                    category=CaseCategory(typed.category),
                    input=typed.input,
                    expected=typed.expected,
                    provenance_ref=typed.provenance_ref,
                    source=CaseSource(typed.source),
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", cases=[value]
                )
            elif command == "evaluation-case.generate-candidates":
                typed = EvaluationCaseGenerateCandidatePayload.model_validate(payload)
                value = self._evaluation_quality.agent_candidate(
                    case_id=typed.case_id,
                    category=CaseCategory(typed.category),
                    input=typed.input,
                    expected=typed.expected,
                    provenance_ref=typed.provenance_ref,
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", cases=[value]
                )
            elif command == "evaluation-case.confirm-candidates":
                typed = EvaluationCaseConfirmPayload.model_validate(payload)
                value = self._evaluation_quality.confirm_candidates(
                    typed.suite_id, typed.version, typed.case_ids
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", suite=value
                )
            elif command == "evaluation-run.start":
                typed = EvaluationRunStartPayload.model_validate(payload)
                run = self._evaluation_quality.start_run(
                    suite_id=typed.suite_id,
                    suite_version=typed.suite_version,
                    provenance=typed.provenance,
                    selected_case_ids=typed.selected_case_ids or None,
                )
                try:
                    run = self._evaluation_quality.execute(run.id)
                except RuntimeError as error:
                    run = run.model_copy(
                        update={"status": "failed", "finished_at": now_iso()}
                    )
                    self._evaluation_quality.repository.save_run(run)
                    result = EvaluationQualityCommandResult(
                        result_type=command,
                        status="failed",
                        run=run,
                        message=str(error),
                        error=ErrorEnvelope(
                            code="EVALUATION_EXECUTOR_NOT_CONFIGURED",
                            message="评测执行器未配置，已明确失败。",
                            retryable=False,
                            request_id=request_id,
                        ),
                    )
                else:
                    result = EvaluationQualityCommandResult(
                        result_type=command,
                        status="succeeded" if run.status == "succeeded" else "failed",
                        run=run,
                    )
            elif command == "evaluation-run.cancel":
                typed = EvaluationRunActionPayload.model_validate(payload)
                run = self._evaluation_quality.cancel(typed.run_id)
                result = EvaluationQualityCommandResult(
                    result_type=command,
                    status="succeeded" if run.status == "cancelled" else "failed",
                    run=run,
                )
            elif command == "evaluation-run.resume":
                typed = EvaluationRunActionPayload.model_validate(payload)
                run = self._evaluation_quality.resume(typed.run_id)
                result = EvaluationQualityCommandResult(
                    result_type=command,
                    status="succeeded" if run.status == "succeeded" else "failed",
                    run=run,
                )
            elif command == "evaluation-run.retry":
                typed = EvaluationRunRetryPayload.model_validate(payload)
                run = self._evaluation_quality.retry(typed.run_id)
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", run=run
                )
            elif command in {
                "evaluation-fix.propose",
                "evaluation-fix.propose-all-unresolved",
            }:
                if command == "evaluation-fix.propose":
                    typed = EvaluationFixProposePayload.model_validate(payload)
                    plan = self._evaluation_quality.propose_fix(
                        run_id=typed.run_id,
                        issue_case_ids=typed.issue_case_ids,
                        affected_case_ids=typed.affected_case_ids,
                        conflicts=typed.conflicts,
                        patch=typed.patch,
                    )
                else:
                    typed = EvaluationFixProposeAllPayload.model_validate(payload)
                    plan = self._evaluation_quality.propose_all_unresolved(
                        run_id=typed.run_id,
                        affected_case_ids=typed.affected_case_ids,
                        conflicts=typed.conflicts,
                        patch=typed.patch,
                    )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", fix_plan=plan
                )
            elif command in {"evaluation-fix.apply", "evaluation-fix.undo"}:
                typed = EvaluationFixActionPayload.model_validate(payload)
                plan = (
                    self._evaluation_quality.apply_fix(typed.plan_id)
                    if command.endswith("apply")
                    else self._evaluation_quality.undo_fix(typed.plan_id)
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", fix_plan=plan
                )
            elif command == "policy-gate.evaluate":
                typed = PolicyGateEvaluatePayload.model_validate(payload)
                gate = self._evaluation_quality.evaluate_run_policy(
                    typed.run_id, typed.checks
                )
                result = EvaluationQualityCommandResult(
                    result_type=command, status="succeeded", gate=gate
                )
            else:
                raise ValueError(f"unsupported evaluation quality command: {command}")
        except (KeyError, ValueError, RuntimeError) as error:
            message = str(error)
            result = EvaluationQualityCommandResult(
                result_type=command,
                status="failed",
                message=message,
                error=ErrorEnvelope(
                    code=(
                        "AGENT_CANDIDATE_CONFIRMATION_REQUIRED"
                        if "explicit confirmation" in message
                        else "EVALUATION_COMMAND_FAILED"
                    ),
                    message=message,
                    retryable=False,
                    request_id=request_id,
                ),
            )
        return CommandResponse(
            accepted=result.status == "succeeded",
            request_id=request_id,
            result=result,
        )

    def unsupported(
        self,
        command: str,
        request_id: str,
        payload: dict[str, object],
        *,
        workspace_id: str = "workspace-local",
        idempotency_key: str | None = None,
        async_mode: bool = False,
    ) -> CommandResponse:
        result: CommandResult
        if command in {
            "evaluation-suite.create",
            "evaluation-suite.revise",
            "evaluation-case.import",
            "evaluation-case.adopt-history",
            "evaluation-case.generate-candidates",
            "evaluation-case.confirm-candidates",
            "evaluation-run.start",
            "evaluation-run.cancel",
            "evaluation-run.resume",
            "evaluation-run.retry",
            "evaluation-fix.propose",
            "evaluation-fix.propose-all-unresolved",
            "evaluation-fix.apply",
            "evaluation-fix.undo",
            "policy-gate.evaluate",
        }:
            return self._run_evaluation_quality_command(
                command, payload, request_id=request_id
            )
        if command in {"evaluation.run", "evaluation.apply"}:
            typed = EvaluationPayload.model_validate(payload)
            result = self._run_evaluation(
                typed,
                request_id=request_id,
                result_type=command,
            )
            return CommandResponse(
                accepted=result.status == "succeeded",
                request_id=request_id,
                result=result,
            )
        if command == "source.profile":
            typed = SourceProfilePayload.model_validate(payload)
            if self.repository.source_revision(typed.source_revision_id) is None:
                result = SourceProfileResult(
                    source_revision_id=typed.source_revision_id,
                    error=self._not_ready_error(command, request_id),
                )
                return CommandResponse(
                    accepted=False, request_id=request_id, result=result
                )
            result = self._run_profile(typed, request_id)
        elif command == "source.clean":
            typed = SourceCleanPayload.model_validate(payload)
            if self.repository.source_revision(typed.source_revision_id) is None:
                result = SourceCleanResult(
                    source_revision_id=typed.source_revision_id,
                    recipe_id=typed.recipe_id,
                    error=self._not_ready_error(command, request_id),
                )
                return CommandResponse(
                    accepted=False, request_id=request_id, result=result
                )
            draft = self.repository.draft(str(payload.get("draft_id", "")))
            workspace_id = draft.workspace_id if draft else "workspace-local"
            result = self._run_clean(typed, workspace_id)
        elif command == "skill-draft.retry":
            typed = SkillDraftRetryPayload.model_validate(payload)
            previous = self.repository.operation(typed.retry_of_operation_id)
            if previous is None:
                result = SkillDraftRunResult(
                    draft_id=typed.draft_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="RETRY_SOURCE_NOT_FOUND",
                        message="待重试的 Builder Operation 不存在。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            elif previous.status != "failed" or not previous.result:
                result = SkillDraftRunResult(
                    draft_id=typed.draft_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="RETRY_NOT_ALLOWED",
                        message="只有失败或部分完成的 Builder Operation 可以重试。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            else:
                run_payload = typed.model_dump(
                    mode="python", exclude={"retry_of_operation_id"}
                )
                retried = self.unsupported(
                    "skill-draft.run",
                    request_id,
                    run_payload,
                    workspace_id=workspace_id,
                    idempotency_key=idempotency_key,
                    async_mode=async_mode,
                )
                return retried
        elif command == "skill-draft.run":
            typed = SkillDraftRunPayload.model_validate(payload)
            operation_id = (
                "run-"
                + hashlib.sha256((idempotency_key or request_id).encode()).hexdigest()[
                    :24
                ]
            )
            self.repository.create_operation(operation_id, request_id)
            existing = self.repository.operation(operation_id)
            if existing is not None and existing.status == "cancelled":
                cancelled_result = SkillDraftRunResult(
                    draft_id=typed.draft_id,
                    status="cancelled",
                    error=ErrorEnvelope(
                        code="EXECUTION_CANCELLED",
                        message="执行已取消，未启动新的 Skill Builder 运行。",
                        retryable=True,
                        request_id=request_id,
                    ),
                )
                return CommandResponse(
                    accepted=False,
                    request_id=request_id,
                    operation_id=operation_id,
                    result=cancelled_result,
                )
            if existing is not None and existing.result is not None:
                return CommandResponse(
                    accepted=existing.status == "succeeded",
                    request_id=request_id,
                    operation_id=operation_id,
                    result=existing.result,
                )
            accepted_event = OperationEvent(
                operation_id=operation_id,
                event_id=f"{operation_id}:accepted",
                sequence=1,
                occurred_at=now_iso(),
                type="accepted",
                terminal=False,
            )
            self.repository.append_operation_event(
                operation_id, accepted_event, status="running"
            )
            progress_event = OperationEvent(
                operation_id=operation_id,
                event_id=f"{operation_id}:progress",
                sequence=2,
                occurred_at=now_iso(),
                type="progress",
                terminal=False,
            )
            self.repository.append_operation_event(
                operation_id, progress_event, status="running"
            )
            if async_mode:
                job = self._builder_jobs.enqueue(
                    job_type="skill-draft.run",
                    idempotency_key=operation_id,
                    profile=self._builder_profile,
                    max_attempts=3,
                )
                self._builder_job_ids[operation_id] = job.job_id
                self._builder_executor.submit(
                    self._complete_builder_operation,
                    typed,
                    request_id,
                    operation_id,
                    workspace_id,
                    job.job_id,
                )
                return CommandResponse(
                    accepted=True,
                    request_id=request_id,
                    operation_id=operation_id,
                )
            result = self._run_skill_draft(
                typed, request_id=request_id, operation_id=operation_id
            )
            terminal_type = (
                "cancelled"
                if result.status == "cancelled"
                else "succeeded"
                if result.status == "ready_for_evaluation"
                else "failed"
            )
            terminal_event = OperationEvent(
                operation_id=operation_id,
                event_id=f"{operation_id}:{terminal_type}",
                sequence=3,
                occurred_at=now_iso(),
                type=terminal_type,
                terminal=True,
                result=result,
                error=result.error,
            )
            self.repository.append_operation_event(
                operation_id,
                terminal_event,
                status=terminal_type,
                result=result.model_dump(mode="json", by_alias=True),
                error=result.error,
            )
            return CommandResponse(
                accepted=terminal_type == "succeeded",
                request_id=request_id,
                operation_id=operation_id,
                result=result,
            )
        elif command == "artifact.export":
            typed = ArtifactExportPayload.model_validate(payload)
            result = self._export_artifact(
                typed, request_id=request_id, workspace_id=workspace_id
            )
        elif command == "resource.share":
            result = self._share_view(
                str(payload["resource_id"]),
                request_id=request_id,
                workspace_id=workspace_id,
            )
        elif command == "resource.revoke":
            resource_id = str(payload["resource_id"])
            reason = str(payload.get("reason", "revoked"))
            golden = self.repository.latest_golden_asset_revision(workspace_id)
            if golden is not None and golden.id == resource_id:
                self.repository.revoke_asset(
                    resource_id, workspace_id, request_id, reason
                )
            result = NotReadyCommandResult(
                command=command,
                error=self._not_ready_error(command, request_id),
            )
        elif command == "publication.publish":
            typed = PublicationPublishPayload.model_validate(payload)
            draft = self.repository.draft(typed.draft_id)
            skill_revision_id = f"{typed.draft_id}:{typed.revision}"
            view = self.repository.latest_skill_view_revision(skill_revision_id)
            if draft is None or draft.revision != typed.revision:
                result = PublicationPublishResult(
                    draft_id=typed.draft_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="DRAFT_REVISION_NOT_FOUND",
                        message="待发布的 SkillDraft revision 不存在。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            elif view is None:
                result = PublicationPublishResult(
                    draft_id=typed.draft_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="SKILL_VIEW_REVISION_NOT_FOUND",
                        message="发布必须绑定真实 SkillViewRevision。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            else:
                run = self.repository.latest_evaluation_run(skill_revision_id)
                gate = None
                if run is not None:
                    gate = self.repository.policy_gate_result(f"gate-{run.id}")
                if (
                    run is None
                    or run.skill_revision_id != skill_revision_id
                    or run.status != "succeeded"
                    or gate is None
                    or gate.decision != "publishable"
                    or gate.evaluation_run_id != run.id
                ):
                    result = PublicationPublishResult(
                        draft_id=typed.draft_id,
                        status="failed",
                        error=ErrorEnvelope(
                            code="POLICY_GATE_REQUIRED",
                            message="发布前必须存在当前 revision 的成功 EvaluationRun 与 publishable PolicyGate。",
                            retryable=False,
                            request_id=request_id,
                        ),
                    )
                else:
                    manifest_bytes = draft.manifest.model_dump_json(
                        by_alias=True, exclude_none=False
                    ).encode()
                    digest = hashlib.sha256(
                        manifest_bytes + view.model_dump_json(by_alias=True).encode()
                    ).hexdigest()
                    version = PublishedSkillVersion(
                        id=f"published://{typed.draft_id}:{typed.semver}",
                        skill_id=typed.draft_id,
                        semver=typed.semver,
                        manifest=draft.manifest,
                        skill_revision_id=skill_revision_id,
                        digest=digest,
                        evaluation_run_id=run.id,
                        policy_gate_result_id=gate.id,
                        skill_view_ref=view.id,
                        published_at=now_iso(),
                    )
                    self.repository.save_published_skill_version(version)
                    self.repository.update_skill_draft_revision_status(
                        typed.draft_id, typed.revision, "published"
                    )
                    result = PublicationPublishResult(
                        draft_id=typed.draft_id,
                        status="succeeded",
                        published_version=version,
                    )
        elif command == "refresh.run":
            typed = RefreshRunPayload.model_validate(payload)
            draft = self.repository.draft(typed.skill_id)
            if draft is None or draft.workspace_id != workspace_id:
                result = RefreshRunResult(
                    skill_id=typed.skill_id,
                    status="failed",
                    error=ErrorEnvelope(
                        code="SKILL_NOT_FOUND",
                        message="待刷新的 Skill 不存在或不属于当前工作区。",
                        retryable=False,
                        request_id=request_id,
                    ),
                )
            else:
                previous = self.repository.latest_golden_asset_revision(workspace_id)
                run = RefreshRun(
                    id=f"refresh-{hashlib.sha256(request_id.encode()).hexdigest()[:24]}",
                    skill_id=typed.skill_id,
                    trigger=typed.trigger,
                    status="running",
                    current_revision=previous.revision if previous else None,
                    last_good_revision=previous.revision if previous else None,
                    started_at=now_iso(),
                )
                try:
                    sources = self.repository.source_revisions_for_workspace(
                        workspace_id
                    )
                    if not sources:
                        raise KnowledgeAssetRepositoryError(
                            "SOURCE_NOT_FOUND", "没有可刷新的来源。"
                        )
                    source = sources[-1]
                    current_bytes = self._source_path(source.id).read_bytes()
                    current_schema = self._schema_digest(
                        current_bytes, source.source_type
                    )
                    if source.schema_ref and current_schema != source.schema_ref.sha256:
                        raise KnowledgeAssetRepositoryError(
                            "SCHEMA_CHANGED", "来源结构已变化，刷新被安全门禁拒绝。"
                        )
                    current_digest = hashlib.sha256(current_bytes).hexdigest()
                    if current_digest != source.source_digest:
                        source = self._register_local_source(
                            str(self._source_path(source.id)),
                            workspace_id=workspace_id,
                            request_id=request_id,
                        )
                        assert source is not None
                    self._run_profile(
                        SourceProfilePayload(source_revision_id=source.id),
                        request_id,
                    )
                    cleaned = self._run_clean(
                        SourceCleanPayload(
                            source_revision_id=source.id,
                            recipe_id=f"refresh-{source.id}",
                        ),
                        workspace_id,
                    )
                    run = run.model_copy(
                        update={
                            "status": "succeeded",
                            "staging_ref": cleaned.golden_asset_revision.storage_ref,
                            "current_revision": cleaned.golden_asset_revision.revision,
                            "last_good_revision": cleaned.golden_asset_revision.revision,
                            "finished_at": now_iso(),
                        }
                    )
                    result = RefreshRunResult(
                        skill_id=typed.skill_id,
                        status="succeeded",
                        refresh_run=run,
                    )
                except (KnowledgeAssetRepositoryError, OSError, UnicodeError) as error:
                    code = getattr(error, "code", "SOURCE_READ_FAILED")
                    run = run.model_copy(
                        update={
                            "status": "failed",
                            "error_code": code,
                            "finished_at": now_iso(),
                        }
                    )
                    result = RefreshRunResult(
                        skill_id=typed.skill_id,
                        status="failed",
                        refresh_run=run,
                        error=ErrorEnvelope(
                            code=code,
                            message=str(error),
                            retryable=False,
                            request_id=request_id,
                        ),
                    )
                self.repository.save_refresh_run(run)
        elif command == "invocation.start":
            typed = InvocationStartPayload.model_validate(payload)
            result = self._start_invocation(
                typed,
                request_id=request_id,
                workspace_id=workspace_id,
            )
        elif command == "assistant.turn":
            typed = AssistantTurnPayload.model_validate(payload)
            result = self._assistant_turn(
                typed,
                request_id=request_id,
                workspace_id=workspace_id,
            )
        elif command in {"evaluation.run", "evaluation.apply"}:
            typed = EvaluationPayload.model_validate(payload)
            result = self._run_evaluation(
                typed,
                request_id=request_id,
                result_type=command,
            )
        else:
            result = InvocationStartResult(
                skill_version_id="unsupported",
                error=self._not_ready_error(command, request_id),
            )
        accepted_statuses = {
            "planning",
            "awaiting_input",
            "running",
            "partially_succeeded",
            "succeeded",
            "ready_for_evaluation",
        }
        return CommandResponse(
            accepted=getattr(result, "status", "not_ready") in accepted_statuses,
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

    async def authoring_operation(self, operation_id: str) -> AuthoringReadModel | None:
        if self._authoring is None:
            return None
        operation = await self._authoring.repository.get_operation(operation_id)
        if operation is None:
            return None
        return await self._authoring.read_operation(operation_id)

    def cancel(self, operation_id: str, request_id: str) -> OperationResponse:
        job_id = self._builder_job_ids.get(operation_id)
        if job_id is None:
            job = self._builder_jobs.find_by_key(
                profile=self._builder_profile, idempotency_key=operation_id
            )
            job_id = job.job_id if job is not None else None
        if job_id is not None:
            self._builder_jobs.request_cancel(job_id=job_id)
        return self.repository.cancel_operation(operation_id, request_id)
