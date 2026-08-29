#!/usr/bin/env python3
"""Real PostgreSQL -> AutoSkill -> immutable publication smoke.

This harness intentionally has no fake client fallback. It composes the real
KnowledgeWorkspaceService with its SQLite repository while keeping AutoSkill,
Connection Service, PostgreSQL, and the MCP transport out of process.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.server.knowledge_workspace.autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
)
from frontend.server.knowledge_workspace.connection import (
    ConnectionServiceConfig,
    ConnectionServiceGateway,
    EphemeralConnectionContext,
)
from frontend.server.knowledge_workspace.models import (
    Invocation,
    InvocationKind,
    InvocationStatus,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import Actor, KnowledgeWorkspaceService

ACTOR = Actor("w0-postgresql-e2e", "w0-postgresql-e2e", "w0-postgresql-e2e")
MODEL_ID = "W0-Verified-Model"
EXPECTED_CUSTOMERS = {"Ada", "Lin", "Sam"}
TERMINAL = {
    InvocationStatus.SUCCEEDED,
    InvocationStatus.FAILED,
    InvocationStatus.CANCELLED,
}


def redacted(value: str) -> str:
    return (
        f"{value[:4]}...[REDACTED]...{value[-4:]}" if len(value) > 10 else "[REDACTED]"
    )


class TunnelHeaderConnectionGateway(ConnectionServiceGateway):
    """Add the localtunnel non-browser header to this smoke's MCP transport."""

    async def prepare_autoskill(
        self,
        *,
        context: EphemeralConnectionContext,
        autoskill: Any,
        agent_id: str,
        session_id: str,
        invocation_id: str,
    ) -> None:
        runtime = json.loads(context.runtime_ref)
        servers: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(runtime.get("leases") or []):
            query = urlencode(
                {
                    "connectionId": str(item["connection_id"]),
                    "invocationId": invocation_id,
                    "audience": self.config.audience,
                }
            )
            servers[f"knowledge-connection-{index + 1}"] = {
                "transport": "http",
                "url": f"{self.config.runtime_public_url}/v1/runtime/mcp/sse?{query}",
                "headers": {
                    "X-Connection-Lease": str(item["token"]),
                    "Bypass-Tunnel-Reminder": "true",
                },
            }
        state = await autoskill.download_optional_state(
            agent_id=agent_id, session_id=session_id
        )
        configured = self._state_with_mcp(
            state, servers, runtime.get("resources") or []
        )
        await autoskill.upload(
            agent_id=agent_id,
            session_id=session_id,
            file_type="state",
            file_name="state.zip",
            content=configured,
        )


async def wait_for_job(
    gateway: ConnectionServiceGateway, job: dict[str, Any]
) -> dict[str, Any]:
    actor = ACTOR.__dict__
    for _ in range(120):
        if job["status"] == "succeeded":
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"Connection job failed: {job.get('error')}")
        await asyncio.sleep(0.5)
        job = await gateway.get_job(job["job_id"], **actor)
    raise RuntimeError("Connection job timed out")


async def wait_for_invocation(
    service: KnowledgeWorkspaceService, invocation: Invocation, timeout: float = 1_800
) -> Invocation:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        current = service.repository.get_invocation(
            invocation.invocation_id,
            tenant_id=ACTOR.tenant_id,
            workspace_id=ACTOR.workspace_id,
        )
        if current is not None and current.status in TERMINAL:
            if current.status is not InvocationStatus.SUCCEEDED:
                raise RuntimeError(
                    f"{current.kind.value} failed: {current.error_code}: {current.error_message}"
                )
            return current
        await asyncio.sleep(1)
    raise RuntimeError(f"invocation {redacted(invocation.invocation_id)} timed out")


def raw_event_types(
    service: KnowledgeWorkspaceService, invocation_id: str
) -> list[str]:
    return [
        str(item["raw"].get("type") or "unknown").casefold().replace("-", "_")
        for item in service.repository.raw_events(invocation_id)
    ]


def event_text(service: KnowledgeWorkspaceService, invocation_id: str) -> str:
    return json.dumps(
        [item["raw"] for item in service.repository.raw_events(invocation_id)],
        ensure_ascii=False,
        sort_keys=True,
    )


