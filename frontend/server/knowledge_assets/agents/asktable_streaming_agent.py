"""Streaming AskTable Agent loop with governed Semantic Skill tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import uuid4

from google.genai import types
from pydantic import Field

from ..builders.dashboard.askdata_query_service import (
    AskDataQueryBody,
    AskDataQueryService,
)
from ..builders.dashboard.dashboard_skill_writer import DashboardSkillBuildBody
from ..models import ApiModel
from ..service import KnowledgeAssetServiceError, KnowledgeAssetStore, redact_sensitive
from .ask_dashboard import AskTableDashboardAgent
from .runner import DEFAULT_INTERNAL_MODEL, model_configured


class AskDataStreamBody(ApiModel):
    semantic_asset_id: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    dashboard_intent: str | None = Field(default=None, max_length=1000)
    metric: str | None = Field(default=None, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_range: dict[str, Any] = Field(default_factory=dict)
    mode: str = Field(default="production", max_length=80)
    limit: int = Field(default=100, ge=1, le=500)


class StreamingRunner(Protocol):
    def health(self) -> dict[str, Any]:
        ...

    async def run(
        self,
        *,
        instruction: str,
        message: str,
        session_id: str,
        conversation_id: str,
        semantic_asset: dict[str, Any],
        tools: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        ...


class VeadkStreamingRunner:
    def __init__(self, *, model_name: str | None = None) -> None:
        self._model_name = model_name or os.getenv(
            "VEADK_KNOWLEDGE_AGENT_MODEL",
            os.getenv("VEADK_STUDIO_EVALUATION_MODEL", DEFAULT_INTERNAL_MODEL),
        )

    def health(self) -> dict[str, Any]:
        configured = model_configured()
        return {
            "configured": configured,
            "status": "available" if configured else "not_configured",
            "runner_backend": "veadk.Agent+Runner" if configured else "not_configured",
            "model_name": self._model_name if configured else "not_configured",
        }

    async def run(
        self,
        *,
        instruction: str,
        message: str,
        session_id: str,
        conversation_id: str,
        semantic_asset: dict[str, Any],
        tools: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        if not model_configured():
            raise KnowledgeAssetServiceError("模型未配置：请配置模型后再运行 AskTable Agent。")

        from veadk import Agent, Runner

        agent = Agent(
            name=AskTableStreamingAgent.agent_name,
            description="AgentKit Studio AskTable streaming Agent.",
            instruction=instruction,
            model_name=self._model_name,
            tools=list(tools.values()),
            enable_responses=True,
            enable_responses_cache=False,
            model_extra_config={"extra_body": {"thinking": {"type": "disabled"}}},
        )
        runner = Runner(agent=agent, app_name=AskTableStreamingAgent.agent_name)
        await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id="studio-asktable",
            session_id=session_id,
            state={
                "conversation_id": conversation_id,
                "semantic_asset_id": semantic_asset.get("asset_id"),
            },
        )
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        )
        async for event in runner.run_async(
            user_id="studio-asktable",
            session_id=session_id,
            invocation_id=conversation_id,
            new_message=new_message,
        ):
            yield _event_to_payload(event)


class AskTableStreamingAgent:
    agent_name = "studio_asktable_streaming_agent"

    def __init__(
        self,
        store: KnowledgeAssetStore,
        *,
        dashboard_agent: AskTableDashboardAgent | None = None,
        runner: StreamingRunner | None = None,
    ) -> None:
        self._store = store
        self._dashboard_agent = dashboard_agent or AskTableDashboardAgent(store)
        self._askdata = AskDataQueryService(store)
        self._runner = runner or VeadkStreamingRunner()

    def health(self) -> dict[str, Any]:
        return self._runner.health()

    async def stream(self, body: AskDataStreamBody) -> AsyncIterator[dict[str, Any]]:
        conversation_id = body.conversation_id or f"askdata_{uuid4().hex}"
        session_id = body.session_id or conversation_id
        mode = _mode(body.mode)
        semantic_asset = await self._store.get_asset(
            asset_type="semantic_model",
            asset_id=body.semantic_asset_id,
        )
        await self._store.upsert_askdata_conversation(
            conversation_id=conversation_id,
            semantic_asset_id=body.semantic_asset_id,
            session_id=session_id,
            title=body.message[:120],
            mode=mode,
            metadata={
                "agent_name": self.agent_name,
                "semantic_asset_name": semantic_asset.get("name"),
            },
        )
        user_message = await self._store.record_askdata_message(
            conversation_id=conversation_id,
            role="user",
            content={"text": body.message, "request": body.model_dump(mode="json")},
        )
        yield _adk_event(
            author="user",
            role="user",
            parts=[types.Part.from_text(text=body.message)],
            conversation_id=conversation_id,
            session_id=session_id,
        )

        tools = {
            "query_semantic_skill": self._query_semantic_skill_tool(body, conversation_id, user_message["id"]),
            "build_dashboard_skill": self._build_dashboard_skill_tool(body, conversation_id, user_message["id"]),
        }

        if not self.health().get("configured"):
            async for event in self._blocked_not_configured(
                body,
                conversation_id=conversation_id,
                session_id=session_id,
                message_id=user_message["id"],
            ):
                yield event
            return

        final_text = ""
        try:
            async for event in self._runner.run(
                instruction=_asktable_instruction(semantic_asset, mode=mode),
                message=body.message,
                session_id=session_id,
                conversation_id=conversation_id,
                semantic_asset=semantic_asset,
                tools=tools,
            ):
                final_text += _event_text(event)
                yield _with_session(event, conversation_id, session_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - streaming boundary degrades to a blocked tool response.
            response = _blocked_tool_result(
                body,
                reason=f"AskTable Agent streaming failed: {redact_sensitive(str(error))}",
            )
            async for event in self._manual_tool_answer(
                body,
                response,
                conversation_id=conversation_id,
                session_id=session_id,
                message_id=user_message["id"],
                final_text="AskTable Agent 无法完成本次生产查询；请检查模型配置和 Semantic Skill live 查询能力。",
            ):
                yield event
            return

        if final_text.strip():
            await self._store.record_askdata_message(
                conversation_id=conversation_id,
                role="assistant",
                content={"text": final_text.strip()},
            )

    def _query_semantic_skill_tool(
        self,
        body: AskDataStreamBody,
        conversation_id: str,
        message_id: str,
    ):
        async def query_semantic_skill(
            metric: str | None = None,
            dimension: str | None = None,
            dimensions: list[str] | None = None,
            filters: dict[str, Any] | None = None,
            time_range: dict[str, Any] | None = None,
            question: str | None = None,
            limit: int | None = None,
        ) -> dict[str, Any]:
            request = AskDataQueryBody(
                semantic_asset_id=body.semantic_asset_id,
                metric=metric or body.metric,
                dimension=dimension or body.dimension,
                dimensions=dimensions or body.dimensions,
                filters=filters or body.filters,
                time_range=time_range or body.time_range,
                question=question or body.message,
                limit=limit or body.limit,
                mode=body.mode,
            )
            try:
                result = await self._askdata.query(request)
            except Exception as error:  # noqa: BLE001 - tool boundary records the blocked query response.
                response = _blocked_tool_result(
                    body,
                    reason="Semantic Skill live governed query failed: "
                    + str(redact_sensitive(str(error))),
                )
                await self._store.record_askdata_tool_event(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_call_id=f"tool_{uuid4().hex}",
                    tool_name="query_semantic_skill",
                    status="blocked",
                    args=request.model_dump(mode="json"),
                    response=response,
                )
                return response
            data = result.get("data") if isinstance(result, dict) else {}
            execution = data.get("execution") if isinstance(data, dict) else {}
            demo_offline = bool(
                isinstance(execution, dict) and execution.get("demo_offline")
            )
            status = result.get("status", "completed")
            if demo_offline and _mode(body.mode) == "production":
                status = "blocked"
            response = redact_sensitive(
                {
                    "success": status == "completed",
                    "status": status,
                    "semantic_asset_id": body.semantic_asset_id,
                    "conversation_id": conversation_id,
                    "result": data.get("rows", []) if isinstance(data, dict) else [],
                    "rows": data.get("rows", []) if isinstance(data, dict) else [],
                    "returnedCount": data.get("returnedCount", 0) if isinstance(data, dict) else 0,
                    "sql": data.get("sql", "") if isinstance(data, dict) else "",
                    "metricDefinition": data.get("metricDefinition", "") if isinstance(data, dict) else "",
                    "policyDecision": data.get("policyDecision", {}) if isinstance(data, dict) else {},
                    "freshness": data.get("freshness", {}) if isinstance(data, dict) else {},
                    "lineage": data.get("lineage", []) if isinstance(data, dict) else [],
                    "evidence": data.get("evidence", []) if isinstance(data, dict) else [],
                    "execution": execution if isinstance(execution, dict) else {},
                    "askdata": result,
                    "query_evidence_hash": _evidence_hash(data),
                    "demo_offline": demo_offline,
                    "production_completed": status == "completed" and not demo_offline,
                }
            )
            await self._store.record_askdata_tool_event(
                conversation_id=conversation_id,
                message_id=message_id,
                tool_call_id=f"tool_{uuid4().hex}",
                tool_name="query_semantic_skill",
                status=status,
                args=request.model_dump(mode="json"),
                response=response,
            )
            return response

        query_semantic_skill.__name__ = "query_semantic_skill"
        return query_semantic_skill

    def _build_dashboard_skill_tool(
        self,
        body: AskDataStreamBody,
        conversation_id: str,
        message_id: str,
    ):
        async def build_dashboard_skill(
            name: str | None = None,
            intent: str | None = None,
            metric: str | None = None,
            dimensions: list[str] | None = None,
            query_evidence_hash: str | None = None,
            tool_call_id: str | None = None,
        ) -> dict[str, Any]:
            call_id = tool_call_id or f"tool_{uuid4().hex}"
            request = DashboardSkillBuildBody(
                semantic_asset_id=body.semantic_asset_id,
                name=name or "AskTable Dashboard",
                intent=intent or body.dashboard_intent or body.message,
                metric=metric or body.metric,
                dimensions=dimensions or body.dimensions,
                filters=body.filters,
                time_range=body.time_range,
                mode=body.mode,
                conversation_id=conversation_id,
                tool_call_id=call_id,
                query_evidence_hash=query_evidence_hash,
                publish=True,
            )
            result = await self._dashboard_agent.build_dashboard(request)
            response = redact_sensitive(
                {
                    "success": result.get("status") == "succeeded",
                    "status": result.get("status"),
                    "conversation_id": conversation_id,
                    "dashboard_asset_id": result.get("dashboard_asset_id"),
                    "dashboard": result.get("dashboard"),
                    "preview": result.get("preview"),
                }
            )
            await self._store.record_askdata_tool_event(
                conversation_id=conversation_id,
                message_id=message_id,
                tool_call_id=call_id,
                tool_name="build_dashboard_skill",
                status=str(result.get("status") or "completed"),
                args=request.model_dump(mode="json"),
                response=response,
            )
            return response

        build_dashboard_skill.__name__ = "build_dashboard_skill"
        return build_dashboard_skill

    async def _blocked_not_configured(
        self,
        body: AskDataStreamBody,
        *,
        conversation_id: str,
        session_id: str,
        message_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        response = _blocked_tool_result(
            body,
            reason="模型未配置：生产 AskTable streaming Agent 必须配置模型，不能伪造 success。",
        )
        async for event in self._manual_tool_answer(
            body,
            response,
            conversation_id=conversation_id,
            session_id=session_id,
            message_id=message_id,
            final_text="AskTable Agent 已阻断本次查询：模型未配置，无法运行生产 streaming tool loop。",
        ):
            yield event

    async def _manual_tool_answer(
        self,
        body: AskDataStreamBody,
        response: dict[str, Any],
        *,
        conversation_id: str,
        session_id: str,
        message_id: str,
        final_text: str,
    ) -> AsyncIterator[dict[str, Any]]:
        call_id = f"tool_{uuid4().hex}"
        args = {
            "semantic_asset_id": body.semantic_asset_id,
            "question": body.message,
            "mode": body.mode,
        }
        yield _adk_event(
            author=self.agent_name,
            role="model",
            parts=[types.Part.from_function_call(name="query_semantic_skill", args=args)],
            conversation_id=conversation_id,
            session_id=session_id,
        )
        await self._store.record_askdata_tool_event(
            conversation_id=conversation_id,
            message_id=message_id,
            tool_call_id=call_id,
            tool_name="query_semantic_skill",
            status=str(response.get("status") or "blocked"),
            args=args,
            response=response,
        )
        yield _adk_event(
            author=self.agent_name,
            role="user",
            parts=[
                types.Part.from_function_response(
                    name="query_semantic_skill",
                    response=response,
                )
            ],
            conversation_id=conversation_id,
            session_id=session_id,
        )
        yield _adk_event(
            author=self.agent_name,
            role="model",
            parts=[types.Part.from_text(text=final_text)],
            conversation_id=conversation_id,
            session_id=session_id,
        )
        await self._store.record_askdata_message(
            conversation_id=conversation_id,
            role="assistant",
            content={"text": final_text, "status": "blocked"},
        )


def _asktable_instruction(semantic_asset: dict[str, Any], *, mode: str) -> str:
    capabilities = semantic_asset.get("capabilities") or {}
    return f"""
