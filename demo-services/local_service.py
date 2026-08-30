#!/usr/bin/env python3
"""Dependency-free local Web Action, form API, and MCP demo providers."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    service = "web"

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
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
            self._send(200, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"tool": method or "inspect_store", "rows": [{"store_id": "store-sh", "score": 98}]}})
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
