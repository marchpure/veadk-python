"""Real Connection Service and AutoSkill gate for the commercial demo."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from typing import Any

from .connection import ConnectionServiceGateway, service_connection_name
from .html_artifact import validate_html_artifact
from .models import InvocationKind, InvocationStatus
from .service import Actor, KnowledgeWorkspaceService


def _actor_kwargs(actor: Actor) -> dict[str, str]:
    return {
        "tenant_id": actor.tenant_id,
        "workspace_id": actor.workspace_id,
        "principal_id": actor.principal_id,
    }


async def _wait_job(
    gateway: ConnectionServiceGateway,
    actor: Actor,
    job: dict[str, Any],
) -> dict[str, Any]:
    for _ in range(120):
        if job["status"] == "succeeded":
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"Connection job failed: {job.get('error')}")
        await asyncio.sleep(0.5)
        job = await gateway.get_job(job["job_id"], **_actor_kwargs(actor))
    raise RuntimeError("Connection job timed out")


async def _wait_invocation(
    service: KnowledgeWorkspaceService,
    actor: Actor,
    invocation_id: str,
) -> Any:
    timeout = min(
        480,
        max(30, int(os.getenv("KNOWLEDGE_DEMO_GATE_TIMEOUT_SECONDS", "480"))),
    )
    max_turns = min(
        30,
        max(1, int(os.getenv("KNOWLEDGE_DEMO_GATE_MAX_TURNS", "30"))),
    )
    for _ in range(timeout * 2):
        invocation = service.repository.get_invocation(
            invocation_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        if invocation is None:
            raise RuntimeError("AutoSkill invocation disappeared")
        if invocation.status in {
            InvocationStatus.SUCCEEDED,
            InvocationStatus.FAILED,
            InvocationStatus.CANCELLED,
        }:
            if invocation.status is not InvocationStatus.SUCCEEDED:
                raise RuntimeError(
                    "AutoSkill invocation failed: "
                    f"{invocation.error_code or invocation.error_message or invocation.status}"
                )
            return invocation
        turn_count = sum(
            1
            for item in service.repository.events_after(invocation_id)
            if item.get("event", {}).get("type") == "turn.started"
        )
        if turn_count >= max_turns:
            await service.cancel(actor, invocation_id)
            raise RuntimeError(
                f"AutoSkill invocation exceeded hard turn limit ({max_turns})"
            )
        await asyncio.sleep(0.5)
    await service.cancel(actor, invocation_id)
    raise RuntimeError("AutoSkill invocation timed out")


def _query_rows(payload: Mapping[str, Any]) -> list[Any]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return []
    output = result.get("output")
    if isinstance(output, Mapping) and isinstance(output.get("rows"), list):
        return output["rows"]
    rows = result.get("rows")
    return rows if isinstance(rows, list) else []


class RealDemoGate:
    def __init__(
        self,
        actor: Actor,
        service: KnowledgeWorkspaceService,
        gateway: ConnectionServiceGateway,
    ) -> None:
        self.actor = actor
        self.service = service
        self.gateway = gateway

    async def __call__(self, scenario: dict[str, Any]) -> Mapping[str, Any]:
        if scenario["scenario_id"] != "anta-sports-daily":
            raise RuntimeError(
                "该 P1 场景尚未完成真实 Connection/AutoSkill lifecycle；"
                "主演示请使用安踏经营日报。"
            )
        connection = await self._postgres_connection()
        connection_id = str(connection["connection_id"])
        validate = await _wait_job(
            self.gateway,
            self.actor,
            await self.gateway.start_job(
                connection_id, "validate", **_actor_kwargs(self.actor)
            ),
        )
        discover = await self._leased_discover_and_query(connection_id)
        actions = discover.get("result", {}).get("actions", [])
        required_actions = {
            str(item)
            for item in scenario["actions"]
            if not str(item).endswith(".discover_resources")
        }
        discovered_actions = {
            str(item.get("id"))
            for item in actions
            if isinstance(item, Mapping) and item.get("executable") is True
        }
        if not required_actions.issubset(discovered_actions):
            raise RuntimeError("PostgreSQL discover did not return executable actions")
        lifecycle = await self._skill_lifecycle(connection_id, scenario)
        return {
            "connection_status": "verified",
            "skill_status": "generated",
            "connection_id": connection_id,
            "last_verified_at": validate.get("finished_at"),
            "skill_types_generated": ["semantic", "dashboard"],
            "evidence": [
                "validate",
                "discover",
                "lease",
                "query",
                "autoskill_create",
                "autoskill_validate",
                "revision",
                "artifact_html",
            ],
            **lifecycle,
        }

    async def _postgres_connection(self) -> dict[str, Any]:
        name = service_connection_name(
            os.getenv(
                "KNOWLEDGE_DEMO_POSTGRES_CONNECTION_NAME",
                "knowledge-demo-anta-postgresql",
            ),
            "postgresql",
        )
        actor = _actor_kwargs(self.actor)
        for item in await self.gateway.list_connections(**actor):
            if (
                item.get("connector_key") == "postgresql"
                and item.get("display_name") == name
            ):
                return item
        return await self.gateway.create_connection(
            {
                "connector_key": "postgresql",
                "display_name": name,
                "scope": "personal",
                "config": {
                    "host": os.getenv("KNOWLEDGE_DEMO_POSTGRES_HOST", ""),
                    "port": os.getenv("KNOWLEDGE_DEMO_POSTGRES_PORT", "25432"),
                    "database": os.getenv("KNOWLEDGE_DEMO_POSTGRES_DATABASE", "demo"),
                    "tls": os.getenv("KNOWLEDGE_DEMO_POSTGRES_TLS", "disable"),
                },
                "credential": {
                    "_auth_type": "custom_credential",
                    "username": os.getenv("KNOWLEDGE_DEMO_POSTGRES_USER", "demo"),
                    "password": os.getenv(
                        "KNOWLEDGE_DEMO_POSTGRES_PASSWORD", "demo-local-only"
                    ),
                },
            },
            **actor,
        )

    async def _leased_discover_and_query(self, connection_id: str) -> dict[str, Any]:
        invocation_id = "demo-query-" + uuid.uuid4().hex
        lease_response = await self.gateway._request(
            "POST",
            f"/v1/connections/{connection_id}/lease",
            **_actor_kwargs(self.actor),
            json={
                "invocationId": invocation_id,
                "audience": self.gateway.config.audience,
                "allowedActions": [
                    "postgresql.discover_resources",
                    "postgresql.execute_read_query",
                ],
                "ttlSeconds": 300,
            },
        )
        lease_payload = lease_response.json()
        lease_token = str(lease_payload["token"])
        lease_jti = str(lease_payload["claims"]["jti"])
        try:
            headers = {
                "X-Connection-Lease": lease_token,
                "X-Connection-Invocation-Id": invocation_id,
                "X-Connection-Audience": self.gateway.config.audience,
            }
            discover_response = await self.gateway._request(
                "POST",
                f"/v1/connections/{connection_id}/discover",
                **_actor_kwargs(self.actor),
                headers=headers,
                json={},
            )
            discovered = discover_response.json().get("job")
            if not isinstance(discovered, Mapping):
                raise RuntimeError(  # noqa: TRY004 - malformed upstream response
                    "PostgreSQL discover returned no job"
                )
            discover = await _wait_job(
                self.gateway,
                self.actor,
                {
                    "job_id": str(discovered["id"]),
                    "status": str(discovered["status"]),
                    **(
                        {"result": discovered["result"]}
                        if "result" in discovered
                        else {}
                    ),
                    **({"error": discovered["error"]} if "error" in discovered else {}),
                },
            )
            response = await self.gateway._request(
                "POST",
                "/v1/runtime/actions/postgresql.execute_read_query",
                **_actor_kwargs(self.actor),
                headers=headers,
                json={
                    "connectionId": connection_id,
                    "invocationId": invocation_id,
                    "audience": self.gateway.config.audience,
                    "input": {
                        "query": (
                            "SELECT s.store_name, o.order_date, "
                            "COUNT(*) AS order_count, "
                            "SUM(o.amount_cents) AS gmv_cents "
                            "FROM stores s JOIN orders o USING (store_id) "
                            "GROUP BY s.store_name, o.order_date "
                            "ORDER BY s.store_name"
                        ),
                        "maxRows": 20,
                    },
                },
            )
            if not _query_rows(response.json()):
                raise RuntimeError("PostgreSQL live query returned no rows")
            audit = await self.gateway.list_audit(**_actor_kwargs(self.actor))
            if not any(
                item.get("invocationId") == invocation_id and item.get("ok") is True
                for item in audit
            ):
                raise RuntimeError(
                    "PostgreSQL live query has no successful audit record"
                )
            return discover
        finally:
            await self.gateway._request(
                "POST",
                f"/v1/leases/{lease_jti}/revoke",
                **_actor_kwargs(self.actor),
            )

    async def _skill_lifecycle(
        self, connection_id: str, scenario: Mapping[str, Any]
    ) -> dict[str, Any]:
        request_key = (
            f"knowledge-demo-{os.getenv('KNOWLEDGE_DEMO_SEED_VERSION', 'w5-v1')}-"
            f"{scenario['scenario_id']}"
        )
        goal = (
            f"{scenario['goal']} Create exactly one Skill named "
            "`store-order-dashboard`; do not create or update any other Skill. "
            "First call mcp__knowledge-connection-1__execute_action with "
            "actionId=postgresql.execute_read_query against the real stores and "
            "orders tables and use those returned rows. Implement only one "
            "self-contained static HTML dashboard artifact. Keep HTML/CSS in an "
            "independent template file or render it with string.Template. Never put "
            "a complete HTML document containing CSS or JavaScript braces in a "
            "Python f-string. Before validate_skill, run py_compile on every Python "
            "file and run pytest once; fix failures, then call validate_skill exactly "
            "for store-order-dashboard, and only after it succeeds call final_answer. "
            "Do not add features, alternate Skills, or visual polish."
        )
        draft = self.service.create_draft(
            self.actor,
            goal,
            (connection_id,),
            template_key="dashboard",
            template_config={
                "mode": "interactive_dashboard",
                "semantic_layer": True,
                "source": "knowledge-commercial-demo",
            },
            idempotency_key=request_key,
            request_digest=goal,
        )
        revisions = self.service.list_revisions(self.actor, draft.draft_id)
        if revisions:
            revision = revisions[-1]
        else:
            generated = self.service.start(
                self.actor,
                draft.draft_id,
                InvocationKind.GENERATE,
                message=goal,
                if_match=self.service.get_draft(self.actor, draft.draft_id).etag,
                idempotency_key=request_key + "-generate",
                request_digest=goal,
            )
            await _wait_invocation(self.service, self.actor, generated.invocation_id)
            revision = await self.service.freeze(
                self.actor,
                draft.draft_id,
                generated.invocation_id,
                idempotency_key=request_key + "-freeze",
                request_digest=generated.invocation_id,
            )
        artifacts = [
            item
            for item in self.service.repository.artifacts_for_revision(
                revision.revision_id,
                tenant_id=self.actor.tenant_id,
                workspace_id=self.actor.workspace_id,
            )
            if item.media_type == "text/html"
        ]
        if not artifacts:
            run = await self.service.run_revision(
                self.actor,
                revision.revision_id,
                (
                    "Call postgresql.execute_read_query now for the stores and orders "
                    "tables. Generate the final immutable HTML business dashboard from "
                    "those live rows."
                ),
                (connection_id,),
                idempotency_key=request_key + "-run",
                request_digest=revision.revision_id,
            )
            await _wait_invocation(self.service, self.actor, run.invocation_id)
            artifacts = [
                item
                for item in self.service.repository.artifacts_for_revision(
                    revision.revision_id,
                    tenant_id=self.actor.tenant_id,
                    workspace_id=self.actor.workspace_id,
                )
                if item.invocation_id == run.invocation_id
                and item.media_type == "text/html"
            ]
        if not artifacts:
            raise RuntimeError("AutoSkill run produced no immutable HTML artifact")
        for artifact in artifacts:
            validate_html_artifact(self.service.repository.read_object(artifact.uri))
        publications = [
            item
            for item in self.service.list_publications(self.actor)
            if item.revision_id == revision.revision_id
        ]
        publication = (
            publications[-1]
            if publications
            else self.service.publish(
                self.actor,
                revision.revision_id,
                "personal",
                idempotency_key=request_key + "-publish",
                request_digest=revision.revision_id,
            )
        )
        sessions = self.service.list_sessions(self.actor, draft.draft_id)
        return {
            "draft_id": draft.draft_id,
            "authoring_session_id": sessions[0].authoring_session_id,
            "publication_id": publication.publication_id,
            "revision_ids": [revision.revision_id],
            "artifact_ids": [item.artifact_id for item in artifacts],
        }


def build_real_demo_gate(
    actor: Actor,
    service: KnowledgeWorkspaceService,
    gateway: ConnectionServiceGateway,
) -> RealDemoGate:
    return RealDemoGate(actor, service, gateway)
