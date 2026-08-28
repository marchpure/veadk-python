#!/usr/bin/env python3
"""Run the required real AutoSkill sequence without mock fallback.

Optional:
  KNOWLEDGE_AUTOSKILL_TOKEN=...
  KNOWLEDGE_AUTOSKILL_BASE_URL=https://test-bytebrain.byted.org

The official stateful API currently accepts anonymous requests. When a token is
configured it is sent by the server-side adapter; otherwise Authorization is
omitted. The command prints only redacted IDs/digests and exits 2 when the live
service or required lifecycle contract is unavailable.
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
from frontend.server.knowledge_workspace.html_artifact import (
    HtmlArtifactError,
    validate_html_artifact,
    validate_output_archive,
)
from frontend.server.knowledge_workspace.zip_validator import validate_skill_zip


def redacted(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "[REDACTED]"


def command_data(answer: object) -> dict:
    if not isinstance(answer, str):
        return {}
    try:
        payload = json.loads(answer)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    value = payload.get("data", payload)
    if isinstance(value, dict) and isinstance(value.get("data"), dict):
        value = value["data"]
    return value if isinstance(value, dict) else {}


def event_types(events: list[ParsedUpstreamEvent]) -> list[str]:
    return [
        event.event_type.casefold().replace("-", "_")
        for event in events
        if not event.malformed
    ]


async def collect(
    stream,
    *,
    require_progress: bool = False,
) -> tuple[list[ParsedUpstreamEvent], dict]:
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
    kinds = event_types(events)
    required = {"final_answer", "state_update", "request_summary", "done"}
    missing = sorted(required.difference(kinds))
    if missing:
        raise RuntimeError(f"missing required SSE events: {', '.join(missing)}")
    if require_progress:
        progress = {"planning", "action", "observation"}
        missing_progress = sorted(progress.difference(kinds))
        if missing_progress:
            raise RuntimeError(
                f"missing required progress SSE events: {', '.join(missing_progress)}"
            )
    if str(summary.get("status", "")).casefold() != "succeeded":
        raise RuntimeError("request_summary did not report succeeded")
    return events, summary


async def main() -> int:
    config = AutoSkillConfig.from_env()
    base = config.base_url
    agent_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    cross_session_id = str(uuid.uuid4())
    requested_name = f"json-validation-dashboard-{uuid.uuid4().hex[:8]}"
    result: dict[str, object] = {
        "status": "RUNNING",
        "base_url": base,
        "authorization": "configured" if config.token else "anonymous",
        "state_mode": "stateful",
        "agent_id": redacted(agent_id),
        "session_id": redacted(session_id),
        "cross_session_id": redacted(cross_session_id),
        "requests": [],
    }
    try:
        client = AutoSkillClient(config)
        health = await client.health()
        if str(health.get("state_mode", "")).casefold() != "stateful":
            raise RuntimeError("configured smoke requires stateful deployment")
        models = await client.models()
        model_items = models.get("models")
        if not isinstance(model_items, list) or not model_items:
            raise RuntimeError("models returned no available model")

        request_id = str(uuid.uuid4())
        create_events, create_summary = await collect(
            client.command(
                "create_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=request_id,
                prompt=(
                    f"Create a reusable Skill named `{requested_name}` that validates "
                    "a JSON object, reports missing required fields, and reports "
                    "unexpected fields. When invoked, it must write a self-contained "
                    "static HTML report to output_files/json-validation-report.html. "
                    "The HTML must not contain scripts, event handlers, forms, iframes, "
                    "external URLs, or network-loaded assets."
                ),
            ),
            require_progress=True,
        )
        result["requests"].append(
            {
                "kind": "create",
                "request_id": redacted(request_id),
                "event_count": len(create_events),
                "event_types": event_types(create_events),
                "summary_status": create_summary.get("status"),
            }
        )
        list_request_id = str(uuid.uuid4())
        list_events, _ = await collect(
            client.command(
                "list_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=list_request_id,
            )
        )
        answer = next(
            (
                event.payload.get("data", {}).get("answer", "")
                for event in list_events
                if event.event_type == "final_answer"
            ),
            "",
        )
        skills = command_data(answer).get("skills", [])
        created_names = [
            str(item)
            for item in create_summary.get("skills_created", [])
            if isinstance(item, str) and item
        ]
        listed_names = {
            str(item["name"])
            for item in skills
            if isinstance(item, dict) and item.get("name")
        }
        name = created_names[0] if created_names else requested_name
        if not name or name not in listed_names:
            raise RuntimeError("could not identify the Skill created by this request")
        view_request_id = str(uuid.uuid4())
        view_events, _ = await collect(
            client.command(
                "view_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=view_request_id,
                name=name,
            )
        )
        if not any(event.event_type == "final_answer" for event in view_events):
            raise RuntimeError("view_skill returned no content")
        zip_one = await client.download(
            agent_id=agent_id, session_id=session_id, file_type="skill", name=name
        )
        checked_one = validate_skill_zip(zip_one)
        invoke_request_id = str(uuid.uuid4())
        invoke_events, invoke_summary = await collect(
            client.invoke(
                agent_id=agent_id,
                session_id=session_id,
                request_id=invoke_request_id,
                message=f"Use the {name} Skill to validate {{'name': 'sample'}} and report the result.",
            ),
            require_progress=True,
        )
        output = await client.download(
            agent_id=agent_id,
            session_id=session_id,
            file_type="output",
        )
        output_evidence: dict[str, object] = {
            "sha256": hashlib.sha256(output).hexdigest(),
            "size_bytes": len(output),
            "media_type": "application/octet-stream",
        }
        try:
            if output.lstrip().lower().startswith((b"<html", b"<!doctype html")):
                output_evidence.update(validate_html_artifact(output))
            else:
                output_name, output_content, output_metadata = (
                    validate_output_archive(output)
                )
                output_evidence.update(output_metadata)
                output_evidence["output_name"] = output_name
                output_evidence["content_sha256"] = hashlib.sha256(
                    output_content
                ).hexdigest()
        except HtmlArtifactError as error:
            # A valid output archive without one unambiguous HTML file is
            # retained as a real file result. Invalid or unsafe archives
            # are hard failures and must never be relabeled as text.
            if error.code not in {
                "ARTIFACT_HTML_MISSING",
                "ARTIFACT_HTML_AMBIGUOUS",
            }:
                raise
            output_evidence["non_html_output"] = True
        update_request_id = str(uuid.uuid4())
        update_events, update_summary = await collect(
            client.command(
                "update_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=update_request_id,
                prompt=f"Update Skill `{name}` to also report unexpected fields.",
            ),
            require_progress=True,
        )
        zip_two = await client.download(
            agent_id=agent_id, session_id=session_id, file_type="skill", name=name
        )
        checked_two = validate_skill_zip(zip_two)
        # A newly constructed client proves persisted state survives a BFF-side
        # client refresh before the separate-session invocation.
        refreshed_client = AutoSkillClient(config)
        refreshed_request_id = str(uuid.uuid4())
        refreshed_events, _ = await collect(
            refreshed_client.command(
                "list_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=refreshed_request_id,
            )
        )
        refreshed_answer = next(
            (
                event.payload.get("data", {}).get("answer", "")
                for event in refreshed_events
                if event.event_type == "final_answer"
            ),
            "",
        )
        if name not in {
            str(item["name"])
            for item in command_data(refreshed_answer).get("skills", [])
            if isinstance(item, dict) and item.get("name")
        }:
            raise RuntimeError("refreshed client could not read the created Skill")
        cross_request_id = str(uuid.uuid4())
        cross_events, cross_summary = await collect(
            refreshed_client.invoke(
                agent_id=agent_id,
                session_id=cross_session_id,
                request_id=cross_request_id,
                message=(
                    f"Use the shared `{name}` Skill to validate "
                    '{"name":"cross-session","extra":true} and report the result.'
                ),
            ),
            require_progress=True,
        )
        if name not in {
            str(item) for item in cross_summary.get("skills_used", [])
        }:
            raise RuntimeError(
                "cross-session request did not report using the created Skill"
            )
        result.update(
            {
                "status": "PASS",
                "skill_name": name,
                "health": {
                    "status": health.get("status"),
                    "state_mode": health.get("state_mode"),
                },
                "models": {
                    "count": len(model_items),
                    "default_model_id": models.get("default_model_id"),
                },
                "requests": result["requests"]
                + [
                    {
                        "kind": "list",
                        "request_id": redacted(list_request_id),
                        "event_types": event_types(list_events),
                    },
                    {
                        "kind": "view",
                        "request_id": redacted(view_request_id),
                        "event_types": event_types(view_events),
                    },
                    {
                        "kind": "invoke",
                        "request_id": redacted(invoke_request_id),
                        "summary_status": invoke_summary.get("status"),
                        "event_count": len(invoke_events),
                        "event_types": event_types(invoke_events),
                    },
                    {
                        "kind": "update",
                        "request_id": redacted(update_request_id),
                        "summary_status": update_summary.get("status"),
                        "event_count": len(update_events),
                        "event_types": event_types(update_events),
                    },
                    {
                        "kind": "refresh_list",
                        "request_id": redacted(refreshed_request_id),
                        "event_count": len(refreshed_events),
                        "event_types": event_types(refreshed_events),
                    },
                    {
                        "kind": "cross_session_invoke",
                        "request_id": redacted(cross_request_id),
                        "summary_status": cross_summary.get("status"),
                        "event_count": len(cross_events),
                        "event_types": event_types(cross_events),
                    },
                ],
                "zip_one_sha256": checked_one["sha256"],
                "zip_two_sha256": checked_two["sha256"],
                "zip_digests_differ": checked_one["sha256"]
                != checked_two["sha256"],
                "output": output_evidence,
                "old_zip_digest_preserved": checked_one["sha256"]
                != checked_two["sha256"],
            }
        )
        if checked_one["sha256"] == checked_two["sha256"]:
            raise RuntimeError("update did not produce a distinct Skill ZIP digest")
    except (
        AutoSkillProtocolError,
        httpx.HTTPError,
        RuntimeError,
        ValueError,
        KeyError,
    ) as error:
        result.update(
            {
                "status": "BLOCKED",
                "reason": type(error).__name__,
                "message": str(error)[:500],
            }
        )
        return_code = 2
    else:
        return_code = 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
