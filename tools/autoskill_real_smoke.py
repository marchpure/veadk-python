#!/usr/bin/env python3
"""Run the required real AutoSkill sequence without mock fallback.

Required environment:
  KNOWLEDGE_AUTOSKILL_TOKEN=...

Optional:
  KNOWLEDGE_AUTOSKILL_BASE_URL=https://test-bytebrain.byted.org

The command intentionally prints only redacted IDs/digests and exits 2 when
credentials are absent or the live service is unreachable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from frontend.server.knowledge_workspace.autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
    AutoSkillProtocolError,
)
from frontend.server.knowledge_workspace.sse import ParsedUpstreamEvent
from frontend.server.knowledge_workspace.zip_validator import validate_skill_zip


def redacted(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "[REDACTED]"


async def collect(stream) -> tuple[list[ParsedUpstreamEvent], dict]:
    events: list[ParsedUpstreamEvent] = []
    summary: dict = {}
    async for event in stream:
        events.append(event)
        if event.event_type == "request_summary":
            payload = event.payload.get("data")
            if isinstance(payload, dict):
                summary = payload
        if event.event_type == "error":
            raise RuntimeError("upstream error event")
        if event.event_type == "done":
            break
    if not any(event.event_type == "final_answer" for event in events):
        raise RuntimeError("missing final_answer")
    if not summary:
        raise RuntimeError("missing request_summary")
    if not any(event.event_type == "done" for event in events):
        raise RuntimeError("missing done")
    return events, summary


async def main() -> int:
    token = os.getenv("KNOWLEDGE_AUTOSKILL_TOKEN", "")
    if not token:
        print(json.dumps({
            "status": "BLOCKED",
            "reason": "KNOWLEDGE_AUTOSKILL_TOKEN is not configured",
            "repro": "KNOWLEDGE_AUTOSKILL_TOKEN=... python tools/autoskill_real_smoke.py",
        }))
        return 2
    base = os.getenv("KNOWLEDGE_AUTOSKILL_BASE_URL", "https://test-bytebrain.byted.org")
    agent_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    result: dict[str, object] = {
        "status": "RUNNING",
        "base_url": base,
        "state_mode": "stateful",
        "agent_id": redacted(agent_id),
        "session_id": redacted(session_id),
        "requests": [],
    }
    try:
        async with httpx.AsyncClient() as transport:
            client = AutoSkillClient(
                AutoSkillConfig(base_url=base, token=token),
                client=transport,
            )
            health = await client.health()
            if str(health.get("state_mode", "")).casefold() != "stateful":
                raise RuntimeError("configured smoke requires stateful deployment")
            request_id = str(uuid.uuid4())
            create_events, create_summary = await collect(client.command(
                "create_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=request_id,
                prompt="Create a small reusable Skill that explains how to validate a JSON object and reports missing required fields.",
            ))
            result["requests"].append({"kind": "create", "request_id": redacted(request_id), "event_count": len(create_events), "summary_status": create_summary.get("status")})
            list_request_id = str(uuid.uuid4())
            list_events, _ = await collect(client.command("list_skill", agent_id=agent_id, session_id=session_id, request_id=list_request_id))
            answer = next((event.payload.get("data", {}).get("answer", "") for event in list_events if event.event_type == "final_answer"), "")
            parsed = json.loads(answer) if isinstance(answer, str) else {}
            skills = parsed.get("data", {}).get("skills", [])
            if not skills:
                raise RuntimeError("list_skill returned no Skill")
            name = str(skills[0]["name"])
            view_request_id = str(uuid.uuid4())
            view_events, _ = await collect(client.command("view_skill", agent_id=agent_id, session_id=session_id, request_id=view_request_id, name=name))
            if not any(event.event_type == "final_answer" for event in view_events):
                raise RuntimeError("view_skill returned no content")
            zip_one = await client.download(agent_id=agent_id, session_id=session_id, file_type="skill", name=name)
            checked_one = validate_skill_zip(zip_one)
            invoke_request_id = str(uuid.uuid4())
            invoke_events, invoke_summary = await collect(client.invoke(agent_id=agent_id, session_id=session_id, request_id=invoke_request_id, message=f"Use the {name} Skill to validate {{'name': 'sample'}} and report the result."))
            update_request_id = str(uuid.uuid4())
            update_events, update_summary = await collect(client.command("update_skill", agent_id=agent_id, session_id=session_id, request_id=update_request_id, prompt=f"Update Skill `{name}` to also report unexpected fields."))
            zip_two = await client.download(agent_id=agent_id, session_id=session_id, file_type="skill", name=name)
            checked_two = validate_skill_zip(zip_two)
            result.update({
                "status": "PASS",
                "skill_name": name,
                "requests": result["requests"] + [
                    {"kind": "list", "request_id": redacted(list_request_id)},
                    {"kind": "view", "request_id": redacted(view_request_id)},
                    {"kind": "invoke", "request_id": redacted(invoke_request_id), "summary_status": invoke_summary.get("status"), "event_count": len(invoke_events)},
                    {"kind": "update", "request_id": redacted(update_request_id), "summary_status": update_summary.get("status"), "event_count": len(update_events)},
                ],
                "zip_one_sha256": checked_one["sha256"],
                "zip_two_sha256": checked_two["sha256"],
                "zip_digests_differ": checked_one["sha256"] != checked_two["sha256"],
            })
            if checked_one["sha256"] == checked_two["sha256"]:
                raise RuntimeError("update did not produce a distinct Skill ZIP digest")
    except (AutoSkillProtocolError, httpx.HTTPError, RuntimeError, ValueError, KeyError) as error:
        result.update({"status": "BLOCKED", "reason": type(error).__name__, "message": str(error)[:500]})
        return_code = 2
    else:
        return_code = 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
