"""Real stdio MCP client with bounded subprocess and JSON-RPC handling."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..security import sanitize_mcp_output, validate_mcp_tool
from .models import (
    McpExchange,
    McpProcessTrace,
    McpStructuredResult,
    StdioMcpConfiguration,
)


class McpProcessError(RuntimeError):
    def __init__(self, code: str, message: str, *, trace: McpProcessTrace) -> None:
        super().__init__(message)
        self.code = code
        self.trace = trace


class McpProcessStartError(RuntimeError):
    code = "MCP_PROCESS_START_FAILED"


class _McpOutputLimitError(ValueError):
    pass


@dataclass(frozen=True)
class McpCallResult:
    rows: list[dict[str, object]]
    schema: list[tuple[str, str, bool]]
    trace: McpProcessTrace
    tool_name: str
    structured_result: McpStructuredResult


class StdioMcpClient:
    def __init__(
        self,
        *,
        secret_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self.secret_resolver = secret_resolver or (lambda _ref: None)

    def discover(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        connection_id: str,
        configuration: Mapping[str, object],
        trace_id: str,
    ) -> tuple[list[dict[str, object]], McpProcessTrace]:
        result, trace, _resolved_secrets = self._session(
            workspace_id=workspace_id,
            principal_id=principal_id,
            connection_id=connection_id,
            configuration=configuration,
            trace_id=trace_id,
            tool_name=None,
            tool_arguments={},
        )
        return result, trace

    def call(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        connection_id: str,
        configuration: Mapping[str, object],
        trace_id: str,
        tool_name: str,
        tool_arguments: dict[str, object],
    ) -> McpCallResult:
        result, trace, resolved_secrets = self._session(
            workspace_id=workspace_id,
            principal_id=principal_id,
            connection_id=connection_id,
            configuration=configuration,
            trace_id=trace_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )
        payload = result[-1]
        content = payload.get("structuredContent")
        rows = content.get("rows") if isinstance(content, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            content_items = payload.get("content")
            texts = (
                [
                    item.get("text")
                    for item in content_items
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if isinstance(content_items, list)
                else []
            )
            if not texts:
                raise McpProcessError(
                    "MCP_INVALID_TOOL_RESULT",
                    "tools/call returned no structured rows or text content.",
                    trace=trace,
                )
            sanitized = sanitize_mcp_output(str(texts[0]))
            if sanitized.startswith("[QUARANTINED"):
                raise McpProcessError(
                    "MCP_UNTRUSTED_OUTPUT",
                    "tools/call output was quarantined.",
                    trace=trace,
                )
            try:
                decoded = json.loads(sanitized)
            except json.JSONDecodeError as error:
                raise McpProcessError(
                    "MCP_INVALID_TOOL_RESULT",
                    "tools/call text content is not JSON.",
                    trace=trace,
                ) from error
            rows = decoded if isinstance(decoded, list) else [decoded]
        if not all(isinstance(row, dict) for row in rows):
            raise McpProcessError(
                "MCP_INVALID_TOOL_RESULT",
                "tools/call result must be an object or array of objects.",
                trace=trace,
            )
        typed_rows = cast(list[dict[str, object]], rows)
        sanitized_rows = [
            cast(dict[str, object], _sanitize_result(row, resolved_secrets))
            for row in typed_rows
        ]
        schema = _infer_schema(sanitized_rows)
        content_digest = hashlib.sha256(
            json.dumps(
                sanitized_rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        data_as_of = _data_as_of(sanitized_rows, trace.finished_at)
        structured = McpStructuredResult(
            tool_name=tool_name,
            rows=sanitized_rows,
            content_digest=content_digest,
            data_as_of=data_as_of,
            correlation_id=trace_id,
            run_id=trace.id,
        )
        return McpCallResult(
            rows=sanitized_rows,
            schema=schema,
            trace=trace,
            tool_name=tool_name,
            structured_result=structured,
        )

    def _session(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        connection_id: str,
        configuration: Mapping[str, object],
        trace_id: str,
        tool_name: str | None,
        tool_arguments: dict[str, object],
    ) -> tuple[list[dict[str, object]], McpProcessTrace, frozenset[str]]:
        typed = StdioMcpConfiguration.model_validate(configuration)
        command = typed.command
        args = typed.args
        cwd = self._validate_cwd(typed.cwd)
        self._validate_command(command, args)
        environment, env_keys, resolved_secrets = self._resolve_environment(
            typed.env, workspace_id=workspace_id
        )
        startup_timeout = typed.startup_timeout_seconds
        call_timeout = typed.call_timeout_seconds
        max_output = typed.output_bytes
        allowlist = typed.tool_allowlist

        started_at = _timestamp()
        exchanges: list[McpExchange] = []
        try:
            process: subprocess.Popen[bytes] = subprocess.Popen(
                [command, *args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=environment,
                bufsize=0,
                shell=False,
            )
        except OSError as error:
            raise McpProcessStartError(
                "stdio MCP process could not be started."
            ) from error
        pid = process.pid
        output_queue: queue.Queue[bytes | BaseException | None] = queue.Queue()
        output_lock = threading.Lock()
        output_total = 0
        output_limit_reached = threading.Event()
        assert process.stdout and process.stderr and process.stdin
        stdout = process.stdout
        stderr = process.stderr
        stdin = process.stdin

        def account_output(chunk: bytes) -> bool:
            nonlocal output_total
            with output_lock:
                output_total += len(chunk)
                within_limit = output_total <= max_output
                if not within_limit and not output_limit_reached.is_set():
                    output_limit_reached.set()
                    output_queue.put(
                        _McpOutputLimitError("MCP process output exceeds output budget")
                    )
                return within_limit

        def read_stdout() -> None:
            pending = b""
            try:
                while chunk := os.read(stdout.fileno(), 4096):
                    if not account_output(chunk):
                        return
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        output_queue.put(line + b"\n")
                if pending:
                    output_queue.put(pending)
            except BaseException as error:
                output_queue.put(error)
            finally:
                output_queue.put(None)

        def read_stderr() -> None:
            try:
                while chunk := os.read(stderr.fileno(), 4096):
                    if not account_output(chunk):
                        return
            except BaseException as error:
                output_queue.put(error)

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        next_id = 1
        protocol_version = None
        server_name = None
        shutdown_mode = "forced_termination"
        process_reaped = False
        result_payloads: list[dict[str, object]] = []

        def trace(status: str, exit_code: int | None = None) -> McpProcessTrace:
            return McpProcessTrace(
                id=(
                    "mcp-trace-"
                    + hashlib.sha256(
                        f"{trace_id}:{pid}:{started_at}".encode()
                    ).hexdigest()[:24]
                ),
                workspace_id=workspace_id,
                principal_id=principal_id,
                connection_id=connection_id,
                correlation_id=trace_id,
                pid=pid,
                command=command,
                args=args,
                cwd=str(cwd),
                shell=False,
                environment_count=len(env_keys),
                protocol_version=protocol_version,
                server_name=server_name,
                exit_code=exit_code,
                status=status,
                shutdown_mode=shutdown_mode,
                process_reaped=process_reaped,
                exchanges=exchanges,
                started_at=started_at,
                finished_at=_timestamp(),
            )

        def request(
            method: str,
            params: dict[str, object],
            timeout: float,
            *,
            allow_method_not_found: bool = False,
        ) -> dict[str, object]:
            nonlocal next_id
            request_id = next_id
            next_id += 1
            stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    },
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            stdin.flush()
            sequence = len(exchanges) + 1
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    exchanges.append(
                        McpExchange(
                            sequence=sequence,
                            method=method,
                            request_id=request_id,
                            status="failed",
                            error_code="MCP_TIMEOUT",
                        )
                    )
                    raise TimeoutError(f"MCP {method} timed out")
                try:
                    line = output_queue.get(timeout=remaining)
                except queue.Empty as error:
                    exchanges.append(
                        McpExchange(
                            sequence=sequence,
                            method=method,
                            request_id=request_id,
                            status="failed",
                            error_code="MCP_TIMEOUT",
                        )
                    )
                    raise TimeoutError(f"MCP {method} timed out") from error
                if line is None:
                    exchanges.append(
                        McpExchange(
                            sequence=sequence,
                            method=method,
                            request_id=request_id,
                            status="failed",
                            error_code="MCP_PROCESS_EXITED",
                        )
                    )
                    raise RuntimeError(f"MCP process exited before {method} response")
                if isinstance(line, _McpOutputLimitError):
                    exchanges.append(
                        McpExchange(
                            sequence=sequence,
                            method=method,
                            request_id=request_id,
                            status="failed",
                            error_code="MCP_OUTPUT_LIMIT",
                        )
                    )
                    raise line
                if isinstance(line, BaseException):
                    raise RuntimeError("MCP stdout reader failed") from line
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as error:
                    exchanges.append(
                        McpExchange(
                            sequence=sequence,
                            method=method,
                            request_id=request_id,
                            status="failed",
                            error_code="MCP_INVALID_MESSAGE",
                        )
                    )
                    raise ValueError("MCP returned an invalid JSON message") from error
                if (
                    isinstance(response, dict)
                    and response.get("jsonrpc") == "2.0"
                    and "id" not in response
                    and isinstance(response.get("method"), str)
                ):
                    continue
                if (
                    not isinstance(response, dict)
                    or response.get("jsonrpc") != "2.0"
                    or response.get("id") != request_id
                ):
                    exchanges.append(
                        McpExchange(
                            sequence=sequence,
                            method=method,
                            request_id=request_id,
                            status="failed",
                            error_code="MCP_INVALID_MESSAGE",
                        )
                    )
                    raise ValueError("MCP returned an invalid JSON-RPC response")
                break
            if "error" in response:
                rpc_error = response["error"]
                code = rpc_error.get("code") if isinstance(rpc_error, dict) else None
                exchanges.append(
                    McpExchange(
                        sequence=sequence,
                        method=method,
                        request_id=request_id,
                        status="failed",
                        error_code=(
                            "MCP_SHUTDOWN_UNSUPPORTED"
                            if allow_method_not_found and code in {-32601, -32602}
                            else "MCP_METHOD_NOT_FOUND"
                            if code == -32601
                            else "MCP_JSONRPC_ERROR"
                        ),
                    )
                )
                if allow_method_not_found and code in {-32601, -32602}:
                    return {"_stdioEofRequired": True}
                raise RuntimeError("MCP returned a JSON-RPC error")
            result = response.get("result")
            if not isinstance(result, dict):
                raise ValueError("MCP response result must be an object")
            exchanges.append(
                McpExchange(
                    sequence=sequence,
                    method=method,
                    request_id=request_id,
                    status="succeeded",
                    response_digest=hashlib.sha256(
                        json.dumps(result, sort_keys=True).encode()
                    ).hexdigest(),
                )
            )
            return result

        try:
            initialized = request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "knowledge-sources-golden",
                        "version": "1.0.0",
                    },
                },
                startup_timeout,
            )
            protocol_version = str(initialized.get("protocolVersion", ""))
            server_info = initialized.get("serverInfo")
            server_name = (
                str(server_info.get("name"))
                if isinstance(server_info, dict) and server_info.get("name")
                else None
            )
            stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    },
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            stdin.flush()
            exchanges.append(
                McpExchange(
                    sequence=len(exchanges) + 1,
                    method="notifications/initialized",
                    status="sent",
                )
            )
            listed = request("tools/list", {}, call_timeout)
            tools = listed.get("tools")
            if not isinstance(tools, list):
                raise ValueError("MCP tools/list result must contain tools")
            result_payloads.extend(item for item in tools if isinstance(item, dict))
            names = {
                str(item.get("name")) for item in result_payloads if item.get("name")
            }
            if not names <= set(allowlist):
                raise ValueError("MCP server exposed a tool outside the allowlist")
            if tool_name is not None:
                validate_mcp_tool(
                    tool_name,
                    allowlist=set(allowlist),
                    output_bytes=0,
                    max_output_bytes=max_output,
                )
                if tool_name not in names:
                    raise ValueError("requested MCP tool was not discovered")
                called = request(
                    "tools/call",
                    {"name": tool_name, "arguments": tool_arguments},
                    call_timeout,
                )
                if called.get("isError") is True:
                    exchanges[-1] = exchanges[-1].model_copy(
                        update={
                            "status": "failed",
                            "error_code": "MCP_TOOL_FAILED",
                        }
                    )
                    raise RuntimeError("MCP tool reported failure")
                result_payloads.append(called)
            # MCP SDK 1.26 follows the current lifecycle specification: EOF is
            # the shutdown signal and it does not register the legacy
            # ``shutdown`` request. We still send the explicit request for
            # older servers and truthfully record -32601 before closing stdin.
            shutdown_result = request(
                "shutdown",
                {},
                call_timeout,
                allow_method_not_found=True,
            )
            shutdown_mode = (
                "stdio_eof"
                if shutdown_result.get("_stdioEofRequired") is True
                else "jsonrpc"
            )
            stdin.close()
            exit_code = process.wait(timeout=call_timeout)
            process_reaped = True
            if shutdown_mode == "stdio_eof":
                exchanges.append(
                    McpExchange(
                        sequence=len(exchanges) + 1,
                        method="stdio/eof",
                        status="succeeded",
                        response_digest=hashlib.sha256(b"stdio-eof").hexdigest(),
                    )
                )
            stdout_thread.join()
            stderr_thread.join()
            if output_limit_reached.is_set():
                raise _McpOutputLimitError("MCP process output exceeds output budget")
            if exit_code != 0:
                raise RuntimeError(f"MCP process exited with code {exit_code}")
            return (
                result_payloads,
                trace("succeeded", exit_code),
                frozenset(resolved_secrets),
            )
        except (TimeoutError, subprocess.TimeoutExpired) as error:
            if process.poll() is None:
                process.kill()
            process.wait()
            process_reaped = True
            stdout_thread.join()
            stderr_thread.join()
            raise McpProcessError(
                "MCP_TIMEOUT", str(error), trace=trace("timed_out", process.returncode)
            ) from error
        except Exception as error:
            exited_before_cleanup = process.poll() is not None
            if not exited_before_cleanup:
                process.kill()
            process.wait()
            process_reaped = True
            stdout_thread.join()
            stderr_thread.join()
            error_code = _error_code(error)
            if exited_before_cleanup and error_code == "MCP_PROTOCOL_ERROR":
                error_code = "MCP_PROCESS_EXITED"
            raise McpProcessError(
                error_code,
                _redacted_message(str(error), environment),
                trace=trace("failed", process.returncode),
            ) from error

    @staticmethod
    def _validate_cwd(raw: object) -> Path:
        if not isinstance(raw, str) or not raw:
            raise ValueError("stdio MCP cwd is required")
        if not Path(raw).is_absolute():
            raise ValueError("stdio MCP cwd must be an absolute directory")
        path = Path(raw).resolve()
        if not path.is_dir():
            raise ValueError("stdio MCP cwd must be an existing directory")
        return path

    @staticmethod
    def _validate_command(command: str, args: list[str]) -> None:
        if "\x00" in command or any("\x00" in argument for argument in args):
            raise ValueError("stdio MCP command and args contain invalid bytes")
        sensitive_argument = re.compile(
            r"(?i)(?:^|[-_])(?:password|token|secret|credential|api[-_]?key)"
            r"(?:$|[-_]=?|=)"
        )
        if any(
            "secret://" in argument or sensitive_argument.search(argument)
            for argument in args
        ):
            raise ValueError(
                "sensitive stdio MCP arguments must use secretRef environment injection"
            )

    def _resolve_environment(
        self, raw: object, *, workspace_id: str
    ) -> tuple[dict[str, str], list[str], set[str]]:
        if not isinstance(raw, dict):
            raise ValueError("stdio MCP env must be an object")
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "PYTHONPATH", "SYSTEMROOT"}
        }
        env_keys: list[str] = []
        resolved_secrets: set[str] = set()
        for key, raw_value in raw.items():
            if not isinstance(key, str) or not isinstance(raw_value, str):
                raise ValueError("stdio MCP env keys and values must be strings")
            if not key or "=" in key or "\x00" in key:
                raise ValueError("stdio MCP env key is invalid")
            if raw_value.startswith("secret://"):
                if not raw_value.startswith(f"secret://{workspace_id}/"):
                    raise ValueError(
                        "stdio MCP secretRef must belong to the active workspace"
                    )
                try:
                    value = self.secret_resolver(raw_value)
                except Exception as error:
                    raise ValueError("stdio MCP secretRef resolution failed") from error
                if value is None:
                    raise ValueError("stdio MCP secretRef could not be resolved")
                resolved_secrets.add(value)
            elif any(
                marker in key.casefold()
                for marker in ("secret", "token", "password", "credential", "key")
            ):
                raise ValueError(
                    "sensitive stdio MCP env values must be secretRef references"
                )
            else:
                value = raw_value
            if "\x00" in value:
                raise ValueError("stdio MCP env value is invalid")
            environment[key] = value
            env_keys.append(key)
        return environment, sorted(env_keys), resolved_secrets


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _error_code(error: Exception) -> str:
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return "MCP_TIMEOUT"
    if isinstance(error, _McpOutputLimitError):
        return "MCP_OUTPUT_LIMIT"
    message = str(error).casefold()
    if (
        "outside the allowlist" in message
        or "not on the configured allowlist" in message
    ):
        return "MCP_TOOL_NOT_ALLOWED"
    if "output budget" in message:
        return "MCP_OUTPUT_LIMIT"
    if "invalid json" in message or "invalid json-rpc" in message:
        return "MCP_INVALID_MESSAGE"
    if "tool reported failure" in message:
        return "MCP_TOOL_FAILED"
    if "exited" in message:
        return "MCP_PROCESS_EXITED"
    return "MCP_PROTOCOL_ERROR"


def _redacted_message(message: str, environment: dict[str, str]) -> str:
    redacted = message
    for key, value in environment.items():
        if (
            any(
                marker in key.casefold()
                for marker in ("secret", "token", "password", "credential", "key")
            )
            and value
        ):
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _infer_schema(
    rows: list[dict[str, object]],
) -> list[tuple[str, str, bool]]:
    if not rows:
        return []
    names: list[str] = []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(key)
    result = []
    for name in names:
        values = [row.get(name) for row in rows]
        present = [value for value in values if value is not None]
        if present and all(isinstance(value, bool) for value in present):
            kind = "boolean"
        elif present and all(
            isinstance(value, int) and not isinstance(value, bool) for value in present
        ):
            kind = "integer"
        elif present and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in present
        ):
            kind = "number"
        else:
            kind = "string"
        result.append((name, kind, len(present) != len(values)))
    return result


def _sanitize_result(value: object, resolved_secrets: Set[str]) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _is_sensitive_key(str(key)) and item not in (None, "")
                else _sanitize_result(item, resolved_secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_result(item, resolved_secrets) for item in value]
    if isinstance(value, str):
        sanitized = sanitize_mcp_output(value)
        for secret in resolved_secrets:
            if secret:
                sanitized = sanitized.replace(secret, "[REDACTED]")
        return sanitized
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "").replace("_", "")
    return any(
        marker in normalized
        for marker in (
            "password",
            "token",
            "secret",
            "credential",
            "apikey",
            "privatekey",
        )
    )


def _data_as_of(rows: list[dict[str, object]], fallback: str) -> str:
    values = [
        str(row["dataAsOf"]) for row in rows if row.get("dataAsOf") not in (None, "")
    ]
    return max(values) if values else fallback
