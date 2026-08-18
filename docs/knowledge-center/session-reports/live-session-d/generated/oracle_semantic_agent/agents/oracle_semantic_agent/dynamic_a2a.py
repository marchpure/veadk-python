# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from google.adk.agents import RunConfig
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.run_config import StreamingMode
from google.adk.apps.app import App
from google.adk.cli.adk_web_server import RunAgentRequest
from google.adk.runners import Runner as AdkRunner
from google.adk.utils.context_utils import Aclosing
from google.genai import types
from veadk.cli.frontend_invocation import FrontendInvocationPlugin


_SERVER_STATE_KEY = "_veadk_agentkit_server"
_ADK_SERVER_STATE_KEY = "_veadk_adk_server"
_DYNAMIC_A2A_ROUTES_ENABLED_STATE_KEY = "_veadk_dynamic_a2a_routes_enabled"
_REGISTRY_CONFIG_ATTR = "_veadk_a2a_registry_config"


def _tool_name(tool: object) -> str | None:
    name = getattr(tool, "__name__", None) or getattr(tool, "name", None)
    return str(name) if name else None


def _content_text(content: object) -> str:
    parts = getattr(content, "parts", None) or []
    texts: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            texts.append(str(text))
    return "\n".join(texts)


def _has_a2a_registry_config(agent: object) -> bool:
    if getattr(agent, _REGISTRY_CONFIG_ATTR, None) is not None:
        return True
    return any(
        _has_a2a_registry_config(child)
        for child in getattr(agent, "sub_agents", []) or []
    )


def _add_dynamic_a2a_agent_tools(agent: object, prompt: str) -> int:
    attached = 0
    registry_config = getattr(agent, _REGISTRY_CONFIG_ATTR, None)
    prompt = prompt.strip()
    if registry_config is not None and prompt:
        from veadk.tools.builtin_tools.a2a_registry import build_remote_a2a_agent_tools

        dynamic_tools = build_remote_a2a_agent_tools(prompt, registry_config)
        existing = {
            name
            for tool in getattr(agent, "tools", []) or []
            if (name := _tool_name(tool))
        }
        for tool in dynamic_tools:
            name = _tool_name(tool)
            if not name or name in existing:
                continue
            getattr(agent, "tools").append(tool)
            existing.add(name)
            attached += 1

    for child in getattr(agent, "sub_agents", []) or []:
        attached += _add_dynamic_a2a_agent_tools(child, prompt)
    return attached


def _spawn_dynamic_a2a_agent(base_agent: BaseAgent, prompt: str) -> BaseAgent:
    cloned = base_agent.clone(update={})
    attached = _add_dynamic_a2a_agent_tools(cloned, prompt)
    if _has_a2a_registry_config(cloned):
        print(
            f"dynamic A2A tool assembly completed for this turn: attached={attached}",
            flush=True,
        )
    return cloned


def _promote_route(app: FastAPI, endpoint) -> None:
    routes = app.router.routes
    for index, route in enumerate(routes):
        if getattr(route, "endpoint", None) == endpoint:
            routes.insert(0, routes.pop(index))
            return


def _has_dynamic_a2a_routes(app: FastAPI) -> bool:
    expected = {
        ("/run", "run_agent_dynamic"),
        ("/run_sse", "run_agent_sse_dynamic"),
        ("/invoke", "invoke_agent_dynamic"),
    }
    found: set[tuple[str, str]] = set()
    for route in app.router.routes:
        path = getattr(route, "path", None)
        endpoint_name = getattr(getattr(route, "endpoint", None), "__name__", "")
        if (path, endpoint_name) in expected:
            found.add((path, endpoint_name))
    return expected.issubset(found)


