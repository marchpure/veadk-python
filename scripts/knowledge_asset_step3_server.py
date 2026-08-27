"""Stable local STEP 3 integration server entrypoint.

The MCP subprocess is deliberately configured on the server side.  The
browser may select the profile, but never supplies a command, cwd, or env.
"""

import os
import sys
from pathlib import Path

from frontend.server.knowledge_assets.runtime import create_app

profile_id = os.getenv("STEP3_MCP_PROFILE_ID")
server_path = os.getenv("STEP3_MCP_SERVER_PATH")
data_path = os.getenv("STEP3_MCP_DATA_PATH")
mcp_profiles: dict[str, dict[str, object]] = {}
if profile_id or server_path or data_path:
    if not (profile_id and server_path and data_path):
        raise RuntimeError(
            "STEP3_MCP_PROFILE_ID, STEP3_MCP_SERVER_PATH and "
            "STEP3_MCP_DATA_PATH are required together"
        )
    server = Path(server_path).resolve()
    data = Path(data_path).resolve()
    if not server.is_file() or not data.is_file():
        raise RuntimeError("configured STEP3 MCP server/data path does not exist")
    mcp_profiles[profile_id] = {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(server)],
        "env": {"MCP_FIXTURE_DATA_PATH": str(data)},
        "cwd": str(data.parent),
        "startupTimeoutSeconds": 5,
        "callTimeoutSeconds": 5,
        "toolAllowlist": ["infrastructure.metrics"],
        "outputBytes": 1_000_000,
    }

repository_path = os.getenv(
    "STEP3B_DATABASE_PATH", ".veadk/knowledge-assets-step3.sqlite3"
)
workspace_id = os.getenv("STEP3B_WORKSPACE_ID", "workspace-step3")
app = create_app(
    repository_path=repository_path,
    identity_resolver=lambda request: (workspace_id, "editor"),
    mcp_profiles=mcp_profiles,
)