You are AgentKit Studio AskTable, aligned with BYAAN governed Semantic Model Agent behavior.

The conversation is locked to this Semantic Skill:
- asset_id: {semantic_asset.get("asset_id")}
- name: {semantic_asset.get("name")}
- mode: {mode}
- metrics: {capabilities.get("metrics") or []}
- dimensions: {capabilities.get("dimensions") or []}

Rules:
1. For every quantitative business answer, call query_semantic_skill before answering.
2. Do not infer numeric values. Use only tool rows/result.
3. Do not use raw SQL fallback, direct database credentials, connection strings, tokens, AK/SK, or datasource secrets.
4. If requested metrics/dimensions are not exposed by the Semantic Skill, explain the missing semantic capability and do not bypass it.
5. Final answers must cite the governed query evidence when relevant: SQL, metricDefinition, policyDecision, freshness, lineage/evidence, and row values.
6. If the query result is blocked or demo/offline, say so plainly and do not call it production completed.
7. Use build_dashboard_skill only when the user asks to create/generate/build a dashboard.
""".strip()


def _blocked_tool_result(body: AskDataStreamBody, *, reason: str) -> dict[str, Any]:
    return redact_sensitive(
        {
            "success": False,
            "status": "blocked",
            "semantic_asset_id": body.semantic_asset_id,
            "rows": [],
            "result": [],
            "returnedCount": 0,
            "sql": "-- blocked: AskTable streaming Agent is not configured for production execution",
            "metricDefinition": "",
            "policyDecision": {
                "decision": "deny",
                "reason": reason,
                "raw_sql_fallback": False,
                "direct_database_access": False,
            },
            "freshness": {"status": "blocked"},
            "lineage": [],
            "evidence": [{"kind": "agent_status", "title": "AskTable Agent blocked"}],
            "execution": {
                "mode": "agent_not_configured",
                "governed_rest": True,
                "direct_database_access": False,
                "raw_sql_fallback": False,
                "production_completed": False,
            },
            "demo_offline": False,
            "production_completed": False,
        }
    )


def _adk_event(
    *,
    author: str,
    role: str,
    parts: list[types.Part],
    conversation_id: str,
    session_id: str,
    partial: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid4().hex}",
        "author": author,
        "partial": partial,
        "conversation_id": conversation_id,
        "session_id": session_id,
        "content": {
            "role": role,
            "parts": [
                part.model_dump(mode="json", by_alias=True, exclude_none=True)
                for part in parts
            ],
        },
    }


def _event_to_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return redact_sensitive(event)
    if hasattr(event, "model_dump"):
        return redact_sensitive(event.model_dump(mode="json", by_alias=True, exclude_none=True))
    out: dict[str, Any] = {}
    for key in ("id", "author", "partial", "content", "actions", "timestamp"):
        if hasattr(event, key):
            out[key] = getattr(event, key)
    return redact_sensitive(out)


def _with_session(
    event: dict[str, Any],
    conversation_id: str,
    session_id: str,
) -> dict[str, Any]:
    payload = dict(event)
    payload.setdefault("conversation_id", conversation_id)
    payload.setdefault("session_id", session_id)
    return payload


def _event_text(event: dict[str, Any]) -> str:
    content = event.get("content") if isinstance(event, dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else []
    if not isinstance(parts, list):
        return ""
    return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))


def _evidence_hash(data: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(redact_sensitive(data), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _mode(value: str | None) -> str:
    normalized = str(value or "production").strip().casefold()
    if normalized in {"demo", "offline", "schema_only", "snapshot", "test"}:
        return "offline"
    return "production"


def sse_frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(redact_sensitive(payload), ensure_ascii=False)}\n\n"


__all__ = [
    "AskDataStreamBody",
    "AskTableStreamingAgent",
    "StreamingRunner",
    "VeadkStreamingRunner",
    "sse_frame",
]
