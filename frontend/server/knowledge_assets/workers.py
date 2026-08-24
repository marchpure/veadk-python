"""Small, deterministic STEP 1 job framework.

The framework owns lifecycle semantics only.  A production queue adapter can
persist the same records; this in-memory implementation is intentionally
explicitly injectable for contract and unit tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeVar
from uuid import uuid4

from .contracts import JobEvent, JobState, RuntimeProfile, StorageRef

T = TypeVar("T")


@dataclass(frozen=True)
class OperationJob:
    job_type: str
    idempotency_key: str
    operation_id: str


class SynchronousOperationWorker:
    """Compatibility adapter for the already-frozen M1 operation path."""

    def run_once(self, job: OperationJob, handler: Callable[[], T]) -> T:
        del job
        return handler()


class JobLeaseError(RuntimeError):
    """Raised when a worker does not own a live job lease."""


@dataclass
class _DeadLetter:
    job_id: str
    reason: str
    payload_ref: StorageRef | None
    created_at: str


class JobFramework:
    """In-memory reference implementation of the durable job contract."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        retry_base_seconds: int = 5,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._retry_base_seconds = retry_base_seconds
        self._jobs: dict[str, JobState] = {}
        self._by_key: dict[tuple[RuntimeProfile, str], str] = {}
        self._events: dict[str, list[JobEvent]] = {}
        self._outbox: list[JobEvent] = []
        self._dead_letters: dict[str, _DeadLetter] = {}

    def enqueue(
        self,
        *,
        job_type: str,
        idempotency_key: str,
        profile: RuntimeProfile,
        max_attempts: int = 3,
        payload_ref: StorageRef | None = None,
    ) -> JobState:
        key = (profile, idempotency_key)
        existing_id = self._by_key.get(key)
        if existing_id is not None:
            return self._jobs[existing_id].model_copy(deep=True)
        job = JobState(
            job_id=f"job-{uuid4()}",
            job_type=job_type,
            profile=profile,
            idempotency_key=idempotency_key,
            status="queued",
            attempt=0,
            max_attempts=max_attempts,
        )
        self._jobs[job.job_id] = job
        self._by_key[key] = job.job_id
        self._emit(job.job_id, "enqueued", payload_ref=payload_ref)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> JobState:
        return self._jobs[job_id].model_copy(deep=True)

    def lease(self, *, job_id: str, owner: str, ttl_seconds: int = 30) -> JobState:
        job = self._jobs[job_id]
        now = self._now()
        if job.status in {"leased", "running"} and not self._lease_expired(job, now):
            raise JobLeaseError("job already has a live lease")
        if job.status in {"succeeded", "failed", "cancelled", "dead_letter"}:
            raise JobLeaseError("terminal job cannot be leased")
        job.status = "leased"
        job.attempt += 1
        job.lease_owner = owner
        job.lease_expires_at = self._iso(now + timedelta(seconds=ttl_seconds))
        job.heartbeat_at = self._iso(now)
        self._emit(job_id, "leased")
        return job.model_copy(deep=True)

    def heartbeat(self, *, job_id: str, owner: str, ttl_seconds: int = 30) -> JobState:
        job = self._owned(job_id, owner)
        if job.status not in {"leased", "running"}:
            raise JobLeaseError("only active jobs can heartbeat")
        now = self._now()
        job.status = "running"
        job.heartbeat_at = self._iso(now)
        job.lease_expires_at = self._iso(now + timedelta(seconds=ttl_seconds))
        self._emit(job_id, "heartbeat")
        return job.model_copy(deep=True)

    def request_cancel(self, *, job_id: str) -> JobState:
        job = self._jobs[job_id]
        if job.status in {"succeeded", "failed", "cancelled", "dead_letter"}:
            return job.model_copy(deep=True)
        job.cancel_requested = True
        job.status = "cancelling" if job.lease_owner else "cancelled"
        self._emit(job_id, "cancel_requested")
        if job.status == "cancelled":
            self._emit(job_id, "cancelled")
        return job.model_copy(deep=True)

    def complete(self, *, job_id: str, owner: str) -> JobState:
        job = self._owned(job_id, owner)
        if job.cancel_requested:
            job.status = "cancelled"
            job.lease_owner = None
            job.lease_expires_at = None
            self._emit(job_id, "cancelled")
        else:
            job.status = "succeeded"
            job.lease_owner = None
            job.lease_expires_at = None
            self._emit(job_id, "succeeded")
        return job.model_copy(deep=True)

    def fail(self, *, job_id: str, owner: str, reason: str) -> JobState:
        job = self._owned(job_id, owner)
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempt < job.max_attempts and not job.cancel_requested:
            delay = self._retry_base_seconds * (2 ** max(job.attempt - 1, 0))
            job.status = "queued"
            job.next_attempt_at = self._iso(self._now() + timedelta(seconds=delay))
            self._emit(job_id, "retry_scheduled")
        elif job.cancel_requested:
            job.status = "cancelled"
            self._emit(job_id, "cancel_requested")
        else:
            job.status = "dead_letter"
            self._dead_letters[job_id] = _DeadLetter(
                job_id=job_id,
                reason=reason,
                payload_ref=None,
                created_at=self._iso(self._now()),
            )
            self._emit(job_id, "dead_letter")
        return job.model_copy(deep=True)

    def events(self, job_id: str) -> list[JobEvent]:
        return [event.model_copy(deep=True) for event in self._events.get(job_id, [])]

    def outbox(self, *, after_sequence: int = 0) -> list[JobEvent]:
        return [
            event.model_copy(deep=True)
            for event in self._outbox
            if event.sequence > after_sequence
        ]

    def checkpoint(self, *, job_id: str, owner: str, after_sequence: int) -> JobState:
        """Acknowledge only committed outbox events owned by the live worker."""
        job = self._owned(job_id, owner)
        if after_sequence < 0 or after_sequence > job.outbox_sequence:
            raise ValueError("checkpoint must reference an emitted sequence")
        job.outbox_sequence = max(job.outbox_sequence, after_sequence)
        return job.model_copy(deep=True)

    def resume(self, *, after_sequence: int = 0) -> list[JobEvent]:
        """Replay committed events in sequence order after a consumer restart."""
        return self.outbox(after_sequence=after_sequence)

    def dead_letter(self, job_id: str) -> dict[str, str] | None:
        item = self._dead_letters.get(job_id)
        if item is None:
            return None
        return {
            "jobId": item.job_id,
            "reason": item.reason,
            "createdAt": item.created_at,
        }

    def _owned(self, job_id: str, owner: str) -> JobState:
        job = self._jobs[job_id]
        if job.lease_owner != owner or self._lease_expired(job, self._now()):
            raise JobLeaseError("worker does not own a live job lease")
        return job

    def _lease_expired(self, job: JobState, now: datetime) -> bool:
        if job.lease_expires_at is None:
            return True
        return datetime.fromisoformat(job.lease_expires_at) <= now

    def _emit(
        self,
        job_id: str,
        event_type: Literal[
            "enqueued",
            "leased",
            "heartbeat",
            "retry_scheduled",
            "cancel_requested",
            "succeeded",
            "failed",
            "cancelled",
            "dead_letter",
        ],
        *,
        payload_ref: StorageRef | None = None,
    ) -> None:
        job = self._jobs[job_id]
        sequence = job.outbox_sequence + 1
        job.outbox_sequence = sequence
        event = JobEvent(
            job_id=job_id,
            sequence=sequence,
            event_type=event_type,
            occurred_at=self._iso(self._now()),
            payload_ref=payload_ref,
        )
        self._events.setdefault(job_id, []).append(event)
        self._outbox.append(event)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()
