from __future__ import annotations

import asyncio
import io
import json
import zipfile
from collections.abc import AsyncIterator

import pytest

from frontend.server.knowledge_workspace.models import InvocationKind, InvocationStatus
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import (
    Actor,
    KnowledgeWorkspaceError,
    KnowledgeWorkspaceService,
)
from frontend.server.knowledge_workspace.sse import ParsedUpstreamEvent

from tests.knowledge_workspace.test_service_contracts import (
    FakeLeasePort,
    FreezeAutoSkill,
    make_skill_zip,
    event,
    policy_summary,
    tool_event,
)


class RecordingFreezeAutoSkill(FreezeAutoSkill):
    def __init__(self, events, *, invoke_events=None) -> None:
        super().__init__(events, invoke_events=invoke_events)
        self.command_calls: list[dict[str, object]] = []

    async def command(
        self, command: str, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        self.command_calls.append({"command": command, **kwargs})
        async for item in super().command(command, **kwargs):
            yield item


class PreparedStateRecordingAutoSkill(RecordingFreezeAutoSkill):
    def __init__(self, events, *, prepared_state: bytes) -> None:
        super().__init__(events)
        self.command_states: list[bytes | None] = []
        self.prepared_state = prepared_state

    async def command(
        self, command: str, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        value = kwargs.get("state")
        self.command_states.append(value if isinstance(value, bytes) else None)
        async for item in super().command(command, **kwargs):
            yield item


class PreparedStateLeasePort(FakeLeasePort):
    async def prepare_autoskill(self, **_: object) -> bytes:
        return b"lease-scoped-mcp-state"


def w4_skill_zip(name: str = "demo", marker: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"skillhub/{name}/SKILL.md",
            f"# Demo\n\nUses real connection context. {marker}\n",
        )
        archive.writestr(
            f"skillhub/{name}/scripts/run.py",
            "def main():\n    return {'ok': True}\n",
        )
        archive.writestr(
            f"skillhub/{name}/tests/test_skill.py",
            "def test_skill_contract():\n    assert True\n",
        )
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_w4_template_metadata_flows_to_prompt_revision_and_artifact() -> None:
    autoskill = RecordingFreezeAutoSkill(
        [
            event("planning", {"text": "discover schema and create the semantic skill"}),
            event(
                "action",
                {
                    "tool_name": "mcp__knowledge-connection-1__execute_action",
                    "arguments": {"actionId": "fixture.read"},
                },
            ),
            event("observation", {"summary": "schema and sample rows observed"}),
            tool_event(
                "action",
                call_id="validate-skill-call",
                name="validate_skill",
            ),
            tool_event(
                "observation",
                call_id="validate-skill-call",
                name="validate_skill",
                ok=True,
            ),
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary(target_skill="demo")),
            event("done"),
        ],
        invoke_events=[
            event("final_answer", {"answer": "ran"}),
            event(
                "request_summary",
                policy_summary(target_skill="demo", skills_field="skills_used"),
            ),
            event("done"),
        ],
    )
    autoskill.skill_zip = w4_skill_zip()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(
        actor,
        "Create a revenue semantic layer",
        ["connection-a"],
        template_key="semantic",
        template_config={
            "dialect": "postgresql",
            "business_area": "finance analytics",
            "primary_key": "customer_id",
            "secret": "must-not-leak",
        },
    )

    assert service.public_draft(draft)["template_key"] == "semantic"
    assert service.public_draft(draft)["template_config"] == {
        "dialect": "postgresql",
        "business_area": "finance analytics",
        "primary_key": "customer_id",
    }

    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    command_prompt = autoskill.command_calls[0]["prompt"]
    assert "template_key=semantic" in command_prompt
    assert "schema discovery" in command_prompt
    assert "read-only SQL" in command_prompt
    assert "tenant/row/column policy" in command_prompt
    assert "presentation HTML artifact" in command_prompt
    assert "must-not-leak" not in command_prompt

    revision = await service.freeze(actor, draft.draft_id, invocation.invocation_id)
    assert [call["command"] for call in autoskill.command_calls].count(
        "validate_skill"
    ) == 0
    assert revision.manifest["template_key"] == "semantic"
    assert revision.manifest["template_config"] == {
        "dialect": "postgresql",
        "business_area": "finance analytics",
        "primary_key": "customer_id",
    }
    assert revision.manifest["provenance"]["target_skill"] == "demo"
    assert revision.manifest["provenance"]["template_key"] == "semantic"

    run = await service.run_revision(
        actor,
        revision.revision_id,
        "Validate example SQL and produce the HTML view",
        ("connection-a",),
    )
    await asyncio.sleep(0)
    saved_run = service.repository.get_invocation(
        run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_run is not None
    assert saved_run.status is InvocationStatus.SUCCEEDED

    artifact = service.repository.artifacts_for_revision(
        revision.revision_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )[0]
    lineage = artifact.lineage
    assert lineage["template_key"] == "semantic"
    assert lineage["revision_id"] == revision.revision_id
    assert lineage["invocation_id"] == run.invocation_id
    assert lineage["source_refs"] == {
        "connection_ids": ["connection-a"],
        "resource_ids": [],
        "upload_ids": [],
    }
    public_lineage = service.public_artifact(artifact)["lineage"]
    assert "autoskill_request_id" not in json.dumps(public_lineage)


@pytest.mark.asyncio
async def test_w4_template_freeze_requires_scripts_and_tests() -> None:
    autoskill = RecordingFreezeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    autoskill.skill_zip = make_skill_zip("demo", "# Demo\n")
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(
        actor,
        "Create a dashboard skill",
        ["connection-a"],
        template_key="dashboard",
    )
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    with pytest.raises(KnowledgeWorkspaceError, match="template Skill ZIP must include"):
        await service.freeze(actor, draft.draft_id, invocation.invocation_id)


@pytest.mark.asyncio
async def test_w4_update_prompt_binds_current_revision_skill() -> None:
    events = [
        event("planning", {"text": "update the bound skill"}),
        tool_event("action", call_id="validate", name="validate_skill"),
        tool_event(
            "observation",
            call_id="validate",
            name="validate_skill",
            ok=True,
        ),
        event("final_answer", {"answer": "updated"}),
        event(
            "request_summary",
            policy_summary(target_skill="demo", skills_field="skills_updated"),
        ),
        event("done"),
    ]
    autoskill = RecordingFreezeAutoSkill(events)
    autoskill.skill_zip = w4_skill_zip("demo", "updated")
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(actor, "Create a dashboard skill", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    first = await service.freeze(actor, draft.draft_id, generation.invocation_id)

    update = service.start(
        actor,
        draft.draft_id,
        InvocationKind.UPDATE,
        message="add a refresh state",
    )
    await asyncio.sleep(0)
    update_prompt = autoskill.command_calls[-1]["prompt"]

    assert first.skill_name == "demo"
    assert "current_revision_skill" in str(update_prompt)
    assert "existing Skill 'demo'" in str(update_prompt)


@pytest.mark.asyncio
async def test_w4_creator_passes_prepared_runtime_state_to_create() -> None:
    autoskill = PreparedStateRecordingAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ],
        prepared_state=b"unused",
    )
    autoskill.skill_zip = w4_skill_zip("demo")
    autoskill.config = type("Config", (), {"state_mode": "stateless"})()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        connection_context=PreparedStateLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(actor, "Create a dashboard skill", ["connection-a"])
    service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    assert autoskill.command_states == [b"lease-scoped-mcp-state"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("template_key", "required_terms"),
    [
        (
            "dashboard",
            [
                "template_key=dashboard",
                "schema/data-driven",
                "filters",
                "refresh",
                "no-permission",
                "same revision rerun",
                "event listeners",
                "onclick",
            ],
        ),
        (
            "sop",
            [
                "template_key=sop",
                "OpenViking",
                "evidence",
                "side-effect action",
                "idempotent",
                "human handoff",
            ],
        ),
    ],
)
async def test_w4_dashboard_and_sop_prompts_are_template_specific(
    template_key: str,
    required_terms: list[str],
) -> None:
    autoskill = RecordingFreezeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(
        actor,
        f"Create {template_key} skill",
        ["connection-a"],
        template_key=template_key,
    )

    service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    prompt = autoskill.command_calls[0]["prompt"]
    for term in required_terms:
        assert term in prompt
    assert "BuildPlan" not in prompt
    assert "多阶段产物生成计划" not in prompt
