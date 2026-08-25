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
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from pydantic import BaseModel

from .models import (
    AgentEventEvidence,
    AgentExecutionEvidence,
    AgentToolCallEvidence,
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


@dataclass(frozen=True)
class McpToolBundle:
    """W1-provided MCP tools and schemas; this worker does not own lifecycle."""

    tools: tuple[object, ...]
    schemas: Mapping[str, object]
    credentialed: bool = True


class McpToolProvider(Protocol):
    async def tools_for(self, context: ResolvedContext) -> McpToolBundle: ...


class ResourceResolver(Protocol):
    async def resolve(
        self, envelope: ContextEnvelope, refs: Sequence[ResourceRef]
    ) -> ResolvedContext: ...


class ModelGateway(Protocol):
    async def propose_plan(
        self, context: ResolvedContext, *, requested_kind: SkillKind | None
    ) -> BuildPlan: ...

    @property
    def execution_evidence(self) -> AgentExecutionEvidence | None: ...


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
                "current_skill_id": envelope.current_skill_id,
                "current_view_id": envelope.current_view_id,
                "current_component_id": envelope.current_component_id,
                "comment_ids": envelope.comment_ids,
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

    @property
    def execution_evidence(self) -> AgentExecutionEvidence | None:
        return None


class AgentKitModelGateway:
    """Legacy proposal-only adapter; it is not the P0 production path.

    ``proposer`` must return a validated ``BuildPlan``.  This adapter does not
    accept raw HTML, source code, arbitrary tool calls, or persistence methods
    from the model response. Production wiring must use
    :class:`VeADKModelGateway`.
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

    @property
    def execution_evidence(self) -> AgentExecutionEvidence | None:
        return None


class VeADKModelGateway:
    """Production adapter using the repository's public Agent and Runner.

    W1 owns MCP connection/authentication and injects already-authorized tool
    objects.  This adapter only supplies those tools to the official VEADK
    Agent and records the official Runner event stream.
    """

    def __init__(
        self,
        *,
        mcp_tools: McpToolBundle | McpToolProvider | None = None,
        model: object | None = None,
        model_name: str | None = None,
        model_api_base: str | None = None,
        model_api_key: str | None = None,
    ) -> None:
        self._mcp_tools = mcp_tools
        self._model = model
        self._model_name = model_name
        self._model_api_base = model_api_base
        self._model_api_key = model_api_key
        self._last_execution: AgentExecutionEvidence | None = None

    @property
    def execution_evidence(self) -> AgentExecutionEvidence | None:
        return self._last_execution

    async def _resolve_tools(self, context: ResolvedContext) -> McpToolBundle:
        if self._mcp_tools is None:
            raise SkillAuthoringError(
                AuthoringErrorCode.CREDENTIAL_BLOCKED,
                "W1 MCP tools and credentials are not configured",
            )
        if isinstance(self._mcp_tools, McpToolBundle):
            bundle = self._mcp_tools
        else:
            bundle = await self._mcp_tools.tools_for(context)
        if not bundle.credentialed or not bundle.tools:
            raise SkillAuthoringError(
                AuthoringErrorCode.CREDENTIAL_BLOCKED,
                "authorized MCP tools and usable credentials are required",
            )
        return bundle

    async def propose_plan(
        self, context: ResolvedContext, *, requested_kind: SkillKind | None
    ) -> BuildPlan:
        requires_tools = self._requires_mcp_tools(context, requested_kind)
        bundle = (
            await self._resolve_tools(context)
            if requires_tools
            else McpToolBundle(tools=(), schemas={}, credentialed=True)
        )
        if self._model is None and not (
            self._model_api_key or os.getenv("MODEL_AGENT_API_KEY")
        ):
            raise SkillAuthoringError(
                AuthoringErrorCode.CREDENTIAL_BLOCKED,
                "VEADK model credentials are not configured",
            )

        try:
            from google.genai import types
            from veadk import Agent, Runner
            from veadk.memory.short_term_memory import ShortTermMemory
            from veadk.tracing.telemetry.opentelemetry_tracer import (
                OpentelemetryTracer,
            )
        except Exception as error:
            raise SkillAuthoringError(
                AuthoringErrorCode.MODEL_UNAVAILABLE,
                "official VEADK Agent/Runner is unavailable",
            ) from error

        session_id = f"skill-authoring-{context.envelope.request_id}"
        instruction = self._instruction(context, requested_kind, bundle)
        agent_kwargs: dict[str, Any] = {
            "name": "skill_authoring_agent",
            "description": "Structured SkillDraft and BuildPlan authoring agent.",
            "instruction": instruction,
            "tools": list(bundle.tools),
            "output_schema": BuildPlan,
            "tracers": [OpentelemetryTracer()],
            # BuildPlan is sent as Ark's structured response schema.  The
            # Responses API is the VeADK path that supports this contract;
            # caching is deliberately disabled because Ark does not support
            # cached responses together with a text/schema output.
            "enable_responses": True,
            "enable_responses_cache": False,
            "model_extra_config": {
                "extra_body": {"thinking": {"type": "disabled"}}
            },
        }
        if self._model is not None:
            agent_kwargs["model"] = self._model
        else:
            if self._model_name:
                agent_kwargs["model_name"] = self._model_name
            if self._model_api_base:
                agent_kwargs["model_api_base"] = self._model_api_base
            if self._model_api_key:
                agent_kwargs["model_api_key"] = self._model_api_key

        events: list[AgentEventEvidence] = []
        tool_calls: list[AgentToolCallEvidence] = []
        try:
            agent = Agent(**agent_kwargs)
            runner = Runner(
                agent=agent,
                app_name="skill_authoring",
                short_term_memory=ShortTermMemory(backend="local"),
            )
            await runner.session_service.create_session(
                app_name=runner.app_name,
                user_id=context.envelope.caller_id,
                session_id=session_id,
            )
            message = types.Content(
                role="user",
                parts=[types.Part(text=json.dumps(context.model_input, ensure_ascii=False))],
            )
            output_text: str | None = None
            async for event in runner.run_async(
                user_id=context.envelope.caller_id,
                session_id=session_id,
                new_message=message,
            ):
                events.append(
                    AgentEventEvidence(
                        event_type=event.__class__.__name__,
                        author=getattr(event, "author", None),
                        has_content=bool(getattr(event, "content", None)),
                        output_present=getattr(event, "output", None) is not None,
                    )
                )
                content = getattr(event, "content", None)
                for part in getattr(content, "parts", None) or ():
                    function_call = getattr(part, "function_call", None)
                    if function_call is not None:
                        tool_calls.append(
                            AgentToolCallEvidence(
                                name=function_call.name,
                                call_id=function_call.id,
                                status="requested",
                            )
                        )
                    function_response = getattr(part, "function_response", None)
                    if function_response is not None:
                        response = getattr(function_response, "response", None)
                        response_status = (
                            "failed"
                            if self._mcp_response_failed(response)
                            else "succeeded"
                        )
                        tool_calls.append(
                            AgentToolCallEvidence(
                                name=function_response.name,
                                call_id=function_response.id,
                                status=response_status,
                            )
                        )
                    if getattr(part, "text", None):
                        output_text = part.text
                if getattr(event, "output", None):
                    output_text = str(event.output)
            trace_id = runner.get_trace_id()
            if not trace_id or trace_id == "<unknown_trace_id>":
                raise SkillAuthoringError(
                    AuthoringErrorCode.MODEL_UNAVAILABLE,
                    "VEADK Runner did not provide a trace_id",
                )
            failed_tool = next(
                (call for call in tool_calls if call.status == "failed"), None
            )
            if failed_tool is not None:
                raise SkillAuthoringError(
                    AuthoringErrorCode.MODEL_UNAVAILABLE,
                    f"MCP tool call failed: {failed_tool.name}",
                )
            evidence = AgentExecutionEvidence(
                session_id=session_id,
                trace_id=trace_id,
                status="succeeded",
                events=tuple(events),
                tool_calls=tuple(tool_calls),
            )
            self._last_execution = evidence
            if not output_text:
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "VEADK Runner returned no structured output",
                )
            plan = self._parse_build_plan_output(
                output_text, requested_kind=requested_kind
            )
            # A simple conversational prompt may be answered with a typed
            # clarification and need no data inspection. Tool-assisted
            # authoring remains mandatory for plans that actually depend on
            # data; the service validates all refs against server context.
            if not tool_calls and not plan.clarification_questions:
                raise SkillAuthoringError(
                    AuthoringErrorCode.VALIDATION_FAILED,
                    "VEADK Agent produced neither an authorized MCP tool call nor a clarification",
                )
            return plan
        except SkillAuthoringError as error:
            if self._last_execution is None:
                self._last_execution = AgentExecutionEvidence(
                    session_id=session_id,
                    trace_id=(
                        trace_id
                        if "trace_id" in locals()
                        and trace_id != "<unknown_trace_id>"
                        else "unavailable"
                    ),
                    status="failed",
                    events=tuple(events),
                    tool_calls=tuple(tool_calls),
                    error_code=error.code,
                    error_message=error.message,
                )
            raise
        except ValueError as error:
            self._last_execution = AgentExecutionEvidence(
                session_id=session_id,
                trace_id=trace_id if "trace_id" in locals() else "unavailable",
                status="failed",
                events=tuple(events),
                tool_calls=tuple(tool_calls),
                error_code=AuthoringErrorCode.VALIDATION_FAILED,
                error_message="VEADK Runner output was not a valid BuildPlan",
            )
            raise SkillAuthoringError(
                AuthoringErrorCode.VALIDATION_FAILED,
                "VEADK Runner output was not a valid BuildPlan",
            ) from error
        except TimeoutError as error:
            self._last_execution = AgentExecutionEvidence(
                session_id=session_id,
                trace_id="unavailable",
                status="failed",
                events=tuple(events),
                tool_calls=tuple(tool_calls),
                error_code=AuthoringErrorCode.MODEL_TIMEOUT,
                error_message="VEADK Runner timed out",
            )
            raise SkillAuthoringError(
                AuthoringErrorCode.MODEL_TIMEOUT, "VEADK Runner timed out"
            ) from error
        except Exception as error:
            self._last_execution = AgentExecutionEvidence(
                session_id=session_id,
                trace_id="unavailable",
                status="failed",
                events=tuple(events),
                tool_calls=tuple(tool_calls),
                error_code=AuthoringErrorCode.MODEL_UNAVAILABLE,
                error_message="VEADK Agent/Runner execution failed",
            )
            raise SkillAuthoringError(
                AuthoringErrorCode.MODEL_UNAVAILABLE,
                "VEADK Agent/Runner execution failed",
            ) from error

    @staticmethod
    def _parse_build_plan_output(
        output_text: str, *, requested_kind: SkillKind | None = None
    ) -> BuildPlan:
        """Validate the bounded shapes emitted by structured VeADK responses.

        Ark/ADK can expose a structured response as raw JSON text, a fenced
        JSON block, or an already-decoded object wrapped once by an event
        adapter.  Accept only those transport representations; the final
        ``BuildPlan`` validation remains the authority and no fields are
        synthesized here.
        """
        if not isinstance(output_text, str) or not output_text.strip():
            raise ValueError("empty BuildPlan output")
        candidate: object = output_text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            if len(lines) < 3:
                raise ValueError("invalid fenced BuildPlan output")
            candidate = "\n".join(lines[1:-1]).strip()
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except json.JSONDecodeError as error:
                raise ValueError("BuildPlan output is not JSON") from error
        if not isinstance(candidate, Mapping):
            raise ValueError("BuildPlan output is not an object")
        # Some Runner event adapters wrap the structured response once. Do
        # not recursively search arbitrary model output: only canonical
        # transport keys are unwrapped and the resulting object is validated.
        for key in ("output", "result", "plan"):
            nested = candidate.get(key)
            if isinstance(nested, Mapping):
                candidate = nested
                break
            if isinstance(nested, str):
                try:
                    decoded = json.loads(nested)
                except json.JSONDecodeError as error:
                    raise ValueError("wrapped BuildPlan output is not JSON") from error
                if not isinstance(decoded, Mapping):
                    raise ValueError("wrapped BuildPlan output is not an object")
                candidate = decoded
                break
        # A greeting is a valid non-authoring outcome. VeADK's structured
        # response may contain only this typed clarification payload; turn it
        # into the smallest non-executable BuildPlan so the service can
        # persist the real Agent evidence and return AWAITING_INPUT. No
        # dependencies, data refs, or execution result are invented.
        if (
            "clarification_questions" in candidate
            and "plan_id" not in candidate
            and "intent" not in candidate
        ):
            questions = candidate["clarification_questions"]
            if not isinstance(questions, list) or not questions:
                raise ValueError("clarification_questions must be a non-empty list")
            clarification_kind = requested_kind or SkillKind.KNOWLEDGE
            candidate = {
                "plan_id": f"plan_clarification_{digest(questions)}",
                "intent": clarification_kind.value,
                "purpose": "Clarify the user's authoring intent before creating a SkillDraft.",
                "nodes": [
                    {"node_id": "resolve_intent", "role": "intent_resolution"},
                    {
                        "node_id": "resolve_context",
                        "role": "context_resolution",
                        "depends_on": ["resolve_intent"],
                    },
                    {
                        "node_id": "worker3_execution",
                        "role": "worker3_execution",
                        "depends_on": ["resolve_context"],
                    },
                ],
                "outputs": [{"name": "answer", "type": "answer"}],
                "kind_spec": {
                    "kind": clarification_kind.value,
                    "citation_intent": ["source_revision"],
                    "retrieval_mode": "hybrid",
                },
                "clarification_questions": questions,
                "layout_intent": "document",
                "plan_digest": digest(
                    {"clarification_questions": questions, "kind": clarification_kind.value}
                ),
            }
        return BuildPlan.model_validate(candidate)

    @staticmethod
    def _instruction(
        context: ResolvedContext,
        requested_kind: SkillKind | None,
        bundle: McpToolBundle,
    ) -> str:
        return (
            "Create only a typed BuildPlan for a SkillDraft. Use the provided MCP "
            "tools through the formal tool mechanism when schema/data inspection is "
            "needed. Never emit HTML, URLs, timers, code, or persistence commands. "
            "For dependencies, data_refs, and lineage, copy the exact authorized "
            "resource references from authorized_context.resources, including kind, "
            "object_id, revision, and scope. Do not infer, broaden, or change scope. "
            "For a simple conversational greeting or underspecified request, return "
            "a concise typed clarification_questions list and do not call MCP or "
            "invent a Dashboard, sales report, or other artifact. For the exact "
            "prompt 你好, use clarification_questions=[\"请说明你希望查询或创建的知识内容。\"]. "
            "The downstream Worker 3 owns execution and rendering. "
            f"requested_kind={requested_kind.value if requested_kind else None}; "
            f"mcp_schemas={json.dumps(bundle.schemas, ensure_ascii=False, sort_keys=True)}; "
            f"authorized_context={json.dumps(context.model_input, ensure_ascii=False, sort_keys=True)}"
        )

    @staticmethod
    def _requires_mcp_tools(
        context: ResolvedContext, requested_kind: SkillKind | None
    ) -> bool:
        """Keep ordinary conversation out of the data-tool execution path.

        The request still goes through the real Agent/Runner. This narrow
        classifier only recognizes conversational greetings; all authoring
        kinds and non-greeting knowledge requests retain the MCP tool gate.
        """
        if requested_kind != SkillKind.KNOWLEDGE:
            return True
        prompt = context.envelope.prompt.strip().casefold()
        return not bool(
            re.fullmatch(
                r"(?:你好|您好|嗨|哈喽|hello|hi|hey|你好呀|您好呀)[!！。．，, ]*",
                prompt,
            )
        )

    @staticmethod
    def _mcp_response_failed(response: object) -> bool:
        """Recognize W1/MCP error envelopes without trusting model text."""
        if isinstance(response, Mapping):
            if response.get("isError") is True:
                return True
            if response.get("status") == "failed" or response.get("error"):
                return True
            return any(
                VeADKModelGateway._mcp_response_failed(value)
                for value in response.values()
            )
        if isinstance(response, (list, tuple)):
            return any(
                VeADKModelGateway._mcp_response_failed(value) for value in response
            )
        if isinstance(response, str):
            try:
                return VeADKModelGateway._mcp_response_failed(json.loads(response))
            except (TypeError, ValueError):
                return False
        return False


class LocalPlanningHarness:
    """Credential-free deterministic planner for replayable local journeys.

    The prompt digest selects a stable, different projection shape.  It is a
    test harness for the port, not a production fallback and does not assert a
    fake execution success.
    """

    TEST_ONLY = True

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
            data_refs=tuple(item.ref for item in context.resources),
            metrics=(
                tuple(fields[2:3])
                if kind in {SkillKind.ANALYSIS, SkillKind.MONITORING}
                else ()
            ),
            dimensions=tuple(fields[:2]),
            layout_intent=(
                "trend"
                if kind == SkillKind.ANALYSIS and variant == 0
                else "breakdown"
                if kind == SkillKind.ANALYSIS
                else "graph"
                if kind == SkillKind.GRAPH_ONTOLOGY
                else "alert"
                if kind == SkillKind.MONITORING
                else "document"
            ),
            refresh_policy=context.envelope.freshness,
            lineage=tuple(item.ref for item in context.resources),
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

    @property
    def execution_evidence(self) -> AgentExecutionEvidence | None:
        """LocalPlanningHarness is explicitly test-only and has no Agent run."""
        return None

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
