"""Typed, server-only AutoSkill HTTP/SSE client."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from .sse import (
    ParsedUpstreamEvent,
    SseParser,
    parse_upstream_frame,
    sanitize_event_payload,
)


class AutoSkillProtocolError(RuntimeError):
    pass


OFFICIAL_AUTOSKILL_BASE_URL = "https://test-bytebrain.byted.org"


@dataclass(frozen=True)
class AutoSkillConfig:
    base_url: str = OFFICIAL_AUTOSKILL_BASE_URL
    token: str | None = None
    state_mode: str = "stateful"
    timeout_seconds: float = 1_800.0
    connect_timeout_seconds: float = 10.0
    first_event_timeout_seconds: float = 180.0
    idle_timeout_seconds: float = 180.0
    max_reconnects: int = 2
    max_event_bytes: int = 2 * 1024 * 1024
    max_response_bytes: int = 20 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "AutoSkillConfig":
        configured_base = os.getenv("KNOWLEDGE_AUTOSKILL_BASE_URL", "").strip()
        environment = os.getenv(
            "KNOWLEDGE_AUTOSKILL_ENVIRONMENT", "development"
        ).strip().casefold()
        if environment in {"production", "prod"} and not configured_base:
            raise AutoSkillProtocolError(
                "production AutoSkill base URL is not configured"
            )
        base = (configured_base or OFFICIAL_AUTOSKILL_BASE_URL).rstrip("/")
        token = os.getenv("KNOWLEDGE_AUTOSKILL_TOKEN", "").strip() or None
        if not base:
            raise AutoSkillProtocolError("AutoSkill base URL is not configured")
        return cls(
            base_url=base,
            token=token,
            state_mode=os.getenv("KNOWLEDGE_AUTOSKILL_STATE_MODE", "stateful"),
        )


class AutoSkillClient:
    def __init__(
        self, config: AutoSkillConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        parsed = urlsplit(config.base_url)
        hostname = (parsed.hostname or "").casefold()
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if (
            (
                parsed.scheme != "https"
                and not (parsed.scheme == "http" and hostname in local_hosts)
            )
            or not hostname
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AutoSkill base URL must be server-configured HTTPS")
        self.config = config
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}/openapi/autoskill/v1/{path.lstrip('/')}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.config.timeout_seconds, connect=self.config.connect_timeout_seconds
            )
        )
        try:
            response = await client.request(
                method, self._url(path), headers=self._headers(), **kwargs
            )
            if response.status_code >= 400:
                raise AutoSkillProtocolError(
                    f"AutoSkill {path} returned HTTP {response.status_code}"
                )
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > self.config.max_response_bytes:
                        raise AutoSkillProtocolError(
                            f"AutoSkill {path} response exceeds configured size limit"
                        )
                except ValueError as exc:
                    raise AutoSkillProtocolError(
                        f"AutoSkill {path} returned invalid content length"
                    ) from exc
            if len(response.content) > self.config.max_response_bytes:
                raise AutoSkillProtocolError(
                    f"AutoSkill {path} response exceeds configured size limit"
                )
            return response
        finally:
            if owns:
                await client.aclose()

    async def health(self) -> Mapping[str, Any]:
        response = await self._request("GET", "health")
        return response.json()

    async def models(self) -> Mapping[str, Any]:
        response = await self._request("GET", "models")
        return response.json()

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
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        if self.config.state_mode.casefold() == "stateless":
            message = prompt or f"/{command.replace('_', '-')}"
            if name:
                message = f"{message} {name}"
            async for item in self.invoke_stateless(
                agent_id=agent_id,
                session_id=session_id,
                request_id=request_id,
                message=message,
                model=model,
                state=state,
            ):
                yield item
            return
        data = {
            "agent_id": agent_id,
            "session_id": session_id,
            "request_id": request_id,
        }
        if prompt is not None:
            data["prompt"] = prompt
        if model:
            data["model"] = model
        params = {
            "agent_id": agent_id,
            "session_id": session_id,
            "request_id": request_id,
        }
        if name:
            params["name"] = name
        method = "GET" if command in {"list_skill", "view_skill"} else "POST"
        if method == "GET":
            query = dict(params)
            if prompt:
                query["prompt"] = prompt
            kwargs = {"params": query}
        else:
            kwargs = {
                "files": {key: (None, str(value)) for key, value in data.items()},
            }
        async for item in self.stream_request(command, method, **kwargs):
            yield item

    async def invoke(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        if self.config.state_mode.casefold() == "stateless":
            async for item in self.invoke_stateless(**kwargs):
                yield item
            return
        async for item in self.stream_request(
            "invoke",
            "POST",
            params={},
            files={
                key: (None, str(value))
                for key, value in kwargs.items()
                if value is not None and key != "state"
            },
        ):
            yield item

    async def invoke_stateless(
        self, *, state: bytes | None = None, **kwargs: Any
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        files: dict[str, tuple[Any, ...]] = {
            key: (None, str(value))
            for key, value in kwargs.items()
            if value is not None
        }
        if state is not None:
            files["state"] = ("state.zip", state, "application/zip")
        async for item in self.stream_request("invoke_stateless", "POST", files=files):
            yield item

    async def create_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.command("create_skill", **kwargs):
            yield item

    async def update_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.command("update_skill", **kwargs):
            yield item

    async def find_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.command("find_skill", **kwargs):
            yield item

    async def list_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.command("list_skill", **kwargs):
            yield item

    async def view_skill(self, **kwargs: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.command("view_skill", **kwargs):
            yield item

    async def delete_skill_stream(
        self, **kwargs: Any
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.stream_request(
            "delete_skill",
            "DELETE",
            params={
                key: str(value) for key, value in kwargs.items() if value is not None
            },
        ):
            yield item

    async def stream_request(
        self,
        path: str,
        method: str,
        *,
        params: Mapping[str, str] | None = None,
        last_event_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        parser = SseParser(max_buffer_bytes=self.config.max_event_bytes)
        headers = self._headers() | {"Accept": "text/event-stream"}
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        response: httpx.Response | None = None
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.config.timeout_seconds, connect=self.config.connect_timeout_seconds
            )
        )
        try:
            stream_context = client.stream(
                method, self._url(path), headers=headers, params=params, **kwargs
            )
            response = await stream_context.__aenter__()
            if response.status_code >= 400:
                raise AutoSkillProtocolError(
                    f"AutoSkill {path} returned HTTP {response.status_code}"
                )
            content_type = response.headers.get("content-type", "").casefold()
            if "application/json" in content_type:
                raw_body = await response.aread()
                if len(raw_body) > self.config.max_response_bytes:
                    raise AutoSkillProtocolError(
                        f"AutoSkill {path} response exceeds configured size limit"
                    )
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    raise AutoSkillProtocolError(
                        f"AutoSkill {path} returned invalid JSON"
                    ) from exc
                safe_payload = sanitize_event_payload(payload)
                yield ParsedUpstreamEvent(
                    None,
                    "final_answer",
                    {
                        "type": "final_answer",
                        "data": {
                            "answer": json.dumps(safe_payload, ensure_ascii=False),
                        },
                    },
                    raw_body.decode("utf-8", errors="replace"),
                )
                yield ParsedUpstreamEvent(
                    None,
                    "done",
                    {"type": "done", "data": {}},
                    "",
                )
                return
            iterator = response.aiter_bytes().__aiter__()
            first_event_seen = False
            terminal_seen = False
            stream_bytes = 0
            async with asyncio.timeout(self.config.timeout_seconds):
                while True:
                    timeout = (
                        self.config.first_event_timeout_seconds
                        if not first_event_seen
                        else self.config.idle_timeout_seconds
                    )
                    try:
                        chunk = await asyncio.wait_for(
                            iterator.__anext__(), timeout=timeout
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError as exc:
                        raise AutoSkillProtocolError(
                            "AutoSkill SSE first-event/idle timeout"
                        ) from exc
                    stream_bytes += len(chunk)
                    if stream_bytes > self.config.max_response_bytes:
                        raise AutoSkillProtocolError(
                            f"AutoSkill {path} stream exceeds configured size limit"
                        )
                    try:
                        frames = parser.feed(chunk)
                    except ValueError as exc:
                        raise AutoSkillProtocolError(str(exc)) from exc
                    for frame in frames:
                        if frame.heartbeat:
                            # Provider keepalives prove that the stream is
                            # alive and move subsequent waits to idle timeout.
                            first_event_seen = True
                        parsed = parse_upstream_frame(frame)
                        if parsed:
                            first_event_seen = True
                            terminal_seen = (
                                parsed.event_type.casefold().replace("-", "_") == "done"
                            )
                            yield parsed
                            if terminal_seen:
                                break
                    if terminal_seen:
                        break
                for frame in parser.finish():
                    parsed = parse_upstream_frame(frame)
                    if parsed:
                        terminal_seen = (
                            parsed.event_type.casefold().replace("-", "_") == "done"
                        )
                        yield parsed
                        if terminal_seen:
                            break
            if not terminal_seen:
                raise AutoSkillProtocolError("AutoSkill SSE disconnected before done")
        except TimeoutError as exc:
            raise AutoSkillProtocolError("AutoSkill SSE total timeout") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AutoSkillProtocolError(
                f"AutoSkill stream transport failure: {type(exc).__name__}"
            ) from exc
        finally:
            if response is not None:
                await response.aclose()
            if owns:
                await client.aclose()

    async def reconnect(
        self,
        *,
        agent_id: str,
        session_id: str,
        request_id: str,
        last_event_id: str | None,
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        async for item in self.stream_request(
            "stream",
            "GET",
            params={
                "agent_id": agent_id,
                "session_id": session_id,
                "request_id": request_id,
            },
            last_event_id=last_event_id,
        ):
            yield item

    async def stop(
        self, *, agent_id: str, session_id: str, request_id: str
    ) -> Mapping[str, Any]:
        response = await self._request(
            "POST",
            "stop",
            params={
                "agent_id": agent_id,
                "session_id": session_id,
                "request_id": request_id,
            },
        )
        return response.json()

    async def upload(
        self,
        *,
        agent_id: str,
        session_id: str,
        file_type: str,
        file_name: str,
        content: bytes,
    ) -> Mapping[str, Any]:
        response = await self._request(
            "POST",
            "upload",
            data={
                "agent_id": agent_id,
                "session_id": session_id,
                "type": file_type,
                "name": file_name,
            },
            files={"file": (file_name, content)},
        )
        return response.json()

    async def download(
        self, *, agent_id: str, session_id: str, file_type: str, name: str | None = None
    ) -> bytes:
        params = {"agent_id": agent_id, "session_id": session_id, "type": file_type}
        if name:
            params["name"] = name
        response = await self._request("GET", "download", params=params)
        return response.content

    async def download_optional_state(
        self, *, agent_id: str, session_id: str
    ) -> bytes | None:
        try:
            return await self.download(
                agent_id=agent_id,
                session_id=session_id,
                file_type="state",
            )
        except AutoSkillProtocolError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    async def get_state(
        self, *, agent_id: str, session_id: str, request_id: str
    ) -> Mapping[str, Any]:
        response = await self._request(
            "GET",
            "get_state",
            params={
                "agent_id": agent_id,
                "session_id": session_id,
                "request_id": request_id,
            },
        )
        return response.json()

    async def list_sessions(
        self, *, agent_id: str, session_id: str, request_id: str
    ) -> Mapping[str, Any]:
        response = await self._request(
            "GET",
            "list_sessions",
            params={
                "agent_id": agent_id,
                "session_id": session_id,
                "request_id": request_id,
            },
        )
        return response.json()

    async def delete_skill(
        self, *, agent_id: str, session_id: str, request_id: str, name: str
    ) -> Mapping[str, Any]:
        response = await self._request(
            "DELETE",
            "delete_skill",
            params={
                "agent_id": agent_id,
                "session_id": session_id,
                "request_id": request_id,
                "name": name,
            },
        )
        return response.json()

    async def get_state_zip(
        self, *, agent_id: str, session_id: str, request_id: str
    ) -> bytes:
        value = await self.get_state(
            agent_id=agent_id, session_id=session_id, request_id=request_id
        )
        data = value.get("data", value)
        encoded = data.get("state_zip_b64") if isinstance(data, Mapping) else None
        if not isinstance(encoded, str):
            raise AutoSkillProtocolError(
                "AutoSkill get_state did not return state_zip_b64"
            )
        import base64

        try:
            return base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise AutoSkillProtocolError(
                "AutoSkill get_state returned invalid state_zip_b64"
            ) from exc


class UnavailableAutoSkillClient:
    """Explicit fail-closed client used when server credentials are absent."""

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

    async def invoke_stateless(self, **_: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        await self._raise()
        if False:
            yield ParsedUpstreamEvent(None, "error", {}, "", True)

    async def reconnect(self, **_: Any) -> AsyncIterator[ParsedUpstreamEvent]:
        await self._raise()
        if False:
            yield ParsedUpstreamEvent(None, "error", {}, "", True)

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