class _RuntimeServices:
    def __init__(self, app: FastAPI):
        agent_server = getattr(app.state, _SERVER_STATE_KEY, None)
        if agent_server is not None:
            self._load_from_server(getattr(agent_server, "server", agent_server))
            return

        adk_server = getattr(app.state, _ADK_SERVER_STATE_KEY, None)
        if adk_server is not None:
            self._load_from_server(adk_server)
            return

        attrs = getattr(app, "_tmpl_attrs", {})
        self.default_app_name = attrs.get("app_name")
        self.current_app_name_ref = attrs.get("current_app_name_ref")
        self.artifact_service = attrs.get("artifact_service")
        self.session_service = attrs.get("session_service")
        self.memory_service = attrs.get("memory_service")
        self.credential_service = attrs.get("credential_service")
        self.auto_create_session = bool(attrs.get("auto_create_session", False))

    def _load_from_server(self, server: object) -> None:
        self.default_app_name = getattr(server, "default_app_name", None)
        self.current_app_name_ref = getattr(server, "current_app_name_ref", None)
        self.artifact_service = getattr(server, "artifact_service", None)
        self.session_service = getattr(server, "session_service", None)
        self.memory_service = getattr(server, "memory_service", None)
        self.credential_service = getattr(server, "credential_service", None)
        self.auto_create_session = bool(getattr(server, "auto_create_session", False))


def _dynamic_runner(services: _RuntimeServices, *, app_name: str, root_agent: BaseAgent, prompt: str):
    if services.session_service is None:
        raise RuntimeError("ADK session service is unavailable")
    run_agent = _spawn_dynamic_a2a_agent(root_agent, prompt)
    agent_app = App(
        name=app_name,
        root_agent=run_agent,
        plugins=[FrontendInvocationPlugin()],
    )
    return AdkRunner(
        app=agent_app,
        artifact_service=services.artifact_service,
        session_service=services.session_service,
        memory_service=services.memory_service,
        credential_service=services.credential_service,
        auto_create_session=services.auto_create_session,
    )


def _resolve_run_app_name(services: _RuntimeServices, root_agent: BaseAgent, req: RunAgentRequest) -> str:
    app_name = req.app_name or services.default_app_name
    if not app_name:
        app_name = getattr(root_agent, "name", "") or ""
    if not app_name:
        raise HTTPException(
            status_code=400,
            detail="app_name is required when ADK_DEFAULT_APP_NAME is not set",
        )
    req.app_name = app_name
    if services.current_app_name_ref is not None:
        services.current_app_name_ref.value = app_name
    return app_name


def _run_request_custom_metadata(req: RunAgentRequest) -> dict[str, Any] | None:
    metadata = getattr(req, "custom_metadata", None)
    return metadata if isinstance(metadata, dict) and metadata else None


def _resolve_invoke_app_name(services: _RuntimeServices, root_agent: BaseAgent) -> str:
    app_name = services.default_app_name or getattr(root_agent, "name", "") or ""
    if not app_name:
        raise HTTPException(
            status_code=400,
            detail="app_name is required when ADK_DEFAULT_APP_NAME is not set",
        )
    if services.current_app_name_ref is not None:
        services.current_app_name_ref.value = app_name
    return app_name


async def _invoke_text(request: Request) -> str:
    body = await request.body()
    if not body:
        return ""
    try:
        payload = json.loads(body)
    except Exception:
        return body.decode("utf-8", errors="replace")
    if isinstance(payload, dict):
        text = payload.get("prompt")
        if text is not None:
            return str(text)
    try:
        return json.dumps(payload, ensure_ascii=False)
    except Exception:
        return ""