def invocation_evidence(
    service: KnowledgeWorkspaceService, invocation: Invocation
) -> dict[str, Any]:
    events = raw_event_types(service, invocation.invocation_id)
    text = event_text(service, invocation.invocation_id)
    summary = invocation.request_summary or {}
    return {
        "kind": invocation.kind.value,
        "status": invocation.status.value,
        "event_types": events,
        "planning": "planning" in events,
        "action": "action" in events,
        "observation": "observation" in events,
        "assistant_delta": any(
            item in events for item in ("assistant_delta", "answer_delta")
        ),
        "final_answer": "final_answer" in events,
        "state_update": "state_update" in events,
        "request_summary": "request_summary" in events,
        "done": "done" in events,
        "validate_skill_observed": "validate_skill" in text,
        "policy_satisfied": isinstance(summary.get("policy_evaluation"), Mapping)
        and summary["policy_evaluation"].get("satisfied") is True,
        "connection_execute_successes": (summary.get("policy_evaluation") or {}).get(
            "successful_call_count"
        ),
    }


async def execute_action(
    gateway: ConnectionServiceGateway,
    context: EphemeralConnectionContext,
    connection_id: str,
    invocation_id: str,
    action: str,
    input_value: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = json.loads(context.runtime_ref)
    token = str(runtime["leases"][0]["token"])
    response = await gateway._request(
        "POST",
        f"/v1/runtime/actions/postgresql.{action}",
        json={
            "connectionId": connection_id,
            "invocationId": invocation_id,
            "audience": gateway.config.audience,
            "input": dict(input_value),
        },
        headers={"X-Connection-Lease": token},
        **ACTOR.__dict__,
    )
    payload = response.json()
    if payload.get("ok") is not True or payload.get("auditPersisted") is not True:
        raise RuntimeError(f"postgresql.{action} did not execute successfully")
    return dict(payload.get("result", {}).get("output", {}))


async def main(evidence_path: Path, state_dir: Path) -> int:
    result: dict[str, Any] = {"status": "RUNNING", "requests": []}
    state_dir.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    autoskill = AutoSkillClient(AutoSkillConfig.from_env())
    gateway = TunnelHeaderConnectionGateway(ConnectionServiceConfig.from_env())
    repository = KnowledgeWorkspaceRepository(
        state_dir / "workspace.sqlite3", state_dir / "objects"
    )
    service = KnowledgeWorkspaceService(repository, autoskill, gateway)
    actor = ACTOR.__dict__
    try:
        health, models = await asyncio.gather(autoskill.health(), autoskill.models())
        if health.get("state_mode") != "stateful":
            raise RuntimeError("AutoSkill is not stateful")
        if MODEL_ID not in {item.get("model_id") for item in models.get("models", [])}:
            raise RuntimeError("verified AutoSkill model is unavailable")
        result["runtime"] = {
            "autoskill_state_mode": health.get("state_mode"),
            "autoskill_model": MODEL_ID,
            "autoskill_ipv6": True,
            "autoskill_localhost": True,
            "autoskill_ipv4": False,
            "connection_public_https": gateway.config.runtime_public_url,
        }

        connection = await gateway.create_connection(
            {
                "connector_key": "postgresql",
                "display_name": f"w0-postgresql-{uuid.uuid4().hex[:8]}",
                "scope": "personal",
                "config": {
                    "host": os.environ["W0_POSTGRES_HOST"],
                    "port": "38103",
                    "database": "w0db",
                    "tls": "disable",
                },
                "credential": {
                    "_auth_type": "custom_credential",
                    "username": "w0user",
                    "password": os.environ["W0_POSTGRES_PASSWORD"],
                },
            },
            **actor,
        )
        connection_id = connection["connection_id"]
        validate = await wait_for_job(
            gateway, await gateway.start_job(connection_id, "validate", **actor)
        )
        discovery_id = f"w0-discovery-{uuid.uuid4()}"
        discovery_lease_response = await gateway._request(
            "POST",
            f"/v1/connections/{connection_id}/lease",
            json={
                "invocationId": discovery_id,
                "audience": gateway.config.audience,
                "allowedActions": ["postgresql.discover_resources"],
                "ttlSeconds": 300,
            },
            **actor,
        )
        discovery_lease = discovery_lease_response.json()
        try:
            discovery_response = await gateway._request(
                "POST",
                f"/v1/connections/{connection_id}/discover",
                json={},
                headers={
                    "X-Connection-Lease": str(discovery_lease["token"]),
                    "X-Connection-Invocation-Id": discovery_id,
                    "X-Connection-Audience": gateway.config.audience,
                },
                **actor,
            )
            discovery_job = discovery_response.json()["job"]
            discover = await wait_for_job(
                gateway,
                {
                    "job_id": str(discovery_job["id"]),
                    "status": str(discovery_job["status"]),
                    **(
                        {"result": discovery_job["result"]}
                        if "result" in discovery_job
                        else {}
                    ),
                    **(
                        {"error": discovery_job["error"]}
                        if "error" in discovery_job
                        else {}
                    ),
                },
            )
        finally:
            await gateway._request(
                "POST",
                f"/v1/leases/{discovery_lease['claims']['jti']}/revoke",
                **actor,
            )
        preflight_id = f"w0-preflight-{uuid.uuid4()}"
        context = await gateway.issue(
            **actor,
            invocation_id=preflight_id,
            connection_ids=[connection_id],
            allowed_actions=["postgresql.execute_read_query"],
            ttl_seconds=300,
        )
        try:
            schemas = await execute_action(
                gateway,
                context,
                connection_id,
                preflight_id,
                "list_schemas",
                {"database": "w0db"},
            )
            tables = await execute_action(
                gateway,
                context,
                connection_id,
                preflight_id,
                "list_tables",
                {"database": "w0db", "schema": "public"},
            )
            preview = await execute_action(
                gateway,
                context,
                connection_id,
                preflight_id,
                "preview_table",
                {
                    "database": "w0db",
                    "schema": "public",
                    "table": "orders",
                    "pageSize": 10,
                },
            )
            query = await execute_action(
                gateway,
                context,
                connection_id,
                preflight_id,
                "execute_read_query",
                {
                    "query": "SELECT order_id, customer_name, amount_cents, status FROM public.orders ORDER BY order_id",
                    "maxRows": 10,
                },
            )
        finally:
            await gateway.revoke(context.lease_id)
        rows = query.get("rows") or preview.get("rows") or []
        if {str(row.get("customer_name")) for row in rows} != EXPECTED_CUSTOMERS:
            raise RuntimeError(
                "PostgreSQL preflight did not return the three business rows"
            )
        result["connection"] = {
            "connection_id": redacted(connection_id),
            "validate": validate["status"],
            "discover": discover["status"],
            "public_schema_observed": "public" in json.dumps(schemas),
            "orders_table_observed": "orders" in json.dumps(tables),
            "business_rows": len(rows),
            "customers": sorted(EXPECTED_CUSTOMERS),
            "preflight_lease_revoked": True,
        }

        skill_name = f"postgresql-orders-{uuid.uuid4().hex[:8]}"
        tool = "mcp__knowledge-connection-1__execute_action"
        query_instruction = (
            f"Call `{tool}` with actionId `postgresql.execute_read_query` and input "
            "containing query `SELECT order_id, customer_name, amount_cents, status FROM "
            "public.orders ORDER BY order_id` and maxRows 10."
        )
        draft = service.create_draft(
            ACTOR,
            (
                f"Create a reusable Skill named `{skill_name}`. {query_instruction} "
                f"Your first data operation must be a successful direct call to `{tool}`. "
                "The Skill must repeat that live query on every use and write a self-contained "
                "HTML table to output_files/postgresql-orders.html containing all returned rows. "
                "Never embed, simulate, mock, sample, cache, or fall back to order rows. Do not "
                "write a wrapper that pretends to invoke MCP. Fail if the MCP tool is unavailable. "
                "Include no scripts, forms, iframes, external URLs, or network assets."
            ),
            [connection_id],
        )
        generated = await wait_for_invocation(
            service,
            service.start(
                ACTOR, draft.draft_id, InvocationKind.GENERATE, model=MODEL_ID
            ),
        )
        result["requests"].append(invocation_evidence(service, generated))
        revision_v1 = await service.freeze(
            ACTOR, draft.draft_id, generated.invocation_id
        )
        v1_bytes = repository.read_object(revision_v1.zip_uri)
        if hashlib.sha256(v1_bytes).hexdigest() != revision_v1.sha256:
            raise RuntimeError("revision v1 ZIP digest mismatch")

        run_v1 = await wait_for_invocation(
            service,
            await service.run_revision(
                ACTOR,
                revision_v1.revision_id,
                f"{query_instruction} Render the live orders table now.",
                [connection_id],
            ),
        )
        result["requests"].append(invocation_evidence(service, run_v1))

        updated = await wait_for_invocation(
            service,
            service.start(
                ACTOR,
                draft.draft_id,
                InvocationKind.UPDATE,
                message=(
                    f"Update `{skill_name}`. {query_instruction} Preserve the table and add a "
                    "visible `Source: PostgreSQL Connection Service` footer. Validate the Skill."
                ),
                model=MODEL_ID,
            ),
        )
        result["requests"].append(invocation_evidence(service, updated))
        revision_v2 = await service.freeze(ACTOR, draft.draft_id, updated.invocation_id)
        if revision_v1.sha256 == revision_v2.sha256:
            raise RuntimeError("update_skill did not create a distinct revision")
        if repository.read_object(revision_v1.zip_uri) != v1_bytes:
            raise RuntimeError("revision v1 changed after revision v2 was frozen")

        run_v2 = await wait_for_invocation(
            service,
            await service.run_revision(
                ACTOR,
                revision_v2.revision_id,
                f"{query_instruction} Render the revised live orders table and source footer.",
                [connection_id],
            ),
        )
        result["requests"].append(invocation_evidence(service, run_v2))
        publication = service.publish(ACTOR, revision_v2.revision_id, "personal")
        creator_session = repository.get_session(
            draft.draft_id, tenant_id=ACTOR.tenant_id, workspace_id=ACTOR.workspace_id
        )
        consumer = await wait_for_invocation(
            service,
            await service.invoke_publication(
                ACTOR,
                publication.publication_id,
                f"{query_instruction} Render the published Skill from fresh live data.",
                [connection_id],
            ),
        )
        result["requests"].append(invocation_evidence(service, consumer))
        if creator_session is None:
            raise RuntimeError("authoring session disappeared")
        if consumer.autoskill_agent_id == creator_session.autoskill_agent_id:
            raise RuntimeError("publication reused the creator Agent")
        if consumer.autoskill_session_id == creator_session.autoskill_session_id:
            raise RuntimeError("publication reused the creator session")

        audits = await gateway.list_audit(**actor)
        request_ids = {
            item.autoskill_request_id
            for item in (generated, run_v1, updated, run_v2, consumer)
        }
        matched_audits = [
            item for item in audits if item.get("invocationId") in request_ids
        ]
        if (
            len({item.get("invocationId") for item in matched_audits if item.get("ok")})
            < 5
        ):
            raise RuntimeError(
                "not every workspace invocation has a successful Connection audit"
            )
        consumer_artifacts = [
            item
            for item in repository.artifacts_for_revision(
                revision_v2.revision_id,
                tenant_id=ACTOR.tenant_id,
                workspace_id=ACTOR.workspace_id,
            )
            if item.invocation_id == consumer.invocation_id
        ]
        if not consumer_artifacts:
            raise RuntimeError("fresh publication consumer produced no artifact")
        artifact_text = repository.read_object(consumer_artifacts[-1].uri).decode(
            "utf-8", errors="replace"
        )
        if not EXPECTED_CUSTOMERS.issubset(
            {name for name in EXPECTED_CUSTOMERS if name in artifact_text}
        ):
            raise RuntimeError(
                "published consumer artifact omitted PostgreSQL business rows"
            )

        result.update(
            {
                "status": "PASS",
                "revisions": {
                    "v1": {"number": revision_v1.number, "sha256": revision_v1.sha256},
                    "v2": {"number": revision_v2.number, "sha256": revision_v2.sha256},
                    "hashes_differ": revision_v1.sha256 != revision_v2.sha256,
                    "v1_immutable": True,
                },
                "publication": {
                    "status": publication.status,
                    "target_space": publication.target_space,
                    "consumer_reauthorization_required": publication.policy_snapshot.get(
                        "consumer_reauthorization_required"
                    ),
                    "fresh_agent": True,
                    "fresh_session": True,
                    "consumer_artifact_sha256": consumer_artifacts[-1].sha256,
                    "consumer_business_rows_verified": True,
                },
                "connection_audit": {
                    "successful_workspace_invocations": len(
                        {
                            item.get("invocationId")
                            for item in matched_audits
                            if item.get("ok")
                        }
                    ),
                    "redacted": True,
                },
            }
        )
    except Exception as error:  # noqa: BLE001 - persist terminal evidence for every failure
        result.update(
            {
                "status": "FAIL",
                "reason": type(error).__name__,
                "message": str(error)[:500],
            }
        )
        return_code = 2
    else:
        return_code = 0
    evidence_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.evidence, args.state_dir)))
