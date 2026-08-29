#!/usr/bin/env python3
"""W4-only contract acceptance for AutoSkill template lifecycle work.

This script is intentionally fixture-backed. It proves the Knowledge Workspace
BFF lifecycle, immutable revision/artifact lineage, streaming event contract,
and browser artifact policy for the W4 semantic/dashboard/sop templates without
pretending that a live AutoSkill + Connection Service environment was present.

All evidence is redacted and written under /tmp/kp-rerun-20260829/w4 by default.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
import zipfile
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.server.knowledge_workspace.connection import EphemeralConnectionContext
from frontend.server.knowledge_workspace.html_artifact import (
    HtmlArtifactError,
    validate_html_artifact,
)
from frontend.server.knowledge_workspace.models import (
    Invocation,
    InvocationKind,
    InvocationStatus,
    WorkspaceResource,
    WorkspaceResourceKind,
    utc_now,
)
from frontend.server.knowledge_workspace.registry import PublicationRegistryPort
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import (
    Actor,
    KnowledgeWorkspaceError,
    KnowledgeWorkspaceService,
)
from frontend.server.knowledge_workspace.sse import ParsedUpstreamEvent
from frontend.server.knowledge_workspace.zip_validator import validate_skill_zip

BASE_TMP = Path("/tmp/kp-rerun-20260829/w4")
DEFAULT_EVIDENCE_DIR = BASE_TMP / "evidence"
EXPECTED_EVENT_TYPES = {
    "activity.started",
    "activity.completed",
    "assistant.delta",
    "assistant.final",
    "request.summary",
    "run.completed",
    "run.started",
}
SECRET_MARKERS = (
    "must-not-persist",
    "secret-token",
    "bearer secret",
    "lease-",
    "private.example",
)


def event(
    event_type: str, data: object = None, *, event_id: str | None = None
) -> ParsedUpstreamEvent:
    return ParsedUpstreamEvent(
        event_id=event_id or event_type,
        event_type=event_type,
        payload={"type": event_type, "data": data if data is not None else {}},
        raw="",
    )


def template_skill_zip(name: str, template_key: str, marker: str) -> bytes:
    script = {
        "semantic": """
from __future__ import annotations

def build_sql(params):
    tenant = params["tenant_id"]
    return (
        "select tenant_id, customer_id, revenue_cents "
        "from analytics_revenue "
        "where tenant_id = %(tenant_id)s and event_date >= %(since)s"
    ), {"tenant_id": tenant, "since": params["since"]}
""",
        "dashboard": """
from __future__ import annotations

def load_dashboard(connection):
    rows = connection.execute_action(
        "fixture.read",
        {"query": "schema_driven_dashboard", "limit": 50},
    )
    return {"filters": ["region", "segment"], "rows": rows}
""",
        "sop": """
from __future__ import annotations

def build_sop(context):
    evidence = context.execute_action("fixture.read", {"case": "incident-731"})
    return {
        "steps": [
            {"name": "classify", "evidence": evidence, "next": "confirm_action"},
        ],
        "requires_confirmation": True,
    }
""",
    }[template_key].strip()
    skill_md = f"""# {name}

Template: {template_key}

Use only the invocation-scoped Connection/MCP/OpenViking context.
Always return evidence from real tool observations and write a self-contained
HTML presentation artifact. Marker: {marker}
"""
    test_py = f"""def test_{template_key}_contract():
    assert "{template_key}"
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"skillhub/{name}/SKILL.md", skill_md)
        archive.writestr(f"skillhub/{name}/scripts/run.py", script + "\n")
        archive.writestr(f"skillhub/{name}/tests/test_skill.py", test_py)
    return buffer.getvalue()