def enable_dynamic_a2a_tools(app: FastAPI, root_agent: BaseAgent) -> None:
    if _has_dynamic_a2a_routes(app):
        return

    services = _RuntimeServices(app)
    session_service = services.session_service
    if session_service is None:
        return

    @app.post("/run", response_model=None)
    async def run_agent_dynamic(
        req: RunAgentRequest,
        request: Request,
    ) -> list[Any] | Response:
        app_name = _resolve_run_app_name(services, root_agent, req)
        runner = _dynamic_runner(
            services,
            app_name=app_name,
            root_agent=root_agent,
            prompt=_content_text(req.new_message),
        )
        custom_metadata = _run_request_custom_metadata(req)
        run_config = (
            RunConfig(custom_metadata=custom_metadata) if custom_metadata else None
        )

        async def worker() -> list[Any]:
            async with Aclosing(
                runner.run_async(
                    user_id=req.user_id,
                    session_id=req.session_id,
                    new_message=req.new_message,
                    state_delta=req.state_delta,
                    invocation_id=req.invocation_id,
                    run_config=run_config,
                )
            ) as agen:
                return [event async for event in agen]

        worker_task = asyncio.create_task(worker())

        async def monitor() -> None:
            try:
                while True:
                    message = await request.receive()
                    if message.get("type") == "http.disconnect":
                        worker_task.cancel()
                        break
            except asyncio.CancelledError:
                pass

        monitor_task = asyncio.create_task(monitor())
        try:
            return await worker_task
        except asyncio.CancelledError:
            if await request.is_disconnected():
                return Response(status_code=499)
            raise
        finally:
            monitor_task.cancel()

    @app.post("/run_sse")
    async def run_agent_sse_dynamic(req: RunAgentRequest) -> StreamingResponse:
        app_name = _resolve_run_app_name(services, root_agent, req)
        runner = _dynamic_runner(
            services,
            app_name=app_name,
            root_agent=root_agent,
            prompt=_content_text(req.new_message),
        )
        stream_mode = StreamingMode.SSE if req.streaming else StreamingMode.NONE
        custom_metadata = _run_request_custom_metadata(req)

        if not runner.auto_create_session:
            session = await session_service.get_session(
                app_name=app_name,
                user_id=req.user_id,
                session_id=req.session_id,
            )
            if not session:
                await session_service.create_session(
                    app_name=app_name,
                    user_id=req.user_id,
                    session_id=req.session_id,
                )

        async def event_generator():
            try:
                async with Aclosing(
                    runner.run_async(
                        user_id=req.user_id,
                        session_id=req.session_id,
                        new_message=req.new_message,
                        state_delta=req.state_delta,
                        run_config=RunConfig(
                            streaming_mode=stream_mode,
                            custom_metadata=custom_metadata,
                        ),
                        invocation_id=req.invocation_id,
                    )
                ) as agen:
                    async for event in agen:
                        events_to_stream = [event]
                        if (
                            not req.function_call_event_id
                            and event.actions.artifact_delta
                            and event.content
                            and event.content.parts
                        ):
                            content_event = event.model_copy(deep=True)
                            content_event.actions.artifact_delta = {}
                            artifact_event = event.model_copy(deep=True)
                            artifact_event.content = None
                            events_to_stream = [content_event, artifact_event]

                        for event_to_stream in events_to_stream:
                            yield (
                                "data: "
                                + event_to_stream.model_dump_json(
                                    exclude_none=True,
                                    by_alias=True,
                                )
                                + "\n\n"
                            )
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/invoke")
    async def invoke_agent_dynamic(request: Request) -> StreamingResponse:
        app_name = _resolve_invoke_app_name(services, root_agent)
        user_id = request.headers.get("user_id") or "agentkit_user"
        session_id = request.headers.get("session_id") or ""
        prompt = await _invoke_text(request)
        content = types.UserContent(parts=[types.Part(text=prompt or "")])

        session = await session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
        if not session:
            await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
            )

        runner = _dynamic_runner(
            services,
            app_name=app_name,
            root_agent=root_agent,
            prompt=prompt,
        )

        async def event_generator():
            try:
                async with Aclosing(
                    runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        new_message=content,
                        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
                    )
                ) as agen:
                    async for event in agen:
                        yield (
                            "data: "
                            + event.model_dump_json(
                                exclude_none=True,
                                by_alias=True,
                            )
                            + "\n\n"
                        )
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    _promote_route(app, run_agent_dynamic)
    _promote_route(app, run_agent_sse_dynamic)
    _promote_route(app, invoke_agent_dynamic)
    setattr(app.state, _DYNAMIC_A2A_ROUTES_ENABLED_STATE_KEY, True)
