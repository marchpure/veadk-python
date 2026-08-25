"""Official MCP SDK client for bounded streamable HTTP and SSE connectors."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from ..security import sanitize_mcp_output, validate_mcp_tool
from .http_transport import network_origin, validate_network_endpoint
from .models import (
    McpTraceStatus,
    RemoteMcpConfiguration,
    RemoteMcpExchange,
    RemoteMcpMethod,
    RemoteMcpTrace,
)


class RemoteMcpError(RuntimeError):
    def __init__(self, code: str, message: str, *, trace: RemoteMcpTrace) -> None:
        super().__init__(message)
        self.code = code
        self.trace = trace


@dataclass(frozen=True)
class RemoteMcpCallResult:
    rows: list[dict[str, object]]
    schema: list[tuple[str, str, bool]]
    trace: RemoteMcpTrace
    tool_name: str
    run_id: str


class RemoteMcpClient:
    def __init__(
        self,
        *,
        secret_resolver: Callable[[str], str | None] | None = None,
        resolver: Callable[[str], list[str]] | None = None,
        allow_private_hosts: set[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secret_resolver = secret_resolver or (lambda _ref: None)
        self._resolver = resolver
        self._allow_private_hosts = frozenset(allow_private_hosts or ())
        self._transport = transport

    def discover(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        connection_id: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        trace_id: str,
    ) -> tuple[list[dict[str, object]], RemoteMcpTrace]:
        tools, _payload, trace, _secrets = self._run(
            workspace_id=workspace_id,
            principal_id=principal_id,
            connection_id=connection_id,
            configuration=configuration,
            secret_ref=secret_ref,
            trace_id=trace_id,
            tool_name=None,
            tool_arguments={},
        )
        return tools, trace

    def call(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        connection_id: str,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        trace_id: str,
        tool_name: str,
        tool_arguments: dict[str, object],
    ) -> RemoteMcpCallResult:
        _tools, payload, trace, secrets = self._run(
            workspace_id=workspace_id,
            principal_id=principal_id,
            connection_id=connection_id,
            configuration=configuration,
            secret_ref=secret_ref,
            trace_id=trace_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )
        if payload is None:
            raise RemoteMcpError(
                "MCP_INVALID_TOOL_RESULT",
                "Remote MCP tools/call returned no result.",
                trace=_failed_result_trace(trace, "MCP_INVALID_TOOL_RESULT"),
            )
        try:
            rows = _rows(payload, secrets)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RemoteMcpError(
                "MCP_INVALID_TOOL_RESULT",
                "Remote MCP returned an invalid tool result.",
                trace=_failed_result_trace(trace, "MCP_INVALID_TOOL_RESULT"),
            ) from error
        return RemoteMcpCallResult(
            rows=rows,
            schema=_infer_schema(rows),
            trace=trace,
            tool_name=tool_name,
            run_id=trace.id,
        )

    def _run(self, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(anyio.run, self._session, kwargs).result()

    async def _session(
        self,
        values: dict[str, object],
    ) -> tuple[
        list[dict[str, object]],
        dict[str, object] | None,
        RemoteMcpTrace,
        frozenset[str],
    ]:
        configuration = RemoteMcpConfiguration.model_validate(values["configuration"])
        workspace_id = str(values["workspace_id"])
        principal_id = str(values["principal_id"])
        connection_id = str(values["connection_id"])
        trace_id = str(values["trace_id"])
        tool_name = values["tool_name"]
        tool_arguments = values["tool_arguments"]
        if tool_name is not None and not isinstance(tool_name, str):
            raise TypeError("remote MCP tool name must be a string")
        if not isinstance(tool_arguments, dict):
            raise TypeError("remote MCP tool arguments must be an object")
        endpoint = configuration.endpoint
        origin = network_origin(endpoint)
        headers: dict[str, str] = {}
        secrets: frozenset[str] = frozenset()
        pinned_addresses: frozenset[str] = frozenset()
        exchanges: list[RemoteMcpExchange] = []
        protocol_version: str | None = None
        server_name: str | None = None
        session_id: str | None = None
        started_at = _timestamp()
        total_output = 0

        def trace(
            status: McpTraceStatus,
            *,
            error_code: str | None = None,
        ) -> RemoteMcpTrace:
            safe_endpoint = _safe_endpoint(endpoint)
            digest_source = (
                f"{trace_id}:{configuration.transport}:{safe_endpoint}:{started_at}"
            )
            return RemoteMcpTrace(
                id="mcp-remote-trace-"
                + hashlib.sha256(digest_source.encode()).hexdigest()[:24],
                workspace_id=workspace_id,
                principal_id=principal_id,
                connection_id=connection_id,
                correlation_id=trace_id,
                transport=configuration.transport,
                endpoint=safe_endpoint,
                protocol_version=protocol_version,
                server_name=server_name,
                session_id_digest=(
                    hashlib.sha256(session_id.encode()).hexdigest()
                    if session_id
                    else None
                ),
                status=status,
                error_code=error_code,
                exchanges=exchanges,
                started_at=started_at,
                finished_at=_timestamp(),
            )

        def record(method: RemoteMcpMethod, result: object) -> None:
            nonlocal total_output
            raw = json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            total_output += len(raw)
            if total_output > configuration.output_bytes:
                exchanges.append(
                    RemoteMcpExchange(
                        sequence=len(exchanges) + 1,
                        method=method,
                        status="failed",
                        error_code="MCP_OUTPUT_LIMIT",
                    )
                )
                raise ValueError("remote MCP output exceeds the configured budget")
            exchanges.append(
                RemoteMcpExchange(
                    sequence=len(exchanges) + 1,
                    method=method,
                    status="succeeded",
                    response_digest=hashlib.sha256(raw).hexdigest(),
                )
            )

        async def request_guard(request: httpx.Request) -> None:
            if network_origin(str(request.url)) != origin:
                raise ValueError("remote MCP cross-origin requests are not allowed")
            current = validate_network_endpoint(
                str(request.url),
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
            if current != pinned_addresses:
                raise ValueError(
                    "remote MCP endpoint DNS resolution changed during the session"
                )

        async def response_guard(response: httpx.Response) -> None:
            current = validate_network_endpoint(
                str(response.request.url),
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
            if current != pinned_addresses:
                raise ValueError(
                    "remote MCP endpoint DNS resolution changed during the session"
                )

        timeout = httpx.Timeout(
            configuration.call_timeout_seconds,
            read=configuration.call_timeout_seconds,
        )

        def client_factory(
            headers: dict[str, str] | None = None,
            timeout: httpx.Timeout | None = None,
            auth: httpx.Auth | None = None,
        ) -> httpx.AsyncClient:
            merged = {**self_headers, **(headers or {})}
            return httpx.AsyncClient(
                headers=merged,
                timeout=timeout or httpx.Timeout(configuration.call_timeout_seconds),
                auth=auth,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
                event_hooks={
                    "request": [request_guard],
                    "response": [response_guard],
                },
            )

        try:
            headers, secrets = self._headers(
                values.get("secret_ref"), workspace_id=workspace_id
            )
            pinned_addresses = validate_network_endpoint(
                endpoint,
                resolver=self._resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
            self_headers = headers
            if configuration.transport == "streamable_http":
                client = client_factory(timeout=timeout)
                async with (
                    client,
                    streamable_http_client(
                        endpoint,
                        http_client=client,
                    ) as streams,
                ):
                    read_stream, write_stream, get_session_id = streams
                    result = await self._sdk_session(
                        read_stream=read_stream,
                        write_stream=write_stream,
                        configuration=configuration,
                        tool_name=tool_name,
                        tool_arguments=tool_arguments,
                        record=record,
                    )
                    session_id = get_session_id()
            else:
                captured_session: list[str] = []
                async with sse_client(
                    endpoint,
                    headers=headers,
                    timeout=configuration.startup_timeout_seconds,
                    sse_read_timeout=configuration.call_timeout_seconds,
                    httpx_client_factory=client_factory,
                    on_session_created=captured_session.append,
                ) as streams:
                    read_stream, write_stream = streams
                    result = await self._sdk_session(
                        read_stream=read_stream,
                        write_stream=write_stream,
                        configuration=configuration,
                        tool_name=tool_name,
                        tool_arguments=tool_arguments,
                        record=record,
                    )
                    session_id = captured_session[-1] if captured_session else None
            protocol_version, server_name, tools, call_payload = result
            exchanges.append(
                RemoteMcpExchange(
                    sequence=len(exchanges) + 1,
                    method="close",
                    status="succeeded",
                    response_digest=hashlib.sha256(b"closed").hexdigest(),
                )
            )
            return tools, call_payload, trace("succeeded"), secrets
        except BaseException as error:
            code = _error_code(error)
            if not exchanges or exchanges[-1].status != "failed":
                failed_method: RemoteMcpMethod = (
                    "tools/call" if tool_name else "initialize"
                )
                exchanges.append(
                    RemoteMcpExchange(
                        sequence=len(exchanges) + 1,
                        method=failed_method,
                        status="failed",
                        error_code=code,
                    )
                )
            status: McpTraceStatus = "timed_out" if code == "MCP_TIMEOUT" else "failed"
            failed_trace = trace(status, error_code=code)
            raise RemoteMcpError(
                code,
                _safe_error_message(code),
                trace=failed_trace,
            ) from error

    @staticmethod
    async def _sdk_session(
        *,
        read_stream,
        write_stream,
        configuration: RemoteMcpConfiguration,
        tool_name: str | None,
        tool_arguments: dict[str, object],
        record,
    ) -> tuple[
        str | None,
        str | None,
        list[dict[str, object]],
        dict[str, object] | None,
    ]:
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=configuration.call_timeout_seconds),
        ) as session:
            with anyio.fail_after(configuration.startup_timeout_seconds):
                initialized = await session.initialize()
            initialized_payload = initialized.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            record("initialize", initialized_payload)
            tools: list[dict[str, object]] = []
            cursor = None
            for _page in range(configuration.max_pages):
                listed = await session.list_tools(cursor=cursor)
                payload = listed.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
                record("tools/list", payload)
                tools.extend(
                    tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for tool in listed.tools
                    if tool.name in configuration.tool_allowlist
                )
                cursor = listed.nextCursor
                if not cursor:
                    break
            else:
                raise ValueError("remote MCP tools/list exceeds the page limit")
            discovered = {str(tool["name"]) for tool in tools}
            missing = set(configuration.tool_allowlist) - discovered
            if missing:
                raise ValueError(
                    f"remote MCP allowlisted tools were not discovered: {sorted(missing)}"
                )
            call_payload = None
            if tool_name is not None:
                validate_mcp_tool(
                    tool_name,
                    allowlist=set(configuration.tool_allowlist),
                    output_bytes=0,
                    max_output_bytes=configuration.output_bytes,
                )
                called = await session.call_tool(tool_name, tool_arguments)
                call_payload = called.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
                record("tools/call", call_payload)
                if called.isError:
                    raise ValueError("remote MCP tool reported failure")
            server_info = initialized.serverInfo
            return (
                str(initialized.protocolVersion),
                server_info.name if server_info else None,
                tools,
                call_payload,
            )

    def _headers(
        self, secret_ref: object, *, workspace_id: str
    ) -> tuple[dict[str, str], frozenset[str]]:
        if secret_ref is None:
            return {}, frozenset()
        if not isinstance(secret_ref, str) or not secret_ref.startswith(
            f"secret://{workspace_id}/"
        ):
            raise ValueError("remote MCP secretRef must belong to the active workspace")
        value = self._secret_resolver(secret_ref)
        if value is None:
            raise ValueError("remote MCP secretRef could not be resolved")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"Authorization": f"Bearer {value}"}, frozenset({value})
        if not isinstance(decoded, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in decoded.items()
        ):
            raise ValueError("remote MCP secret must contain a string header map")
        forbidden = {"host", "content-length", "transfer-encoding", "connection"}
        if any(key.casefold() in forbidden for key in decoded):
            raise ValueError("remote MCP secret contains a forbidden HTTP header")
        return (
            {str(key): str(item) for key, item in decoded.items()},
            frozenset(str(item) for item in decoded.values()),
        )

    def validate_credentials(self, secret_ref: object, *, workspace_id: str) -> None:
        """Resolve optional remote credentials without opening a connection."""
        self._headers(secret_ref, workspace_id=workspace_id)


def _rows(
    payload: dict[str, object], secrets: frozenset[str]
) -> list[dict[str, object]]:
    structured = payload.get("structuredContent")
    rows = structured.get("rows") if isinstance(structured, dict) else None
    if not isinstance(rows, list):
        content = payload.get("content")
        texts = (
            [
                item.get("text")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if isinstance(content, list)
            else []
        )
        if not texts:
            raise ValueError("remote MCP result contains no rows")
        value = json.loads(sanitize_mcp_output(str(texts[0])))
        rows = value if isinstance(value, list) else [value]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("remote MCP result rows must be objects")
    return [
        {str(key): _sanitize(item, secrets, key=str(key)) for key, item in row.items()}
        for row in rows
    ]


def _sanitize(value: object, secrets: frozenset[str], *, key: str = "") -> object:
    normalized = key.casefold().replace("-", "").replace("_", "")
    if any(
        marker in normalized
        for marker in ("password", "token", "secret", "credential", "apikey")
    ) and value not in (None, ""):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child): _sanitize(item, secrets, key=str(child))
            for child, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        result = sanitize_mcp_output(value)
        for secret in secrets:
            result = result.replace(secret, "[REDACTED]")
        return result
    return value


def _infer_schema(
    rows: list[dict[str, object]],
) -> list[tuple[str, str, bool]]:
    from .adapters import _infer_mapping_fields

    return _infer_mapping_fields(rows)


def _safe_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _failed_result_trace(trace: RemoteMcpTrace, error_code: str) -> RemoteMcpTrace:
    exchanges = [
        *trace.exchanges,
        RemoteMcpExchange(
            sequence=len(trace.exchanges) + 1,
            method="tools/call",
            status="failed",
            error_code=error_code,
        ),
    ]
    return trace.model_copy(
        update={
            "status": "failed",
            "error_code": error_code,
            "exchanges": exchanges,
            "finished_at": _timestamp(),
        }
    )


def _error_code(error: BaseException) -> str:
    for current in _exception_chain(error):
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return "MCP_TIMEOUT"
        if isinstance(current, httpx.HTTPStatusError):
            if current.response.status_code in {401, 403}:
                return "MCP_AUTHENTICATION_FAILED"
            if 300 <= current.response.status_code < 400:
                return "MCP_REDIRECT_FORBIDDEN"
            return "MCP_REMOTE_UNAVAILABLE"
        message = str(current).casefold()
        if "secretref" in message or "credential" in message:
            return "MCP_AUTHENTICATION_FAILED"
        if "output" in message and ("budget" in message or "limit" in message):
            return "MCP_OUTPUT_LIMIT"
        if "allowlist" in message or "not discovered" in message:
            return "MCP_TOOL_NOT_ALLOWED"
        if "dns resolution changed" in message:
            return "MCP_DNS_REBINDING"
        if "cross-origin" in message or "redirect" in message:
            return "MCP_REDIRECT_FORBIDDEN"
        if "tool reported failure" in message:
            return "MCP_TOOL_FAILED"
    return "MCP_REMOTE_PROTOCOL_ERROR"


def _exception_chain(error: BaseException):
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        nested = getattr(current, "exceptions", ())
        if isinstance(nested, tuple) and all(
            isinstance(item, BaseException) for item in nested
        ):
            pending[0:0] = list(nested)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)


def _safe_error_message(code: str) -> str:
    messages = {
        "MCP_TIMEOUT": "Remote MCP exceeded the configured timeout.",
        "MCP_AUTHENTICATION_FAILED": "Remote MCP rejected the configured credential reference.",
        "MCP_REMOTE_UNAVAILABLE": "Remote MCP endpoint is unavailable.",
        "MCP_OUTPUT_LIMIT": "Remote MCP output exceeds the configured budget.",
        "MCP_TOOL_NOT_ALLOWED": "Remote MCP tool is not on the configured allowlist.",
        "MCP_DNS_REBINDING": "Remote MCP DNS resolution changed during the session.",
        "MCP_REDIRECT_FORBIDDEN": "Remote MCP attempted a cross-origin redirect.",
        "MCP_TOOL_FAILED": "Remote MCP tool reported failure.",
        "MCP_REMOTE_PROTOCOL_ERROR": "Remote MCP returned an invalid protocol response.",
    }
    return messages[code]
