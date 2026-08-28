#!/usr/bin/env python3
"""Exercise the real Connection Service -> official AutoSkill lifecycle.

Required environment:
  KNOWLEDGE_CONNECTION_SERVICE_BASE_URL=http://127.0.0.1:3417
  KNOWLEDGE_CONNECTION_SERVICE_RUNTIME_PUBLIC_URL=https://public-runtime.example
  KNOWLEDGE_CONNECTION_SERVICE_AUTH_SECRET=...

Optional:
  KNOWLEDGE_AUTOSKILL_BASE_URL=https://test-bytebrain.byted.org
  KNOWLEDGE_AUTOSKILL_TOKEN=...

This smoke has no mock or fixture fallback. Its JSON output contains no lease
tokens, credentials, downloaded content, or raw SSE payloads.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from frontend.server.knowledge_workspace.autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
    AutoSkillProtocolError,
)
from frontend.server.knowledge_workspace.connection import (
    ConnectionServiceConfig,
    ConnectionServiceError,
    ConnectionServiceGateway,
)
from frontend.server.knowledge_workspace.html_artifact import (
    validate_html_artifact,
    validate_output_archive,
)
from frontend.server.knowledge_workspace.sse import ParsedUpstreamEvent
from frontend.server.knowledge_workspace.zip_validator import validate_skill_zip


ACTOR = {
    "tenant_id": "knowledge-step2-smoke",
    "workspace_id": "knowledge-step2-smoke",
    "principal_id": "knowledge-step2-smoke",
}
REQUIRED_EVENTS = {"final_answer", "state_update", "request_summary", "done"}
PROGRESS_EVENTS = {"planning", "action", "observation"}


def redacted(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "[REDACTED]"


def event_types(events: list[ParsedUpstreamEvent]) -> list[str]:
    return [
        event.event_type.casefold().replace("-", "_")
        for event in events
        if not event.malformed
    ]


def final_answer_data(events: list[ParsedUpstreamEvent]) -> dict[str, Any]:
    for event in events:
        if event.event_type.casefold().replace("-", "_") != "final_answer":
            continue
        data = event.payload.get("data")
        if not isinstance(data, Mapping):
            continue
        answer = data.get("answer")
        if not isinstance(answer, str):
            continue
        try:
            parsed = json.loads(answer)
        except ValueError:
            continue
        if not isinstance(parsed, dict):
            continue
        nested = parsed.get("data", parsed)
        if isinstance(nested, dict) and isinstance(nested.get("data"), dict):
            nested = nested["data"]
        if isinstance(nested, dict):
            return nested
    return {}


async def collect(
    stream: Any,
    *,
    require_progress: bool = False,
) -> tuple[list[ParsedUpstreamEvent], dict[str, Any]]:
    events: list[ParsedUpstreamEvent] = []
    summary: dict[str, Any] = {}
    async for event in stream:
        events.append(event)
        kind = event.event_type.casefold().replace("-", "_")
        if kind == "request_summary":
            value = event.payload.get("data")
            if isinstance(value, dict):
                summary = value
        if kind == "error":
            raise RuntimeError("AutoSkill returned an error event")
        if kind == "done":
            break
    kinds = set(event_types(events))
    missing = REQUIRED_EVENTS.difference(kinds)
    if require_progress:
        missing |= PROGRESS_EVENTS.difference(kinds)
    if missing:
        raise RuntimeError(f"missing required SSE events: {', '.join(sorted(missing))}")
    if str(summary.get("status", "")).casefold() != "succeeded":
        raise RuntimeError("AutoSkill request_summary did not report succeeded")
    return events, summary


async def wait_for_job(
    gateway: ConnectionServiceGateway,
    job: dict[str, Any],
) -> dict[str, Any]:
    for _ in range(240):
        if job["status"] == "succeeded":
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"Connection {job['job_id']} failed: {job.get('error')}")
        await asyncio.sleep(0.5)
        job = await gateway.get_job(job["job_id"], **ACTOR)
    raise RuntimeError(f"Connection {job['job_id']} timed out")


async def prepare_connection(
    gateway: ConnectionServiceGateway,
    autoskill: AutoSkillClient,
    *,
    connection_id: str,
    agent_id: str,
    session_id: str,
    invocation_id: str,
) -> Any:
    context = await gateway.issue(
        **ACTOR,
        invocation_id=invocation_id,
        connection_ids=[connection_id],
        allowed_actions=["connection.execute"],
        ttl_seconds=900,
    )
    await gateway.prepare_autoskill(
        context=context,
        autoskill=autoskill,
        agent_id=agent_id,
        session_id=session_id,
        invocation_id=invocation_id,
    )
    return context


async def run_with_connection(
    gateway: ConnectionServiceGateway,
    autoskill: AutoSkillClient,
    *,
    connection_id: str,
    agent_id: str,
    session_id: str,
    invocation_id: str,
    stream: Any,
) -> tuple[list[ParsedUpstreamEvent], dict[str, Any]]:
    context = await prepare_connection(
        gateway,
        autoskill,
        connection_id=connection_id,
        agent_id=agent_id,
        session_id=session_id,
        invocation_id=invocation_id,
    )
    try:
        return await collect(stream(), require_progress=True)
    finally:
        await gateway.revoke(context.lease_id)


async def audit_for(
    gateway: ConnectionServiceGateway,
    invocation_id: str,
) -> list[dict[str, Any]]:
    items = await gateway.list_audit(**ACTOR)
    matched = [
        {
            "execution_id": redacted(str(item.get("id", ""))),
            "invocation_id": redacted(str(item.get("invocationId", ""))),
            "connection_id": redacted(str(item.get("connectionId", ""))),
            "action_id": item.get("actionId"),
            "ok": item.get("ok"),
        }
        for item in items
        if item.get("invocationId") == invocation_id
    ]
    if not matched or not all(item["ok"] is True for item in matched):
        raise RuntimeError(
            f"no successful Connection audit matched AutoSkill invocation {redacted(invocation_id)}"
        )
    return matched


async def invoke_with_connection_audit(
    gateway: ConnectionServiceGateway,
    autoskill: AutoSkillClient,
    *,
    connection_id: str,
    agent_id: str,
    session_id: str,
    skill_name: str,
    tool_name: str,
    kind: str,
    attempts: int = 3,
) -> tuple[str, list[ParsedUpstreamEvent], dict[str, Any], list[dict[str, Any]]]:
    last_error: RuntimeError | None = None
    for attempt in range(1, attempts + 1):
        invocation_id = str(uuid.uuid4())
        events, summary = await run_with_connection(
            gateway,
            autoskill,
            connection_id=connection_id,
            agent_id=agent_id,
            session_id=session_id,
            invocation_id=invocation_id,
            stream=lambda: autoskill.invoke(
                agent_id=agent_id,
                session_id=session_id,
                request_id=invocation_id,
                message=(
                    f"Use the shared `{skill_name}` now. This is live-data attempt "
                    f"{attempt}: first call the configured MCP tool `{tool_name}` "
                    "and use its returned max_item_id before writing "
                    "output_files/hackernews-live.html. Never reuse a prior value."
                ),
            ),
        )
        try:
            audit = await audit_for(gateway, invocation_id)
        except RuntimeError as error:
            last_error = error
            continue
        return invocation_id, events, summary, audit
    raise last_error or RuntimeError(f"{kind} did not call the Connection Service")


def html_evidence(content: bytes) -> dict[str, Any]:
    if content.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        return validate_html_artifact(content)
    name, html, metadata = validate_output_archive(content)
    return {
        **metadata,
        "name": name,
        "archive_sha256": hashlib.sha256(content).hexdigest(),
        "content_sha256": hashlib.sha256(html).hexdigest(),
    }


def request_evidence(
    kind: str,
    request_id: str,
    events: list[ParsedUpstreamEvent],
    summary: Mapping[str, Any],
    audit: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "request_id": redacted(request_id),
        "event_types": event_types(events),
        "summary_status": summary.get("status"),
        **({"connection_audit": audit} if audit is not None else {}),
    }


async def main(
    evidence_path: Path | None,
    *,
    existing_agent_id: str | None = None,
    existing_skill_name: str | None = None,
    existing_connection_id: str | None = None,
    cross_session_only: bool = False,
) -> int:
    result: dict[str, Any] = {"status": "RUNNING"}
    try:
        autoskill_config = AutoSkillConfig.from_env()
        connection_config = ConnectionServiceConfig.from_env()
        autoskill = AutoSkillClient(autoskill_config)
        gateway = ConnectionServiceGateway(connection_config)
        if bool(existing_agent_id) != bool(existing_skill_name):
            raise ValueError(
                "--existing-agent-id and --existing-skill-name must be provided together"
            )
        if cross_session_only and not (
            existing_agent_id and existing_skill_name and existing_connection_id
        ):
            raise ValueError(
                "--cross-session-only requires --existing-agent-id, "
                "--existing-skill-name, and --existing-connection-id"
            )
        replay = existing_agent_id is not None
        agent_id = existing_agent_id or str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        cross_session_id = str(uuid.uuid4())
        connection_name = f"hackernews-smoke-{uuid.uuid4().hex[:8]}"
        skill_name = existing_skill_name or f"hackernews-live-dashboard-{uuid.uuid4().hex[:8]}"
        result.update(
            {
                "autoskill_base_url": autoskill_config.base_url,
                "autoskill_authorization": (
                    "configured" if autoskill_config.token else "anonymous"
                ),
                "connection_service_base_url": connection_config.base_url,
                "connection_service_runtime": connection_config.runtime_public_url,
                "agent_id": redacted(agent_id),
                "session_id": redacted(session_id),
                "cross_session_id": redacted(cross_session_id),
                "lifecycle_mode": "existing_skill_replay" if replay else "create",
                "skill_name": skill_name,
                "requests": [],
            }
        )

        health = await autoskill.health()
        models = await autoskill.models()
        model_items = models.get("models")
        if str(health.get("state_mode", "")).casefold() != "stateful":
            raise RuntimeError("official AutoSkill API is not stateful")
        if not isinstance(model_items, list) or not model_items:
            raise RuntimeError("official AutoSkill API returned no models")
        result["health"] = {
            "status": health.get("status"),
            "state_mode": health.get("state_mode"),
        }
        result["models"] = {
            "count": len(model_items),
            "default_model_id": models.get("default_model_id"),
        }
        catalog = await gateway.catalog(**ACTOR)
        hackernews = next(
            (item for item in catalog if item["connector_key"] == "hackernews"),
            None,
        )
        if hackernews is None:
            raise RuntimeError("Hacker News is not enabled in Connection Service catalog")
        if not hackernews["config_schema"] or not hackernews["auth_schema"]:
            raise RuntimeError("Connection Service omitted provider-owned schemas")
        if existing_connection_id:
            connection_id = existing_connection_id
            connection = {
                "connection_id": connection_id,
                "connector_key": "hackernews",
                "status": "ready",
            }
        else:
            connection = await gateway.create_connection(
                {
                    "connector_key": "hackernews",
                    "display_name": connection_name,
                    "scope": "personal",
                    "config": {},
                    "credential": {"_auth_type": "no_auth"},
                },
                **ACTOR,
            )
            connection_id = connection["connection_id"]
        tool_name = f"{connection_id[:12]}__hackernews.get_max_item_id"
        result["connection_id"] = redacted(connection_id)
        if not cross_session_only:
            validate_job = await wait_for_job(
                gateway,
                await gateway.start_job(connection_id, "validate", **ACTOR),
            )
            discover_job = await wait_for_job(
                gateway,
                await gateway.start_job(connection_id, "discover", **ACTOR),
            )
            actions = discover_job.get("result", {}).get("actions", [])
            if not any(
                isinstance(action, Mapping)
                and action.get("id") == "hackernews.get_max_item_id"
                and action.get("executable") is True
                for action in actions
            ):
                raise RuntimeError("Hacker News live action was not discovered")
            result["connection"] = {
                "connector_key": connection["connector_key"],
                "status": connection["status"],
                "validate_status": validate_job["status"],
                "discover_status": discover_job["status"],
                "discovered_action_count": len(actions),
            }
        else:
            result["connection"] = {
                "connector_key": connection["connector_key"],
                "status": connection["status"],
                "resume_mode": "previously_validated_and_discovered",
            }

        if cross_session_only:
            cross_id, cross_events, cross_summary, cross_audit = (
                await invoke_with_connection_audit(
                    gateway,
                    autoskill,
                    connection_id=connection_id,
                    agent_id=agent_id,
                    session_id=cross_session_id,
                    skill_name=skill_name,
                    tool_name=tool_name,
                    kind="cross-session invoke",
                )
            )
            result["requests"].append(
                request_evidence(
                    "cross_session_invoke",
                    cross_id,
                    cross_events,
                    cross_summary,
                    cross_audit,
                )
            )
            cross_html = html_evidence(
                await autoskill.download(
                    agent_id=agent_id,
                    session_id=cross_session_id,
                    file_type="output",
                )
            )
            result.update(
                {
                    "status": "PASS_CROSS_SESSION_RESUME",
                    "skill_name": skill_name,
                    "html_cross_session": cross_html,
                }
            )
            rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            if evidence_path is not None:
                evidence_path.write_text(rendered + "\n", encoding="utf-8")
            print(rendered)
            return 0

        if not replay:
            create_id = str(uuid.uuid4())
            create_events, create_summary = await run_with_connection(
                gateway,
                autoskill,
                connection_id=connection_id,
                agent_id=agent_id,
                session_id=session_id,
                invocation_id=create_id,
                stream=lambda: autoskill.command(
                    "create_skill",
                    agent_id=agent_id,
                    session_id=session_id,
                    request_id=create_id,
                    prompt=(
                        f"Create a reusable Skill named `{skill_name}`. First call the "
                        f"configured Connection Service MCP tool `{tool_name}` to verify "
                        "the source. On every invoke, call that exact live tool again and "
                        "write a self-contained static HTML "
                        "dashboard to output_files/hackernews-live.html showing the returned "
                        "max_item_id. Include no scripts, forms, iframes, external URLs, or "
                        "network-loaded assets."
                    ),
                ),
            )
            result["requests"].append(
                request_evidence("create_skill", create_id, create_events, create_summary)
            )
            created_names = [
                str(value)
                for value in create_summary.get("skills_created", [])
                if isinstance(value, str)
            ]
            if created_names:
                skill_name = created_names[0]

        list_id = str(uuid.uuid4())
        list_events, list_summary = await collect(
            autoskill.command(
                "list_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=list_id,
            )
        )
        result["requests"].append(
            request_evidence("list_skill", list_id, list_events, list_summary)
        )
        listed = final_answer_data(list_events).get("skills", [])
        if skill_name not in {
            str(item.get("name"))
            for item in listed
            if isinstance(item, Mapping)
        }:
            raise RuntimeError("created Skill was not returned by list_skill")

        view_id = str(uuid.uuid4())
        view_events, view_summary = await collect(
            autoskill.command(
                "view_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=view_id,
                name=skill_name,
            )
        )
        result["requests"].append(
            request_evidence("view_skill", view_id, view_events, view_summary)
        )
        first_zip = validate_skill_zip(
            await autoskill.download(
                agent_id=agent_id,
                session_id=session_id,
                file_type="skill",
                name=skill_name,
            )
        )
        result["skill_zip_before"] = {
            key: value for key, value in first_zip.items() if key != "skill_md"
        }

        invoke_id, invoke_events, invoke_summary, invoke_audit = (
            await invoke_with_connection_audit(
                gateway,
                autoskill,
                connection_id=connection_id,
                agent_id=agent_id,
                session_id=session_id,
                skill_name=skill_name,
                tool_name=tool_name,
                kind="invoke",
            )
        )
        result["requests"].append(
            request_evidence(
                "invoke",
                invoke_id,
                invoke_events,
                invoke_summary,
                invoke_audit,
            )
        )
        first_html = html_evidence(
            await autoskill.download(
                agent_id=agent_id,
                session_id=session_id,
                file_type="output",
            )
        )
        result["html_first"] = first_html

        update_id = str(uuid.uuid4())
        update_events, update_summary = await run_with_connection(
            gateway,
            autoskill,
            connection_id=connection_id,
            agent_id=agent_id,
            session_id=session_id,
            invocation_id=update_id,
            stream=lambda: autoskill.command(
                "update_skill",
                agent_id=agent_id,
                session_id=session_id,
                request_id=update_id,
                prompt=(
                    f"Update `{skill_name}` after calling the live Hacker News MCP tool "
                    f"`{tool_name}`. "
                    "Require the dashboard to visibly include `Source: Connection Service MCP`."
                ),
            ),
        )
        result["requests"].append(
            request_evidence(
                "update_skill", update_id, update_events, update_summary
            )
        )
        second_zip = validate_skill_zip(
            await autoskill.download(
                agent_id=agent_id,
                session_id=session_id,
                file_type="skill",
                name=skill_name,
            )
        )
        if first_zip["sha256"] == second_zip["sha256"]:
            raise RuntimeError("update_skill did not change the Skill artifact digest")
        result["skill_zip_after"] = {
            key: value for key, value in second_zip.items() if key != "skill_md"
        }

        cross_id, cross_events, cross_summary, cross_audit = (
            await invoke_with_connection_audit(
                gateway,
                autoskill,
                connection_id=connection_id,
                agent_id=agent_id,
                session_id=cross_session_id,
                skill_name=skill_name,
                tool_name=tool_name,
                kind="cross-session invoke",
            )
        )
        result["requests"].append(
            request_evidence(
                "cross_session_invoke",
                cross_id,
                cross_events,
                cross_summary,
                cross_audit,
            )
        )
        cross_html = html_evidence(
            await autoskill.download(
                agent_id=agent_id,
                session_id=cross_session_id,
                file_type="output",
            )
        )

        result.update(
            {
                "status": "PASS_REPLAY" if replay else "PASS",
                "connection_id": redacted(connection_id),
                "skill_name": skill_name,
                "html_cross_session": cross_html,
            }
        )
    except (
        AutoSkillProtocolError,
        ConnectionServiceError,
        httpx.HTTPError,
        KeyError,
        RuntimeError,
        ValueError,
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

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if evidence_path is not None:
        evidence_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return return_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--existing-agent-id")
    parser.add_argument("--existing-skill-name")
    parser.add_argument("--existing-connection-id")
    parser.add_argument("--cross-session-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                args.evidence,
                existing_agent_id=args.existing_agent_id,
                existing_skill_name=args.existing_skill_name,
                existing_connection_id=args.existing_connection_id,
                cross_session_only=args.cross_session_only,
            )
        )
    )
