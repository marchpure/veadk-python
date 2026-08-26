from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from frontend.server.skill_authoring.models import (
    AuthoringEvent,
    AuthoringOperation,
    AuthoringStatus,
)
from frontend.server.skill_authoring.ports import JsonFileAuthoringRepository
from frontend.server.skill_authoring.streaming import (
    AuthoringEventFeed,
    parse_last_event_id,
)


def operation(
    *, status: AuthoringStatus = AuthoringStatus.RUNNING
) -> AuthoringOperation:
    return AuthoringOperation(
        operation_id="op_stream",
        operation_type="create_draft",
        status=status,
        caller_id="user_1",
        workspace_id="workspace_1",
        trace_id="trace_stream",
    )


def event(sequence: int, event_type: str, *, terminal: bool = False) -> AuthoringEvent:
    return AuthoringEvent(
        operation_id="op_stream",
        event_type=event_type,
        sequence=sequence,
        public_summary=f"event {sequence}",
        terminal=terminal,
    )


def test_last_event_id_accepts_numeric_and_canonical_authoring_cursors() -> None:
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("") == 0
    assert parse_last_event_id("2") == 2
    assert parse_last_event_id("op_stream:7", operation_id="op_stream") == 7
    with pytest.raises(ValueError):
        parse_last_event_id("other:7", operation_id="op_stream")
    with pytest.raises(ValueError):
        parse_last_event_id("-1")


def test_public_events_redact_secrets_and_bound_nested_tool_output() -> None:
    unsafe = AuthoringEvent(
        operation_id="op_stream",
        event_type="tool.completed",
        sequence=1,
        public_summary="Authorization: Bearer super-secret-token",
        payload={
            "tool_name": "query_database",
            "password": "hunter2",
            "connection": "postgresql://admin:hunter2@db.example/orders",
            "output_summary": {
                "rows": [
                    {
                        "api_key": "sk-live-value",
                        "value": "x" * 10_000,
                    }
                    for _ in range(80)
                ]
            },
        },
    )

    serialized = json.dumps(unsafe.model_dump(mode="json"), ensure_ascii=False)

    assert "super-secret-token" not in serialized
    assert "hunter2" not in serialized
    assert "sk-live-value" not in serialized
    assert "[REDACTED]" in serialized
    assert len(unsafe.payload["output_summary"]["rows"]) <= 32
    assert len(unsafe.payload["output_summary"]["rows"][0]["value"]) <= 2_001


def test_only_operation_events_default_to_terminal() -> None:
    final_answer = AuthoringEvent(
        operation_id="op_stream",
        event_type="answer.final",
        sequence=1,
        payload={"text": "done"},
    )
    completed = AuthoringEvent(
        operation_id="op_stream",
        event_type="operation.completed",
        sequence=2,
    )

    assert final_answer.terminal is False
    assert completed.terminal is True


@pytest.mark.asyncio
async def test_event_feed_waits_for_incremental_events_and_resumes_without_duplicates(
    tmp_path: Path,
) -> None:
    repository = JsonFileAuthoringRepository(tmp_path / "authoring.json")
    await repository.save_operation(operation())
    feed = AuthoringEventFeed(
        repository,
        poll_interval_seconds=0.005,
        heartbeat_seconds=0.02,
        batch_size=2,
    )

    iterator = feed.iter_frames("op_stream", after_sequence=0)
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0.015)
    assert not pending.done()

    await repository.save_event(event(1, "message.accepted"))
    first = await asyncio.wait_for(pending, timeout=0.2)
    assert first.kind == "event"
    assert first.event is not None
    assert first.event.sequence == 1

    heartbeat = await asyncio.wait_for(anext(iterator), timeout=0.2)
    assert heartbeat.kind == "heartbeat"

    await repository.save_event(event(2, "operation.completed", terminal=True))
    await repository.save_operation(operation(status=AuthoringStatus.SUCCEEDED))
    terminal = await asyncio.wait_for(anext(iterator), timeout=0.2)
    assert terminal.kind == "event"
    assert terminal.event is not None
    assert terminal.event.sequence == 2
    assert terminal.event.terminal is True
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)

    resumed = [
        frame
        async for frame in feed.iter_frames("op_stream", after_sequence=1)
        if frame.kind == "event"
    ]
    assert [frame.event.sequence for frame in resumed if frame.event] == [2]


