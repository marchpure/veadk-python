from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from frontend.server.knowledge_workspace.connection import EphemeralConnectionContext
from frontend.server.knowledge_workspace.models import InvocationKind, InvocationStatus
from frontend.server.knowledge_workspace.repository import KnowledgeWorkspaceRepository
from frontend.server.knowledge_workspace.service import Actor, KnowledgeWorkspaceService
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
