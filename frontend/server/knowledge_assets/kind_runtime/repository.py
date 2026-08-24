"""Durable Worker 3 execution repository.

This repository is Worker 3-owned and stores only lifecycle records produced by
`KindRuntime`. Main can later mirror these records into shared tables.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Protocol

from .models import SkillKindExecutionRecord


class KindRuntimeRepository(Protocol):
    def operation_id_for_key(self, idempotency_key: str) -> str: ...

    def begin(self, operation_id: str, request_json: dict[str, object]) -> SkillKindExecutionRecord | None: ...

    def mark_cancel_requested(self, operation_id: str) -> None: ...

    def cancel_requested(self, operation_id: str) -> bool: ...

    def complete(self, record: SkillKindExecutionRecord) -> SkillKindExecutionRecord: ...

    def get(self, operation_id: str) -> SkillKindExecutionRecord | None: ...

    def recover_incomplete(self) -> list[str]: ...


class SqliteKindRuntimeRepository:
    def __init__(self, path: str | Path, *, replay_wait_seconds: float = 30.0) -> None:
        self.path = str(path)
        self.replay_wait_seconds = replay_wait_seconds
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS worker3_kind_operations (
              operation_id TEXT PRIMARY KEY,
              idempotency_key TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL,
              request_json TEXT NOT NULL,
              result_json TEXT,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def operation_id_for_key(self, idempotency_key: str) -> str:
        import hashlib

        return "w3op-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]

    def begin(
        self, operation_id: str, request_json: dict[str, object]
    ) -> SkillKindExecutionRecord | None:
        idempotency_key = str(request_json["idempotencyKey"])
        request_payload = json.dumps(request_json, sort_keys=True)
        with self._lock:
            inserted = self.connection.execute(
                """
                INSERT OR IGNORE INTO worker3_kind_operations
                  (operation_id, idempotency_key, status, request_json)
                VALUES (?, ?, 'running', ?)
                """,
                (operation_id, idempotency_key, request_payload),
            ).rowcount
            if inserted:
                return None
            row = self.connection.execute(
                """
                SELECT result_json FROM worker3_kind_operations
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if row is not None and row["result_json"] is not None:
                return SkillKindExecutionRecord.model_validate(
                    json.loads(row["result_json"])
                )
        deadline = time.monotonic() + self.replay_wait_seconds
        while time.monotonic() < deadline:
            with self._lock:
                row = self.connection.execute(
                    """
                    SELECT result_json FROM worker3_kind_operations
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if row is not None and row["result_json"] is not None:
                    return SkillKindExecutionRecord.model_validate(
                        json.loads(row["result_json"])
                    )
            time.sleep(0.01)
        return None

    def mark_cancel_requested(self, operation_id: str) -> None:
        with self._lock:
            self.connection.execute(
                """
                UPDATE worker3_kind_operations
                SET cancel_requested = 1, status = CASE
                  WHEN status IN ('succeeded', 'failed', 'cancelled') THEN status
                  ELSE 'cancelled'
                END,
                updated_at = CURRENT_TIMESTAMP
                WHERE operation_id = ?
                """,
                (operation_id,),
            )

    def cancel_requested(self, operation_id: str) -> bool:
        with self._lock:
            row = self.connection.execute(
                "SELECT cancel_requested FROM worker3_kind_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def complete(self, record: SkillKindExecutionRecord) -> SkillKindExecutionRecord:
        with self._lock:
            row = self.connection.execute(
                "SELECT status, result_json FROM worker3_kind_operations WHERE operation_id = ?",
                (record.operation_id,),
            ).fetchone()
            if row is not None and row["result_json"]:
                return SkillKindExecutionRecord.model_validate(json.loads(row["result_json"]))
            if row is not None and row["status"] == "cancelled":
                record = record.model_copy(
                    update={
                        "status": "cancelled",
                        "state": "cancelled",
                        "message": record.message
                        or "Execution was cancelled while handler was running.",
                    }
                )
            self.connection.execute(
                """
                UPDATE worker3_kind_operations
                SET status = ?, result_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE operation_id = ? AND result_json IS NULL
                """,
                (
                    record.status,
                    record.model_dump_json(by_alias=True),
                    record.operation_id,
                ),
            )
        return self.get(record.operation_id) or record

    def get(self, operation_id: str) -> SkillKindExecutionRecord | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT result_json FROM worker3_kind_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None or row["result_json"] is None:
            return None
        return SkillKindExecutionRecord.model_validate(json.loads(row["result_json"]))

    def recover_incomplete(self) -> list[str]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT operation_id FROM worker3_kind_operations
                WHERE status IN ('queued', 'running', 'awaiting_input', 'cancelled')
                  AND result_json IS NULL
                ORDER BY created_at, operation_id
                """
            ).fetchall()
        return [row["operation_id"] for row in rows]