@pytest.mark.asyncio
async def test_event_feed_does_not_exit_between_terminal_status_and_event(
    tmp_path: Path,
) -> None:
    repository = JsonFileAuthoringRepository(tmp_path / "authoring.json")
    await repository.save_operation(operation())
    await repository.save_event(event(1, "answer.final"))
    feed = AuthoringEventFeed(
        repository,
        poll_interval_seconds=0.005,
        heartbeat_seconds=1,
        terminal_settle_seconds=0.2,
    )
    iterator = feed.iter_frames("op_stream", after_sequence=1)

    await repository.save_operation(operation(status=AuthoringStatus.SUCCEEDED))
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0.03)
    assert not pending.done()

    await repository.save_event(event(2, "operation.completed", terminal=True))
    terminal = await asyncio.wait_for(pending, timeout=0.2)
    assert terminal.event is not None
    assert terminal.event.type == "operation.completed"


@pytest.mark.asyncio
async def test_event_feed_waits_for_completion_event_when_draft_is_ready(
    tmp_path: Path,
) -> None:
    repository = JsonFileAuthoringRepository(tmp_path / "authoring.json")
    await repository.save_operation(
        operation(status=AuthoringStatus.READY_FOR_EXECUTION)
    )
    feed = AuthoringEventFeed(
        repository,
        poll_interval_seconds=0.005,
        heartbeat_seconds=1,
        terminal_settle_seconds=0.03,
    )
    iterator = feed.iter_frames("op_stream", after_sequence=0)
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0.05)
    assert not pending.done()

    await repository.save_event(event(1, "operation.completed", terminal=True))
    terminal = await asyncio.wait_for(pending, timeout=0.2)
    assert terminal.event is not None
    assert terminal.event.type == "operation.completed"


@pytest.mark.asyncio
async def test_event_feed_replays_from_cursor_after_repository_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authoring.json"
    before_restart = JsonFileAuthoringRepository(path)
    await before_restart.save_operation(operation(status=AuthoringStatus.SUCCEEDED))
    await before_restart.save_event(event(1, "answer.delta"))
    await before_restart.save_event(event(2, "answer.final"))
    await before_restart.save_event(event(3, "operation.completed", terminal=True))

    after_restart = JsonFileAuthoringRepository(path)
    replayed = [
        frame.event
        async for frame in AuthoringEventFeed(after_restart).iter_frames(
            "op_stream", after_sequence=1
        )
        if frame.event is not None
    ]

    assert [item.sequence for item in replayed] == [2, 3]
    assert replayed[-1].terminal is True


@pytest.mark.asyncio
async def test_json_repository_allocates_unique_sequences_for_concurrent_writers(
    tmp_path: Path,
) -> None:
    repository = JsonFileAuthoringRepository(tmp_path / "authoring.json")
    await repository.save_operation(operation())

    # Service-side event creation can happen from separate Runner callbacks.
    # The repository is the serialization boundary, so every append must get
    # a durable cursor even when callers calculated the same optimistic value.
    await asyncio.gather(
        *(
            repository.save_event(
                event(1, "answer.delta").model_copy(
                    update={"payload": {"text": str(index)}}
                )
            )
            for index in range(24)
        )
    )

    persisted = await repository.list_events("op_stream")
    assert [item.sequence for item in persisted] == list(range(1, 25))
    assert len({item.sequence for item in persisted}) == 24


@pytest.mark.asyncio
async def test_terminal_event_is_the_last_replayed_event(
    tmp_path: Path,
) -> None:
    repository = JsonFileAuthoringRepository(tmp_path / "authoring.json")
    await repository.save_operation(operation(status=AuthoringStatus.SUCCEEDED))
    await repository.save_event(event(1, "answer.final"))
    await repository.save_event(event(2, "operation.completed", terminal=True))

    frames = [
        frame
        async for frame in AuthoringEventFeed(repository).iter_frames(
            "op_stream", after_sequence=0
        )
        if frame.kind == "event" and frame.event is not None
    ]

    assert [frame.event.sequence for frame in frames] == [1, 2]
    assert sum(frame.event.terminal for frame in frames) == 1
    assert frames[-1].event.type == "operation.completed"
