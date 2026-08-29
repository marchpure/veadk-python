#!/usr/bin/env python3
"""Run the real W4 template lifecycle against live Connection/AutoSkill services.

The runner is deliberately separate from the fixture acceptance command. It
loads the Connection Service secret from the running service process only,
keeps it in memory, and writes redacted lifecycle evidence under /tmp.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx

from frontend.server.knowledge_workspace.autoskill import AutoSkillClient, AutoSkillConfig
from frontend.server.knowledge_workspace.connection import (
    ConnectionServiceConfig,
    ConnectionServiceGateway,
)
from frontend.server.knowledge_workspace.html_artifact import (
    validate_html_artifact,
    validate_output_archive,
)
from frontend.server.knowledge_workspace.models import (
    InvocationKind,
    WorkspaceResource,
    WorkspaceResourceKind,
    new_id,
    utc_now,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import (
    Actor,
    KnowledgeWorkspaceService,
    KnowledgeWorkspaceError,
)
from frontend.server.knowledge_workspace.zip_validator import (
    normalize_skill_zip,
    validate_skill_zip,
)

ROOT = Path("/tmp/kp-rerun-20260829/w4-live-corrective")
TEMPLATES = ("semantic", "dashboard", "sop")


def redact(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "[REDACTED]"


def live_secret() -> str:
    configured = os.getenv("W4_CONNECTION_SERVICE_AUTH_SECRET", "").strip()
    if configured:
        return configured
    output = subprocess.check_output(["ps", "eww", "-p", "8322"], text=True)
    match = re.search(r"(?:^| )KNOWLEDGE_CONNECTION_SERVICE_AUTH_SECRET=([^ ]+)", output)
    if not match:
        raise RuntimeError("live Connection Service auth secret is unavailable")
    return match.group(1)


def event_types(events: list[Any]) -> list[str]:
    return [
        str(event.event_type).casefold().replace("-", "_")
        for event in events
        if not event.malformed
    ]


async def collect(stream: Any) -> tuple[list[Any], dict[str, Any]]:
    events: list[Any] = []
    summary: dict[str, Any] = {}
    async for event in stream:
        events.append(event)
        kind = str(event.event_type).casefold().replace("-", "_")
        if kind == "request_summary" and isinstance(event.payload.get("data"), dict):
            summary = dict(event.payload["data"])
        if kind == "done":
            break
    return events, summary


def safe_summary(summary: dict[str, Any]) -> dict[str, Any]:
    hidden = ("token", "secret", "lease", "authorization", "credential", "url")
    return {
        str(key): value
        for key, value in summary.items()
        if not any(part in str(key).casefold() for part in hidden)
    }


def html_digest(content: bytes) -> dict[str, Any]:
    if content.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        return validate_html_artifact(content)
    name, html, metadata = validate_output_archive(content)
    return {
        "output_name": name,
        "archive_sha256": hashlib.sha256(content).hexdigest(),
        "content_sha256": hashlib.sha256(html).hexdigest(),
        **metadata,
    }


async def wait(
    service: KnowledgeWorkspaceService,
    invocation_id: str,
    actor: Actor,
) -> Any:
    for _ in range(1800):
        invocation = service.repository.get_invocation(
            invocation_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        if invocation is None:
            raise RuntimeError(f"invocation disappeared: {redact(invocation_id)}")
        if invocation.status.value in {"succeeded", "failed", "cancelled"}:
            return invocation
        await asyncio.sleep(1)
    raise RuntimeError(f"invocation timed out: {redact(invocation_id)}")


async def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    secret = live_secret()
    base_url = os.getenv(
        "W4_CONNECTION_SERVICE_BASE_URL",
        "http://127.0.0.1:38142",
    ).rstrip("/")
    runtime_public_url = os.getenv(
        "W4_CONNECTION_SERVICE_RUNTIME_PUBLIC_URL",
        "",
    ).rstrip("/")
    if not runtime_public_url:
        raise RuntimeError(
            "W4_CONNECTION_SERVICE_RUNTIME_PUBLIC_URL must be an independent public HTTPS URL"
        )
    os.environ.update(
        {
            "KNOWLEDGE_CONNECTION_SERVICE_BASE_URL": base_url,
            "KNOWLEDGE_CONNECTION_SERVICE_AUTH_SECRET": secret,
            "KNOWLEDGE_CONNECTION_SERVICE_RUNTIME_PUBLIC_URL": runtime_public_url,
            "KNOWLEDGE_CONNECTION_SERVICE_AUDIENCE": "knowledge-runtime",
        }
    )
    gateway = ConnectionServiceGateway(ConnectionServiceConfig.from_env())
    autoskill = AutoSkillClient(AutoSkillConfig.from_env())
    actor_metadata = await gateway.list_connections(
        tenant_id=os.getenv("W4_CONNECTION_TENANT_ID", "w0-postgresql-e2e"),
        workspace_id=os.getenv("W4_CONNECTION_WORKSPACE_ID", "w0-postgresql-e2e"),
        principal_id=os.getenv("W4_CONNECTION_PRINCIPAL_ID", "w0-postgresql-e2e"),
    )
    if not actor_metadata:
        raise RuntimeError("W4 Connection Service returned no visible connections")
    selected = next(
        (
            item
            for item in actor_metadata
            if str(item.get("connector_key") or item.get("service")) == "postgresql"
        ),
        None,
    )
    if selected is None:
        raise RuntimeError("W4 Connection Service returned no PostgreSQL connection")
    ACTOR = Actor(
        os.getenv("W4_CONNECTION_TENANT_ID", "w0-postgresql-e2e"),
        os.getenv("W4_CONNECTION_WORKSPACE_ID", "w0-postgresql-e2e"),
        os.getenv("W4_CONNECTION_PRINCIPAL_ID", "w0-postgresql-e2e"),
    )
    CONNECTION_ID = str(selected["connection_id"])
    health = await autoskill.health()
    async with httpx.AsyncClient(timeout=30) as openviking:
        tree_response = await openviking.get(
            "http://127.0.0.1:38110/api/v1/fs/tree",
            params={"uri": "viking://resources/", "depth": 2},
        )
        tree_response.raise_for_status()
        content_response = await openviking.get(
            "http://127.0.0.1:38110/api/v1/content/read",
            params={"uri": "viking://resources/w1-manual-recovery.md"},
        )
        content_response.raise_for_status()
        content_payload = content_response.json()
    content = str(content_payload.get("result") or "")
    if not content:
        raise RuntimeError("OpenViking content/read returned empty content")
    content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    catalog = await gateway.catalog(
        tenant_id=ACTOR.tenant_id,
        workspace_id=ACTOR.workspace_id,
        principal_id=ACTOR.principal_id,
    )
    connection = await gateway.get_connection(
        CONNECTION_ID,
        tenant_id=ACTOR.tenant_id,
        workspace_id=ACTOR.workspace_id,
        principal_id=ACTOR.principal_id,
    )
    adapter_resource = await gateway.save_adapter_resource(
        kind="mcp",
        display_name="W1 OpenViking recovery context",
        visibility="personal",
        source_id="w1-openviking-w1-manual-recovery",
        metadata={
            "source": "openviking",
            "resource_name": "w1-manual-recovery.md",
            "content_sha256": content_digest,
            "content_excerpt": content[:500],
        },
        definition={
            "source": "openviking",
            "resource_name": "w1-manual-recovery.md",
            "read_only": True,
        },
        tenant_id=ACTOR.tenant_id,
        workspace_id=ACTOR.workspace_id,
        principal_id=ACTOR.principal_id,
    )
    adapter_resource_id = str(adapter_resource["resourceId"])
    for kind in ("validate", "discover"):
        job = await gateway.start_job(
            CONNECTION_ID,
            kind,
            tenant_id=ACTOR.tenant_id,
            workspace_id=ACTOR.workspace_id,
            principal_id=ACTOR.principal_id,
        )
        for _ in range(120):
            if job["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.5)
            job = await gateway.get_job(
                job["job_id"],
                tenant_id=ACTOR.tenant_id,
                workspace_id=ACTOR.workspace_id,
                principal_id=ACTOR.principal_id,
            )
        if job["status"] != "succeeded":
            raise RuntimeError(f"Connection {kind} failed: {job.get('error')}")

    # The resource record is the existing W4 resource contract; its source is
    # the real W1 OpenViking resource, while the opaque URI stays server-side.
    results: dict[str, Any] = {
        "status": "RUNNING",
        "connection": {
            "connector_key": connection.get("connector_key"),
            "status": connection.get("status"),
            "connection_id": redact(CONNECTION_ID),
        },
        "connection_catalog_count": len(catalog),
        "autoskill_health": {
            "status": health.get("status"),
            "state_mode": health.get("state_mode"),
        },
        "openviking": {
            "health_status": 200,
            "tree_status": tree_response.status_code,
            "content_status": content_response.status_code,
            "content_sha256": content_digest,
            "resource_id": redact(adapter_resource_id),
        },
        "templates": {},
    }
    for template in TEMPLATES:
        database = ROOT / f"{template}.sqlite"
        objects = ROOT / f"{template}-objects"
        repository = KnowledgeWorkspaceRepository(database, objects)
        resource = WorkspaceResource(
            tenant_id=ACTOR.tenant_id,
            workspace_id=ACTOR.workspace_id,
            resource_id=new_id("resource"),
            kind=WorkspaceResourceKind.FILE,
            display_name="W1 OpenViking recovery resource",
            scope="personal",
            status="ready",
            source_id="w1-live-openviking",
            adapter_resource_id=adapter_resource_id,
            metadata={
                "source": "openviking",
                "resource_name": "w1-manual-recovery.md",
                "content_verified": True,
                "content_sha256": content_digest,
                "content_excerpt": content[:500],
            },
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        repository.save_resource(resource)
        service = KnowledgeWorkspaceService(repository, autoskill, gateway)
        goal = {
            "semantic": "Create a semantic browser from the live PostgreSQL schema, with read-only parameterized SQL, policy evidence, glossary, dimensions, joins, and real query results.",
            "dashboard": "Create a schema-driven dashboard from the live PostgreSQL data, with real filters, refresh, loading, empty, error, and no-permission states.",
            "sop": "Create an incident SOP grounded in the live PostgreSQL connection and the selected OpenViking recovery document, with evidence, branches, confirmation, idempotent action, risks, and handoff.",
        }[template]
        draft = service.create_draft(
            ACTOR,
            goal,
            (CONNECTION_ID,),
            resource_ids=(resource.resource_id,),
            template_key=template,
            template_config={"live_context": True, "source": "postgresql+openviking"},
        )
        generate = service.start(
            ACTOR,
            draft.draft_id,
            InvocationKind.GENERATE,
            message=goal,
            if_match=draft.etag,
        )
        generated = await wait(service, generate.invocation_id, ACTOR)
        if generated.status.value != "succeeded":
            raise RuntimeError(
                f"{template} generate failed: {generated.error_code} {generated.error_message}"
            )
        conversation = service.conversation(ACTOR, draft.draft_id)
        stream_types = sorted(
            {
                str(item["type"])
                for item in conversation[0]["events"]
                if isinstance(item, dict) and item.get("type")
            }
        )
        revision_one = await service.freeze(ACTOR, draft.draft_id, generate.invocation_id)
        run_one = await service.run_revision(
            ACTOR,
            revision_one.revision_id,
            f"Use the {template} Skill with live data and selected OpenViking evidence.",
            (CONNECTION_ID,),
            resource_ids=(resource.resource_id,),
        )
        run_one_done = await wait(service, run_one.invocation_id, ACTOR)
        if run_one_done.status.value != "succeeded":
            raise RuntimeError(f"{template} first run failed: {run_one_done.error_message}")
        artifact_one = service.repository.artifacts_for_revision(
            revision_one.revision_id,
            tenant_id=ACTOR.tenant_id,
            workspace_id=ACTOR.workspace_id,
        )[0]
        html_one = service.repository.read_object(artifact_one.uri)
        update = service.start(
            ACTOR,
            draft.draft_id,
            InvocationKind.UPDATE,
            message=f"Update the {template} Skill with a comparable live-data presentation.",
            if_match=service.get_draft(ACTOR, draft.draft_id).etag,
        )
        updated = await wait(service, update.invocation_id, ACTOR)
        if updated.status.value != "succeeded":
            raise RuntimeError(f"{template} update failed: {updated.error_message}")
        revision_two = await service.freeze(ACTOR, draft.draft_id, update.invocation_id)
        run_two = await service.run_revision(
            ACTOR,
            revision_two.revision_id,
            f"Re-run the updated {template} Skill with fresh live data.",
            (CONNECTION_ID,),
            resource_ids=(resource.resource_id,),
        )
        run_two_done = await wait(service, run_two.invocation_id, ACTOR)
        if run_two_done.status.value != "succeeded":
            raise RuntimeError(f"{template} second run failed: {run_two_done.error_message}")
        artifact_two = service.repository.artifacts_for_revision(
            revision_two.revision_id,
            tenant_id=ACTOR.tenant_id,
            workspace_id=ACTOR.workspace_id,
        )[0]
        html_two = service.repository.read_object(artifact_two.uri)
        if artifact_one.artifact_id == artifact_two.artifact_id:
            raise RuntimeError(f"{template} rerun overwrote artifact")
        publication = service.publish(ACTOR, revision_two.revision_id, "personal")
        results["templates"][template] = {
            "status": "PASS",
            "draft_id": redact(draft.draft_id),
            "revision_ids": [redact(revision_one.revision_id), redact(revision_two.revision_id)],
            "artifact_ids": [redact(artifact_one.artifact_id), redact(artifact_two.artifact_id)],
            "zip_sha256": [revision_one.sha256, revision_two.sha256],
            "html": [html_digest(html_one), html_digest(html_two)],
            "stream_event_types": stream_types,
            "publication_id": redact(publication.publication_id),
            "new_revision": revision_one.sha256 != revision_two.sha256,
            "refresh_recovery": service.get_draft(ACTOR, draft.draft_id).current_revision_id
            == revision_two.revision_id,
        }
    results["status"] = "PASS"
    (ROOT / "w4-live-template-lifecycle.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
