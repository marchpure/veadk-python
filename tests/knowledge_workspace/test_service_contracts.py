from __future__ import annotations

import asyncio
import json
import io
import zipfile
from collections.abc import AsyncIterator, Sequence

import pytest

from frontend.server.knowledge_workspace.connection import EphemeralConnectionContext
from frontend.server.knowledge_workspace.models import (
    DraftStatus,
    Invocation,
    InvocationKind,
    InvocationStatus,
    WorkspaceUpload,
    new_id,
)
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import Actor, KnowledgeWorkspaceError, KnowledgeWorkspaceService
from frontend.server.knowledge_workspace.sse import ParsedUpstreamEvent


def event(event_type: str, data: object = None) -> ParsedUpstreamEvent:
    return ParsedUpstreamEvent(
        event_id=event_type,
        event_type=event_type,
        payload={"type": event_type, "data": data if data is not None else {}},
        raw="",
    )


class FakeAutoSkill:
    def __init__(self, events: Sequence[ParsedUpstreamEvent]) -> None:
        self.events = tuple(events)
        self.stops: list[str] = []
        self.uploads: list[dict[str, object]] = []
        self.output = b"<!doctype html><html><body>real output</body></html>"
        self.skill_zip = make_skill_zip("demo", "# Demo\n")

    async def upload(self, **kwargs: object) -> dict[str, str]:
        self.uploads.append(kwargs)
        return {"status": "ok"}

    async def download(self, **kwargs: object) -> bytes:
        return self.output if kwargs["file_type"] == "output" else self.skill_zip

    async def command(self, *_args: object, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        for item in self.events:
            yield item

    async def invoke(self, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        for item in self.events:
            yield item

    async def reconnect(self, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        if False:
            yield event("done")

    async def stop(self, **kwargs: object) -> dict[str, str]:
        self.stops.append(str(kwargs["request_id"]))
        return {"message": "stopped"}


def make_skill_zip(name: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"skillhub/{name}/SKILL.md", content)
    return buffer.getvalue()


class FakeLeasePort:
    def __init__(self) -> None:
        self.issued: list[dict[str, object]] = []
        self.revoked: list[str] = []

    async def issue(self, **kwargs: object) -> EphemeralConnectionContext:
        self.issued.append(kwargs)
        return EphemeralConnectionContext(
            lease_id=f"lease-{kwargs['invocation_id']}",
            connection_ids=tuple(kwargs["connection_ids"]),
            allowed_actions=tuple(kwargs["allowed_actions"]),
            expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            runtime_ref="runtime://lease",
        )

    async def revoke(self, lease_id: str) -> None:
        self.revoked.append(lease_id)


def make_service(events: Sequence[ParsedUpstreamEvent]) -> tuple[KnowledgeWorkspaceService, Actor, FakeLeasePort]:
    lease = FakeLeasePort()
    service = KnowledgeWorkspaceService(
        KnowledgeWorkspaceRepository(),
        FakeAutoSkill(events),
        lease,
    )
    return service, Actor("tenant", "workspace", "principal"), lease


class FreezeAutoSkill(FakeAutoSkill):
    async def command(self, command: str, **kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
        if command == "list_skill":
            answer = json.dumps({"data": {"command": "list-skill", "data": {"skills": [{"name": "demo"}]}}})
            for item in (event("final_answer", {"answer": answer}), event("done")):
                yield item
            return
        if command == "view_skill":
            for item in (event("final_answer", {"answer": "# Demo"}), event("done")):
                yield item
            return
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
                event("request_summary", {"status": "success"}),
                event("done"),
            ]
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
    saved_run = service.repository.get_invocation(run.invocation_id, tenant_id="tenant", workspace_id="workspace")
    assert saved_run is not None
    assert saved_run.status is InvocationStatus.SUCCEEDED
    artifacts = service.repository.artifacts_for_revision(revision.revision_id, tenant_id="tenant", workspace_id="workspace")
    assert len(artifacts) == 1
    assert artifacts[0].media_type == "text/html"
    assert "autoskill_request_id" not in service.public_artifact(artifacts[0])["lineage"]
    publication = service.publish(actor, revision.revision_id, "personal")
    assert publication.revision_id == revision.revision_id


@pytest.mark.asyncio
async def test_publication_consumer_gets_fresh_autoskill_identity() -> None:
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
    publication = service.publish(actor, revision.revision_id, "personal")
    consumer = await service.invoke_publication(actor, publication.publication_id, "use it", ("connection-a",))
    assert consumer.autoskill_agent_id != generation.autoskill_agent_id
    assert consumer.autoskill_session_id != generation.autoskill_session_id
    assert consumer.connection_ids == ("connection-a",)


@pytest.mark.asyncio
async def test_invocation_issues_invocation_bound_lease_and_revokes_it() -> None:
    service, actor, lease = make_service(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", {"status": "success"}),
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
    assert lease.issued[0]["invocation_id"] == invocation.invocation_id
    assert lease.issued[0]["connection_ids"] == ("connection-a",)
    assert lease.revoked == [f"lease-{invocation.invocation_id}"]


@pytest.mark.asyncio
async def test_invocation_forwards_workspace_uploads_to_autoskill() -> None:
    service, actor, _ = make_service(
        [
            event("final_answer", {"answer": "created"}),
            event("request_summary", {"status": "success"}),
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
    draft = service.create_draft(actor, "goal", ["connection-a"], upload_ids=[upload.upload_id])
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
        [event("request_summary", {"status": "success"}), event("done")],
        [
            event("error", {"code": "UPSTREAM", "message": "failed"}),
            event("final_answer", {"answer": "answer"}),
            event("request_summary", {"status": "success"}),
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
async def test_unknown_event_is_not_a_success_path() -> None:
    service, actor, _ = make_service(
        [
            event("final_answer", {"answer": "answer"}),
            event("request_summary", {"status": "success"}),
            event("future_provider_event", {"token": "secret"}),
            event("done"),
        ]
    )
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    await asyncio.sleep(0)
    saved = service.repository.get_invocation(invocation.invocation_id, tenant_id="tenant", workspace_id="workspace")
    assert saved is not None
    assert saved.status is InvocationStatus.FAILED
    assert "secret" not in json.dumps(service.repository.raw_events(invocation.invocation_id))


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_archives_cancelled_event() -> None:
    service, actor, _ = make_service([])
    draft = service.create_draft(actor, "goal", ["connection-a"])
    invocation = service.start(actor, draft.draft_id, InvocationKind.GENERATE)
    first = await service.cancel(actor, invocation.invocation_id)
    second = await service.cancel(actor, invocation.invocation_id)
    assert first.status is second.status is InvocationStatus.CANCELLED
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
                    event("request_summary", {"status": "success"}),
                    event("done"),
                ]
            )
            self.commands = 0
            self.reconnects = 0

        async def command(self, *_args: object, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
            self.commands += 1
            if False:
                yield event("done")

        async def reconnect(self, **_kwargs: object) -> AsyncIterator[ParsedUpstreamEvent]:
            self.reconnects += 1
            for item in self.events:
                yield item

    autoskill = Resumable()
    repository = KnowledgeWorkspaceRepository()
    service = KnowledgeWorkspaceService(repository, autoskill, FakeLeasePort())
    actor = Actor("tenant", "workspace", "principal")
    draft = service.create_draft(actor, "goal", ["connection-a"])
    session = repository.get_session(draft.draft_id, tenant_id="tenant", workspace_id="workspace")
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
    )
    repository.save_invocation(invocation)
    repository.save_draft(draft.model_copy(update={"status": DraftStatus.GENERATING}))
    await service.resume_pending()
    await asyncio.sleep(0)
    saved = repository.get_invocation(invocation.invocation_id, tenant_id="tenant", workspace_id="workspace")
    assert saved is not None
    assert saved.status is InvocationStatus.SUCCEEDED
    assert autoskill.commands == 0
    assert autoskill.reconnects == 1
