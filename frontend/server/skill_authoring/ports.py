"""Adapters and repositories owned by the authoring worker.

These are deliberately dependency-inverted.  Main can wire the repository to
its existing persistence and the model adapter to the existing Agent/model
gateway without importing either implementation into this domain.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol, Sequence

from pydantic import BaseModel

from .models import (
    BuildPlan,
    ContextEnvelope,
    DraftRevision,
    PlanNode,
    QueryPlan,
    ResolvedContext,
    ResolvedResource,
    ResourceRef,
    Scope,
    SemanticKindSpec,
    AnalysisKindSpec,
    GraphOntologyKindSpec,
    KnowledgeKindSpec,
    MonitoringKindSpec,
    InputContract,
    OutputContract,
    SkillKind,
    AuthoringErrorCode,
    SkillAuthoringError,
    digest,
)


class ResourceResolver(Protocol):
    async def resolve(
        self, envelope: ContextEnvelope, refs: Sequence[ResourceRef]
    ) -> ResolvedContext: ...


class ModelGateway(Protocol):
    async def propose_plan(
        self, context: ResolvedContext, *, requested_kind: SkillKind | None
    ) -> BuildPlan: ...


class AuthoringRepository(Protocol):
    async def save_operation(self, operation: object) -> None: ...
    async def get_operation(self, operation_id: str) -> object | None: ...
    async def save_event(self, event: object) -> None: ...
    async def list_events(self, operation_id: str) -> tuple[object, ...]: ...
    async def save_draft(self, draft: DraftRevision) -> None: ...
    async def get_draft(self, draft_id: str, revision: int | None = None) -> DraftRevision | None: ...
    async def list_drafts(self, workspace_id: str, caller_id: str) -> tuple[DraftRevision, ...]: ...
    async def save_create_request(self, operation_id: str, request: object) -> None: ...
    async def get_create_request(self, operation_id: str) -> object | None: ...
    async def save_patch(self, proposal: object) -> None: ...
    async def get_patch(self, patch_id: str) -> object | None: ...


class Worker3Executor(Protocol):
    async def request_execution(self, request: object) -> object: ...


class InMemoryResourceResolver:
    """Server-side resource catalog used by integration wiring and tests."""

    def __init__(self, resources: Sequence[ResolvedResource] = ()) -> None:
        self._resources = {
            (item.ref.scope, item.ref.kind, item.ref.object_id, item.ref.revision): item
            for item in resources
        }
        self._access: dict[tuple[str, str], frozenset[tuple[Scope, str, str, str]]] = {}

    def grant(
        self,
        caller_id: str,
        workspace_id: str,
        resource: ResourceRef,
    ) -> None:
        self._access.setdefault((caller_id, workspace_id), set()).add(
            (resource.scope, resource.kind, resource.object_id, resource.revision)
        )

    async def resolve(
        self, envelope: ContextEnvelope, refs: Sequence[ResourceRef]
    ) -> ResolvedContext:
        unique: list[ResolvedResource] = []
        seen: set[tuple[Scope, str, str, str]] = set()
        for ref in refs:
            key = (ref.scope, ref.kind, ref.object_id, ref.revision)
            if key in seen:
                continue
            seen.add(key)
            resource = self._resources.get(key)
            if resource is None:
                raise SkillAuthoringError(
                    AuthoringErrorCode.RESOURCE_NOT_FOUND,
                    f"resource revision {ref.object_id}@{ref.revision} was not found",
                )
            if key not in self._access.get((envelope.caller_id, envelope.workspace_id), set()):
                raise SkillAuthoringError(
                    AuthoringErrorCode.PERMISSION_DENIED,
                    f"caller is not authorized for {ref.object_id}@{ref.revision}",
                )
            if not resource.authorized:
                raise SkillAuthoringError(
                    AuthoringErrorCode.PERMISSION_DENIED,
                    f"resource authorization was revoked for {ref.object_id}",
                )
            if (
                envelope.freshness.require_fixed_revision
                and ref.revision not in envelope.fixed_revisions
            ):
                raise SkillAuthoringError(
                    AuthoringErrorCode.INVALID_CONTEXT,
                    f"resource {ref.object_id} is not pinned to a fixed revision",
                )
            unique.append(resource)
        authorized_permissions = tuple(
            sorted(
                {
                    capability
                    for item in unique
                    for capability in item.capabilities
                }
            )
        )
        context_digest = digest(
            {
                "caller": envelope.caller_id,
                "workspace": envelope.workspace_id,
                "prompt": envelope.prompt,
                "refs": [item.model_dump(mode="json") for item in unique],
                "permissions": envelope.permissions,
                "authorized_permissions": authorized_permissions,
                "fixed_revisions": envelope.fixed_revisions,
            }
        )
        return ResolvedContext(
            envelope=envelope,
            resources=tuple(unique),
            authorized_permissions=authorized_permissions,
            context_digest=context_digest,
        )


class CredentialBlockedGateway:
    """Production-safe adapter when the configured model gateway has no credentials."""

    async def propose_plan(
        self, context: ResolvedContext, *, requested_kind: SkillKind | None
    ) -> BuildPlan:
        del context, requested_kind
        raise SkillAuthoringError(
            AuthoringErrorCode.CREDENTIAL_BLOCKED,
            "model gateway credentials are not configured",
        )


class AgentKitModelGateway:
    """Adapter around an existing Agent/LLM gateway.

    ``proposer`` must return a validated ``BuildPlan``.  This adapter does not
    accept raw HTML, source code, arbitrary tool calls, or persistence methods
    from the model response.
    """

    def __init__(self, proposer: object | None = None) -> None:
        self._proposer = proposer

    async def propose_plan(
        self, context: ResolvedContext, *, requested_kind: SkillKind | None
    ) -> BuildPlan:
        if self._proposer is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.CREDENTIAL_BLOCKED,
                "AgentKit model gateway is not configured",
            )
        propose = getattr(self._proposer, "propose_plan", None)
        if not callable(propose):
            raise SkillAuthoringError(
                AuthoringErrorCode.MODEL_UNAVAILABLE,
                "configured model gateway does not expose propose_plan",
            )
        try:
            result = propose(
                context.model_input,
                requested_kind=requested_kind.value if requested_kind else None,
            )
            if hasattr(result, "__await__"):
                result = await result
        except TimeoutError as error:
            raise SkillAuthoringError(
                AuthoringErrorCode.MODEL_TIMEOUT, "model gateway timed out"
            ) from error
        except SkillAuthoringError:
            raise
        except Exception as error:
            raise SkillAuthoringError(
                AuthoringErrorCode.MODEL_UNAVAILABLE,
                "model gateway failed to produce a structured plan",
            ) from error
        if isinstance(result, BuildPlan):
            return result
        try:
            return BuildPlan.model_validate(result)
        except Exception as error:
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "model gateway returned an invalid BuildPlan",
            ) from error


class LocalPlanningHarness:
    """Credential-free deterministic planner for replayable local journeys.

    The prompt digest selects a stable, different projection shape.  It is a
    test harness for the port, not a production fallback and does not assert a
    fake execution success.
    """

    async def propose_plan(
        self, context: ResolvedContext, *, requested_kind: SkillKind | None
    ) -> BuildPlan:
        kind = requested_kind or self._infer_kind(context)
        if not context.resources:
            raise SkillAuthoringError(
                AuthoringErrorCode.AMBIGUOUS,
                "select at least one authorized resource before creating a skill",
            )
        variant = int(hashlib.sha256(context.envelope.prompt.encode()).hexdigest()[:2], 16) % 2
        source = context.resources[0]
        fields = source.semantic_fields or ("value",)
        plan_id = f"plan_{digest({'context': context.context_digest, 'kind': kind})}"
        nodes = (
            PlanNode(
                node_id="resolve_intent",
                role="intent_resolution",
                output_names=("intent",),
            ),
            PlanNode(
                node_id="resolve_context",
                role="context_resolution",
                depends_on=("resolve_intent",),
                output_names=("authorized_context",),
            ),
        )
        if kind in {SkillKind.ANALYSIS, SkillKind.KNOWLEDGE, SkillKind.SEMANTIC}:
            nodes += (
                PlanNode(
                    node_id="prepare_source",
                    role="query_plan" if kind == SkillKind.ANALYSIS else "retrieval",
                    depends_on=("resolve_context",),
                    input_names=("authorized_context",),
                    output_names=("source_binding",),
                ),
            )
        elif kind == SkillKind.GRAPH_ONTOLOGY:
            nodes += (
                PlanNode(
                    node_id="map_schema",
                    role="schema_mapping",
                    depends_on=("resolve_context",),
                    input_names=("authorized_context",),
                    output_names=("mapping",),
                ),
            )
        else:
            nodes += (
                PlanNode(
                    node_id="define_policy",
                    role="threshold_policy",
                    depends_on=("resolve_context",),
                    input_names=("authorized_context",),
                    output_names=("policy",),
                ),
            )
        nodes += (
            PlanNode(
                node_id="worker3_execution",
                role="worker3_execution",
                depends_on=(nodes[-1].node_id,),
                input_names=("source_binding",),
                output_names=("typed_result",),
            ),
        )
        query = QueryPlan(
            source_revision=source.provider_revision,
            selected_fields=tuple(fields[: 3 + variant]),
            filters={},
            limit=50 if variant == 0 else 100,
        )
        if kind == SkillKind.KNOWLEDGE:
            spec = KnowledgeKindSpec(
                citation_intent=("source_revision", "locator", "permission"),
                retrieval_mode="hybrid" if variant == 0 else "semantic",
            )
            inputs = (InputContract(name="question", type="string"),)
            outputs = (OutputContract(name="answer", type="answer"),)
        elif kind == SkillKind.SEMANTIC:
            spec = SemanticKindSpec(
                entities=tuple(fields[:2]),
                relationships=("belongs_to",) if variant == 0 else ("relates_to",),
                dimensions=tuple(fields[:2]),
                measures=tuple(fields[2:3]),
            )
            inputs = ()
            outputs = (OutputContract(name="schema", type="schema"),)
        elif kind == SkillKind.ANALYSIS:
            spec = AnalysisKindSpec(
                query_plan=query,
                analysis_shape="trend" if variant == 0 else "breakdown",
                unit="count" if variant == 0 else "value",
            )
            inputs = (
                InputContract(name="date_range", type="date", required=False),
            )
            outputs = (
                OutputContract(name="table", type="table"),
                OutputContract(name="metric", type="metric", required=False),
            )
        elif kind == SkillKind.GRAPH_ONTOLOGY:
            spec = GraphOntologyKindSpec(
                entity_types=tuple(fields[:2]),
                relation_types=("belongs_to",) if variant == 0 else ("depends_on",),
                mapping_intent=tuple(fields[:2]),
            )
            inputs = ()
            outputs = (OutputContract(name="graph", type="graph"),)
        else:
            spec = MonitoringKindSpec(
                metric=fields[0],
                threshold=0.9 if variant == 0 else 0.8,
                comparator="gte" if variant == 0 else "change_rate",
                duration_minutes=5 if variant == 0 else 15,
                refresh_seconds=900 if variant == 0 else 1800,
            )
            inputs = ()
            outputs = (OutputContract(name="observation", type="observation"),)
        plan = BuildPlan(
            plan_id=plan_id,
            intent=kind,
            purpose=context.envelope.prompt,
            nodes=nodes,
            inputs=inputs,
            outputs=outputs,
            dependencies=tuple(item.ref for item in context.resources),
            kind_spec=spec,
            query_plan=query if kind == SkillKind.ANALYSIS else None,
            plan_digest=digest(
                {
                    "plan": plan_id,
                    "kind": kind,
                    "variant": variant,
                    "fields": fields,
                    "prompt": context.envelope.prompt,
                }
            ),
        )
        return plan

    @staticmethod
    def _infer_kind(context: ResolvedContext) -> SkillKind:
        # Intent classification belongs to the model gateway.  The harness
        # only uses an explicit marker supplied by local test journeys.
        marker = context.envelope.prompt.casefold()
        for kind in SkillKind:
            if f"[{kind.value}]" in marker:
                return kind
        raise SkillAuthoringError(
            AuthoringErrorCode.AMBIGUOUS,
            "skill kind is ambiguous; choose one of the five supported kinds",
        )


class NoopWorker3Executor:
    """Boundary stub: accepts a typed request but never fabricates a result."""

    async def request_execution(self, request: object) -> object:
        del request
        from .models import Worker3ExecutionAccepted

        return Worker3ExecutionAccepted(
            execution_id="exec_pending_worker3",
            state="queued",
            reason="Worker 3 executor is not wired in this worker",
        )


class JsonFileAuthoringRepository:
    """Small durable adapter for local replay and contract tests.

    Main can replace this with its repository.  Writes use an atomic rename so
    refresh/restart never observes a half-written operation or draft.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._state: dict[str, dict[str, object]] = {
            "operations": {},
            "events": {},
            "drafts": {},
            "create_requests": {},
            "patches": {},
        }
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            if self.path.exists():
                self._state = json.loads(self.path.read_text(encoding="utf-8"))
            self._state.setdefault("operations", {})
            self._state.setdefault("events", {})
            self._state.setdefault("drafts", {})
            self._state.setdefault("create_requests", {})
            self._state.setdefault("patches", {})
            self._loaded = True

    async def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._state, stream, ensure_ascii=False, sort_keys=True, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def save_operation(self, operation: object) -> None:
        await self._ensure_loaded()
        async with self._lock:
            operation_id = getattr(operation, "operation_id")
            self._state["operations"][operation_id] = operation.model_dump(mode="json")
            await self._write()

    async def get_operation(self, operation_id: str) -> object | None:
        await self._ensure_loaded()
        from .models import AuthoringOperation

        data = self._state["operations"].get(operation_id)
        return AuthoringOperation.model_validate(data) if data else None

    async def save_event(self, event: object) -> None:
        await self._ensure_loaded()
        async with self._lock:
            operation_id = getattr(event, "operation_id")
            events = self._state["events"].setdefault(operation_id, [])
            events.append(event.model_dump(mode="json"))
            await self._write()

    async def list_events(self, operation_id: str) -> tuple[object, ...]:
        await self._ensure_loaded()
        from .models import AuthoringEvent

        return tuple(
            AuthoringEvent.model_validate(data)
            for data in self._state["events"].get(operation_id, [])
        )

    async def save_draft(self, draft: DraftRevision) -> None:
        await self._ensure_loaded()
        async with self._lock:
            entries = self._state["drafts"].setdefault(draft.draft_id, [])
            entries.append(draft.model_dump(mode="json"))
            await self._write()

    async def get_draft(
        self, draft_id: str, revision: int | None = None
    ) -> DraftRevision | None:
        await self._ensure_loaded()
        from .models import DraftRevision

        entries = self._state["drafts"].get(draft_id, [])
        if revision is not None:
            entries = [item for item in entries if item["revision"] == revision]
        if not entries:
            return None
        return DraftRevision.model_validate(entries[-1])

    async def list_drafts(self, workspace_id: str, caller_id: str) -> tuple[DraftRevision, ...]:
        await self._ensure_loaded()
        from .models import DraftRevision

        result: list[DraftRevision] = []
        for entries in self._state["drafts"].values():
            if not entries:
                continue
            draft = DraftRevision.model_validate(entries[-1])
            if draft.workspace_id == workspace_id and (
                draft.owner_id == caller_id or draft.scope == Scope.TEAM
            ):
                result.append(draft)
        return tuple(result)

    async def save_create_request(self, operation_id: str, request: object) -> None:
        await self._ensure_loaded()
        async with self._lock:
            self._state["create_requests"][operation_id] = request.model_dump(mode="json")
            await self._write()

    async def get_create_request(self, operation_id: str) -> object | None:
        await self._ensure_loaded()
        from .models import CreateDraftRequest

        data = self._state["create_requests"].get(operation_id)
        return CreateDraftRequest.model_validate(data) if data else None

    async def save_patch(self, proposal: object) -> None:
        await self._ensure_loaded()
        async with self._lock:
            self._state["patches"][proposal.patch_id] = proposal.model_dump(mode="json")
            await self._write()

    async def get_patch(self, patch_id: str) -> object | None:
        await self._ensure_loaded()
        from .models import PatchProposal

        data = self._state["patches"].get(patch_id)
        return PatchProposal.model_validate(data) if data else None
