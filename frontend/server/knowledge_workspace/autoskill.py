"""Server-only native AgentKit adapter for the Knowledge Workspace."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import zipfile
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .sse import ParsedUpstreamEvent, SseParser, sanitize_event_payload


class AutoSkillProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutoSkillConfig:
    base_url: str = ""
    runtime_api_key: str = ""
    app_name: str = "autoskill_creator"
    timeout_seconds: float = 1_800.0
    connect_timeout_seconds: float = 10.0
    first_event_timeout_seconds: float = 180.0
    idle_timeout_seconds: float = 180.0
    max_event_bytes: int = 2 * 1024 * 1024
    max_response_bytes: int = 20 * 1024 * 1024
    # Retained for callers that distinguish the old stateful/stateless adapter.
    # Native AgentKit owns session state and artifacts, so it is always stateful.
    state_mode: str = "native"

    @classmethod
    def from_env(cls) -> AutoSkillConfig:
        base = os.getenv("KNOWLEDGE_AUTOSKILL_BASE_URL", "").strip().rstrip("/")
        api_key = os.getenv("KNOWLEDGE_AUTOSKILL_API_KEY", "").strip()
        environment = os.getenv(
            "KNOWLEDGE_AUTOSKILL_ENVIRONMENT", "development"
        ).casefold()
        if not base:
            prefix = "production " if environment in {"production", "prod"} else ""
            raise AutoSkillProtocolError(
                f"{prefix}AutoSkill base URL is not configured"
            )
        if environment in {"production", "prod"} and not api_key:
            raise AutoSkillProtocolError(
                "production AutoSkill Runtime API key is not configured"
            )
        return cls(base_url=base, runtime_api_key=api_key)


class AutoSkillClient:
    """Translate the existing BFF port to native ADK session/run/artifact APIs."""

    def __init__(
        self, config: AutoSkillConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        parsed = urlsplit(config.base_url)
        hostname = (parsed.hostname or "").casefold()
        environment = os.getenv(
            "KNOWLEDGE_AUTOSKILL_ENVIRONMENT", "development"
        ).casefold()
        loopback = hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
            or (environment in {"production", "prod"} and parsed.scheme != "https")
        ):
            raise ValueError(
                "AutoSkill base URL must be server-configured HTTPS "
                "(loopback HTTP is development-only)"
            )
        self.config = config
        if environment in {"production", "prod"} and not config.runtime_api_key:
            raise AutoSkillProtocolError(
                "production AutoSkill Runtime API key is not configured"
            )
        self._client = client
        self._artifacts: dict[tuple[str, str], tuple[str, int]] = {}
        self._pending_uploads: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    @staticmethod
    def _bearer_authorization(value: str) -> str:
        stripped = value.strip()
        if not stripped:
            return ""
        if any(character in stripped for character in ("\r", "\n")):
            raise AutoSkillProtocolError(
                "AutoSkill Runtime API key contains invalid characters"
            )
        if stripped.casefold().startswith("bearer "):
            return stripped
        return f"Bearer {stripped}"

    def _headers(self, headers: Mapping[str, str] | None = None) -> dict[str, str]:
        prepared = {"Accept": "application/json", **dict(headers or {})}
        authorization = self._bearer_authorization(self.config.runtime_api_key)
        if authorization:
            prepared["Authorization"] = authorization
        return prepared

    def _session_path(self, user_id: str, session_id: str) -> str:
        return (
            f"/apps/{quote(self.config.app_name, safe='')}/users/"
            f"{quote(user_id, safe='')}/sessions/{quote(session_id, safe='')}"
        )

    def _http(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return (
            httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.config.timeout_seconds,
                    connect=self.config.connect_timeout_seconds,
                )
            ),
            True,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        client, owns = self._http()
        try:
            response = await client.request(
                method,
                self._url(path),
                headers=self._headers(headers),
                **kwargs,
            )
            if response.status_code >= 400:
                raise AutoSkillProtocolError(
                    f"AutoSkill AgentKit {path} returned HTTP {response.status_code}"
                )
            if len(response.content) > self.config.max_response_bytes:
                raise AutoSkillProtocolError(
                    f"AutoSkill AgentKit {path} response exceeds configured size limit"
                )
            return response
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AutoSkillProtocolError(
                f"AutoSkill AgentKit transport failure: {type(exc).__name__}"
            ) from exc
        finally:
            if owns:
                await client.aclose()

    async def health(self) -> Mapping[str, Any]:
        try:
            response = await self._request("GET", "/ping")
        except AutoSkillProtocolError as exc:
            if "HTTP 404" not in str(exc):
                raise
            response = await self._request("GET", "/health")
        return {**response.json(), "state_mode": "native"}

    async def models(self) -> Mapping[str, Any]:
        response = await self._request("GET", "/list-apps")
        apps = response.json()
        if not isinstance(apps, list):
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit /list-apps returned invalid JSON"
            )
        return {"models": [], "apps": apps, "source": "agentkit"}

    async def ensure_session(self, *, user_id: str, session_id: str) -> None:
        path = self._session_path(user_id, session_id)
        client, owns = self._http()
        try:
            response = await client.get(self._url(path), headers=self._headers())
            if response.status_code == 200:
                return
            if response.status_code != 404:
                raise AutoSkillProtocolError(
                    f"AutoSkill AgentKit session read returned HTTP {response.status_code}"
                )
            collection = path.rsplit("/", 1)[0]
            created = await client.post(
                self._url(collection),
                headers={
                    **self._headers(),
                    "Content-Type": "application/json",
                },
                json={"sessionId": session_id},
            )
            if created.status_code >= 400:
                raise AutoSkillProtocolError(
                    f"AutoSkill AgentKit session create returned HTTP {created.status_code}"
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AutoSkillProtocolError(
                f"AutoSkill AgentKit session transport failure: {type(exc).__name__}"
            ) from exc
        finally:
            if owns:
                await client.aclose()

    async def command(
        self,
        command: str,
        *,
        agent_id: str,
        session_id: str,
        request_id: str,
        prompt: str | None = None,
        name: str | None = None,
        model: str | None = None,
        state: bytes | None = None,
        invocation_policy: Mapping[str, Any] | None = None,
        connection: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        del model, state, invocation_policy
        command_text = f"/{command.replace('_', '-')}"
        suffix = " ".join(
            item.strip()
            for item in (name, prompt)
            if isinstance(item, str) and item.strip()
        )
        message = f"{command_text} {suffix}".strip()
        async for event in self._run_sse(
            user_id=agent_id,
            session_id=session_id,
            invocation_id=request_id,
            message=message,
            connection=connection,
            named_command=command,
        ):
            yield event

    async def invoke(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self._run_sse(
            user_id=str(kwargs["agent_id"]),
            session_id=str(kwargs["session_id"]),
            invocation_id=str(kwargs["request_id"]),
            message=str(kwargs.get("message") or kwargs.get("prompt") or ""),
            connection=kwargs.get("connection"),
        ):
            yield event

    async def invoke_stateless(
        self, **kwargs: Any
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self.invoke(**kwargs):
            yield event

    async def create_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self.command("create_skill", **kwargs):
            yield event

    async def update_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self.command("update_skill", **kwargs):
            yield event

    async def find_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self.command("find_skill", **kwargs):
            yield event

    async def list_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self.command("list_skill", **kwargs):
            yield event

    async def view_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for event in self.command("view_skill", **kwargs):
            yield event

    async def _run_sse(
        self,
        *,
        user_id: str,
        session_id: str,
        invocation_id: str,
        message: str,
        connection: Mapping[str, Any] | None = None,
        named_command: str | None = None,
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        await self.ensure_session(user_id=user_id, session_id=session_id)
        metadata: Mapping[str, Any] | None = None
        authorization: str | None = None
        if connection:
            candidate = connection.get("metadata")
            if isinstance(candidate, Mapping):
                metadata = dict(candidate)
            value = connection.get("authorization")
            if isinstance(value, str) and value.strip():
                authorization = value.strip()
        body: dict[str, Any] = {
            "appName": self.config.app_name,
            "userId": user_id,
            "sessionId": session_id,
            "invocationId": invocation_id,
            "streaming": True,
            "newMessage": {
                "role": "user",
                "parts": [
                    *self._pending_uploads.pop((user_id, session_id), []),
                    {"text": message},
                ],
            },
        }
        if metadata is not None:
            body["customMetadata"] = {"autoskill_connection": metadata}
        headers = self._headers(
            {"Accept": "text/event-stream", "Content-Type": "application/json"}
        )
        if authorization:
            headers["X-Autoskill-Connection-Authorization"] = authorization

        client, owns = self._http()
        response: httpx.Response | None = None
        parser = SseParser(max_buffer_bytes=self.config.max_event_bytes)
        calls: dict[str, str] = {}
        call_arguments: dict[str, Mapping[str, Any]] = {}
        matched_calls: list[dict[str, Any]] = []
        skills_created: list[str] = []
        skills_updated: list[str] = []
        skills_used: list[str] = []
        final_text: list[str] = []
        terminal_error = False
        sequence = 0
        try:
            stream = client.stream(
                "POST", self._url("/run_sse"), headers=headers, json=body
            )
            response = await stream.__aenter__()
            assert response is not None
            if response.status_code >= 400:
                raise AutoSkillProtocolError(
                    f"AutoSkill AgentKit /run_sse returned HTTP {response.status_code}"
                )
            iterator = response.aiter_bytes().__aiter__()
            first = True
            total = 0
            async with asyncio.timeout(self.config.timeout_seconds):
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            iterator.__anext__(),
                            timeout=(
                                self.config.first_event_timeout_seconds
                                if first
                                else self.config.idle_timeout_seconds
                            ),
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError as exc:
                        raise AutoSkillProtocolError(
                            "AutoSkill AgentKit SSE first-event/idle timeout"
                        ) from exc
                    first = False
                    total += len(chunk)
                    if total > self.config.max_response_bytes:
                        raise AutoSkillProtocolError(
                            "AutoSkill AgentKit SSE exceeds configured size limit"
                        )
                    for frame in parser.feed(chunk):
                        if frame.heartbeat or not frame.data:
                            continue
                        sequence += 1
                        for event in self._map_adk_event(
                            frame.data,
                            invocation_id=invocation_id,
                            sequence=sequence,
                            calls=calls,
                            call_arguments=call_arguments,
                            matched_calls=matched_calls,
                            skills_created=skills_created,
                            skills_updated=skills_updated,
                            skills_used=skills_used,
                            final_text=final_text,
                            user_id=user_id,
                            session_id=session_id,
                        ):
                            if event.event_type == "error":
                                terminal_error = True
                            yield event
                for frame in parser.finish():
                    if not frame.heartbeat and frame.data:
                        sequence += 1
                        for event in self._map_adk_event(
                            frame.data,
                            invocation_id=invocation_id,
                            sequence=sequence,
                            calls=calls,
                            call_arguments=call_arguments,
                            matched_calls=matched_calls,
                            skills_created=skills_created,
                            skills_updated=skills_updated,
                            skills_used=skills_used,
                            final_text=final_text,
                            user_id=user_id,
                            session_id=session_id,
                        ):
                            if event.event_type == "error":
                                terminal_error = True
                            yield event
            if terminal_error:
                return
            if not final_text:
                final_text.append("AutoSkill AgentKit run completed.")
            yield self._event(
                "final_answer", {"answer": "".join(final_text)}, invocation_id
            )
            target = (skills_created or skills_updated or skills_used or [None])[-1]
            summary = {
                "status": "succeeded",
                "skills_created": skills_created,
                "skills_updated": skills_updated,
                "skills_used": skills_used,
                "policy_evaluation": {
                    "satisfied": bool(matched_calls) if metadata is not None else True,
                    "matched_calls": matched_calls,
                },
                **({"target_skill": target} if target else {}),
                "named_command": named_command,
            }
            yield self._event("request_summary", summary, invocation_id)
            yield self._event("done", {}, invocation_id)
        except TimeoutError as exc:
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit SSE total timeout"
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AutoSkillProtocolError(
                f"AutoSkill AgentKit stream transport failure: {type(exc).__name__}"
            ) from exc
        finally:
            if response is not None:
                await response.aclose()
            if owns:
                await client.aclose()

    @staticmethod
    def _event(
        kind: str, data: Mapping[str, Any], invocation_id: str
    ) -> ParsedUpstreamEvent:
        payload = {"type": kind, "data": sanitize_event_payload(dict(data))}
        return ParsedUpstreamEvent(None, kind, payload, json.dumps(payload))

    def _map_adk_event(
        self,
        raw: str,
        *,
        invocation_id: str,
        sequence: int,
        calls: dict[str, str],
        call_arguments: dict[str, Mapping[str, Any]],
        matched_calls: list[dict[str, Any]],
        skills_created: list[str],
        skills_updated: list[str],
        skills_used: list[str],
        final_text: list[str],
        user_id: str,
        session_id: str,
    ) -> list[ParsedUpstreamEvent]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return [
                ParsedUpstreamEvent(
                    None, "unknown", {"raw": sanitize_event_payload(raw)}, raw, True
                )
            ]
        if not isinstance(value, Mapping):
            return []
        if value.get("error"):
            return [
                self._event(
                    "error",
                    {
                        "code": "AGENTKIT_ERROR",
                        "message": str(value["error"]),
                        "retryable": False,
                        "category": "runtime",
                    },
                    invocation_id,
                )
            ]
        result: list[ParsedUpstreamEvent] = []
        artifact_delta = (value.get("actions") or {}).get("artifactDelta")
        if not isinstance(artifact_delta, Mapping):
            artifact_delta = (value.get("actions") or {}).get("artifact_delta")
        if isinstance(artifact_delta, Mapping):
            for filename, version in artifact_delta.items():
                try:
                    parsed_version = int(version)
                except (TypeError, ValueError):
                    continue
                self._artifacts[(user_id, session_id)] = (
                    str(filename),
                    parsed_version,
                )
                result.append(
                    self._event(
                        "artifact_delta",
                        {"filename": str(filename), "version": parsed_version},
                        invocation_id,
                    )
                )
        content = value.get("content")
        parts = content.get("parts", []) if isinstance(content, Mapping) else []
        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, Mapping):
                continue
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, Mapping):
                name = str(function_call.get("name") or "agentkit.tool")
                call_id = str(function_call.get("id") or f"{invocation_id}:{sequence}")
                args = function_call.get("args") or function_call.get("arguments") or {}
                calls[call_id] = name
                call_arguments[call_id] = args if isinstance(args, Mapping) else {}
                skill_name = (
                    str(args.get("new_name") or args.get("name") or "")
                    if isinstance(args, Mapping)
                    else ""
                )
                if (
                    name == "create_skill"
                    and skill_name
                    and skill_name not in skills_created
                ):
                    skills_created.append(skill_name)
                elif (
                    name == "update_skill"
                    and skill_name
                    and skill_name not in skills_updated
                ):
                    skills_updated.append(skill_name)
                elif (
                    name == "read_skill"
                    and skill_name
                    and skill_name not in skills_used
                ):
                    skills_used.append(skill_name)
                result.append(
                    self._event(
                        "action",
                        {
                            "call_id": call_id,
                            "name": name,
                            "arguments": args,
                            "status": "started",
                        },
                        invocation_id,
                    )
                )
            function_response = part.get("functionResponse") or part.get(
                "function_response"
            )
            if isinstance(function_response, Mapping):
                call_id = str(
                    function_response.get("id") or f"{invocation_id}:{sequence}"
                )
                response_value = function_response.get("response")
                ok = not (
                    isinstance(response_value, Mapping)
                    and response_value.get("ok") is False
                )
                response_name = str(
                    function_response.get("name")
                    or calls.get(call_id)
                    or "agentkit.tool"
                )
                arguments = call_arguments.get(call_id, {})
                action_id = str(
                    arguments.get("actionId") or arguments.get("action_id") or ""
                )
                if ok and action_id:
                    matched_calls.append(
                        {
                            "tool": (
                                "mcp__knowledge-connection-1__execute_action"
                                if response_name == "execute_action"
                                else response_name
                            ),
                            "actionId": action_id,
                            "ok": True,
                        }
                    )
                result.append(
                    self._event(
                        "observation",
                        {
                            "call_id": call_id,
                            "name": response_name,
                            "ok": ok,
                            "output_summary": "Tool completed" if ok else "",
                            "error": ""
                            if ok
                            else str(
                                response_value.get("error", "Tool failed")
                                if isinstance(response_value, Mapping)
                                else "Tool failed"
                            ),
                        },
                        invocation_id,
                    )
                )
            text = part.get("text")
            if isinstance(text, str) and text and not part.get("thought"):
                final_text.append(text)
                result.append(
                    self._event(
                        "assistant_delta",
                        {"delta": text, "sequence": sequence},
                        invocation_id,
                    )
                )
        return result

    async def download(
        self,
        *,
        agent_id: str,
        session_id: str,
        file_type: str,
        name: str | None = None,
    ) -> bytes:
        artifact = self._artifacts.get((agent_id, session_id))
        if artifact is None:
            raise AutoSkillProtocolError("AutoSkill AgentKit emitted no artifactDelta")
        filename, version = artifact
        await self._request(
            "GET", f"{self._session_path(agent_id, session_id)}/artifacts"
        )
        await self._request(
            "GET",
            (
                f"{self._session_path(agent_id, session_id)}/artifacts/"
                f"{quote(filename, safe='')}/versions"
            ),
        )
        path = (
            f"{self._session_path(agent_id, session_id)}/artifacts/"
            f"{quote(filename, safe='')}/versions/{version}"
        )
        response = await self._request("GET", path)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit artifact version returned invalid JSON"
            ) from exc
        inline = payload.get("inlineData") or payload.get("inline_data")
        encoded = inline.get("data") if isinstance(inline, Mapping) else None
        if not isinstance(encoded, str):
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit artifact version has no inline ZIP data"
            )
        try:
            normalized = encoded.strip()
            normalized += "=" * (-len(normalized) % 4)
            data = base64.b64decode(normalized, altchars=b"-_", validate=True)
        except (ValueError, TypeError, base64.binascii.Error) as exc:
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit artifact version has invalid base64 data"
            ) from exc
        if len(data) > self.config.max_response_bytes:
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit artifact exceeds configured size limit"
            )
        if file_type == "skill" and name:
            return self._skill_subtree(data, name)
        return data

    @staticmethod
    def _skill_subtree(content: bytes, skill_name: str) -> bytes:
        prefix = f"skillhub/{skill_name}/"
        try:
            source = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise AutoSkillProtocolError(
                "AutoSkill AgentKit artifact is not a valid ZIP"
            ) from exc
        output = io.BytesIO()
        found = False
        with source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                path = info.filename
                if (
                    info.is_dir()
                    or not path.startswith(prefix)
                    or path.startswith("/")
                    or "\\" in path
                    or ".." in path.split("/")
                ):
                    continue
                target.writestr(path, source.read(info))
                found = True
        if not found:
            raise AutoSkillProtocolError(
                f"AutoSkill AgentKit artifact has no Skill subtree for {skill_name}"
            )
        return output.getvalue()

    async def download_optional_state(self, **_: Any) -> bytes | None:
        return None

    async def upload(
        self,
        *,
        agent_id: str,
        session_id: str,
        file_type: str,
        file_name: str,
        content: bytes,
    ) -> Mapping[str, Any]:
        if file_type == "state" or file_name.casefold() == "state.zip":
            raise AutoSkillProtocolError(
                "native AgentKit forbids BFF state.zip uploads"
            )
        self._pending_uploads.setdefault((agent_id, session_id), []).append(
            {
                "inlineData": {
                    "mimeType": (
                        "application/zip"
                        if file_name.casefold().endswith(".zip")
                        else "application/octet-stream"
                    ),
                    "data": base64.b64encode(content).decode("ascii"),
                    "displayName": file_name,
                }
            }
        )
        return {"accepted": True}

    async def get_state(self, **_: Any) -> Mapping[str, Any]:
        raise AutoSkillProtocolError("native AgentKit state is session-owned")

    async def get_state_zip(self, **_: Any) -> bytes:
        raise AutoSkillProtocolError("native AgentKit state ZIP is not exposed")

    async def reconnect(self, **_: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        raise AutoSkillProtocolError(
            "native AgentKit has no Last-Event-ID replay; resume from BFF events"
        )
        if False:
            yield self._event("done", {}, "")

    async def stop(self, **_: Any) -> Mapping[str, Any]:
        # Cancellation is BFF-authoritative. AgentKit has no portable interrupt API.
        return {"status": "cancelled"}

    async def list_sessions(self, **_: Any) -> Mapping[str, Any]:
        raise AutoSkillProtocolError("use the native AgentKit session API")

    async def delete_skill(self, **_: Any) -> Mapping[str, Any]:
        raise AutoSkillProtocolError("delete Skill through a native AgentKit run")


class UnavailableAutoSkillClient:
    """Explicit fail-closed client used when server configuration is absent."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def _raise(self) -> None:
        raise AutoSkillProtocolError(self.reason)

    async def health(self) -> Mapping[str, Any]:
        await self._raise()
        return {}

    async def models(self) -> Mapping[str, Any]:
        await self._raise()
        return {}

    async def command(self, **_: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        await self._raise()
        if False:
            yield ParsedUpstreamEvent(None, "error", {}, "", True)

    async def invoke(self, **_: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        await self._raise()
        if False:
            yield ParsedUpstreamEvent(None, "error", {}, "", True)

    invoke_stateless = invoke
    reconnect = invoke

    async def stop(self, **_: Any) -> Mapping[str, Any]:
        await self._raise()
        return {}

    async def download(self, **_: Any) -> bytes:
        await self._raise()
        return b""

    async def download_optional_state(self, **_: Any) -> bytes | None:
        await self._raise()
        return None

    async def upload(self, **_: Any) -> Mapping[str, Any]:
        await self._raise()
        return {}

    async def get_state(self, **_: Any) -> Mapping[str, Any]:
        await self._raise()
        return {}

    async def get_state_zip(self, **_: Any) -> bytes:
        await self._raise()
        return b""

    async def list_sessions(self, **_: Any) -> Mapping[str, Any]:
        await self._raise()
        return {}

    async def delete_skill(self, **_: Any) -> Mapping[str, Any]:
        await self._raise()
        return {}
