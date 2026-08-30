#!/usr/bin/env python3
"""Run the real W4 template lifecycle against live Connection/AutoSkill services.

The runner is deliberately separate from the fixture acceptance command. It
loads the Connection Service secret from the running service process only,
keeps it in memory, and writes redacted lifecycle evidence under /tmp.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    extract_skill_from_state_zip,
    normalize_skill_zip,
    validate_skill_zip,
)

ROOT = Path(os.getenv("W4_EVIDENCE_ROOT", "/tmp/kp-rerun-20260829/w4-live-final"))
_requested_templates = tuple(
    item.strip().casefold()
    for item in os.getenv("W4_TEMPLATES", "semantic,dashboard,sop").split(",")
    if item.strip()
)
if not _requested_templates or any(
    item not in {"semantic", "dashboard", "sop"} for item in _requested_templates
):
    raise RuntimeError("W4_TEMPLATES must contain only semantic, dashboard, or sop")
TEMPLATES = _requested_templates


def redact(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else "[REDACTED]"


def live_secret() -> str:
    configured = os.getenv("W4_CONNECTION_SERVICE_AUTH_SECRET", "").strip()
    if configured:
        return configured
    env_path = Path(
        os.getenv(
            "W4_FROZEN_CONNECTION_ENV",
            "/tmp/kp-rerun-20260829/w0-corrective-runtime/connection.env",
        )
    )
    if not env_path.is_file():
        raise RuntimeError(f"frozen Connection Service env is unavailable: {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if key == "CONNECTION_SERVICE_AUTH_SECRET" and separator:
            return value.strip().strip("'\"")
    raise RuntimeError("frozen Connection Service auth secret is unavailable")


def postgres_readonly_credentials() -> dict[str, str]:
    """Read the existing W0 container credential into memory only."""

    output = subprocess.check_output(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .Config.Env}}{{println .}}{{end}}",
            "kp-w0-corrective-postgres",
        ],
        text=True,
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    password = values.get("AUTOSKILL_READONLY_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "kp-w0-corrective-postgres has no AUTOSKILL_READONLY_PASSWORD"
        )
    return {
        "host": os.getenv("W4_POSTGRES_HOST", "192.168.43.68"),
        "port": os.getenv("W4_POSTGRES_PORT", "38123"),
        "database": os.getenv("W4_POSTGRES_DATABASE", "w0db"),
        "username": os.getenv("W4_POSTGRES_USERNAME", "w0user"),
        "password": password,
        "tls": os.getenv("W4_POSTGRES_TLS", "disable"),
    }


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


def persisted_request_summary(
    repository: KnowledgeWorkspaceRepository, invocation_id: str
) -> dict[str, Any]:
    """Read the last raw summary even when terminal validation later fails."""

    summary: dict[str, Any] = {}
    for item in repository.raw_events(invocation_id):
        raw = item.get("raw")
        if not isinstance(raw, dict):
            continue
        if str(raw.get("type", "")).casefold().replace("-", "_") != "request_summary":
            continue
        data = raw.get("data")
        if isinstance(data, dict):
            summary = dict(data)
    return summary


def raw_tool_evidence(
    repository: KnowledgeWorkspaceRepository, invocation_id: str
) -> dict[str, Any]:
    actions: list[str] = []
    observations: list[dict[str, Any]] = []
    for item in repository.raw_events(invocation_id):
        raw = item.get("raw")
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).casefold().replace("-", "_")
        data = raw.get("data")
        if not isinstance(data, dict):
            continue
        if kind == "action":
            name = str(data.get("name") or data.get("title") or "")
            if name:
                actions.append(name)
        elif kind == "observation":
            observations.append(
                {
                    "name": str(data.get("name") or data.get("title") or ""),
                    "call_id": str(data.get("call_id") or ""),
                    "ok": data.get("ok") is True,
                    "error": str(data.get("error") or "")[:500],
                }
            )
    return {
        "action_counts": {
            name: actions.count(name) for name in sorted(set(actions))
        },
        "actions": actions,
        "observations": observations,
    }


def state_skill_evidence(
    repository: KnowledgeWorkspaceRepository,
    draft_id: str,
    *,
    tenant_id: str,
    workspace_id: str,
    target_skill: str,
) -> dict[str, Any]:
    session = repository.get_session(
        draft_id, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if session is None or not session.state_uri:
        raise RuntimeError("semantic probe did not persist state.zip")
    state_zip = repository.read_object(session.state_uri)
    original_sha256 = hashlib.sha256(state_zip).hexdigest()
    with zipfile.ZipFile(io.BytesIO(state_zip)) as archive:
        paths = tuple(sorted(archive.namelist()))
    skill_zip = extract_skill_from_state_zip(state_zip, target_skill)
    normalized = normalize_skill_zip(skill_zip)
    manifest = validate_skill_zip(normalized)
    prefix = f"skillhub/{target_skill}/"
    skill_paths = tuple(path for path in manifest["paths"] if path.startswith(prefix))
    if f"{prefix}SKILL.md" not in skill_paths:
        raise RuntimeError("state.zip does not contain target Skill SKILL.md")
    if not any("/scripts/" in path for path in skill_paths):
        raise RuntimeError("state.zip target Skill has no scripts")
    if not any("/tests/" in path for path in skill_paths):
        raise RuntimeError("state.zip target Skill has no tests")
    if not any(path.endswith(".html") for path in skill_paths):
        raise RuntimeError("state.zip target Skill has no presentation HTML")
    return {
        "state_sha256": original_sha256,
        "state_entry_count": len(paths),
        "normalized_skill_sha256": manifest["sha256"],
        "skill_name": manifest["skill_name"],
        "skill_paths": skill_paths,
    }


def write_evidence(name: str, payload: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
            # Carry the authoring state with every real command so view,
            # validate, update, and recovery do not depend on the isolated
            # provider's in-memory stateful request registry.
            "KNOWLEDGE_AUTOSKILL_STATE_MODE": os.getenv(
                "KNOWLEDGE_AUTOSKILL_STATE_MODE", "stateless"
            ),
        }
    )
    gateway = ConnectionServiceGateway(ConnectionServiceConfig.from_env())
    autoskill = AutoSkillClient(AutoSkillConfig.from_env())
    probe_only = os.getenv("W4_PROBE_ONLY", "").strip() == "1"
    tenant_id = os.getenv("W4_CONNECTION_TENANT_ID", "w0-postgresql-e2e")
    workspace_id = os.getenv("W4_CONNECTION_WORKSPACE_ID", "w0-postgresql-e2e")
    principal_id = os.getenv("W4_CONNECTION_PRINCIPAL_ID", "w0-postgresql-e2e")
    ACTOR = Actor(
        tenant_id,
        workspace_id,
        principal_id,
    )
    existing_connection_id = os.getenv("W4_CONNECTION_ID", "").strip()
    if existing_connection_id:
        connection = await gateway.get_connection(
            existing_connection_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=principal_id,
        )
        if connection.get("connector_key") != "postgresql":
            raise RuntimeError("W4_CONNECTION_ID is not a PostgreSQL connection")
        if connection.get("status") not in {"ready", "verified", "active"}:
            raise RuntimeError(
                f"W4_CONNECTION_ID is not ready: {connection.get('status')}"
            )
    else:
        credentials = postgres_readonly_credentials()
        connection = await gateway.create_connection(
            {
                "connector_key": "postgresql",
                "display_name": "w4-live-final-" + uuid.uuid4().hex[:12],
                "scope": "personal",
                "config": {
                    "host": credentials["host"],
                    "port": credentials["port"],
                    "database": credentials["database"],
                    "tls": credentials["tls"],
                },
                "credential": {
                    "_auth_type": "custom_credential",
                    "username": credentials["username"],
                    "password": credentials["password"],
                },
            },
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            principal_id=principal_id,
        )
    CONNECTION_ID = str(connection["connection_id"])
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
    validate_job = await gateway.start_job(
        CONNECTION_ID,
        "validate",
        tenant_id=ACTOR.tenant_id,
        workspace_id=ACTOR.workspace_id,
        principal_id=ACTOR.principal_id,
    )
    for _ in range(120):
        if validate_job["status"] in {"succeeded", "failed"}:
            break
        await asyncio.sleep(0.5)
        validate_job = await gateway.get_job(
            validate_job["job_id"],
            tenant_id=ACTOR.tenant_id,
            workspace_id=ACTOR.workspace_id,
            principal_id=ACTOR.principal_id,
        )
    if validate_job["status"] != "succeeded":
        raise RuntimeError(f"Connection validate failed: {validate_job.get('error')}")

    invocation_id = "w4-live-gate-" + uuid.uuid4().hex
    lease_actions = (
        "postgresql.discover_resources",
        "postgresql.execute_read_query",
    )
    lease_response = await gateway._request(
        "POST",
        f"/v1/connections/{CONNECTION_ID}/lease",
        tenant_id=ACTOR.tenant_id,
        workspace_id=ACTOR.workspace_id,
        principal_id=ACTOR.principal_id,
        json={
            "invocationId": invocation_id,
            "audience": gateway.config.audience,
            "allowedActions": list(lease_actions),
            "ttlSeconds": 300,
        },
    )
    lease_payload = lease_response.json()
    lease_claims = lease_payload["claims"]
    lease_token = str(lease_payload["token"])
    auth_token = gateway._token(
        ACTOR.tenant_id,
        ACTOR.workspace_id,
        ACTOR.principal_id,
    )
    runtime_headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-Connection-Lease": lease_token,
        "X-Connection-Invocation-Id": invocation_id,
        "X-Connection-Audience": gateway.config.audience,
    }
    async with httpx.AsyncClient(timeout=60) as control_client:
        discover_response = await control_client.post(
            f"{base_url}/v1/connections/{CONNECTION_ID}/discover",
            headers=runtime_headers,
            json={},
        )
        discover_response.raise_for_status()
        discover_job = discover_response.json()["job"]
        for _ in range(120):
            if discover_job["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.5)
            discover_job = (
                await gateway.get_job(
                    str(discover_job["id"]),
                    tenant_id=ACTOR.tenant_id,
                    workspace_id=ACTOR.workspace_id,
                    principal_id=ACTOR.principal_id,
                )
            )
        if discover_job["status"] != "succeeded":
            raise RuntimeError(f"Connection discover failed: {discover_job.get('error')}")
        query_body = {
            "connectionId": CONNECTION_ID,
            "invocationId": invocation_id,
            "audience": gateway.config.audience,
            "input": {
                "query": (
                    "SELECT order_id, customer_name, amount_cents, status "
                    "FROM public.orders ORDER BY order_id"
                ),
                "maxRows": 10,
            },
        }
        local_query_response = await control_client.post(
            f"{base_url}/v1/runtime/actions/postgresql.execute_read_query",
            headers=runtime_headers,
            json=query_body,
        )
        local_query_response.raise_for_status()
        local_query = local_query_response.json()
        public_query_response = await control_client.post(
            f"{runtime_public_url}/v1/runtime/actions/postgresql.execute_read_query",
            headers=runtime_headers,
            json=query_body,
        )
        public_query_response.raise_for_status()
        public_query = public_query_response.json()
    def result_rows(payload: dict[str, Any]) -> list[Any]:
        result = payload.get("result") or {}
        if not isinstance(result, dict):
            return []
        output = result.get("output")
        if isinstance(output, dict) and isinstance(output.get("rows"), list):
            return output["rows"]
        if isinstance(result.get("rows"), list):
            return result["rows"]
        return []

    local_result = result_rows(local_query)
    public_result = result_rows(public_query)
    if len(local_result) != 3 or len(public_result) != 3:
        raise RuntimeError("live public.orders query did not return exactly three rows")
    audit = await gateway.list_audit(
        tenant_id=ACTOR.tenant_id,
        workspace_id=ACTOR.workspace_id,
        principal_id=ACTOR.principal_id,
    )

    # The resource record is the existing W4 resource contract; its source is
    # the real W1 OpenViking resource, while the opaque URI stays server-side.
    results: dict[str, Any] = {
        "status": "RUNNING",
        "connection": {
            "connector_key": connection.get("connector_key"),
            "status": connection.get("status"),
            "connection_id": redact(CONNECTION_ID),
        },
        "connection_gate": {
            "validate": validate_job["status"],
            "discover": discover_job["status"],
            "lease_allowed_actions": list(lease_claims["allowedActions"]),
            "local_query_status": local_query_response.status_code,
            "public_query_status": public_query_response.status_code,
            "local_row_count": len(local_result),
            "public_row_count": len(public_result),
            "audit_count": len(audit),
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
    write_evidence(
        "connection-gate.json",
        {
            "status": "PASS",
            "connection_id": redact(CONNECTION_ID),
            "catalog_count": len(catalog),
            "validate": validate_job["status"],
            "discover": discover_job["status"],
            "lease_allowed_actions": list(lease_claims["allowedActions"]),
            "local_query_status": local_query_response.status_code,
            "public_query_status": public_query_response.status_code,
            "local_row_count": len(local_result),
            "public_row_count": len(public_result),
            "audit_count": len(audit),
        },
    )
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
            status="verified",
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
            persisted = service.repository.get_invocation(
                generate.invocation_id,
                tenant_id=ACTOR.tenant_id,
                workspace_id=ACTOR.workspace_id,
            )
            write_evidence(
                f"{template}-{'probe-' if probe_only else ''}blocked.json",
                {
                    "status": "BLOCKED",
                    "stage": "generate",
                    "error_code": generated.error_code,
                    "error_message": generated.error_message,
                    "invocation_id": redact(generate.invocation_id),
                    "autoskill_request_id": redact(
                        persisted.autoskill_request_id
                        if persisted is not None
                        else generate.invocation_id
                    ),
                    "event_types": event_types(
                        [
                            event
                            for event in service.conversation(
                                ACTOR, draft.draft_id
                            )[0]["events"]
                            if hasattr(event, "event_type")
                        ]
                    ),
                    "request_summary": safe_summary(
                        persisted_request_summary(
                            service.repository, generate.invocation_id
                        )
                    ),
                    "request_summary_policy_evaluation": (
                        persisted.request_summary.get("policy_evaluation")
                        if persisted is not None
                        and isinstance(persisted.request_summary, dict)
                        else None
                    ),
                },
            )
            raise RuntimeError(
                f"{template} generate failed: {generated.error_code} {generated.error_message}"
            )
        if probe_only:
            persisted = service.repository.get_invocation(
                generate.invocation_id,
                tenant_id=ACTOR.tenant_id,
                workspace_id=ACTOR.workspace_id,
            )
            if persisted is None:
                raise RuntimeError("semantic probe invocation disappeared")
            summary = persisted_request_summary(
                service.repository, generate.invocation_id
            )
            tools = raw_tool_evidence(service.repository, generate.invocation_id)
            created = summary.get("skills_created")
            target_skill = str(summary.get("target_skill") or "")
            policy = summary.get("policy_evaluation")
            state = state_skill_evidence(
                service.repository,
                persisted.draft_id,
                tenant_id=ACTOR.tenant_id,
                workspace_id=ACTOR.workspace_id,
                target_skill=target_skill,
            )
            if not target_skill:
                raise RuntimeError("semantic probe summary has no target_skill")
            if not isinstance(created, list) or target_skill not in created:
                raise RuntimeError("semantic probe target_skill is not skills_created")
            if not any(item == "create_skill" for item in tools["actions"]):
                raise RuntimeError("semantic probe observed no create_skill action")
            if not any(
                item["name"] == "create_skill" and item["ok"]
                for item in tools["observations"]
            ):
                raise RuntimeError("semantic probe create_skill observation was not ok")
            if not any(item == "validate_skill" for item in tools["actions"]):
                raise RuntimeError("semantic probe observed no validate_skill action")
            if not any(
                item["name"] == "validate_skill" and item["ok"]
                for item in tools["observations"]
            ):
                raise RuntimeError(
                    "semantic probe validate_skill observation was not ok"
                )
            if str(summary.get("status", "")).casefold() not in {
                "success",
                "succeeded",
                "ok",
                "completed",
            }:
                raise RuntimeError("semantic probe request_summary is not succeeded")
            if not isinstance(policy, dict) or policy.get("status") != "satisfied":
                raise RuntimeError("semantic probe policy_evaluation is not satisfied")
            write_evidence(
                "semantic-probe.json",
                {
                    "status": "PASS",
                    "target_skill": target_skill,
                    "request_summary": safe_summary(summary),
                    "tools": tools,
                    "state": state,
                },
            )
            print(json.dumps({"status": "PROBE_PASS", "target_skill": target_skill}))
            return 0
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
