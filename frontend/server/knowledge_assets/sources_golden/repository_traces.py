"""Connector operation, event, and remote trace persistence."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from .models import (
    ConnectorEventRecord,
    ConnectorOperationRecord,
    ConnectorTraceView,
    RemoteMcpTrace,
)


class ConnectorTraceRepositoryMixin:
    """Persistence methods mixed into the source/Golden repository."""

    _lock: threading.RLock
    _connection: sqlite3.Connection

    def operations(
        self, workspace_id: str, connection_id: str
    ) -> list[ConnectorOperationRecord]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, trace_id, operation, status, payload_json, created_at
                FROM source_connector_operations
                WHERE workspace_id = ? AND connection_id = ?
                ORDER BY id
                """,
                (workspace_id, connection_id),
            ).fetchall()
        records = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            records.append(
                ConnectorOperationRecord.model_validate(
                    {
                        "id": f"connector-operation-{row['id']}",
                        "workspace_id": workspace_id,
                        "connection_id": connection_id,
                        "trace_id": row["trace_id"],
                        "operation": row["operation"],
                        "status": row["status"],
                        "reason": payload.get("reason")
                        or {
                            "code": "RECORDED",
                            "message": "Connector operation was recorded.",
                        },
                        "resources": payload.get("resources", []),
                        "checkpoint": payload.get("checkpoint", {}),
                        "created_at": row["created_at"],
                    }
                )
            )
        return records

    def next_event_sequence(self, workspace_id: str, connection_id: str) -> int:
        with self._lock:
            return int(
                self._connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1
                    FROM source_connector_events
                    WHERE workspace_id = ? AND connection_id = ?
                    """,
                    (workspace_id, connection_id),
                ).fetchone()[0]
            )

    def event_exists(self, event_id: str) -> bool:
        with self._lock:
            return (
                self._connection.execute(
                    "SELECT 1 FROM source_connector_events WHERE id = ?",
                    (event_id,),
                ).fetchone()
                is not None
            )

    def recent_event_count(
        self,
        workspace_id: str,
        connection_id: str,
        *,
        seconds: int = 60,
    ) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        with self._lock:
            return int(
                self._connection.execute(
                    """
                    SELECT COUNT(*) FROM source_connector_events
                    WHERE workspace_id = ? AND connection_id = ?
                      AND created_at >= ?
                    """,
                    (workspace_id, connection_id, cutoff),
                ).fetchone()[0]
            )

    def save_event(self, event: ConnectorEventRecord) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO source_connector_events
                (id, workspace_id, connection_id, sequence, event_type, trace_id,
                 payload_digest, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.workspace_id,
                    event.connection_id,
                    event.sequence,
                    event.event_type,
                    event.trace_id,
                    event.payload_digest,
                    json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
                    event.created_at,
                ),
            )

    def events(
        self,
        workspace_id: str,
        connection_id: str,
        *,
        event_type: str | None = None,
    ) -> list[ConnectorEventRecord]:
        query = """
            SELECT id, sequence, event_type, trace_id, payload_digest,
                   payload_json, created_at
            FROM source_connector_events
            WHERE workspace_id = ? AND connection_id = ?
        """
        values: list[object] = [workspace_id, connection_id]
        if event_type is not None:
            query += " AND event_type = ?"
            values.append(event_type)
        query += " ORDER BY sequence"
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return [
            ConnectorEventRecord(
                id=row["id"],
                workspace_id=workspace_id,
                connection_id=connection_id,
                sequence=row["sequence"],
                event_type=row["event_type"],
                trace_id=row["trace_id"],
                payload_digest=row["payload_digest"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def trace(
        self,
        workspace_id: str,
        connection_id: str,
        trace_id: str,
    ) -> ConnectorTraceView:
        return ConnectorTraceView(
            trace_id=trace_id,
            workspace_id=workspace_id,
            connection_id=connection_id,
            operations=[
                operation
                for operation in self.operations(workspace_id, connection_id)
                if operation.trace_id == trace_id
            ],
            events=[
                event
                for event in self.events(workspace_id, connection_id)
                if event.trace_id == trace_id
            ],
        )

    def save_connector_trace(self, trace: RemoteMcpTrace) -> None:
        with self._lock:
            trace_id = trace.id
            suffix = 1
            while self._connection.execute(
                "SELECT 1 FROM source_connector_traces WHERE id = ?",
                (trace_id,),
            ).fetchone():
                suffix += 1
                trace_id = f"{trace.id}-{suffix}"
            if trace_id != trace.id:
                trace = trace.model_copy(update={"id": trace_id})
            self._connection.execute(
                """
                INSERT INTO source_connector_traces
                (id, workspace_id, connection_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    trace.id,
                    trace.workspace_id,
                    trace.connection_id,
                    trace.model_dump_json(by_alias=True),
                ),
            )

    def connector_traces(
        self, workspace_id: str, connection_id: str
    ) -> list[RemoteMcpTrace]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json FROM source_connector_traces
                WHERE workspace_id = ? AND connection_id = ?
                ORDER BY rowid
                """,
                (workspace_id, connection_id),
            ).fetchall()
        return [RemoteMcpTrace.model_validate_json(row["payload_json"]) for row in rows]
