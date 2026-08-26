"""Official MCP SDK server used for real streamable HTTP and SSE tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, cast

from mcp.server.fastmcp import FastMCP

server = FastMCP(
    "repository-remote-inventory",
    host="127.0.0.1",
    port=int(os.environ["MCP_FIXTURE_PORT"]),
    log_level="ERROR",
)


@server.tool(
    name="inventory.read",
    description="Read the current bounded inventory fixture.",
    structured_output=True,
)
def inventory_read(region: str = "all") -> dict[str, object]:
    rows = json.loads(
        Path(os.environ["MCP_FIXTURE_DATA_PATH"]).read_text(encoding="utf-8")
    )
    selected = (
        rows
        if region == "all"
        else [row for row in rows if row.get("region") == region]
    )
    return {"rows": selected}


if __name__ == "__main__":
    transport = os.environ["MCP_FIXTURE_TRANSPORT"]
    if transport not in {"sse", "streamable-http"}:
        raise ValueError(f"Unsupported remote MCP transport: {transport}")
    server.run(transport=cast(Literal["sse", "streamable-http"], transport))
