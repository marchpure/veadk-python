"""Idempotent operation worker boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class OperationJob:
    job_type: str
    idempotency_key: str
    operation_id: str


class SynchronousOperationWorker:
    """STEP 1 adapter; a queue worker can replace the execution boundary."""

    def run_once(self, job: OperationJob, handler: Callable[[], T]) -> T:
        del job
        return handler()
