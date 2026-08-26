"""Durable, resumable event-feed primitives for Skill authoring operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import AsyncIterator, Literal, Protocol

from .models import AuthoringEvent, AuthoringOperation, AuthoringStatus


class EventRepository(Protocol):
    async def get_operation(self, operation_id: str) -> AuthoringOperation | None: ...

    async def list_events(self, operation_id: str) -> tuple[AuthoringEvent, ...]: ...

    async def list_events_after(
        self, operation_id: str, sequence: int, limit: int
    ) -> tuple[AuthoringEvent, ...]: ...


def parse_last_event_id(value: str | None, *, operation_id: str | None = None) -> int:
    """Parse either a numeric cursor or ``operation_id:sequence``."""

    if value is None or not value.strip():
        return 0
    cursor = value.strip()
    if ":" in cursor:
        owner, cursor = cursor.rsplit(":", 1)
        if operation_id is not None and owner != operation_id:
            raise ValueError("Last-Event-ID belongs to another operation")
    try:
        sequence = int(cursor)
    except ValueError as error:
        raise ValueError("Last-Event-ID is not a valid authoring cursor") from error
    if sequence < 0:
        raise ValueError("Last-Event-ID must not be negative")
    return sequence


@dataclass(frozen=True)
class AuthoringStreamFrame:
    kind: Literal["event", "heartbeat"]
    event: AuthoringEvent | None = None


class AuthoringEventFeed:
    """Follow append-only repository events with replay and bounded batches.

    Polling is intentional: it works across BFF processes and after restart,
    whereas an in-memory condition alone cannot observe another worker's
    durable append.
    """

    _TERMINAL_STATUSES = {
        AuthoringStatus.AWAITING_INPUT,
        AuthoringStatus.CREDENTIAL_BLOCKED,
        AuthoringStatus.SUCCEEDED,
        AuthoringStatus.FAILED,
        AuthoringStatus.CANCELLED,
    }

    def __init__(
        self,
        repository: EventRepository,
        *,
        poll_interval_seconds: float = 0.1,
        heartbeat_seconds: float = 15.0,
        batch_size: int = 64,
        terminal_settle_seconds: float = 1.0,
    ) -> None:
        if (
            poll_interval_seconds <= 0
            or heartbeat_seconds <= 0
            or terminal_settle_seconds < 0
        ):
            raise ValueError("stream intervals must be positive")
        if batch_size < 1 or batch_size > 256:
            raise ValueError("stream batch size must be between 1 and 256")
        self._repository = repository
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._batch_size = batch_size
        self._terminal_settle_seconds = terminal_settle_seconds

    async def iter_frames(
        self, operation_id: str, *, after_sequence: int = 0
    ) -> AsyncIterator[AuthoringStreamFrame]:
        cursor = max(0, after_sequence)
        heartbeat_at = monotonic() + self._heartbeat_seconds
        terminal_seen_at: float | None = None
        while True:
            events = await self._repository.list_events_after(
                operation_id, cursor, self._batch_size
            )
            for value in events:
                event = AuthoringEvent.model_validate(value)
                cursor = event.sequence
                yield AuthoringStreamFrame(kind="event", event=event)
                heartbeat_at = monotonic() + self._heartbeat_seconds
                if event.terminal:
                    return
            if len(events) == self._batch_size:
                await asyncio.sleep(0)
                continue

            operation = await self._repository.get_operation(operation_id)
            if operation is None:
                return
            status = getattr(operation, "status", None)
            if status in self._TERMINAL_STATUSES:
                # Operation and event writes are separate repository calls. A
                # follower can observe terminal status in the small interval
                # before the canonical terminal event is committed.
                terminal_seen_at = terminal_seen_at or monotonic()
                if monotonic() - terminal_seen_at >= self._terminal_settle_seconds:
                    # Legacy rows may predate the explicit terminal bit.
                    return
            else:
                terminal_seen_at = None

            now = monotonic()
            if now >= heartbeat_at:
                yield AuthoringStreamFrame(kind="heartbeat")
                heartbeat_at = now + self._heartbeat_seconds
            await asyncio.sleep(self._poll_interval_seconds)
