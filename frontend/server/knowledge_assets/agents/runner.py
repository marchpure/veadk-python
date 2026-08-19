"""Internal VeADK Agent runner for Knowledge Asset workbench builders."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from ..service import redact_sensitive

DEFAULT_INTERNAL_MODEL = "doubao-seed-2-0-lite-260428"
MODEL_KEY_ENV_NAMES = (
    "MODEL_AGENT_API_KEY",
    "ARK_API_KEY",
    "OPENAI_API_KEY",
    "VEADK_SEMANTIC_BUILDER_API_KEY",
    "VEADK_KNOWLEDGE_AGENT_API_KEY",
)


class AgentBlocked(RuntimeError):
    """Raised when an internal agent intentionally fails closed."""

    status = "blocked"


class AgentValidationError(RuntimeError):
    """Raised when a model response cannot pass deterministic validation."""

    status = "failed"


class AgentRunOutput(BaseModel):
    schema: str = "agentkit.knowledge_asset.agent_output.v1"
    status: str = Field(default="completed")
    generation_mode: str = Field(default="agent")
    agent_status: str = Field(default="completed")
    payload: dict[str, Any] = Field(default_factory=dict)
    blocked_reasons: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    validation_result: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunRequest:
    agent_name: str
    instruction: str
    payload: dict[str, Any]
    output_schema: type[BaseModel] | None = None
    tool_names: tuple[str, ...] = ()
    timeout_seconds: int = 180


@dataclass(frozen=True)
class AgentRuntimeMetadata:
    agent_name: str
    agent_invocation_id: str
    runner_backend: str
    model_name: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    generation_mode: str = "agent"
    agent_status: str = "completed"
    validation_result: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return redact_sensitive(
            {
                "agent_name": self.agent_name,
                "agent_invocation_id": self.agent_invocation_id,
                "runner_backend": self.runner_backend,
                "model_name": self.model_name,
                "tool_calls": self.tool_calls,
                "generation_mode": self.generation_mode,
                "agent_status": self.agent_status,
                "validation_result": self.validation_result,
            }
        )


@dataclass(frozen=True)
class AgentRunResult:
    output: AgentRunOutput
    metadata: AgentRuntimeMetadata


@dataclass(frozen=True)
class ParsedAgentJson:
    payload: Any
    validation_result: dict[str, Any]


class InternalAgentRunner(Protocol):
    async def run(self, request: AgentRunRequest) -> AgentRunResult: ...

    def health(self) -> dict[str, Any]: ...


class StudioInternalAgentRunner:
    """Thin audited wrapper around ``veadk.Agent`` and ``veadk.Runner``."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        deterministic_fallback_enabled: bool | None = None,
    ) -> None:
        self._model_name = model_name or os.getenv(
            "VEADK_KNOWLEDGE_AGENT_MODEL",
            os.getenv("VEADK_STUDIO_EVALUATION_MODEL", DEFAULT_INTERNAL_MODEL),
        )
        self._deterministic_fallback_enabled = (
            deterministic_fallback_enabled
            if deterministic_fallback_enabled is not None
            else _env_truthy("VEADK_KNOWLEDGE_AGENT_DETERMINISTIC_FALLBACK")
            or _env_truthy("VEADK_SEMANTIC_BUILDER_DETERMINISTIC")
        )

    def health(self) -> dict[str, Any]:
        configured = model_configured()
        return {
            "configured": configured,
            "status": "available"
            if configured
            else "deterministic_fallback"
            if self._deterministic_fallback_enabled
            else "not_configured",
            "runner_backend": "veadk.Agent+Runner" if configured else "not_configured",
            "model_name": self._model_name if configured else "not_configured",
            "deterministic_fallback_enabled": self._deterministic_fallback_enabled,
        }

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        invocation_id = f"{request.agent_name}-{uuid4().hex}"
        if not model_configured():
            if not self._deterministic_fallback_enabled:
                raise AgentBlocked("模型未配置：请配置模型后再运行内置 Agent。")
            return AgentRunResult(
                output=AgentRunOutput(
                    status="blocked",
                    generation_mode="deterministic_fallback",
                    agent_status="not_configured",
                    payload={},
                    blocked_reasons=["model_not_configured"],
                    tool_calls=_tool_call_summary(request.tool_names, skipped=True),
                    validation_result={
                        "valid": False,
                        "reason": "model_not_configured",
                    },
                ),
                metadata=AgentRuntimeMetadata(
                    agent_name=request.agent_name,
                    agent_invocation_id=invocation_id,
                    runner_backend="not_configured",
                    model_name="not_configured",
                    tool_calls=_tool_call_summary(request.tool_names, skipped=True),
                    generation_mode="deterministic_fallback",
                    agent_status="not_configured",
                    validation_result={
                        "valid": False,
                        "reason": "model_not_configured",
                    },
                ),
            )

        from veadk import Agent, Runner

        agent = Agent(
            name=request.agent_name,
            description="AgentKit Studio internal Knowledge Asset builder.",
            instruction=request.instruction,
            model_name=self._model_name,
            output_schema=request.output_schema or AgentRunOutput,
            enable_responses=True,
            enable_responses_cache=False,
            model_extra_config={"extra_body": {"thinking": {"type": "disabled"}}},
        )
        runner = Runner(agent=agent, app_name=request.agent_name)
        raw = await asyncio.wait_for(
            runner.run(
                json.dumps(redact_sensitive(request.payload), ensure_ascii=False),
                session_id=invocation_id,
            ),
            timeout=request.timeout_seconds,
        )
        try:
            parsed_result = _parse_agent_json(raw)
            parsed = parsed_result.payload
        except json.JSONDecodeError as error:
            raise AgentValidationError("内置 Agent 未返回合法 JSON。") from error
        if request.output_schema:
            model = request.output_schema.model_validate(parsed)
            payload = model.model_dump(mode="json")
        else:
            payload = parsed if isinstance(parsed, dict) else {"value": parsed}
        output = AgentRunOutput(
            status=str(payload.get("status") or "completed"),
            generation_mode=str(payload.get("generation_mode") or "agent"),
            agent_status=str(payload.get("agent_status") or "completed"),
            payload=payload,
            blocked_reasons=[
                str(item) for item in payload.get("blocked_reasons", []) if item
            ]
            if isinstance(payload.get("blocked_reasons"), list)
            else [],
            tool_calls=_tool_call_summary(request.tool_names),
            validation_result=parsed_result.validation_result,
        )
        return AgentRunResult(
            output=output,
            metadata=AgentRuntimeMetadata(
                agent_name=request.agent_name,
                agent_invocation_id=invocation_id,
                runner_backend="veadk.Agent+Runner",
                model_name=self._model_name,
                tool_calls=output.tool_calls,
                generation_mode=output.generation_mode,
                agent_status=output.agent_status,
                validation_result=output.validation_result,
            ),
        )


