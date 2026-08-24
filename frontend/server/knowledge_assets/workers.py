"""Small, deterministic job framework.

The framework owns lifecycle semantics and can persist the same records through
an injected SQLite connection. PostgreSQL queue execution remains an adapter
responsibility.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeVar
from uuid import uuid4
import json
import sqlite3
import threading
from typing import Any

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
    """Reference implementation of the durable job contract."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        retry_base_seconds: int = 5,
        connection: sqlite3.Connection | None = None,
        lock: threading.RLock | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._retry_base_seconds = retry_base_seconds
        self._jobs: dict[str, JobState] = {}
        self._by_key: dict[tuple[RuntimeProfile, str], str] = {}
        self._events: dict[str, list[JobEvent]] = {}
        self._outbox: list[JobEvent] = []
        self._dead_letters: dict[str, _DeadLetter] = {}
        self._connection = connection
        self._lock = lock or threading.RLock()
        if self._connection is not None:
            self._restore()

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
        self._persist()
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> JobState:
        return self._jobs[job_id].model_copy(deep=True)

    def find_by_key(
        self, *, profile: RuntimeProfile, idempotency_key: str
    ) -> JobState | None:
        job_id = self._by_key.get((profile, idempotency_key))
        return self._jobs[job_id].model_copy(deep=True) if job_id else None

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
        self._persist()
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
        self._persist()
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
        self._persist()
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
        self._persist()
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
        self._persist()
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
        self._persist()
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

    def _persist(self) -> None:
        if self._connection is None:
            return
        with self._lock:
            for job in self._jobs.values():
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO jobs
                    (job_id, job_type, profile, idempotency_key, status, attempt,
                     max_attempts, lease_owner, lease_expires_at, heartbeat_at,
                     next_attempt_at, cancel_requested, outbox_sequence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id, job.job_type, job.profile, job.idempotency_key,
                        job.status, job.attempt, job.max_attempts, job.lease_owner,
                        job.lease_expires_at, job.heartbeat_at, job.next_attempt_at,
                        int(job.cancel_requested), job.outbox_sequence,
                    ),
                )
            for job_id, events in self._events.items():
                for event in events:
                    self._connection.execute(
                        """
                        INSERT OR REPLACE INTO job_events
                        (job_id, sequence, event_type, occurred_at, payload_ref_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            job_id, event.sequence, event.event_type,
                            event.occurred_at,
                            event.payload_ref.model_dump_json()
                            if event.payload_ref else None,
                        ),
                    )
            for item in self._dead_letters.values():
                self._connection.execute(
                    """
                    INSERT OR REPLACE INTO dead_letters
                    (job_id, reason, payload_ref_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        item.job_id, item.reason,
                        item.payload_ref.model_dump_json()
                        if item.payload_ref else None,
                        item.created_at,
                    ),
                )

    def _restore(self) -> None:
        assert self._connection is not None
        rows = self._connection.execute(
            "SELECT * FROM jobs"
        ).fetchall()
        for row in rows:
            job = JobState(
                job_id=row["job_id"],
                job_type=row["job_type"],
                profile=row["profile"],
                idempotency_key=row["idempotency_key"],
                status=row["status"],
                attempt=row["attempt"],
                max_attempts=row["max_attempts"],
                lease_owner=row["lease_owner"],
                lease_expires_at=row["lease_expires_at"],
                heartbeat_at=row["heartbeat_at"],
                next_attempt_at=row["next_attempt_at"],
                cancel_requested=bool(row["cancel_requested"]),
                outbox_sequence=row["outbox_sequence"],
            )
            self._jobs[job.job_id] = job
            self._by_key[(job.profile, job.idempotency_key)] = job.job_id
        for row in self._connection.execute(
            "SELECT * FROM job_events ORDER BY job_id, sequence"
        ).fetchall():
            payload = (
                StorageRef.model_validate(json.loads(row["payload_ref_json"]))
                if row["payload_ref_json"] else None
            )
            event = JobEvent(
                job_id=row["job_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                occurred_at=row["occurred_at"],
                payload_ref=payload,
            )
            self._events.setdefault(event.job_id, []).append(event)
            self._outbox.append(event)
        for row in self._connection.execute(
            "SELECT * FROM dead_letters"
        ).fetchall():
            self._dead_letters[row["job_id"]] = _DeadLetter(
                job_id=row["job_id"],
                reason=row["reason"],
                payload_ref=(
                    StorageRef.model_validate(json.loads(row["payload_ref_json"]))
                    if row["payload_ref_json"] else None
                ),
                created_at=row["created_at"],
            )

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class PostgresJobFramework(JobFramework):
    """Durable job framework adapter for a PostgreSQL connection.

    Lifecycle transitions remain owned by :class:`JobFramework`; only the
    persistence boundary differs.  Keeping the state machine shared prevents
    SQLite and PostgreSQL from drifting in lease, retry, and cancellation
    behavior.
    """

    def __init__(
        self,
        *,
        connection: Any,
        now: Callable[[], datetime] | None = None,
        retry_base_seconds: int = 5,
        lock: threading.RLock | None = None,
    ) -> None:
        self._postgres_connection = connection
        super().__init__(
            now=now,
            retry_base_seconds=retry_base_seconds,
            connection=None,
            lock=lock,
        )
        self._restore_postgres()

    def _persist(self) -> None:
        with self._lock:
            with self._postgres_connection.cursor() as cursor:
                for job in self._jobs.values():
                    cursor.execute(
                        """
                        INSERT INTO jobs
                        (job_id, job_type, profile, idempotency_key, status,
                         attempt, max_attempts, lease_owner,
                         lease_expires_at, heartbeat_at, next_attempt_at,
                         cancel_requested, outbox_sequence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s)
                        ON CONFLICT (job_id) DO UPDATE SET
                          job_type = EXCLUDED.job_type,
                          profile = EXCLUDED.profile,
                          idempotency_key = EXCLUDED.idempotency_key,
                          status = EXCLUDED.status,
                          attempt = EXCLUDED.attempt,
                          max_attempts = EXCLUDED.max_attempts,
                          lease_owner = EXCLUDED.lease_owner,
                          lease_expires_at = EXCLUDED.lease_expires_at,
                          heartbeat_at = EXCLUDED.heartbeat_at,
                          next_attempt_at = EXCLUDED.next_attempt_at,
                          cancel_requested = EXCLUDED.cancel_requested,
                          outbox_sequence = EXCLUDED.outbox_sequence
                        """,
                        (
                            job.job_id,
                            job.job_type,
                            job.profile,
                            job.idempotency_key,
                            job.status,
                            job.attempt,
                            job.max_attempts,
                            job.lease_owner,
                            job.lease_expires_at,
                            job.heartbeat_at,
                            job.next_attempt_at,
                            job.cancel_requested,
                            job.outbox_sequence,
                        ),
                    )
                for job_id, events in self._events.items():
                    for event in events:
                        cursor.execute(
                            """
                            INSERT INTO job_events
                            (job_id, sequence, event_type, occurred_at,
                             payload_ref_json)
                            VALUES (%s, %s, %s, %s, %s::jsonb)
                            ON CONFLICT (job_id, sequence) DO UPDATE SET
                              event_type = EXCLUDED.event_type,
                              occurred_at = EXCLUDED.occurred_at,
                              payload_ref_json = EXCLUDED.payload_ref_json
                            """,
                            (
                                job_id,
                                event.sequence,
                                event.event_type,
                                event.occurred_at,
                                (
                                    event.payload_ref.model_dump_json()
                                    if event.payload_ref
                                    else None
                                ),
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT INTO outbox_events
                            (aggregate_type, aggregate_id, sequence,
                             event_json)
                            VALUES ('job', %s, %s, %s::jsonb)
                            ON CONFLICT (aggregate_type, aggregate_id, sequence)
                            DO UPDATE SET event_json = EXCLUDED.event_json
                            """,
                            (
                                job_id,
                                event.sequence,
                                event.model_dump_json(),
                            ),
                        )
                for item in self._dead_letters.values():
                    cursor.execute(
                        """
                        INSERT INTO dead_letters
                        (job_id, reason, payload_ref_json, created_at)
                        VALUES (%s, %s, %s::jsonb, %s)
                        ON CONFLICT (job_id) DO UPDATE SET
                          reason = EXCLUDED.reason,
                          payload_ref_json = EXCLUDED.payload_ref_json,
                          created_at = EXCLUDED.created_at
                        """,
                        (
                            item.job_id,
                            item.reason,
                            (
                                item.payload_ref.model_dump_json()
                                if item.payload_ref
                                else None
                            ),
                            item.created_at,
                        ),
                    )

    def _restore_postgres(self) -> None:
        with self._lock:
            with self._postgres_connection.cursor() as cursor:
                cursor.execute("SELECT * FROM jobs ORDER BY job_id")
                jobs = cursor.fetchall()
                cursor.execute(
                    "SELECT * FROM job_events ORDER BY job_id, sequence"
                )
                events = cursor.fetchall()
                cursor.execute("SELECT * FROM dead_letters ORDER BY job_id")
                dead_letters = cursor.fetchall()
            for row in jobs:
                job = JobState(
                    job_id=row["job_id"],
                    job_type=row["job_type"],
                    profile=row["profile"],
                    idempotency_key=row["idempotency_key"],
                    status=row["status"],
                    attempt=row["attempt"],
                    max_attempts=row["max_attempts"],
                    lease_owner=row["lease_owner"],
                    lease_expires_at=(
                        row["lease_expires_at"].isoformat()
                        if row["lease_expires_at"] is not None
                        else None
                    ),
                    heartbeat_at=(
                        row["heartbeat_at"].isoformat()
                        if row["heartbeat_at"] is not None
                        else None
                    ),
                    next_attempt_at=(
                        row["next_attempt_at"].isoformat()
                        if row["next_attempt_at"] is not None
                        else None
                    ),
                    cancel_requested=row["cancel_requested"],
                    outbox_sequence=row["outbox_sequence"],
                )
                self._jobs[job.job_id] = job
                self._by_key[(job.profile, job.idempotency_key)] = job.job_id
            for row in events:
                payload = (
                    StorageRef.model_validate(row["payload_ref_json"])
                    if row["payload_ref_json"] is not None
                    else None
                )
                event = JobEvent(
                    job_id=row["job_id"],
                    sequence=row["sequence"],
                    event_type=row["event_type"],
                    occurred_at=(
                        row["occurred_at"].isoformat()
                        if hasattr(row["occurred_at"], "isoformat")
                        else row["occurred_at"]
                    ),
                    payload_ref=payload,
                )
                self._events.setdefault(event.job_id, []).append(event)
                self._outbox.append(event)
            for row in dead_letters:
                self._dead_letters[row["job_id"]] = _DeadLetter(
                    job_id=row["job_id"],
                    reason=row["reason"],
                    payload_ref=(
                        StorageRef.model_validate(row["payload_ref_json"])
                        if row["payload_ref_json"] is not None
                        else None
                    ),
                    created_at=(
                        row["created_at"].isoformat()
                        if hasattr(row["created_at"], "isoformat")
                        else row["created_at"]
                    ),
                )
