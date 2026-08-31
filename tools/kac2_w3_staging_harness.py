#!/usr/bin/env python3
"""Probe the Studio BFF native AutoSkill AgentKit contract against staging."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.server.knowledge_workspace.autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
)


def https_url(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise argparse.ArgumentTypeError(f"{label} must be an HTTPS URL")
    return value.rstrip("/")


async def run(args: argparse.Namespace) -> dict[str, object]:
    authorization = os.getenv("KAC2_CONNECTION_PRINCIPAL_AUTHORIZATION", "").strip()
    if not authorization:
        raise RuntimeError("KAC2_CONNECTION_PRINCIPAL_AUTHORIZATION is required")
    client = AutoSkillClient(AutoSkillConfig(base_url=args.autoskill_url))
    events = [
        event
        async for event in client.invoke(
            agent_id=args.user_id,
            session_id=args.session_id,
            request_id=args.invocation_id,
            message=args.message,
            connection={
                "metadata": {
                    "connection_id": args.connection_id,
                    "connection_service_url": args.connection_url,
                    "allowedActions": args.allowed_action,
                    "invocationId": args.invocation_id,
                    "audience": args.audience,
                    "ttlSeconds": args.ttl_seconds,
                },
                "authorization": authorization,
            },
        )
    ]
    kinds = [event.event_type for event in events]
    if "done" not in kinds or "request_summary" not in kinds:
        raise RuntimeError(f"native AgentKit run was incomplete: {kinds}")
    artifacts = [
        event.payload["data"]
        for event in events
        if event.event_type == "artifact_delta"
    ]
    downloaded = 0
    if artifacts:
        content = await client.download(
            agent_id=args.user_id,
            session_id=args.session_id,
            file_type="artifact",
        )
        downloaded = len(content)
    return {
        "status": "KAC2_W3_STAGING_READY",
        "autoskill_url": args.autoskill_url,
        "connection_url": args.connection_url,
        "event_types": kinds,
        "artifact_versions": artifacts,
        "downloaded_bytes": downloaded,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--autoskill-url", required=True)
    parser.add_argument("--connection-url", required=True)
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--allowed-action", action="append", required=True)
    parser.add_argument("--user-id", default="kac2-w3-staging")
    parser.add_argument("--session-id", default="kac2-w3-staging")
    parser.add_argument("--invocation-id", default="kac2-w3-staging")
    parser.add_argument("--audience", default="knowledge-runtime")
    parser.add_argument("--ttl-seconds", type=int, default=300)
    parser.add_argument(
        "--message",
        default="Verify native AgentKit connection access and publish a ZIP artifact.",
    )
    args = parser.parse_args()
    args.autoskill_url = https_url(args.autoskill_url, "AutoSkill URL")
    args.connection_url = https_url(args.connection_url, "Connection URL")
    try:
        result = asyncio.run(run(args))
    except (RuntimeError, httpx.HTTPError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
