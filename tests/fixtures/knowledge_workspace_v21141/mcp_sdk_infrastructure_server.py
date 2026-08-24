#!/usr/bin/env python3
"""Independent stdio server implemented with the official MCP Python SDK."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP


server = FastMCP(
    "repository-infrastructure-metrics",
    instructions="Reads non-sales infrastructure metrics from a local JSON file.",
    log_level="ERROR",
)


@server.tool(
    name="infrastructure.metrics",
    description="Read bounded infrastructure utilization metrics.",
    structured_output=True,
)
def infrastructure_metrics(service: str = "all") -> dict[str, object]:
    """Return local infrastructure metrics for one service or all services."""
    data_path = Path(os.environ["MCP_FIXTURE_DATA_PATH"])
    rows = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("fixture data must be an array of objects")
    selected = (
        rows
        if service == "all"
        else [row for row in rows if row.get("service") == service]
    )
    return {"rows": selected, "dataAsOf": data_path.stat().st_mtime_ns}


if __name__ == "__main__":
    server.run(transport="stdio")