def model_configured() -> bool:
    return any(os.getenv(name, "").strip() for name in MODEL_KEY_ENV_NAMES)


def deterministic_fallback_allowed() -> bool:
    return _env_truthy("VEADK_KNOWLEDGE_AGENT_DETERMINISTIC_FALLBACK") or _env_truthy(
        "VEADK_SEMANTIC_BUILDER_DETERMINISTIC"
    )


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _tool_call_summary(
    names: tuple[str, ...] | list[str],
    *,
    skipped: bool = False,
) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "status": "skipped_not_configured" if skipped else "available_to_agent",
        }
        for name in names
    ]


def _parse_agent_json(raw: Any) -> ParsedAgentJson:
    """Parse a model JSON response with narrow, auditable envelope repair.

    The internal runner still fails closed for unparseable or schema-invalid output.
    Repairs here are intentionally limited to common response-format noise:
    markdown fences, text surrounding the first JSON object, and a stray quote after
    an array/object value before a delimiter.
    """

    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    candidates: list[tuple[str, str]] = [("strict", text)]
    stripped = _strip_markdown_json_fence(text)
    if stripped != text:
        candidates.append(("strip_markdown_fence", stripped))
    extracted = _extract_first_json_object(stripped)
    if extracted and extracted != stripped:
        candidates.append(("extract_first_json_object", extracted))
    repair_base = extracted or stripped
    repaired = _repair_common_json_value_quote(repair_base)
    if repaired != repair_base:
        candidates.append(("repair_stray_quote_after_value", repaired))

    seen: set[str] = set()
    first_error: json.JSONDecodeError | None = None
    for strategy, candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return ParsedAgentJson(
                payload=json.loads(candidate),
                validation_result={
                    "valid": True,
                    "original_json_valid": strategy == "strict",
                    "output_repair": None if strategy == "strict" else strategy,
                },
            )
        except json.JSONDecodeError as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    fence = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return stripped


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1].strip()
    return None


def _repair_common_json_value_quote(text: str) -> str:
    return re.sub(r"(?<=[}\]])\"(?=\s*[,}\]])", "", text)
