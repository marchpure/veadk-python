from __future__ import annotations

import asyncio
import io
import json
import zipfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from frontend.server.knowledge_workspace.connection import EphemeralConnectionContext
from frontend.server.knowledge_workspace.autoskill import AutoSkillProtocolError
from frontend.server.knowledge_workspace.models import (
    DraftStatus,
    Invocation,
    InvocationKind,
    InvocationStatus,
    WorkspaceUpload,
    new_id,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import (
    Actor,
    KnowledgeWorkspaceError,
    KnowledgeWorkspaceService,
)
from frontend.server.knowledge_workspace.sse import ParsedUpstreamEvent


def event(event_type: str, data: object = None) -> ParsedUpstreamEvent:
    return ParsedUpstreamEvent(
        event_id=event_type,
        event_type=event_type,
        payload={"type": event_type, "data": data if data is not None else {}},
        raw="",
    )


class FakeAutoSkill:
    def __init__(
        self,
        events: Sequence[ParsedUpstreamEvent],
        *,
        invoke_events: Sequence[ParsedUpstreamEvent] | None = None,
    ) -> None:
        self.events = tuple(events)
        self.invoke_events = tuple(invoke_events) if invoke_events is not None else None
        self.stops: list[str] = []
        self.uploads: list[dict[str, object]] = []
        self.request_ids: list[str] = []
        self.policies: list[dict[str, object] | None] = []
        self.commands: list[str] = []
        self.command_calls: list[dict[str, object]] = []
        self.downloads: list[dict[str, object]] = []
        self.invocations: list[dict[str, object]] = []
        self.output = b"<!doctype html><html><body>real output</body></html>"
        self.skill_zip = make_skill_zip("demo", "# Demo\n")

    async def upload(self, **kwargs: object) -> dict[str, str]:
        self.uploads.append(kwargs)
        return {"status": "ok"}

    async def download(self, **kwargs: object) -> bytes:
        self.downloads.append(kwargs)
        return self.output if kwargs["file_type"] == "output" else self.skill_zip

    async def command(
        self, *args: object, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        if args:
            self.commands.append(str(args[0]))
        self.command_calls.append(kwargs)
        self.request_ids.append(str(kwargs["request_id"]))
        self.policies.append(kwargs.get("invocation_policy"))
        for item in self.events:
            yield item

    async def invoke(self, **kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        self.invocations.append(kwargs)
        self.request_ids.append(str(kwargs["request_id"]))
        self.policies.append(kwargs.get("invocation_policy"))
        for item in self.invoke_events or self.events:
            yield item

    async def reconnect(self, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        if False:
            yield event("done")

    async def stop(self, **kwargs: object) -> dict[str, str]:
        self.stops.append(str(kwargs["request_id"]))
        return {"message": "stopped"}


class TextOnlyAutoSkill(FakeAutoSkill):
    async def download(self, **kwargs: object) -> bytes:
        if kwargs["file_type"] == "output":
            raise AutoSkillProtocolError("AutoSkill download returned HTTP 404")
        return await super().download(**kwargs)


def make_skill_zip(name: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"skillhub/{name}/SKILL.md", content)
    return buffer.getvalue()


def policy_summary(
    *,
    status: str = "success",
    target_skill: str = "demo",
    skills_field: str = "skills_created",
    satisfied: bool = True,
    matched_action_id: str = "fixture.read",
    matched_tool: str = "mcp__knowledge-connection-1__execute_action",
) -> dict[str, object]:
    return {
        "status": status,
        skills_field: [target_skill],
        "target_skill": target_skill,
        "target_skill_version": "1.0.0",
        "policy_evaluation": {
            "satisfied": satisfied,
            "matched_calls": [
                {
                    "index": 0,
                    "server": "knowledge-connection-1",
                    "tool": matched_tool,
                    "actionId": matched_action_id,
                }
            ],
            "unmet_requirements": [] if satisfied else ["missing call"],
        },
    }


class FakeLeasePort:
    def __init__(self) -> None:
        self.issued: list[dict[str, object]] = []
        self.prepared: list[dict[str, object]] = []
        self.revoked: list[str] = []

    async def issue(self, **kwargs: object) -> EphemeralConnectionContext:
        self.issued.append(kwargs)
        return EphemeralConnectionContext(
            lease_id=f"lease-{kwargs['invocation_id']}",
            connection_ids=tuple(kwargs["connection_ids"]),
            allowed_actions=("fixture.read",),
            expires_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            runtime_ref=json.dumps(
                {
                    "leases": [
                        {
                            "connection_id": connection_id,
                            "allowed_actions": ["fixture.read"],
                        }
                        for connection_id in kwargs["connection_ids"]
                    ]
                }
            ),
        )

    async def revoke(self, lease_id: str) -> None:
        self.revoked.append(lease_id)

    async def prepare_autoskill(self, **kwargs: object) -> None:
        self.prepared.append(kwargs)


class ExpiredLeasePort(FakeLeasePort):
    async def issue(self, **kwargs: object) -> EphemeralConnectionContext:
        self.issued.append(kwargs)
        raise KnowledgeWorkspaceError("LEASE_EXPIRED", "lease expired", 409)


class FakePublicationRegistry:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def register_publication(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def make_service(
    events: Sequence[ParsedUpstreamEvent],
) -> tuple[KnowledgeWorkspaceService, Actor, FakeLeasePort]:
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FakeAutoSkill(events),
        lease,
    )
    return service, Actor("tenant", "workspace", "principal"), lease


@pytest.mark.asyncio
async def test_openviking_context_is_distinct_and_sent_to_autoskill() -> None:
    captured: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def resolve(
        actor: Actor, profile_ids: Sequence[str], refs: Sequence[str]
    ) -> dict[str, object]:
        assert actor.tenant_id == "tenant"
        captured.append((tuple(profile_ids), tuple(refs)))
        return {"profile_ids": list(profile_ids), "resource_refs": list(refs)}

    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FakeAutoSkill((event("done"),)),
        openviking_context_resolver=resolve,
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(
        actor,
        "build with knowledge",
        (),
        openviking_profile_ids=("ovp_a",),
        openviking_resource_refs=("ovr_a",),
    )
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await service._tasks[invocation.invocation_id]

    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    assert captured == [
        (("ovp_a",), ("ovr_a",)),
        (("ovp_a",), ("ovr_a",)),
        (("ovp_a",), ("ovr_a",)),
    ]
    assert fake.commands == ["create_skill"]
    assert '"openviking_context"' in str(fake.command_calls[0]["prompt"])
    assert invocation.openviking_profile_ids == ("ovp_a",)
    assert invocation.openviking_resource_refs == ("ovr_a",)


@pytest.mark.asyncio
async def test_openviking_resolved_content_is_sent_server_side_to_autoskill() -> None:
    async def resolve_content(
        actor: Actor, profile_ids: Sequence[str], refs: Sequence[str]
    ) -> dict[str, object]:
        return {
            "profile_ids": list(profile_ids),
            "resource_refs": list(refs),
            "resolved_resources": [
                {"resource_ref": refs[0], "content": "verified phrase"}
            ],
        }

    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FakeAutoSkill((event("done"),)),
        openviking_context_resolver=lambda _actor, profiles, refs: {
            "profile_ids": list(profiles),
            "resource_refs": list(refs),
        },
        openviking_content_resolver=resolve_content,
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(
        actor,
        "build with knowledge",
        (),
        openviking_profile_ids=("ovp_a",),
        openviking_resource_refs=("ovr_a",),
    )
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await service._tasks[invocation.invocation_id]

    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    assert "verified phrase" in str(fake.command_calls[0]["prompt"])


@pytest.mark.asyncio
async def test_openviking_resolver_failure_finishes_invocation_and_draft() -> None:
    async def fail_resolution(
        _actor: Actor, _profile_ids: Sequence[str], _refs: Sequence[str]
    ) -> dict[str, object]:
        raise KnowledgeWorkspaceError(
            "OPENVIKING_UNAVAILABLE", "OpenViking is unavailable", 503
        )

    repository = KnowledgeWorkspaceRepository()
    autoskill = FakeAutoSkill((event("done"),))
    service = KnowledgeWorkspaceService(
        repository,
        autoskill,
        openviking_context_resolver=lambda _actor, profiles, refs: {
            "profile_ids": list(profiles),
            "resource_refs": list(refs),
        },
        openviking_content_resolver=fail_resolution,
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(
        actor,
        "build with knowledge",
        (),
        openviking_profile_ids=("ovp_a",),
        openviking_resource_refs=("ovr_a",),
    )
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await service._tasks[invocation.invocation_id]

    saved_invocation = repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    saved_draft = repository.get_draft(
        draft.draft_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_invocation is not None
    assert saved_invocation.status is InvocationStatus.FAILED
    assert saved_invocation.error_code == "OPENVIKING_UNAVAILABLE"
    assert saved_invocation.finished_at is not None
    assert saved_draft is not None
    assert saved_draft.status is DraftStatus.FAILED
    assert autoskill.command_calls == []


@pytest.mark.asyncio
async def test_openviking_only_revision_can_run_without_connection() -> None:
    service, actor = make_freeze_service()
    service.openviking_context_resolver = lambda *_: {
        "profile_ids": ["ovp_a"],
        "resource_refs": ["ovr_a"],
    }
    draft = service.create_draft(
        actor,
        "answer from OpenViking",
        (),
        openviking_profile_ids=("ovp_a",),
        openviking_resource_refs=("ovr_a",),
    )
    generated = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generated.invocation_id)

    assert revision.manifest["openviking_profile_ids"] == ["ovp_a"]
    assert revision.manifest["openviking_resource_refs"] == ["ovr_a"]
    run = await service.run_revision(actor, revision.revision_id, "use it", ())
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_text_only_run_persists_real_final_answer_as_artifact() -> None:
    service, actor = make_freeze_service()
    original = service.autoskill
    assert isinstance(original, FakeAutoSkill)
    service.autoskill = TextOnlyAutoSkill(
        original.events,
        invoke_events=(
            event("final_answer", {"answer": "real text result"}),
            event("request_summary", policy_summary(skills_field="skills_used")),
            event("done"),
        ),
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generated = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generated.invocation_id)
    run = await service.run_revision(
        actor, revision.revision_id, "run", ("connection-a",)
    )
    await asyncio.sleep(0)

    artifact = service.repository.artifacts_for_revision(
        revision.revision_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )[-1]
    assert artifact.media_type == "text/plain"
    assert service.repository.read_object(artifact.uri) == b"real text result"


class FreezeAutoSkill(FakeAutoSkill):
    async def command(
        self, command: str, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        if command == "list_skill":
            answer = json.dumps(
                {
                    "data": {
                        "command": "list-skill",
                        "data": {"skills": [{"name": "demo"}]},
                    }
                }
            )
            for item in (event("final_answer", {"answer": answer}), event("done")):
                yield item
            return
        if command == "view_skill":
            for item in (event("final_answer", {"answer": "# Demo"}), event("done")):
                yield item
            return
        async for item in super().command(command, **kwargs):
            yield item


class UnorderedFreezeAutoSkill(FreezeAutoSkill):
    async def command(
        self, command: str, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        if command == "list_skill":
            answer = json.dumps(
                {
                    "data": {
                        "command": "list-skill",
                        "data": {
                            "skills": [
                                {"name": "pre-existing"},
                                {"name": "demo"},
                            ]
                        },
                    }
                }
            )
            for item in (event("final_answer", {"answer": answer}), event("done")):
                yield item
            return
        async for item in super().command(command, **kwargs):
            yield item


class QueryFailureAutoSkill(FreezeAutoSkill):
    async def command(
        self, command: str, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        if command == "view_skill":
            yield event("error", {"code": "QUERY_FAILED", "message": "no view"})
            yield event("done")
            return
        async for item in super().command(command, **kwargs):
            yield item


class QueryUnknownAutoSkill(FreezeAutoSkill):
    async def command(
        self, command: str, **kwargs: object
    ) -> AsyncIterator[ParsedUpstreamEvent]:
        if command == "view_skill":
            yield event("future_provider_progress", {"message": "compatible"})
        async for item in super().command(command, **kwargs):
            yield item


def make_freeze_service() -> tuple[KnowledgeWorkspaceService, Actor]:
    actor = Actor("tenant", "workspace", "principal")
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FreezeAutoSkill(
            [
                event("final_answer", {"answer": "created"}),
                event("request_summary", policy_summary()),
                event("done"),
            ],
            invoke_events=[
                event("final_answer", {"answer": "ran"}),
                event("request_summary", policy_summary(skills_field="skills_used")),
                event("done"),
            ],
        ),
        lease,
    )
    return service, actor


@pytest.mark.asyncio
async def test_freeze_run_artifact_and_publication_require_real_gates() -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, invocation.invocation_id)
    with pytest.raises(KnowledgeWorkspaceError, match="successful real run"):
        service.publish(actor, revision.revision_id, "personal")
    run = service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    saved_run = service.repository.get_invocation(
        run.invocation_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert saved_run is not None
    assert saved_run.status is InvocationStatus.SUCCEEDED
    artifacts = service.repository.artifacts_for_revision(
        revision.revision_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert len(artifacts) == 1
    assert artifacts[0].media_type == "text/html"
    assert (
        "autoskill_request_id" not in service.public_artifact(artifacts[0])["lineage"]
    )
    publication = service.publish(actor, revision.revision_id, "personal")
    assert publication.revision_id == revision.revision_id


@pytest.mark.asyncio
async def test_run_explicitly_loads_the_fixed_revision_skill() -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generated = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generated.invocation_id)

    run = await service.run_revision(
        actor,
        revision.revision_id,
        "produce the report",
        ("connection-a",),
    )
    await asyncio.sleep(0)

    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    invocation_call = next(
        call
        for call in fake.invocations
        if call["request_id"] == run.autoskill_request_id
    )
    assert (
        invocation_call["message"]
        == "First call read_skill(name='demo') and follow that fixed revision's "
        "instructions. Then complete this task: produce the report"
    )


@pytest.mark.asyncio
async def test_freeze_binds_created_skill_when_list_is_not_creation_ordered() -> None:
    actor = Actor("tenant", "workspace", "principal")
    autoskill = UnorderedFreezeAutoSkill(
        [
            event(
                "final_answer",
                {
                    "answer": json.dumps(
                        {
                            "data": {
                                "message": "已创建 skill `demo`",
                            }
                        }
                    )
                },
            ),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        invocation.invocation_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert saved is not None
    service.repository.save_invocation(
        saved.model_copy(
            update={
                "request_summary": policy_summary(),
            }
        )
    )

    revision = await service.freeze(actor, draft.draft_id, invocation.invocation_id)

    assert revision.skill_name == "demo"


@pytest.mark.asyncio
async def test_publication_requires_invocation_lease_and_registers_fixed_revision() -> (
    None
):
    actor = Actor("tenant", "workspace", "principal")
    registry = FakePublicationRegistry()
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FreezeAutoSkill(
            [
                event("final_answer", {"answer": "created"}),
                event("request_summary", policy_summary()),
                event("done"),
            ],
            invoke_events=[
                event("final_answer", {"answer": "ran"}),
                event("request_summary", policy_summary(skills_field="skills_used")),
                event("done"),
            ],
        ),
        lease,
        registry,
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)
    run = service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None and saved.lease_id
    service.repository.save_invocation(saved.model_copy(update={"lease_id": None}))
    with pytest.raises(KnowledgeWorkspaceError, match="successful real run"):
        service.publish(actor, revision.revision_id, "personal")

    service.repository.save_invocation(saved)
    publication = service.publish(actor, revision.revision_id, "personal")
    assert publication.revision_id == revision.revision_id
    assert registry.calls[0]["revision_id"] == revision.revision_id
    assert registry.calls[0]["publication_id"] == publication.publication_id


@pytest.mark.asyncio
async def test_publication_consumer_gets_fresh_autoskill_identity() -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)
    service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    publication = service.publish(actor, revision.revision_id, "personal")
    consumer = await service.invoke_publication(
        actor, publication.publication_id, "use it", ("connection-a",)
    )
    assert consumer.autoskill_agent_id != generation.autoskill_agent_id
    assert consumer.autoskill_session_id != generation.autoskill_session_id
    assert consumer.connection_ids == ("connection-a",)


@pytest.mark.asyncio
async def test_freeze_idempotency_replays_existing_revision() -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    first = await service.freeze(
        actor,
        draft.draft_id,
        invocation.invocation_id,
        idempotency_key="freeze-key-123456",
        request_digest="freeze-digest",
    )
    second = await service.freeze(
        actor,
        draft.draft_id,
        invocation.invocation_id,
        idempotency_key="freeze-key-123456",
        request_digest="freeze-digest",
        if_match="stale-etag",
    )
    assert second.revision_id == first.revision_id


@pytest.mark.asyncio
async def test_freeze_fails_closed_when_skill_query_emits_error() -> None:
    actor = Actor("tenant", "workspace", "principal")
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        QueryFailureAutoSkill(
            [
                event("final_answer", {"answer": "created"}),
                event("request_summary", policy_summary()),
                event("done"),
            ]
        ),
        FakeLeasePort(),
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    with pytest.raises(KnowledgeWorkspaceError, match="error"):
        await service.freeze(actor, draft.draft_id, invocation.invocation_id)


@pytest.mark.asyncio
async def test_freeze_archives_unknown_query_progress_without_killing_success() -> None:
    actor = Actor("tenant", "workspace", "principal")
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        QueryUnknownAutoSkill(
            [
                event("final_answer", {"answer": "created"}),
                event("request_summary", policy_summary()),
                event("done"),
            ]
        ),
        FakeLeasePort(),
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    revision = await service.freeze(actor, draft.draft_id, invocation.invocation_id)

    assert revision.skill_name == "demo"
    raw = service.repository.raw_events(invocation.invocation_id)
    assert (
        sum(item["raw"].get("type") == "future_provider_progress" for item in raw) == 1
    )


@pytest.mark.asyncio
async def test_freeze_persists_distinct_query_request_ids() -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    await service.freeze(actor, draft.draft_id, invocation.invocation_id)
    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert len(saved.autoskill_request_ids) == 2
    assert len(saved.autoskill_request_ids) == len(set(saved.autoskill_request_ids))


@pytest.mark.asyncio
async def test_invocation_uses_autoskill_request_id_for_connection_runtime() -> None:
    service, actor, lease = make_service(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED
    assert lease.issued[0]["invocation_id"] == saved.autoskill_request_id
    assert lease.issued[0]["connection_ids"] == ("connection-a",)
    assert lease.prepared[0]["invocation_id"] == saved.autoskill_request_id
    assert service.autoskill.request_ids == [saved.autoskill_request_id]
    assert lease.revoked == [f"lease-{saved.autoskill_request_id}"]


@pytest.mark.asyncio
async def test_invocation_forwards_workspace_uploads_to_autoskill() -> None:
    service, actor, _ = make_service(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    content = b"source context"
    digest = __import__("hashlib").sha256(content).hexdigest()
    upload = service.repository.save_upload(
        WorkspaceUpload(
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
            upload_id="upload-context",
            filename="context.txt",
            sha256=digest,
            size_bytes=len(content),
            media_type="text/plain",
            purpose="context",
            uri=service.repository.put_object(digest, content),
        )
    )
    draft = service.create_draft(
        actor, "goal", ["connection-a"], upload_ids=[upload.upload_id]
    )
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    assert invocation.upload_ids == (upload.upload_id,)
    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    assert fake.uploads[0]["file_name"] == "context.txt"
    assert fake.uploads[0]["content"] == content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events",
    [
        [event("final_answer", {"answer": "answer"}), event("done")],
        [event("request_summary", policy_summary()), event("done")],
        [
            event("error", {"code": "UPSTREAM", "message": "failed"}),
            event("final_answer", {"answer": "answer"}),
            event("request_summary", policy_summary()),
            event("done"),
        ],
    ],
)
async def test_completion_requires_summary_final_answer_done_and_no_error(
    events: Sequence[ParsedUpstreamEvent],
) -> None:
    service, actor, _ = make_service(events)
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert saved.status is InvocationStatus.FAILED


@pytest.mark.asyncio
async def test_unknown_nonterminal_event_is_archived_without_killing_success() -> None:
    service, actor, _ = make_service(
        [
            event("final_answer", {"answer": "answer"}),
            event(
                "request_summary",
                {
                    **policy_summary(),
                    "lease_id": "lease-secret",
                    "credential": "credential-secret",
                    "internal_url": "http://127.0.0.1:3417/private",
                },
            ),
            event("future_provider_event", {"token": "secret"}),
            event("done"),
        ]
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        invocation.invocation_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED
    assert "secret" not in json.dumps(
        service.repository.raw_events(invocation.invocation_id)
    )
    browser_events = json.dumps(
        service.repository.events_after(invocation.invocation_id)
    )
    assert "lease_id" not in browser_events
    assert "credential" not in browser_events
    assert "127.0.0.1" not in browser_events


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_archives_cancelled_event() -> None:
    service, actor, _ = make_service([])
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    first = await service.cancel(actor, invocation.invocation_id)
    second = await service.cancel(actor, invocation.invocation_id)
    assert first.status is second.status is InvocationStatus.CANCELLED
    assert service.get_draft(actor, draft.draft_id).status is DraftStatus.CANCELLED
    assert any(
        item["event"].get("type") == "run.cancelled"
        for item in service.repository.events_after(invocation.invocation_id)
    )


@pytest.mark.asyncio
async def test_resume_pending_uses_reconnect_without_reinvoking() -> None:
    class Resumable(FakeAutoSkill):
        def __init__(self) -> None:
            super().__init__(
                [
                    event("final_answer", {"answer": "resumed"}),
                    event("request_summary", policy_summary()),
                    event("done"),
                ]
            )
            self.commands = 0
            self.reconnects = 0

        async def command(
            self, *_args: object, **_kwargs: object
        ) -> AsyncIterator[ParsedUpstreamEvent]:
            self.commands += 1
            if False:
                yield event("done")

        async def reconnect(
            self, **_kwargs: object
        ) -> AsyncIterator[ParsedUpstreamEvent]:
            self.reconnects += 1
            for item in self.events:
                yield item

    autoskill = Resumable()
    repository = KnowledgeWorkspaceRepository()
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(repository, autoskill, lease)
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(actor, "goal", ["connection-a"])
    session = repository.get_session(
        draft.draft_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert session is not None
    invocation = Invocation(
        tenant_id="tenant",
        workspace_id="workspace",
        invocation_id=new_id("inv"),
        draft_id=draft.draft_id,
        authoring_session_id=session.authoring_session_id,
        kind=InvocationKind.GENERATE,
        status=InvocationStatus.RUNNING,
        autoskill_agent_id=session.autoskill_agent_id,
        autoskill_session_id=session.autoskill_session_id,
        autoskill_request_id=new_id("request"),
        principal_id="principal",
        message="goal",
        connection_ids=("connection-a",),
        lease_id="lease-before-restart",
    )
    repository.save_invocation(invocation)
    repository.save_draft(draft.model_copy(update={"status": DraftStatus.GENERATING}))
    await service.resume_pending()
    await asyncio.sleep(0)
    saved = repository.get_invocation(
        invocation.invocation_id, tenant_id="tenant", workspace_id="workspace"
    )
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED
    assert autoskill.commands == 0
    assert autoskill.reconnects == 1
    assert lease.revoked == [
        "lease-before-restart",
        f"lease-{invocation.autoskill_request_id}",
    ]
    assert len(lease.issued) == 1


def test_sqlite_repository_reopens_durable_workspace_state(tmp_path: Path) -> None:
    database = tmp_path / "workspace.sqlite3"
    objects = tmp_path / "objects"
    actor = Actor("tenant", "workspace", "principal")
    first = KnowledgeWorkspaceRepository(database, objects)
    draft = KnowledgeWorkspaceService(first, FakeAutoSkill([])).create_draft(
        actor, "durable goal", ["connection-a"]
    )
    reopened = KnowledgeWorkspaceRepository(database, objects)
    loaded = reopened.get_draft(
        draft.draft_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert loaded is not None
    assert loaded.goal == "durable goal"


def test_event_replay_uses_sequence_cursor_without_replacing_semantic_id() -> None:
    repository = KnowledgeWorkspaceRepository()
    repository.append_event(
        "inv",
        {"type": "Turn 1"},
        {
            "id": "upstream-turn",
            "type": "turn.started",
            "invocation_id": "inv",
            "occurred_at": "2026-08-28T00:00:00+00:00",
            "data": {"turn_number": 1, "title": "Turn 1", "status": "running"},
        },
        "upstream-turn",
    )

    event = repository.events_after("inv")[0]["event"]

    assert event["id"] == "upstream-turn"
    assert event["cursor"] == "1"
    assert repository.events_after("inv", after=int(event["cursor"])) == ()


def test_object_storage_rejects_symlink_alias(tmp_path: Path) -> None:
    repository = KnowledgeWorkspaceRepository(
        tmp_path / "db.sqlite3", tmp_path / "objects"
    )
    content = b"immutable"
    digest = __import__("hashlib").sha256(content).hexdigest()
    repository.put_object(digest, content)
    alias = tmp_path / "objects" / "alias"
    alias.symlink_to(tmp_path / "objects" / digest)
    with pytest.raises(ValueError, match="outside"):
        repository.read_object(str(alias))


@pytest.mark.asyncio
async def test_connection_backed_generate_builds_policy_from_lease_actions() -> None:
    autoskill = FakeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        lease,
    )
    actor = Actor("tenant", "workspace", "principal")

    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED
    assert saved.invocation_policy == autoskill.policies[0]
    assert autoskill.policies[0] == {
        "version": 1,
        "allowed_mcp_servers": ["knowledge-connection-1"],
        "allowed_mcp_tools": ["mcp__knowledge-connection-1__execute_action"],
        "allowed_action_ids": ["fixture.read"],
        "required_successful_calls": [
            {
                "tool": "mcp__knowledge-connection-1__execute_action",
                "arguments": {},
            }
        ],
        "min_successes": 1,
        "fail_if_unsatisfied": True,
        "match": "at_least_one_required_successful_call",
    }


@pytest.mark.asyncio
async def test_policy_builder_falls_back_to_lease_actions_when_runtime_ref_is_opaque() -> (
    None
):
    class OpaqueRuntimeLeasePort(FakeLeasePort):
        async def issue(self, **kwargs: object) -> EphemeralConnectionContext:
            lease = await super().issue(**kwargs)
            return lease.model_copy(update={"runtime_ref": "runtime://opaque"})

    autoskill = FakeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        OpaqueRuntimeLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")

    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED
    assert saved.invocation_policy is not None
    assert saved.invocation_policy["allowed_action_ids"] == ["fixture.read"]


@pytest.mark.asyncio
async def test_connection_backed_invocation_requires_satisfied_policy_and_execute_action() -> (
    None
):
    for summary in (
        policy_summary(satisfied=False),
        policy_summary(matched_action_id="fixture.other"),
        {
            **policy_summary(),
            "policy_evaluation": {"satisfied": True, "matched_calls": []},
        },
    ):
        service, actor, _lease = make_service(
            [
                event("final_answer", {"answer": "created"}),
                event("request_summary", summary),
                event("done"),
            ]
        )
        draft = service.create_draft(actor, "goal", ["connection-a"])
        invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
        await asyncio.sleep(0)
        saved = service.repository.get_invocation(
            invocation.invocation_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        )
        assert saved is not None
        assert saved.status is InvocationStatus.FAILED


@pytest.mark.asyncio
async def test_lease_expiry_failure_is_recoverable_by_new_invocation() -> None:
    autoskill = FakeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ]
    )
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        ExpiredLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(actor, "goal", ["connection-a"])
    expired = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved_expired = service.repository.get_invocation(
        expired.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_expired is not None
    assert saved_expired.status is InvocationStatus.FAILED
    assert saved_expired.error_code == "LEASE_EXPIRED"

    service.connection_context = FakeLeasePort()
    recovered = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved_recovered = service.repository.get_invocation(
        recovered.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_recovered is not None
    assert saved_recovered.status is InvocationStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_run_requires_request_summary_skills_used_target_skill() -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)

    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    fake.invoke_events = (
        event("final_answer", {"answer": "ran"}),
        event(
            "request_summary",
            policy_summary(
                skills_field="skills_used",
                target_skill="other",
            ),
        ),
        event("done"),
    )
    run = service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)

    saved = service.repository.get_invocation(
        run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    assert saved.status is InvocationStatus.FAILED
    assert saved.error_code == "SKILL_IDENTITY_UNRESOLVED"


@pytest.mark.asyncio
async def test_run_and_publication_reject_connections_outside_revision_manifest() -> (
    None
):
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)

    with pytest.raises(KnowledgeWorkspaceError, match="not allowed"):
        await service.run_revision(
            actor,
            revision.revision_id,
            "use it",
            ("connection-b",),
        )

    service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    publication = service.publish(actor, revision.revision_id, "personal")

    with pytest.raises(KnowledgeWorkspaceError, match="not allowed"):
        await service.invoke_publication(
            actor,
            publication.publication_id,
            "consumer run",
            ("connection-b",),
        )


@pytest.mark.asyncio
async def test_freeze_requires_request_summary_target_skill_not_list_fallback() -> None:
    actor = Actor("tenant", "workspace", "principal")
    autoskill = UnorderedFreezeAutoSkill(
        [
            event("final_answer", {"answer": "created skill `demo`"}),
            event("request_summary", policy_summary(target_skill="other")),
            event("done"),
        ]
    )
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    with pytest.raises(KnowledgeWorkspaceError, match="target_skill"):
        await service.freeze(actor, draft.draft_id, invocation.invocation_id)

    assert "list_skill" not in autoskill.commands


@pytest.mark.asyncio
async def test_generate_retry_can_freeze_an_updated_target_skill() -> None:
    actor = Actor("tenant", "workspace", "principal")
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FreezeAutoSkill(
            [
                event("final_answer", {"answer": "updated"}),
                event(
                    "request_summary",
                    policy_summary(skills_field="skills_updated"),
                ),
                event("done"),
            ]
        ),
        FakeLeasePort(),
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    revision = await service.freeze(actor, draft.draft_id, invocation.invocation_id)

    assert revision.skill_name == "demo"


@pytest.mark.asyncio
async def test_freeze_downloads_exact_target_zip_and_persists_minimal_manifest() -> (
    None
):
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)

    revision = await service.freeze(actor, draft.draft_id, invocation.invocation_id)
    saved_zip = service.repository.read_object(revision.zip_uri)

    assert revision.skill_name == "demo"
    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    assert fake.downloads[-1] == {
        "agent_id": invocation.autoskill_agent_id,
        "session_id": invocation.autoskill_session_id,
        "file_type": "skill",
        "name": "demo",
    }
    with zipfile.ZipFile(io.BytesIO(saved_zip)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("skillhub/demo/manifest.json"))
    assert "skillhub/demo/SKILL.md" in names
    assert "skillhub/demo/manifest.json" in names
    assert not any("BuildPlan" in name for name in names)
    assert manifest == {
        "kind": "general",
        "skill": {"name": "demo", "version": "1.0.0"},
        "connections": [{"connection_ref": "connection-a"}],
        "allowed_action_ids": ["fixture.read"],
        "entrypoint": "SKILL.md",
        "provenance": {
            "source": "autoskill",
            "target_skill": "demo",
            "contract_version": "autoskill-creator-v1",
        },
    }
    assert "token" not in json.dumps(revision.manifest).casefold()
    assert "lease" not in json.dumps(revision.manifest).casefold()
    assert "autoskill_request_ids" in revision.manifest["provenance"]
    assert (
        "autoskill_request_ids"
        not in service.public_revision(revision)["manifest"]["provenance"]
    )


@pytest.mark.asyncio
async def test_freeze_is_content_addressed_and_update_with_changed_zip_makes_new_revision() -> (
    None
):
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    first_invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    first = await service.freeze(actor, draft.draft_id, first_invocation.invocation_id)
    same = await service.freeze(actor, draft.draft_id, first_invocation.invocation_id)
    assert same.revision_id == first.revision_id

    fake = service.autoskill
    assert isinstance(fake, FakeAutoSkill)
    fake.skill_zip = make_skill_zip("demo", "# Demo\nupdated\n")
    fake.events = (
        event("final_answer", {"answer": "updated"}),
        event("request_summary", policy_summary(skills_field="skills_updated")),
        event("done"),
    )
    update = service.start(
        actor,
        draft.draft_id,
        InvocationKind.UPDATE,
        message="update",
    )
    await asyncio.sleep(0)
    second = await service.freeze(actor, draft.draft_id, update.invocation_id)

    assert second.revision_id != first.revision_id
    assert second.sha256 != first.sha256
    assert second.number == first.number + 1


@pytest.mark.asyncio
async def test_full_autoskill_creator_lifecycle_freezes_updates_and_invokes_published_revision() -> (
    None
):
    registry = FakePublicationRegistry()
    actor = Actor("tenant", "workspace", "principal")
    autoskill = FreezeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ],
        invoke_events=[
            event("final_answer", {"answer": "ran"}),
            event("request_summary", policy_summary(skills_field="skills_used")),
            event("done"),
        ],
    )
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
        registry,
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])

    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    first_revision = await service.freeze(
        actor, draft.draft_id, generation.invocation_id
    )
    first_run = await service.run_revision(
        actor,
        first_revision.revision_id,
        "trial run",
        ("connection-a",),
    )
    await asyncio.sleep(0)
    assert (
        service.repository.get_invocation(
            first_run.invocation_id,
            tenant_id=actor.tenant_id,
            workspace_id=actor.workspace_id,
        ).status
        is InvocationStatus.SUCCEEDED
    )

    autoskill.skill_zip = make_skill_zip("demo", "# Demo\nupdated\n")
    autoskill.events = (
        event("final_answer", {"answer": "updated"}),
        event("request_summary", policy_summary(skills_field="skills_updated")),
        event("done"),
    )
    update = service.start(
        actor,
        draft.draft_id,
        InvocationKind.UPDATE,
        message="update with trial feedback",
    )
    await asyncio.sleep(0)
    second_revision = await service.freeze(actor, draft.draft_id, update.invocation_id)
    second_run = await service.run_revision(
        actor,
        second_revision.revision_id,
        "trial run updated revision",
        ("connection-a",),
    )
    await asyncio.sleep(0)
    saved_second_run = service.repository.get_invocation(
        second_run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_second_run is not None
    assert saved_second_run.status is InvocationStatus.SUCCEEDED
    publication = service.publish(actor, second_revision.revision_id, "personal")
    consumer = await service.invoke_publication(
        actor,
        publication.publication_id,
        "consumer invocation",
        ("connection-a",),
    )
    await asyncio.sleep(0)
    saved_consumer = service.repository.get_invocation(
        consumer.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )

    assert first_revision.sha256 != second_revision.sha256
    assert second_revision.number == first_revision.number + 1
    assert publication.revision_id == second_revision.revision_id
    assert registry.calls[-1]["revision_sha256"] == second_revision.sha256
    assert consumer.autoskill_agent_id != generation.autoskill_agent_id
    assert consumer.autoskill_session_id != generation.autoskill_session_id
    assert saved_consumer is not None
    assert saved_consumer.status is InvocationStatus.SUCCEEDED
    assert saved_consumer.lease_id == f"lease-{saved_consumer.autoskill_request_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summary,match",
    [
        (policy_summary(satisfied=False), "policy_evaluation"),
        (policy_summary(matched_action_id="fixture.other"), "execute_action"),
    ],
)
async def test_freeze_rechecks_persisted_policy_evaluation_before_revision(
    summary: dict[str, object],
    match: str,
) -> None:
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(
        invocation.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved is not None
    service.repository.save_invocation(
        saved.model_copy(update={"request_summary": summary})
    )

    with pytest.raises(KnowledgeWorkspaceError, match=match):
        await service.freeze(actor, draft.draft_id, invocation.invocation_id)


@pytest.mark.asyncio
async def test_repository_reopen_restores_revision_conversation_and_publication(
    tmp_path: Path,
) -> None:
    database = tmp_path / "workspace.sqlite3"
    objects = tmp_path / "objects"
    actor = Actor("tenant", "workspace", "principal")
    autoskill = FreezeAutoSkill(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", policy_summary()),
            event("done"),
        ],
        invoke_events=[
            event("final_answer", {"answer": "ran"}),
            event("request_summary", policy_summary(skills_field="skills_used")),
            event("done"),
        ],
    )
    first = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(database, objects),
        autoskill,
        FakeLeasePort(),
    )
    draft = first.create_draft(actor, "goal", ["connection-a"])
    generation = first.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await first.freeze(actor, draft.draft_id, generation.invocation_id)
    run = await first.run_revision(
        actor,
        revision.revision_id,
        "trial run",
        ("connection-a",),
    )
    await asyncio.sleep(0)
    publication = first.publish(actor, revision.revision_id, "personal")

    reopened = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(database, objects),
        autoskill,
        FakeLeasePort(),
    )

    assert reopened.get_draft(actor, draft.draft_id).current_revision_id == (
        revision.revision_id
    )
    restored_revision = reopened.repository.get_revision(
        revision.revision_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert restored_revision is not None
    assert restored_revision.sha256 == revision.sha256
    assert json.loads(json.dumps(restored_revision.manifest)) == json.loads(
        json.dumps(revision.manifest)
    )
    assert [
        turn["invocation"]["invocation_id"]
        for turn in reopened.conversation(actor, draft.draft_id)
    ] == [generation.invocation_id, run.invocation_id]
    restored_publication = reopened.repository.get_publication(
        publication.publication_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert restored_publication is not None
    assert restored_publication.revision_id == revision.revision_id
    assert restored_publication.policy_snapshot == publication.policy_snapshot


@pytest.mark.asyncio
async def test_publish_snapshot_and_consumer_invocation_use_fixed_policy_and_fresh_identity() -> (
    None
):
    registry = FakePublicationRegistry()
    actor = Actor("tenant", "workspace", "principal")
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FreezeAutoSkill(
            [
                event("final_answer", {"answer": "created"}),
                event("request_summary", policy_summary()),
                event("done"),
            ],
            invoke_events=[
                event("final_answer", {"answer": "ran"}),
                event("request_summary", policy_summary(skills_field="skills_used")),
                event("done"),
            ],
        ),
        lease,
        registry,
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)
    run = service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    saved_run = service.repository.get_invocation(
        run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_run is not None

    publication = service.publish(actor, revision.revision_id, "personal")
    assert publication.policy_snapshot["revision_id"] == revision.revision_id
    assert publication.policy_snapshot["revision_sha256"] == revision.sha256
    assert (
        publication.policy_snapshot["invocation_policy"] == saved_run.invocation_policy
    )
    assert (
        publication.policy_snapshot["policy_evaluation"]
        == (saved_run.request_summary or {})["policy_evaluation"]
    )
    assert registry.calls[0]["policy_snapshot"] == publication.policy_snapshot

    consumer = await service.invoke_publication(
        actor, publication.publication_id, "use it", ("connection-a",)
    )
    assert consumer.autoskill_agent_id != generation.autoskill_agent_id
    assert consumer.autoskill_session_id != generation.autoskill_session_id
    assert consumer.lease_id is None
    await asyncio.sleep(0)
    saved_consumer = service.repository.get_invocation(
        consumer.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_consumer is not None
    assert saved_consumer.lease_id == f"lease-{saved_consumer.autoskill_request_id}"


@pytest.mark.asyncio
async def test_publish_requires_run_policy_snapshot_for_connection_backed_revision() -> (
    None
):
    service, actor = make_freeze_service()
    draft = service.create_draft(actor, "goal", ["connection-a"])
    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)
    run = service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    saved_run = service.repository.get_invocation(
        run.invocation_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert saved_run is not None
    service.repository.save_invocation(
        saved_run.model_copy(update={"invocation_policy": None})
    )

    with pytest.raises(KnowledgeWorkspaceError, match="successful real run"):
        service.publish(actor, revision.revision_id, "personal")

    service.repository.save_invocation(
        saved_run.model_copy(
            update={"request_summary": policy_summary(satisfied=False)}
        )
    )
    with pytest.raises(KnowledgeWorkspaceError, match="successful real run"):
        service.publish(actor, revision.revision_id, "personal")


@pytest.mark.asyncio
async def test_publication_consumer_stateless_run_does_not_inherit_authoring_state() -> (
    None
):
    class StatelessAutoSkill(FreezeAutoSkill):
        class Config:
            state_mode = "stateless"

        config = Config()

        def __init__(self) -> None:
            super().__init__(
                [
                    event("final_answer", {"answer": "created"}),
                    event("request_summary", policy_summary()),
                    event("done"),
                ],
                invoke_events=[
                    event("final_answer", {"answer": "ran"}),
                    event(
                        "request_summary", policy_summary(skills_field="skills_used")
                    ),
                    event("done"),
                ],
            )
            self.invoke_states: list[bytes | None] = []

        async def invoke(self, **kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
            self.invoke_states.append(kwargs.get("state"))
            async for item in super().invoke(**kwargs):
                yield item

    autoskill = StatelessAutoSkill()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        autoskill,
        FakeLeasePort(),
    )
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(actor, "goal", ["connection-a"])
    session = service.repository.get_session(
        draft.draft_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    assert session is not None
    state_content = b"PK\x03\x04author-state"
    state_digest = __import__("hashlib").sha256(state_content).hexdigest()
    state_uri = service.repository.put_object(
        state_digest,
        state_content,
        suffix=".state.zip",
    )
    service.repository.save_session(session.model_copy(update={"state_uri": state_uri}))

    generation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    revision = await service.freeze(actor, draft.draft_id, generation.invocation_id)
    service.start(
        actor,
        draft.draft_id,
        InvocationKind.RUN,
        revision_id=revision.revision_id,
        connection_ids=("connection-a",),
    )
    await asyncio.sleep(0)
    publication = service.publish(actor, revision.revision_id, "personal")
    await service.invoke_publication(
        actor,
        publication.publication_id,
        "consumer run",
        ("connection-a",),
    )
    await asyncio.sleep(0)

    assert autoskill.invoke_states[0] == state_content
    assert autoskill.invoke_states[1] is None