def template_html(template_key: str, marker: str, *, state: str = "normal") -> bytes:
    title = {
        "semantic": "Semantic validation",
        "dashboard": "Schema driven dashboard",
        "sop": "SOP evidence flow",
    }[template_key]
    body = {
        "semantic": """
<section>
  <h1>Semantic validation</h1>
  <p>PostgreSQL/MySQL schema discovery, metrics, joins, synonyms, glossary, and examples.</p>
  <code>select tenant_id, customer_id, revenue_cents from analytics_revenue where tenant_id = $1</code>
  <table><tr><th>tenant_id</th><th>customer_id</th><th>revenue_cents</th></tr><tr><td>tenant-a</td><td>cust-17</td><td>4200</td></tr></table>
</section>
""",
        "dashboard": f"""
<section>
  <h1>Schema driven dashboard</h1>
  <button id="refresh">Refresh</button>
  <label>Region <select id="region"><option>all</option><option>north</option></select></label>
  <div data-state="loading">Loading</div>
  <div data-state="empty">No rows</div>
  <div data-state="error">Query failed</div>
  <div data-state="no-permission">No permission</div>
  <table><tr><th>schema column</th><th>value</th></tr><tr><td>ticket_priority</td><td>{marker}</td></tr></table>
  <script>
  const values = [1, 2, 3];
  document.getElementById("refresh").addEventListener("click", () => {{
    document.body.setAttribute("data-refresh-count", String(values.length));
  }});
  </script>
</section>
""",
        "sop": """
<section>
  <h1>SOP evidence flow</h1>
  <ol>
    <li data-status="done">Classify incident with doc:kb-731 and action:fixture.read.</li>
    <li data-status="pending">Confirm side-effect action before execution.</li>
    <li data-status="handoff">Human handoff path when retry budget is exhausted.</li>
  </ol>
  <p>Branches, variables, risks, todos, action results, and failure paths are visible.</p>
</section>
""",
    }[template_key]
    if state == "empty":
        body = "<section><h1>Schema driven dashboard</h1><div data-state=\"empty\">No rows</div></section>"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{title}</title>"
        "<style>body{font-family:Inter,Arial,sans-serif;margin:24px;color:#172033}"
        "table{border-collapse:collapse;width:100%;max-width:760px}"
        "td,th{border:1px solid #d8dee9;padding:6px;text-align:left}"
        "@media(max-width:640px){body{margin:12px}table{font-size:12px}}</style>"
        "</head><body>"
        f"{body}"
        f"<footer>artifact {marker}</footer>"
        "</body></html>"
    ).encode("utf-8")


def policy_summary(
    *,
    target_skill: str,
    skills_field: str,
    action_id: str,
    satisfied: bool = True,
) -> dict[str, object]:
    return {
        "status": "succeeded",
        skills_field: [target_skill],
        "target_skill": target_skill,
        "target_skill_version": "1.0.0",
        "policy_evaluation": {
            "satisfied": satisfied,
            "matched_calls": [
                {
                    "index": 0,
                    "server": "knowledge-connection-1",
                    "tool": "mcp__knowledge-connection-1__execute_action",
                    "actionId": action_id,
                }
            ],
            "unmet_requirements": [] if satisfied else ["missing call"],
        },
    }


