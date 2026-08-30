#!/usr/bin/env python3
"""Dependency-free local Web Action, form API, and Streamable HTTP MCP providers."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    service = "web"

    def _send(self, status: int, payload: object | None) -> None:
        body = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            if payload is not None
            else b""
        )
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._send(200, {"status": "ok", "service": self.service, "demo": True})
            return
        if self.service == "web" and self.path == "/cases/vehicle-42":
            self._send(200, {"case_id": "vehicle-42", "symptoms": ["制动告警"], "action": "检查制动液位"})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.service == "web" and self.path == "/actions/repair":
            self._send(200, {"ok": True, "action": "repair.lookup", "evidence": {"case_id": body.get("case_id", "vehicle-42"), "next": "检查制动液位"}})
            return
        if self.service == "form" and self.path == "/forms/inspection":
            self._send(200, {"ok": True, "submission_id": "inspection-demo-001", "received": body, "next": "门店经理确认"})
            return
        if self.service == "mcp" and self.path == "/mcp":
            method = body.get("method")
            if method == "notifications/initialized":
                self._send(202, None)
                return
            result: object
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {
                        "name": "knowledge-commercial-demo",
                        "version": "1.0.0",
                    },
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "inspect_store",
                            "description": "Read the demo restaurant inspection result.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "store_id": {"type": "string"},
                                },
                                "additionalProperties": False,
                            },
                        }
                    ]
                }
            elif method == "resources/list":
                result = {
                    "resources": [
                        {
                            "uri": "demo://inspection/store-sh",
                            "name": "上海门店巡检结果",
                            "mimeType": "application/json",
                        }
                    ]
                }
            elif method == "prompts/list":
                result = {"prompts": []}
            elif method == "tools/call":
                params = body.get("params") if isinstance(body.get("params"), dict) else {}
                if params.get("name") != "inspect_store":
                    self._send(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "error": {"code": -32602, "message": "unknown tool"},
                        },
                    )
                    return
                arguments = (
                    params.get("arguments")
                    if isinstance(params.get("arguments"), dict)
                    else {}
                )
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "store_id": arguments.get("store_id", "store-sh"),
                                    "score": 98,
                                    "exceptions": ["后厨温度记录待补签"],
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ]
                }
            else:
                self._send(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "error": {"code": -32601, "message": "method not found"},
                    },
                )
                return
            self._send(
                200,
                {"jsonrpc": "2.0", "id": body.get("id"), "result": result},
            )
            return
        self._send(404, {"error": "not_found"})

    def log_message(self, *_: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=("web", "form", "mcp"), required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    Handler.service = args.service
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
