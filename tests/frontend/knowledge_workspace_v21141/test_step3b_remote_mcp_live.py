from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
    SourcesGoldenError,
)


def _context() -> AccessContext:
    return AccessContext(
        workspace_id="workspace-step3b",
        principal_id="user-step3b",
        role="editor",
    )


def _unused_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


@contextmanager
def _remote_mcp_service(tmp_path: Path):
    port = _unused_port()
    data_path = tmp_path / "remote-mcp-output-limit.json"
    data_path.write_text(
        json.dumps([{"sku": "A-1", "description": "small"}]),
        encoding="utf-8",
    )
    server = (
        Path(__file__).parents[2]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "mcp_sdk_remote_server.py"
    )
    process = subprocess.Popen(
        [sys.executable, str(server)],
        cwd=tmp_path,
        env={
            **os.environ,
            "MCP_FIXTURE_PORT": str(port),
            "MCP_FIXTURE_TRANSPORT": "streamable-http",
            "MCP_FIXTURE_DATA_PATH": str(data_path),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read().decode() if process.stderr else ""
            raise RuntimeError(f"remote MCP fixture exited: {stderr}")
        with socket.socket() as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)
    else:
        process.kill()
        process.wait()
        raise RuntimeError("remote MCP fixture did not start")
    try:
        yield data_path, f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_remote_mcp_output_limit_is_persisted_and_visible_through_trace_api(
    tmp_path: Path,
) -> None:
    with _remote_mcp_service(tmp_path) as (data_path, endpoint):
        application = SourceGoldenApplication(
            database_path=tmp_path / "remote-mcp.sqlite3",
            artifact_root=tmp_path / "artifacts",
            source_root=tmp_path,
            network_allow_private_hosts={"127.0.0.1"},
        )
        created = application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name="Budgeted remote MCP",
            scope="team",
            configuration={
                "transport": "streamable_http",
                "endpoint": endpoint,
                "toolAllowlist": ["inventory.read"],
                "startupTimeoutSeconds": 5,
                "callTimeoutSeconds": 5,
                "outputBytes": 5_000,
                "maxPages": 5,
            },
            secret_ref=None,
            idempotency_key="remote-mcp-output-create",
            trace_id="trace-remote-mcp-output-create",
        )
        data_path.write_text(
            json.dumps([{"sku": "A-1", "description": "x" * 20_000}]),
            encoding="utf-8",
        )

        with pytest.raises(SourcesGoldenError) as failure:
            application.ingest(
                _context(),
                connection_id=created.connection.id,
                resource_id=created.discovery.resources[0].id,
                recipe_operations=[],
                tool_arguments={"region": "all"},
                idempotency_key="remote-mcp-output-ingest",
                trace_id="trace-remote-mcp-output-ingest",
            )

        assert failure.value.code == "MCP_OUTPUT_LIMIT"
        remote_traces = application.connector_traces(_context(), created.connection.id)
        assert remote_traces[-1].correlation_id == "trace-remote-mcp-output-ingest"
        assert remote_traces[-1].status == "failed"
        assert remote_traces[-1].error_code == "MCP_OUTPUT_LIMIT"
        assert remote_traces[-1].exchanges[-1].method == "tools/call"
        assert remote_traces[-1].exchanges[-1].error_code == "MCP_OUTPUT_LIMIT"
        operation_trace = application.connector_trace(
            _context(),
            created.connection.id,
            "trace-remote-mcp-output-ingest",
        )
        assert operation_trace.operations[-2].status == "failed"
        assert operation_trace.operations[-2].reason.code == "MCP_OUTPUT_LIMIT"
