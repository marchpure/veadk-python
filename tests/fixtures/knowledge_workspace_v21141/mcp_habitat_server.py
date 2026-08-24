#!/usr/bin/env python3
"""Minimal standalone stdio MCP server used for real process contract tests."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path


def _send(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _result(request_id: object, value: dict[str, object]) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": value})


def _error(request_id: object, code: int, message: str) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def main() -> int:
    mode = os.environ.get("MCP_FIXTURE_MODE", "normal")
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            if mode == "oversize_stderr":
                sys.stderr.write("fixture diagnostic " * 512 + "\n")
                sys.stderr.flush()
            if mode == "hang_initialize":
                time.sleep(10)
            if mode == "exit_initialize":
                return 23
            if mode == "invalid_initialize":
                sys.stdout.write("not-json\n")
                sys.stdout.flush()
                continue
            _result(
                request_id,
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "repository-habitat-test-server",
                        "version": "1.0.0",
                    },
                },
            )
        elif method == "tools/list":
            if mode == "notification_before_tools":
                _send(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/message",
                        "params": {
                            "level": "info",
                            "data": "fixture notification",
                        },
                    }
                )
            _result(
                request_id,
                {
                    "tools": [
                        {
                            "name": "habitat.readings",
                            "description": "Read current non-sales habitat observations.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"region": {"type": "string"}},
                                "additionalProperties": False,
                            },
                        }
                    ]
                },
            )
        elif method == "tools/call":
            if mode == "hang_tool":
                time.sleep(10)
            if mode == "oversize_tool":
                readings = [{"payload": "x" * 4096}]
                _result(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(readings),
                            }
                        ],
                        "structuredContent": {"rows": readings},
                        "isError": False,
                    },
                )
                continue
            if mode == "tool_error":
                sys.stderr.write(
                    "provider failure token="
                    + os.environ.get("MCP_SECRET_TOKEN", "unset")
                    + "\n"
                )
                sys.stderr.flush()
                _result(
                    request_id,
                    {
                        "isError": True,
                        "content": [{"type": "text", "text": "fixture tool failed"}],
                    },
                )
                continue
            if request.get("params", {}).get("name") != "habitat.readings":
                _error(request_id, -32602, "unknown tool")
                continue
            data_path = Path(os.environ["MCP_FIXTURE_DATA_PATH"])
            readings = json.loads(data_path.read_text(encoding="utf-8"))
            secret = os.environ.get("MCP_SECRET_TOKEN")
            if secret:
                readings = [{**reading, "secretEcho": secret} for reading in readings]
            digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
            _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(readings, separators=(",", ":")),
                        }
                    ],
                    "structuredContent": {
                        "rows": readings,
                        "dataDigest": digest,
                        "serverPid": os.getpid(),
                    },
                    "isError": False,
                },
            )
        elif method == "shutdown":
            _result(request_id, {})
            if mode == "hang_after_shutdown":
                time.sleep(10)
            return 0
        else:
            _error(request_id, -32601, "method not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
