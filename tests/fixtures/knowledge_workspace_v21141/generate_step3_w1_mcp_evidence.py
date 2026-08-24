#!/usr/bin/env python3
"""Generate reproducible STEP 3 W1 evidence using real stdio subprocesses."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from frontend.server.knowledge_assets.sources_golden import (  # noqa: E402
    AccessContext,
    SourceGoldenApplication,
    SourcesGoldenError,
)

FIXTURE_DIRECTORY = Path(__file__).resolve().parent
FIXTURE_SERVER = FIXTURE_DIRECTORY / "mcp_habitat_server.py"
SDK_SERVER = FIXTURE_DIRECTORY / "mcp_sdk_infrastructure_server.py"
HABITAT_DATA = FIXTURE_DIRECTORY / "mcp_habitat_readings.json"
SDK_INITIAL_DATA = FIXTURE_DIRECTORY / "mcp_infrastructure_metrics.initial.json"
SDK_UPDATED_DATA = FIXTURE_DIRECTORY / "mcp_infrastructure_metrics.updated.json"
SECRET_REFERENCE = "secret://workspace-a/mcp-evidence"
SECRET_SENTINEL = "w1-runtime-secret-must-not-persist"


def _context() -> AccessContext:
    return AccessContext(
        workspace_id="workspace-a",
        principal_id="w1-evidence-runner",
        role="admin",
    )


def _application(runtime: Path, name: str) -> SourceGoldenApplication:
    return SourceGoldenApplication(
        database_path=runtime / f"{name}.sqlite3",
        artifact_root=runtime / f"{name}-artifacts",
        source_root=runtime,
        secret_resolver=lambda reference: (
            SECRET_SENTINEL if reference == SECRET_REFERENCE else None
        ),
    )


def _configuration(
    *,
    server: Path,
    data_path: Path,
    runtime: Path,
    mode: str | None = None,
) -> dict[str, object]:
    environment = {"MCP_FIXTURE_DATA_PATH": str(data_path)}
    allowlist = ["infrastructure.metrics"]
    if server == FIXTURE_SERVER:
        environment.update(
            {
                "MCP_FIXTURE_MODE": mode or "normal",
                "MCP_SECRET_TOKEN": SECRET_REFERENCE,
            }
        )
        allowlist = (
            ["other.tool"] if mode == "outside_allowlist" else ["habitat.readings"]
        )
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(server)],
        "env": environment,
        "cwd": str(runtime),
        "startupTimeoutSeconds": 0.05 if mode == "hang_initialize" else 5,
        "callTimeoutSeconds": (
            0.05 if mode in {"hang_tool", "hang_after_shutdown"} else 5
        ),
        "toolAllowlist": allowlist,
        "outputBytes": (
            1_024 if mode in {"oversize_stderr", "oversize_tool"} else 1_000_000
        ),
    }


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _trace_evidence(trace: Any) -> dict[str, object]:
    payload = trace.model_dump(mode="json", by_alias=True)
    payload["pidAliveAfterRun"] = _pid_is_alive(trace.pid)
    return payload


def _startup_command(configuration: dict[str, object]) -> dict[str, object]:
    return {
        "shell": False,
        "argv": [configuration["command"], *configuration["args"]],
        "cwd": configuration["cwd"],
        "env": configuration["env"],
    }


def _successful_fixture(runtime: Path) -> dict[str, object]:
    data_path = runtime / "habitat-readings.json"
    shutil.copyfile(HABITAT_DATA, data_path)
    application = _application(runtime, "fixture-success")
    configuration = _configuration(
        server=FIXTURE_SERVER,
        data_path=data_path,
        runtime=runtime,
    )
    created = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Habitat fault-fixture MCP",
        scope="team",
        configuration=configuration,
        secret_ref=None,
        idempotency_key="fixture-create",
        trace_id="fixture-initialize",
    )
    ingested = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=created.discovery.resources[0].id,
        recipe_operations=["trim"],
        tool_arguments={"region": "all"},
        idempotency_key="fixture-call",
        trace_id="fixture-tools-call",
    )
    rows = application.golden_data(_context(), ingested.golden_asset_revision.id).rows
    traces = application.mcp_process_traces(_context(), created.connection.id)
    assert all(trace.pid != os.getpid() for trace in traces)
    assert all(
        trace.process_reaped and not _pid_is_alive(trace.pid) for trace in traces
    )
    assert all(row.get("secretEcho") == "[REDACTED]" for row in rows)
    return {
        "implementation": "repository fault-injection JSON-RPC server",
        "server": str(FIXTURE_SERVER),
        "startup": _startup_command(configuration),
        "discoveredTools": [
            resource.model_dump(mode="json", by_alias=True)
            for resource in created.discovery.resources
        ],
        "toolCallOutput": rows,
        "sourceRevision": ingested.source_revision.model_dump(
            mode="json", by_alias=True
        ),
        "goldenRevision": ingested.golden_asset_revision.model_dump(
            mode="json", by_alias=True
        ),
        "processes": [_trace_evidence(trace) for trace in traces],
    }


def _official_sdk(runtime: Path) -> dict[str, object]:
    data_path = runtime / "infrastructure-metrics.json"
    shutil.copyfile(SDK_INITIAL_DATA, data_path)
    application = _application(runtime, "official-sdk")
    configuration = _configuration(
        server=SDK_SERVER,
        data_path=data_path,
        runtime=runtime,
    )
    created = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name="Official SDK infrastructure metrics",
        scope="team",
        configuration=configuration,
        secret_ref=None,
        idempotency_key="sdk-create",
        trace_id="sdk-initialize",
    )
    tool = created.discovery.resources[0]
    assert tool.input_schema and tool.output_schema
    first = application.ingest(
        _context(),
        connection_id=created.connection.id,
        resource_id=tool.id,
        recipe_operations=["trim"],
        tool_arguments={"service": "all"},
        idempotency_key="sdk-call-one",
        trace_id="sdk-tools-call-one",
    )
    first_rows = application.golden_data(
        _context(), first.golden_asset_revision.id
    ).rows
    shutil.copyfile(SDK_UPDATED_DATA, data_path)
    second = application.refresh(
        _context(),
        asset_id=first.golden_asset_revision.asset_id,
        idempotency_key="sdk-call-two",
        trace_id="sdk-tools-call-two",
    )
    assert second.golden_asset_revision is not None
    second_source = application.source_revision(
        _context(),
        second.golden_asset_revision.lineage.source_revision_id,
    )
    second_rows = application.golden_data(
        _context(), second.golden_asset_revision.id
    ).rows
    traces = application.mcp_process_traces(_context(), created.connection.id)
    assert len(traces) == 3
    assert all(trace.pid != os.getpid() for trace in traces)
    assert all(
        trace.process_reaped and not _pid_is_alive(trace.pid) for trace in traces
    )
    assert first_rows != second_rows
    assert first.source_revision.id != second_source.id
    assert first.source_revision.source_digest != second_source.source_digest
    assert first.golden_asset_revision.id != second.golden_asset_revision.id
    assert (
        first.golden_asset_revision.storage_ref.sha256
        != second.golden_asset_revision.storage_ref.sha256
    )
    assert (
        first.golden_asset_revision.data_as_of
        != second.golden_asset_revision.data_as_of
    )
    return {
        "implementation": "official MCP Python SDK FastMCP",
        "sdkPackage": "mcp",
        "sdkVersion": version("mcp"),
        "server": str(SDK_SERVER),
        "startup": _startup_command(configuration),
        "toolsListOutput": [
            resource.model_dump(mode="json", by_alias=True)
            for resource in created.discovery.resources
        ],
        "first": {
            "toolsCallOutput": first_rows,
            "sourceRevision": first.source_revision.model_dump(
                mode="json", by_alias=True
            ),
            "goldenRevision": first.golden_asset_revision.model_dump(
                mode="json", by_alias=True
            ),
        },
        "second": {
            "toolsCallOutput": second_rows,
            "sourceRevision": second_source.model_dump(mode="json", by_alias=True),
            "goldenRevision": second.golden_asset_revision.model_dump(
                mode="json", by_alias=True
            ),
        },
        "changed": {
            "toolsCallOutput": first_rows != second_rows,
            "sourceRevision": first.source_revision.id != second_source.id,
            "goldenRevision": (
                first.golden_asset_revision.id != second.golden_asset_revision.id
            ),
            "contentDigest": (
                first.source_revision.source_digest != second_source.source_digest
            ),
            "goldenOutputDigest": (
                first.golden_asset_revision.storage_ref.sha256
                != second.golden_asset_revision.storage_ref.sha256
            ),
            "freshness": (
                first.golden_asset_revision.freshness_at
                != second.golden_asset_revision.freshness_at
            ),
            "dataAsOf": (
                first.golden_asset_revision.data_as_of
                != second.golden_asset_revision.data_as_of
            ),
        },
        "processes": [_trace_evidence(trace) for trace in traces],
    }


def _create_failure(runtime: Path, mode: str) -> dict[str, object]:
    case_runtime = runtime / f"failure-{mode}"
    case_runtime.mkdir()
    data_path = case_runtime / "habitat-readings.json"
    shutil.copyfile(HABITAT_DATA, data_path)
    application = _application(case_runtime, mode)
    configuration = _configuration(
        server=FIXTURE_SERVER,
        data_path=data_path,
        runtime=case_runtime,
        mode=mode,
    )
    try:
        application.create_connection(
            _context(),
            connector_key="mcp_custom",
            display_name=f"Failure {mode}",
            scope="personal",
            configuration=configuration,
            secret_ref=None,
            idempotency_key=f"create-{mode}",
            trace_id=f"trace-{mode}",
        )
    except SourcesGoldenError as error:
        traces = application.mcp_process_traces_for_workspace(_context())
        return {
            "scenario": mode,
            "phase": "initialize_or_discovery",
            "errorCode": error.code,
            "message": str(error),
            "process": _trace_evidence(traces[-1]) if traces else None,
        }
    raise AssertionError(f"{mode} unexpectedly succeeded")


def _call_failure(runtime: Path, mode: str) -> dict[str, object]:
    case_runtime = runtime / f"failure-{mode}"
    case_runtime.mkdir()
    data_path = case_runtime / "habitat-readings.json"
    shutil.copyfile(HABITAT_DATA, data_path)
    application = _application(case_runtime, mode)
    configuration = _configuration(
        server=FIXTURE_SERVER,
        data_path=data_path,
        runtime=case_runtime,
        mode=mode,
    )
    connection = application.create_connection(
        _context(),
        connector_key="mcp_custom",
        display_name=f"Failure {mode}",
        scope="personal",
        configuration=configuration,
        secret_ref=None,
        idempotency_key=f"create-{mode}",
        trace_id=f"trace-create-{mode}",
    ).connection
    try:
        application.ingest(
            _context(),
            connection_id=connection.id,
            resource_id=connection.discovered_resources[0].id,
            recipe_operations=["trim"],
            tool_arguments={},
            idempotency_key=f"call-{mode}",
            trace_id=f"trace-call-{mode}",
        )
    except SourcesGoldenError as error:
        trace = application.mcp_process_traces(_context(), connection.id)[-1]
        return {
            "scenario": mode,
            "phase": "tools/call",
            "errorCode": error.code,
            "message": str(error),
            "revisionCreated": bool(
                application.data_overview(_context()).golden_assets
            ),
            "process": _trace_evidence(trace),
        }
    raise AssertionError(f"{mode} unexpectedly succeeded")


def _pre_spawn_failures(runtime: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    cases = [
        (
            "missing_command",
            {"command": str(runtime / "missing-executable")},
            "MCP_PROCESS_START_FAILED",
        ),
        ("relative_cwd", {"cwd": ".."}, "MCP_CONFIGURATION_INVALID"),
        (
            "plaintext_sensitive_env",
            {"env": {"MCP_SECRET_TOKEN": "inline-value"}},
            "MCP_CONFIGURATION_INVALID",
        ),
        (
            "plaintext_sensitive_args",
            {"args": ["--token", "inline-value"]},
            "MCP_CONFIGURATION_INVALID",
        ),
    ]
    for scenario, mutation, expected in cases:
        case_runtime = runtime / f"failure-{scenario}"
        case_runtime.mkdir()
        data_path = case_runtime / "habitat-readings.json"
        shutil.copyfile(HABITAT_DATA, data_path)
        application = _application(case_runtime, scenario)
        configuration = _configuration(
            server=FIXTURE_SERVER,
            data_path=data_path,
            runtime=case_runtime,
        )
        configuration.update(mutation)
        try:
            application.create_connection(
                _context(),
                connector_key="mcp_custom",
                display_name=f"Failure {scenario}",
                scope="personal",
                configuration=configuration,
                secret_ref=None,
                idempotency_key=f"create-{scenario}",
                trace_id=f"trace-{scenario}",
            )
        except SourcesGoldenError as error:
            assert error.code == expected
            results.append(
                {
                    "scenario": scenario,
                    "phase": "before_spawn",
                    "errorCode": error.code,
                    "message": str(error),
                    "processTraceCount": len(
                        application.mcp_process_traces_for_workspace(_context())
                    ),
                }
            )
            continue
        raise AssertionError(f"{scenario} unexpectedly succeeded")
    return results


def _scan_for_secret(root: Path, evidence: dict[str, object]) -> dict[str, object]:
    leaks = []
    needle = SECRET_SENTINEL.encode()
    for path in root.rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            leaks.append(str(path.relative_to(root)))
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    if SECRET_SENTINEL in serialized:
        leaks.append("<evidence>")
    return {
        "sentinelPersisted": bool(leaks),
        "matchingPaths": leaks,
        "secretReferencePersistedOnly": SECRET_REFERENCE in serialized,
    }


def generate(runtime: Path) -> dict[str, object]:
    runtime.mkdir(parents=True, exist_ok=False)
    fixture = _successful_fixture(runtime)
    official = _official_sdk(runtime)
    failures = [
        *[
            _create_failure(runtime, mode)
            for mode in (
                "hang_initialize",
                "exit_initialize",
                "invalid_initialize",
                "oversize_stderr",
                "outside_allowlist",
                "hang_after_shutdown",
            )
        ],
        *[
            _call_failure(runtime, mode)
            for mode in ("hang_tool", "tool_error", "oversize_tool")
        ],
        *_pre_spawn_failures(runtime),
    ]
    expected_codes = {
        "hang_initialize": "MCP_TIMEOUT",
        "exit_initialize": "MCP_PROCESS_EXITED",
        "invalid_initialize": "MCP_INVALID_MESSAGE",
        "oversize_stderr": "MCP_OUTPUT_LIMIT",
        "outside_allowlist": "MCP_TOOL_NOT_ALLOWED",
        "hang_after_shutdown": "MCP_TIMEOUT",
        "hang_tool": "MCP_TIMEOUT",
        "tool_error": "MCP_TOOL_FAILED",
        "oversize_tool": "MCP_OUTPUT_LIMIT",
    }
    for failure in failures:
        expected = expected_codes.get(str(failure["scenario"]))
        if expected:
            assert failure["errorCode"] == expected
        process = failure.get("process")
        if isinstance(process, dict):
            assert process["processReaped"] is True
            assert process["pidAliveAfterRun"] is False
    evidence: dict[str, object] = {
        "schemaVersion": "knowledge-assets.step3.w1-mcp-evidence.v1",
        "status": "PASS",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "repository": str(REPOSITORY_ROOT),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "runtimeDirectory": str(runtime),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "mcpSdkVersion": version("mcp"),
        },
        "reproduce": {
            "command": [
                sys.executable,
                str(Path(__file__).resolve()),
                "--output",
                "<output-json>",
                "--runtime-dir",
                "<new-empty-runtime-directory>",
            ]
        },
        "fixtureServer": fixture,
        "officialSdkServer": official,
        "faultScenarios": failures,
        "stableErrorCodes": sorted({str(failure["errorCode"]) for failure in failures}),
    }
    evidence["secretLeakCheck"] = _scan_for_secret(runtime, evidence)
    assert evidence["secretLeakCheck"]["sentinelPersisted"] is False
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path)
    arguments = parser.parse_args()
    runtime = arguments.runtime_dir
    if runtime is None:
        runtime = Path(tempfile.mkdtemp(prefix="step3-w1-mcp-evidence-"))
        runtime.rmdir()
    evidence = generate(runtime.resolve())
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "output": str(arguments.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
