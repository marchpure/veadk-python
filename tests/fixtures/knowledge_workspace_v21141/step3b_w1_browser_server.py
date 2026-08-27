"""Browser-certification composition for the complete Source/Golden surface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.repository import (
    KnowledgeAssetRepository,
    SqliteKnowledgeAssetRepository,
)
from frontend.server.knowledge_assets.routes import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
    mount_source_golden_routes,
)
from frontend.server.knowledge_assets.sources_golden.webhook_ingress import (
    create_webhook_ingress,
)

_runtime_root = Path(
    os.environ.get("STEP3B_BROWSER_RUNTIME_ROOT", ".veadk/step3b-browser")
).resolve()
_runtime_root.mkdir(parents=True, exist_ok=True)


def _secret(reference: str) -> str | None:
    webhook_secret = os.environ.get("STEP3B_WEBHOOK_SECRET")
    if webhook_secret and reference == "secret://workspace-step3/browser-webhook":
        return webhook_secret
    database_password = os.environ.get("STEP3B_DB_PASSWORD")
    if database_password and reference.startswith("secret://workspace-step3/"):
        connector = reference.rsplit("/", 1)[-1]
        if connector in {
            "postgresql",
            "mysql",
            "postgresql-wrong",
            "mysql-wrong",
        }:
            return json.dumps(
                {
                    "username": "step3b",
                    "password": (
                        "definitely-wrong"
                        if connector.endswith("-wrong")
                        else database_password
                    ),
                },
                sort_keys=True,
            )
    if reference == "secret://workspace-step3/s3":
        return json.dumps(
            {
                "accessKeyId": os.environ.get("STEP3B_MINIO_ACCESS_KEY", "step3badmin"),
                "secretAccessKey": os.environ.get(
                    "STEP3B_MINIO_SECRET_KEY", "step3bpassword"
                ),
            },
            sort_keys=True,
        )
    if reference == "secret://workspace-step3/kafka":
        return json.dumps({})
    if reference == "secret://workspace-step3/clickhouse":
        return json.dumps(
            {
                "username": os.environ.get("STEP3B_CLICKHOUSE_USER", "step3b"),
                "password": os.environ.get(
                    "STEP3B_CLICKHOUSE_PASSWORD", "step3bpassword"
                ),
            },
            sort_keys=True,
        )
    if reference == "secret://workspace-step3/oracle":
        return json.dumps(
            {
                "username": os.environ.get("STEP3B_ORACLE_USER", "step3b"),
                "password": os.environ.get(
                    "STEP3B_ORACLE_PASSWORD", "Step3bAppPassword1!"
                ),
            },
            sort_keys=True,
        )
    if reference == "secret://workspace-step3/doris":
        return json.dumps(
            {
                "username": os.environ.get("STEP3B_DORIS_USER", "step3b"),
                "password": os.environ.get(
                    "STEP3B_DORIS_PASSWORD", "Step3bDorisPassword1!"
                ),
            },
            sort_keys=True,
        )
    if reference == "secret://workspace-step3/hive":
        return json.dumps(
            {
                "username": os.environ.get("STEP3B_HIVE_USER", "step3b"),
                "password": os.environ.get("STEP3B_HIVE_PASSWORD", "x"),
                "auth": os.environ.get("STEP3B_HIVE_AUTH", "NONE"),
            },
            sort_keys=True,
        )
    if reference == "secret://workspace-step3/sqlserver":
        return json.dumps(
            {
                "username": "sa",
                "password": "Step3bSqlPassword1!",
                "connectionString": (
                    "DRIVER=/opt/homebrew/opt/freetds/lib/libtdsodbc.so;"
                    "SERVER=127.0.0.1;PORT=26353;DATABASE=knowledge;"
                    "UID=sa;PWD=Step3bSqlPassword1!;TDS_Version=7.4;"
                    "Encrypt=no;TrustServerCertificate=yes;"
                ),
            },
            sort_keys=True,
        )
    if reference == "secret://workspace-step3/starrocks":
        return json.dumps(
            {
                "username": os.environ.get("STEP3B_STARROCKS_USER", "root"),
                "password": os.environ["STEP3B_STARROCKS_PASSWORD"],
            },
            sort_keys=True,
        )
    return None


_mcp_profiles: dict[str, dict[str, object]] = {}
_profile_id = os.environ.get("STEP3_MCP_PROFILE_ID")
_server_path = os.environ.get("STEP3_MCP_SERVER_PATH")
_data_path = os.environ.get("STEP3_MCP_DATA_PATH")
if _profile_id and _server_path and _data_path:
    _server = Path(_server_path).resolve()
    _data = Path(_data_path).resolve()
    _mcp_profiles[_profile_id] = {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(_server)],
        "env": {"MCP_FIXTURE_DATA_PATH": str(_data)},
        "cwd": str(_data.parent),
        "startupTimeoutSeconds": 5,
        "callTimeoutSeconds": 5,
        "toolAllowlist": ["infrastructure.metrics"],
        "outputBytes": 1_000_000,
    }


_local_provider_connectors = frozenset(
    item.strip()
    for item in os.environ.get("STEP3B_LOCAL_PROVIDER_CONNECTORS", "").split(",")
    if item.strip()
)


sources_golden = SourceGoldenApplication(
    database_path=_runtime_root / "sources-golden.sqlite3",
    artifact_root=_runtime_root / "artifacts",
    source_root=_runtime_root / "uploads",
    secret_resolver=_secret,
    network_allow_private_hosts={"127.0.0.1", "localhost"},
    mcp_profiles=_mcp_profiles,
    verified_provider_connectors=set(_local_provider_connectors),
)
application = KnowledgeAssetApplication(
    cast(
        KnowledgeAssetRepository,
        SqliteKnowledgeAssetRepository(_runtime_root / "knowledge-assets.sqlite3"),
    ),
    sources_golden=sources_golden,
)


def _workspace(request: Request) -> str:
    # Test-only authentication shim: the browser cannot supply an arbitrary
    # principal to production code; this fixture maps an auth simulation
    # header into the same server-side identity resolver used by both APIs.
    return request.headers.get("X-Step3B-Test-Workspace", "workspace-step3")


def _identity(request: Request) -> tuple[str, str]:
    return _workspace(request), "editor"


def _source_identity(request: Request) -> AccessContext:
    workspace_id = _workspace(request)
    return AccessContext(
        workspace_id=workspace_id,
        principal_id=workspace_id,
        role="editor",
    )


app = FastAPI(
    title="STEP 3B W1 browser certification BFF",
    docs_url=None,
    redoc_url=None,
)
mount_knowledge_asset_routes(
    app,
    application=application,
    identity_resolver=_identity,
)
mount_source_golden_routes(
    app,
    application=sources_golden,
    identity_resolver=_source_identity,
)
app.mount(
    "/api/source-golden/v1/webhooks",
    create_webhook_ingress(
        sources_golden,
        context_resolver=lambda workspace_id, _connection_id: AccessContext(
            workspace_id=workspace_id,
            principal_id=workspace_id,
            role="editor",
        ),
    ),
)


@app.get("/__step3b/mcp-process-status/{connection_id}")
async def mcp_process_status(connection_id: str, request: Request) -> JSONResponse:
    """Expose a redacted process-reaping projection only in this test fixture."""
    traces = sources_golden.mcp_process_traces(
        _source_identity(request),
        connection_id,
    )
    return JSONResponse(
        [
            {
                "pid": trace.pid,
                "status": trace.status,
                "shutdownMode": trace.shutdown_mode,
                "processReaped": trace.process_reaped,
                "exchangeMethods": [exchange.method for exchange in trace.exchanges],
            }
            for trace in traces
        ]
    )