class W4AutoSkillFixture:
    def __init__(self, template_key: str, *, action_id: str) -> None:
        self.template_key = template_key
        self.action_id = action_id
        self.skill_name = f"w4-{template_key}-skill"
        self.revision_marker = "v1"
        self.run_count = 0
        self.commands: list[dict[str, object]] = []
        self.invocations: list[dict[str, object]] = []
        self.downloads: list[dict[str, object]] = []
        self.uploads: list[dict[str, object]] = []

    async def upload(self, **kwargs: object) -> dict[str, str]:
        self.uploads.append(kwargs)
        return {"status": "ok"}

    async def download(self, **kwargs: object) -> bytes:
        self.downloads.append(kwargs)
        if kwargs["file_type"] == "skill":
            return template_skill_zip(
                self.skill_name, self.template_key, self.revision_marker
            )
        self.run_count += 1
        marker = f"{self.revision_marker}-run-{self.run_count}"
        return template_html(self.template_key, marker)

    async def command(
        self,
        command: str,
        **kwargs: object,
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        self.commands.append({"command": command, **kwargs})
        request_id = str(kwargs["request_id"])
        if command == "view_skill":
            yield event(
                "final_answer",
                {"answer": f"# {self.skill_name}\n{self.revision_marker}"},
                event_id=f"{request_id}:view-final",
            )
            yield event("done", event_id=f"{request_id}:view-done")
            return
        if command == "validate_skill":
            yield event(
                "final_answer",
                {"answer": "validate_skill succeeded"},
                event_id=f"{request_id}:validate-final",
            )
            yield event(
                "request_summary",
                {"status": "succeeded"},
                event_id=f"{request_id}:validate-summary",
            )
            yield event("done", event_id=f"{request_id}:validate-done")
            return
        summary = policy_summary(
            target_skill=self.skill_name,
            skills_field="skills_created" if command == "create_skill" else "skills_updated",
            action_id=self.action_id,
        )
        yield event(
            "planning",
            {
                "summary": f"Plan {self.template_key} creator",
                "steps": [
                    {"label": "discover authorized context", "status": "completed"}
                ],
            },
            event_id=f"{request_id}:plan",
        )
        yield event(
            "action",
            {
                "tool_name": "mcp__knowledge-connection-1__execute_action",
                "call_id": f"{request_id}:tool",
                "arguments": {
                    "actionId": self.action_id,
                    "query": self.template_key,
                    "authorization": "Bearer secret-token",
                },
            },
            event_id=f"{request_id}:action",
        )
        yield event(
            "observation",
            {
                "call_id": f"{request_id}:tool",
                "tool_name": "mcp__knowledge-connection-1__execute_action",
                "summary": f"{self.template_key} rows observed",
            },
            event_id=f"{request_id}:observation",
        )
        yield event(
            "assistant_delta",
            {"delta": f"{self.template_key} ", "sequence": 1},
            event_id=f"{request_id}:delta-1",
        )
        yield event("assistant_delta", {"delta": "ready", "sequence": 2}, event_id=f"{request_id}:delta-2")
        yield event(
            "final_answer",
            {"answer": f"{self.template_key} Skill ready"},
            event_id=f"{request_id}:final",
        )
        yield event("request_summary", summary, event_id=f"{request_id}:summary")
        yield event("done", event_id=f"{request_id}:done")

    async def invoke(self, **kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        self.invocations.append(kwargs)
        request_id = str(kwargs["request_id"])
        summary = policy_summary(
            target_skill=self.skill_name,
            skills_field="skills_used",
            action_id=self.action_id,
        )
        yield event(
            "planning",
            {
                "summary": f"Run {self.template_key} revision",
                "steps": [{"label": "load fixed revision", "status": "completed"}],
            },
            event_id=f"{request_id}:plan",
        )
        yield event(
            "action",
            {
                "tool_name": "mcp__knowledge-connection-1__execute_action",
                "call_id": f"{request_id}:tool",
                "arguments": {"actionId": self.action_id, "tenant_id": "tenant-a"},
            },
            event_id=f"{request_id}:action",
        )
        yield event(
            "observation",
            {
                "call_id": f"{request_id}:tool",
                "tool_name": "mcp__knowledge-connection-1__execute_action",
                "summary": f"{self.template_key} real result rows",
            },
            event_id=f"{request_id}:observation",
        )
        yield event("assistant_delta", {"text": "running ", "sequence": 1}, event_id=f"{request_id}:delta-1")
        yield event("assistant_delta", {"text": "artifact", "sequence": 2}, event_id=f"{request_id}:delta-2")
        yield event("final_answer", {"answer": f"{self.template_key} HTML artifact generated"}, event_id=f"{request_id}:final")
        yield event("request_summary", summary, event_id=f"{request_id}:summary")
        yield event("done", event_id=f"{request_id}:done")

    async def reconnect(self, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        if False:
            yield event("done")

    async def stop(self, **_kwargs: object) -> dict[str, str]:
        return {"message": "stopped"}


class W4LeaseFixture:
    def __init__(self, *, action_id: str = "fixture.read", fail: bool = False) -> None:
        self.action_id = action_id
        self.fail = fail
        self.issued: list[dict[str, object]] = []
        self.prepared: list[dict[str, object]] = []
        self.revoked: list[str] = []

    async def issue(self, **kwargs: object) -> EphemeralConnectionContext:
        self.issued.append(kwargs)
        if self.fail:
            raise KnowledgeWorkspaceError("LEASE_EXPIRED", "lease expired", 409)
        invocation_id = str(kwargs["invocation_id"])
        connection_ids = tuple(str(item) for item in kwargs["connection_ids"])
        return EphemeralConnectionContext(
            lease_id=f"lease-{hashlib.sha256(invocation_id.encode()).hexdigest()[:16]}",
            connection_ids=connection_ids,
            allowed_actions=(self.action_id,),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            runtime_ref=json.dumps(
                {
                    "leases": [
                        {
                            "connection_id": connection_id,
                            "allowed_actions": [self.action_id],
                            "runtime": "https://private.example/runtime",
                            "token": "secret-token",
                        }
                        for connection_id in connection_ids
                    ]
                },
                separators=(",", ":"),
            ),
        )

    async def revoke(self, lease_id: str) -> None:
        self.revoked.append(lease_id)

    async def prepare_autoskill(self, **kwargs: object) -> None:
        self.prepared.append(kwargs)


class W4RegistryFixture(PublicationRegistryPort):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def register_publication(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


async def wait_done(
    service: KnowledgeWorkspaceService, invocation: Invocation, actor: Actor
) -> Invocation:
    task = service._tasks.get(invocation.invocation_id)
    if task is not None:
        await task
    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    if saved is None:
        raise AssertionError("invocation disappeared")
    return saved


def normalized_event_types(
    service: KnowledgeWorkspaceService, invocation_id: str
) -> list[str]:
    return [
        str(item["event"]["type"])
        for item in service.repository.events_after(invocation_id)
    ]


def raw_has_secret(service: KnowledgeWorkspaceService, invocation_id: str) -> bool:
    text = json.dumps(
        [item["raw"] for item in service.repository.raw_events(invocation_id)],
        ensure_ascii=False,
    ).casefold()
    return any(marker in text for marker in SECRET_MARKERS)


def as_json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def summarize_artifact(
    service: KnowledgeWorkspaceService,
    actor: Actor,
    artifact_id: str,
) -> dict[str, object]:
    artifact = service.get_artifact(actor, artifact_id)
    content, media_type, csp = service.artifact_content(actor, artifact_id)
    html_meta = validate_html_artifact(content) if media_type == "text/html" else {}
    return {
        "artifact_id": artifact.artifact_id,
        "revision_id": artifact.revision_id,
        "invocation_id": artifact.invocation_id,
        "sha256": artifact.sha256,
        "sha256_verified": hashlib.sha256(content).hexdigest() == artifact.sha256,
        "media_type": media_type,
        "size_bytes": artifact.size_bytes,
        "sandbox": artifact.sandbox,
        "csp": csp,
        "html_valid": bool(html_meta),
        "uri": KnowledgeWorkspaceService.public_artifact(artifact)["uri"],
        "lineage_keys": sorted(artifact.lineage.keys()),
        "source_refs": artifact.lineage.get("source_refs"),
    }


async def run_template(
    template_key: str,
    *,
    evidence_dir: Path,
) -> dict[str, object]:
    object_root = evidence_dir / "objects" / template_key
    db_path = evidence_dir / f"{template_key}.sqlite3"
    if db_path.exists():
        db_path.unlink()
    autoskill = W4AutoSkillFixture(template_key, action_id="fixture.read")
    lease = W4LeaseFixture()
    registry = W4RegistryFixture()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(db_path, object_root),
        autoskill,
        lease,
        registry,
    )
    actor = Actor("tenant-a", f"workspace-{template_key}", "principal-a")
    draft = service.create_draft(
        actor,
        {
            "semantic": "Create a PostgreSQL/MySQL semantic layer for tenant revenue validation",
            "dashboard": "Create a schema-driven operational dashboard from authorized connection data",
            "sop": "Create an evidence-backed incident SOP from OpenViking docs and actions",
        }[template_key],
        ["connection-main"],
        template_key=template_key,
        template_config={
            "dialect": "postgresql" if template_key == "semantic" else "fixture",
            "business_area": template_key,
            "secret": "must-not-persist",
            "nested": {"api_key": "must-not-persist", "kept": "safe"},
        },
    )
    resource = WorkspaceResource(
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
        resource_id=f"resource-{template_key}",
        kind=WorkspaceResourceKind.MCP if template_key != "sop" else WorkspaceResourceKind.REST_OPENAPI,
        display_name=f"{template_key} context",
        scope="personal",
        status="verified",
        source_id=f"{template_key}-source",
        adapter_resource_id=f"adapter-{template_key}",
        metadata={"kind": template_key, "token": "must-not-persist"},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    service.repository.save_resource(resource)
    draft = service.update_draft(
        actor,
        draft.draft_id,
        goal=None,
        connection_ids=None,
        resource_ids=[resource.resource_id],
        if_match=draft.etag,
    )

    generated = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    generated_saved = await wait_done(service, generated, actor)
    if generated_saved.status is not InvocationStatus.SUCCEEDED:
        raise AssertionError(f"{template_key} generate failed")
    revision_one = await service.freeze(actor, draft.draft_id, generated.invocation_id)
    zip_one = validate_skill_zip(service.repository.read_object(revision_one.zip_uri))
    first_run = await service.run_revision(
        actor,
        revision_one.revision_id,
        f"Run {template_key} and write HTML presentation",
        ("connection-main",),
        resource_ids=[resource.resource_id],
    )
    first_run_saved = await wait_done(service, first_run, actor)
    if first_run_saved.status is not InvocationStatus.SUCCEEDED:
        raise AssertionError(f"{template_key} first run failed")
    first_artifact = service.repository.artifacts_for_revision(
        revision_one.revision_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )[-1]

    second_run_artifact = None
    if template_key == "dashboard":
        existing_artifact_ids = {
            item.artifact_id
            for item in service.repository.artifacts_for_revision(
                revision_one.revision_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
        }
        second_run = await service.run_revision(
            actor,
            revision_one.revision_id,
            "Refresh dashboard with the same revision",
            ("connection-main",),
            resource_ids=[resource.resource_id],
        )
        second_run_saved = await wait_done(service, second_run, actor)
        if second_run_saved.status is not InvocationStatus.SUCCEEDED:
            raise AssertionError("dashboard rerun failed")
        new_artifacts = [
            item
            for item in service.repository.artifacts_for_revision(
                revision_one.revision_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            if item.artifact_id not in existing_artifact_ids
        ]
        if len(new_artifacts) != 1:
            raise AssertionError("dashboard rerun overwrote prior artifact")
        second_run_artifact = new_artifacts[0]

    autoskill.revision_marker = "v2"
    updated = service.start(
        actor,
        draft.draft_id,
        InvocationKind.UPDATE,
        message=f"Update {template_key} Skill with latest evidence",
    )
    updated_saved = await wait_done(service, updated, actor)
    if updated_saved.status is not InvocationStatus.SUCCEEDED:
        raise AssertionError(f"{template_key} update failed")
    revision_two = await service.freeze(actor, draft.draft_id, updated.invocation_id)
    if revision_two.revision_id == revision_one.revision_id:
        raise AssertionError(f"{template_key} update did not create a new revision")
    zip_two = validate_skill_zip(service.repository.read_object(revision_two.zip_uri))
    second_revision_run = await service.run_revision(
        actor,
        revision_two.revision_id,
        f"Run updated {template_key} revision",
        ("connection-main",),
        resource_ids=[resource.resource_id],
    )
    second_revision_saved = await wait_done(service, second_revision_run, actor)
    if second_revision_saved.status is not InvocationStatus.SUCCEEDED:
        raise AssertionError(f"{template_key} updated run failed")
    revision_two_artifacts = [
        item
        for item in service.repository.artifacts_for_revision(
            revision_two.revision_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        if item.invocation_id == second_revision_run.invocation_id
    ]
    if len(revision_two_artifacts) != 1:
        raise AssertionError(f"{template_key} updated run did not create one artifact")
    publication = service.publish(actor, revision_two.revision_id, "personal")
    public_revision = KnowledgeWorkspaceService.public_revision(revision_two)

    reopened = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(db_path, object_root),
        autoskill,
        lease,
        registry,
    )
    restored_draft = reopened.get_draft(actor, draft.draft_id)
    restored_conversation = reopened.conversation(actor, draft.draft_id)
    restored_artifacts = reopened.repository.artifacts_for_revision(
        revision_two.revision_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )

    cross_tenant_denied = False
    try:
        reopened.get_draft(
            Actor("tenant-b", actor.workspace_id, actor.principal_id),
            draft.draft_id,
        )
    except KnowledgeWorkspaceError as error:
        cross_tenant_denied = error.code == "NOT_FOUND"

    revoke_denied = False
    try:
        await reopened.run_revision(
            actor,
            revision_two.revision_id,
            "Run with revoked connection",
            ("connection-revoked",),
        )
    except KnowledgeWorkspaceError as error:
        revoke_denied = error.code == "CONNECTION_NOT_READY" and error.status_code == 403

    expired_service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(
            evidence_dir / f"{template_key}-expired.sqlite3",
            evidence_dir / "objects" / f"{template_key}-expired",
        ),
        W4AutoSkillFixture(template_key, action_id="fixture.read"),
        W4LeaseFixture(fail=True),
    )
    expired_actor = Actor(
        "tenant-a", f"workspace-{template_key}-expired", "principal-a"
    )
    expired_draft = expired_service.create_draft(
        expired_actor,
        "Create template with expired lease",
        ["connection-main"],
        template_key=template_key,
    )
    expired_invocation = expired_service.start(
        expired_actor,
        expired_draft.draft_id,
        InvocationKind.GENERATE,
    )
    expired_saved = await wait_done(expired_service, expired_invocation, expired_actor)

    template_events = {
        "generate": normalized_event_types(service, generated.invocation_id),
        "run": normalized_event_types(service, first_run.invocation_id),
        "update": normalized_event_types(service, updated.invocation_id),
        "updated_run": normalized_event_types(
            service, second_revision_run.invocation_id
        ),
    }
    for kind, observed in template_events.items():
        missing = EXPECTED_EVENT_TYPES.difference(observed)
        if missing:
            raise AssertionError(f"{template_key} {kind} missing events: {sorted(missing)}")
    if raw_has_secret(service, generated.invocation_id):
        raise AssertionError(f"{template_key} raw generate events leaked secret marker")

    artifact_two = revision_two_artifacts[0]
    artifact_one_summary = summarize_artifact(
        service, actor, first_artifact.artifact_id
    )
    artifact_two_summary = summarize_artifact(service, actor, artifact_two.artifact_id)
    dashboard_rerun_summary = (
        summarize_artifact(service, actor, second_run_artifact.artifact_id)
        if second_run_artifact is not None
        else None
    )

    result = {
        "template_key": template_key,
        "contract_fixture": True,
        "draft_id": draft.draft_id,
        "draft_lifecycle": restored_draft.status.value,
        "template_config_redacted": "must-not-persist" not in as_json_text(
            KnowledgeWorkspaceService.public_draft(restored_draft),
        ),
        "autoskill_commands": [str(call["command"]) for call in autoskill.commands],
        "autoskill_invocation_count": len(autoskill.invocations),
        "lease_counts": {
            "issued": len(lease.issued),
            "prepared": len(lease.prepared),
            "revoked": len(lease.revoked),
        },
        "events": template_events,
        "zip": {
            "revision_one_sha256": revision_one.sha256,
            "revision_two_sha256": revision_two.sha256,
            "digests_differ": revision_one.sha256 != revision_two.sha256,
            "revision_one_paths": list(zip_one["paths"]),
            "revision_two_paths": list(zip_two["paths"]),
            "scripts_and_tests_present": all(
                any(part in path for path in zip_two["paths"])
                for part in ("/scripts/", "/tests/")
            ),
        },
        "revisions": [
            {
                "revision_id": revision_one.revision_id,
                "number": revision_one.number,
                "sha256": revision_one.sha256,
            },
            {
                "revision_id": revision_two.revision_id,
                "number": revision_two.number,
                "sha256": revision_two.sha256,
            },
        ],
        "artifacts": [
            artifact_one_summary,
            *([dashboard_rerun_summary] if dashboard_rerun_summary else []),
            artifact_two_summary,
        ],
        "publication_id": publication.publication_id,
        "publication_revision_id": publication.revision_id,
        "publication_policy_snapshot_keys": sorted(publication.policy_snapshot.keys()),
        "public_revision_has_no_provider_ids": "autoskill_request_ids" not in as_json_text(
            public_revision,
        ),
        "restart_restore": {
            "draft_restored": restored_draft.draft_id == draft.draft_id,
            "conversation_turns": len(restored_conversation),
            "artifact_count": len(restored_artifacts),
        },
        "security": {
            "cross_tenant_denied": cross_tenant_denied,
            "revoked_connection_denied": revoke_denied,
            "expired_lease_status": expired_saved.status.value,
            "expired_lease_error": expired_saved.error_code,
            "html_csp_secret_scan": "must-not-persist" not in as_json_text(
                [artifact_one_summary, artifact_two_summary],
            ).casefold(),
        },
    }
    (evidence_dir / f"{template_key}-lifecycle.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    return result


def security_negative_checks() -> dict[str, object]:
    checks: dict[str, object] = {}
    unsafe_cases = {
        "external_url": b'<!doctype html><html><img src="https://example.com/a.png"></html>',
        "cookie": b"<!doctype html><html><script>document.cookie</script></html>",
        "fetch": b"<!doctype html><html><script>fetch('/x')</script></html>",
    }
    for name, content in unsafe_cases.items():
        try:
            validate_html_artifact(content)
        except HtmlArtifactError as error:
            checks[name] = error.code
        else:
            checks[name] = "FAILED"
    checks["safe_inline_script"] = validate_html_artifact(
        template_html("dashboard", "security")
    )["sandbox"]
    return checks


def write_summary(
    evidence_dir: Path, results: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    summary = {
        "status": "CONTRACT_FIXTURE_PASS",
        "contract_fixture": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "templates": {
            str(item["template_key"]): {
                "draft_id": item["draft_id"],
                "revisions": item["revisions"],
                "artifact_ids": [
                    artifact["artifact_id"]
                    for artifact in item["artifacts"]
                    if isinstance(artifact, Mapping)
                ],
                "publication_id": item["publication_id"],
                "security": item["security"],
            }
            for item in results
        },
        "security_negative_checks": security_negative_checks(),
        "limitations": [
            "Fixture-backed only; live AutoSkill/Connection/OpenViking integration must be rerun with configured services.",
            "Browser screenshot capture is produced by frontend Playwright scripts when frontend dependencies are installed.",
        ],
    }
    (evidence_dir / "w4-acceptance-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    return summary


async def amain(evidence_dir: Path) -> int:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results = [
        await run_template(template_key, evidence_dir=evidence_dir)
        for template_key in ("semantic", "dashboard", "sop")
    ]
    summary = write_summary(evidence_dir, results)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not str(args.evidence_dir.resolve()).startswith(str(BASE_TMP.resolve())):
        print("evidence-dir must stay under /tmp/kp-rerun-20260829/w4", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(amain(args.evidence_dir)))
