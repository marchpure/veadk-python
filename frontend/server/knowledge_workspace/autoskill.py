"""Typed, server-only AutoSkill HTTP/SSE client."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .sse import ParsedUpstreamEvent, SseParser, parse_upstream_frame


class AutoSkillProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutoSkillConfig:
    base_url: str
    token: str
    state_mode: str = "stateful"
    timeout_seconds: float = 300.0
    connect_timeout_seconds: float = 10.0
    first_event_timeout_seconds: float = 30.0
    idle_timeout_seconds: float = 60.0
    max_reconnects: int = 2

    @classmethod
    def from_env(cls) -> "AutoSkillConfig":
        base = os.getenv("KNOWLEDGE_AUTOSKILL_BASE_URL", "").rstrip("/")
        token = os.getenv("KNOWLEDGE_AUTOSKILL_TOKEN", "")
        if not base or not token:
            raise AutoSkillProtocolError("AutoSkill base URL/token are not configured")
        return cls(base_url=base, token=token, state_mode=os.getenv("KNOWLEDGE_AUTOSKILL_STATE_MODE", "stateful"))


class AutoSkillClient:
    def __init__(self, config: AutoSkillConfig, *, client: httpx.AsyncClient | None = None) -> None:
        if not config.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("AutoSkill base URL must be server-configured HTTPS")
        self.config = config
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}", "Accept": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}/openapi/autoskill/v1/{path.lstrip('/')}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=self.config.connect_timeout_seconds)
        )
        try:
            response = await client.request(method, self._url(path), headers=self._headers(), **kwargs)
            if response.status_code >= 400:
                raise AutoSkillProtocolError(f"AutoSkill {path} returned HTTP {response.status_code}")
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
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        data = {"agent_id": agent_id, "session_id": session_id, "request_id": request_id}
        if prompt is not None:
            data["prompt"] = prompt
        if model:
            data["model"] = model
        params = {"agent_id": agent_id, "session_id": session_id, "request_id": request_id}
        if name:
            params["name"] = name
        method = "GET" if command in {"list_skill", "view_skill", "find_skill"} and prompt is None else "POST"
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
        async for item in self.stream_request(
            "invoke",
            "POST",
            params={},
            files={key: (None, str(value)) for key, value in kwargs.items() if value is not None},
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
        parser = SseParser()
        headers = self._headers() | {"Accept": "text/event-stream"}
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        response: httpx.Response | None = None
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds, connect=self.config.connect_timeout_seconds)
        )
        try:
            stream_context = client.stream(method, self._url(path), headers=headers, params=params, **kwargs)
            response = await stream_context.__aenter__()
            if response.status_code >= 400:
                raise AutoSkillProtocolError(f"AutoSkill {path} returned HTTP {response.status_code}")
            iterator = response.aiter_bytes().__aiter__()
            first = True
            while True:
                timeout = (
                    self.config.first_event_timeout_seconds
                    if first
                    else self.config.idle_timeout_seconds
                )
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    raise AutoSkillProtocolError(
                        "AutoSkill SSE first-event/idle timeout"
                    ) from exc
                first = False
                for frame in parser.feed(chunk):
                    parsed = parse_upstream_frame(frame)
                    if parsed:
                        yield parsed
            for frame in parser.finish():
                parsed = parse_upstream_frame(frame)
                if parsed:
                    yield parsed
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AutoSkillProtocolError(f"AutoSkill stream transport failure: {type(exc).__name__}") from exc
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
            "stream", "GET",
            params={"agent_id": agent_id, "session_id": session_id, "request_id": request_id},
            last_event_id=last_event_id,
        ):
            yield item

    async def stop(self, *, agent_id: str, session_id: str, request_id: str) -> Mapping[str, Any]:
        response = await self._request(
            "POST", "stop",
            params={"agent_id": agent_id, "session_id": session_id, "request_id": request_id},
        )
        return response.json()

    async def upload(self, *, agent_id: str, session_id: str, file_type: str, file_name: str, content: bytes) -> Mapping[str, Any]:
        response = await self._request(
            "POST", "upload",
            data={"agent_id": agent_id, "session_id": session_id, "type": file_type, "name": file_name},
            files={"file": (file_name, content)},
        )
        return response.json()

    async def download(self, *, agent_id: str, session_id: str, file_type: str, name: str | None = None) -> bytes:
        params = {"agent_id": agent_id, "session_id": session_id, "type": file_type}
        if name:
            params["name"] = name
        response = await self._request("GET", "download", params=params)
        return response.content

    async def get_state(self, *, agent_id: str, session_id: str, request_id: str) -> Mapping[str, Any]:
        response = await self._request("GET", "get_state", params={"agent_id": agent_id, "session_id": session_id, "request_id": request_id})
        return response.json()

    async def list_sessions(self, *, agent_id: str, session_id: str, request_id: str) -> Mapping[str, Any]:
        response = await self._request(
            "GET",
            "list_sessions",
            params={"agent_id": agent_id, "session_id": session_id, "request_id": request_id},
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


class UnavailableAutoSkillClient:
    """Explicit fail-closed client used when server credentials are absent."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def _raise(self) -> None:
        raise AutoSkillProtocolError(self.reason)

    async def health(self) -> Mapping[str, Any]:
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
