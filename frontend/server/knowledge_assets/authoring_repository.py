"""Main-owned durable adapter for the W2 authoring ports.

This adapter stores only typed W2 models and secret-free request context in the
same SQLite database as Knowledge Assets.  It is deliberately independent of
W1 provider lifecycle: without an injected resolver/gateway the composition
fails closed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import BaseModel

from frontend.server.skill_authoring.models import (
    AgentTurnRequest,
    AuthoringEvent,
    AuthoringOperation,
    CreateDraftRequest,
    DraftRevision,
    PatchProposal,
)


class SqliteAuthoringRepository:
    def __init__(self, connection: sqlite3.Connection, lock: Any) -> None:
        self._connection = connection
        self._lock = lock

    async def _write(
        self, table: str, key: str, value: BaseModel | dict[str, object]
    ) -> None:
        payload = json.dumps(
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value,
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._lock:
            self._connection.execute(
                f"""
                INSERT INTO {table}(id, payload_json) VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json
                """,
                (key, payload),
            )

    async def _read(self, table: str, key: str) -> dict[str, object] | None:
        with self._lock:
            row = self._connection.execute(
                f"SELECT payload_json FROM {table} WHERE id = ?", (key,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    async def save_operation(self, operation: AuthoringOperation) -> None:
        await self._write("authoring_operations", operation.operation_id, operation)

    async def claim_generation(
        self,
        lane_key: str,
        operation: AuthoringOperation,
        *,
        idempotency_key: str | None,
    ) -> tuple[str, bool, str]:
        payload = json.dumps(
            operation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = (
                    self._connection.execute(
                        "SELECT operation_id FROM authoring_idempotency WHERE id = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if idempotency_key
                    else None
                )
                if row is not None:
                    self._connection.execute("COMMIT")
                    return str(row["operation_id"]), False, "idempotent"
                lease = self._connection.execute(
                    "SELECT operation_id FROM authoring_generation_leases WHERE lane_key = ?",
                    (lane_key,),
                ).fetchone()
                if lease is not None:
                    active = self._connection.execute(
                        "SELECT json_extract(payload_json, '$.status') AS status "
                        "FROM authoring_operations WHERE id = ?",
                        (lease["operation_id"],),
                    ).fetchone()
                    if active and active["status"] not in {
                        "succeeded",
                        "failed",
                        "cancelled",
                        "awaiting_input",
                        "credential_blocked",
                    }:
                        self._connection.execute("COMMIT")
                        return str(lease["operation_id"]), False, "active"
                    self._connection.execute(
                        "DELETE FROM authoring_generation_leases WHERE lane_key = ?",
                        (lane_key,),
                    )
                self._connection.execute(
                    "INSERT INTO authoring_operations(id, payload_json) VALUES (?, ?)",
                    (operation.operation_id, payload),
                )
                if idempotency_key:
                    self._connection.execute(
                        "INSERT INTO authoring_idempotency(id, operation_id) VALUES (?, ?)",
                        (idempotency_key, operation.operation_id),
                    )
                self._connection.execute(
                    "INSERT INTO authoring_generation_leases(lane_key, operation_id) VALUES (?, ?)",
                    (lane_key, operation.operation_id),
                )
                self._connection.execute("COMMIT")
                return operation.operation_id, True, "claimed"
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    async def release_generation(self, operation_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM authoring_generation_leases WHERE operation_id = ?",
                (operation_id,),
            )

    async def claim_idempotency(
        self, key: str, operation: AuthoringOperation
    ) -> tuple[str, bool]:
        return await self._legacy_claim_idempotency(key, operation)

    async def _legacy_claim_idempotency(
        self, key: str, operation: AuthoringOperation
    ) -> tuple[str, bool]:
        payload = json.dumps(
            operation.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT operation_id FROM authoring_idempotency WHERE id = ?",
                    (key,),
                ).fetchone()
                if row:
                    self._connection.execute("COMMIT")
                    return str(row["operation_id"]), False
                self._connection.execute(
                    "INSERT INTO authoring_operations(id, payload_json) VALUES (?, ?)",
                    (operation.operation_id, payload),
                )
                self._connection.execute(
                    "INSERT INTO authoring_idempotency(id, operation_id) VALUES (?, ?)",
                    (key, operation.operation_id),
                )
                self._connection.execute("COMMIT")
                return operation.operation_id, True
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    async def get_operation(self, operation_id: str) -> AuthoringOperation | None:
        value = await self._read("authoring_operations", operation_id)
        return AuthoringOperation.model_validate(value) if value else None

    async def save_event(self, event: AuthoringEvent) -> None:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS latest "
                "FROM authoring_events WHERE operation_id = ?",
                (event.operation_id,),
            ).fetchone()
            latest = int(row["latest"]) if row else 0
            if event.sequence <= latest:
                event = event.model_copy(update={"sequence": latest + 1})
            payload = event.model_dump(mode="json")
            self._connection.execute(
                "INSERT INTO authoring_events(id, operation_id, sequence, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    event.event_id,
                    event.operation_id,
                    event.sequence,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )

    async def list_events(self, operation_id: str) -> tuple[AuthoringEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM authoring_events WHERE operation_id = ? "
                "ORDER BY sequence",
                (operation_id,),
            ).fetchall()
        return tuple(
            AuthoringEvent.model_validate(json.loads(row["payload_json"]))
            for row in rows
        )

    async def list_events_after(
        self, operation_id: str, sequence: int, limit: int
    ) -> tuple[AuthoringEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM authoring_events "
                "WHERE operation_id = ? AND sequence > ? "
                "ORDER BY sequence LIMIT ?",
                (operation_id, sequence, limit),
            ).fetchall()
        return tuple(
            AuthoringEvent.model_validate(json.loads(row["payload_json"]))
            for row in rows
        )

    async def save_draft(self, draft: DraftRevision) -> None:
        payload = json.dumps(
            draft.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO authoring_drafts(
                  id, draft_id, revision, workspace_id, owner_id, scope, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id, revision) DO UPDATE SET
                  updated_at=excluded.updated_at, payload_json=excluded.payload_json
                """,
                (
                    f"{draft.draft_id}:{draft.revision}",
                    draft.draft_id,
                    draft.revision,
                    draft.workspace_id,
                    draft.owner_id,
                    draft.scope.value,
                    draft.updated_at.isoformat(),
                    payload,
                ),
            )

    async def get_draft(
        self, draft_id: str, revision: int | None = None
    ) -> DraftRevision | None:
        with self._lock:
            if revision is None:
                row = self._connection.execute(
                    "SELECT payload_json FROM authoring_drafts WHERE draft_id = ? "
                    "ORDER BY revision DESC LIMIT 1",
                    (draft_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT payload_json FROM authoring_drafts WHERE draft_id = ? AND revision = ?",
                    (draft_id, revision),
                ).fetchone()
        return (
            DraftRevision.model_validate(json.loads(row["payload_json"]))
            if row
            else None
        )

    async def list_drafts(
        self, workspace_id: str, caller_id: str
    ) -> tuple[DraftRevision, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM authoring_drafts WHERE workspace_id = ? "
                "AND (owner_id = ? OR scope = 'team') ORDER BY updated_at DESC",
                (workspace_id, caller_id),
            ).fetchall()
        return tuple(
            DraftRevision.model_validate(json.loads(row["payload_json"]))
            for row in rows
        )

    async def save_authoring_request(
        self,
        operation_id: str,
        request: AgentTurnRequest | CreateDraftRequest,
    ) -> None:
        await self._write(
            "authoring_requests",
            operation_id,
            {
                "request_type": (
                    "agent_turn"
                    if isinstance(request, AgentTurnRequest)
                    else "create_draft"
                ),
                "request": request.model_dump(mode="json"),
            },
        )

    async def get_authoring_request(
        self, operation_id: str
    ) -> AgentTurnRequest | CreateDraftRequest | None:
        value = await self._read("authoring_requests", operation_id)
        if not value:
            return None
        if value.get("request_type") == "agent_turn":
            return AgentTurnRequest.model_validate(value.get("request"))
        if value.get("request_type") == "create_draft":
            return CreateDraftRequest.model_validate(value.get("request"))
        return CreateDraftRequest.model_validate(value)

    async def save_patch(self, proposal: PatchProposal) -> None:
        await self._write("authoring_patches", proposal.patch_id, proposal)

    async def get_patch(self, patch_id: str) -> PatchProposal | None:
        value = await self._read("authoring_patches", patch_id)
        return PatchProposal.model_validate(value) if value else None

    async def save_idempotency(self, key: str, operation_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO authoring_idempotency(id, operation_id) VALUES (?, ?)",
                (key, operation_id),
            )

    async def get_idempotency(self, key: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT operation_id FROM authoring_idempotency WHERE id = ?", (key,)
            ).fetchone()
        return str(row["operation_id"]) if row else None


class PostgresAuthoringRepository:
    """Async-shaped adapter over Main's durable PostgreSQL connection."""

    def __init__(self, connection: Any, lock: Any) -> None:
        self._connection = connection
        self._lock = lock

    @staticmethod
    def _payload(value: BaseModel | dict[str, object]) -> str:
        return json.dumps(
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value,
            ensure_ascii=False,
            sort_keys=True,
        )

    async def _write(
        self, table: str, key: str, value: BaseModel | dict[str, object]
    ) -> None:
        payload = self._payload(value)
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {table}(id, payload_json) VALUES (%s, %s::jsonb)
                    ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json
                    """,
                    (key, payload),
                )

    async def _read(self, table: str, key: str) -> dict[str, object] | None:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT payload_json FROM {table} WHERE id = %s", (key,)
                )
                row = cursor.fetchone()
        if not row:
            return None
        value = row["payload_json"] if isinstance(row, dict) else row[0]
        return value if isinstance(value, dict) else json.loads(value)

    async def save_operation(self, operation: AuthoringOperation) -> None:
        await self._write("authoring_operations", operation.operation_id, operation)

    async def claim_generation(
        self,
        lane_key: str,
        operation: AuthoringOperation,
        *,
        idempotency_key: str | None,
    ) -> tuple[str, bool, str]:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (lane_key,),
                    )
                    row = None
                    if idempotency_key:
                        cursor.execute(
                            "SELECT operation_id FROM authoring_idempotency WHERE id = %s",
                            (idempotency_key,),
                        )
                        row = cursor.fetchone()
                    if row is not None:
                        existing = (
                            row["operation_id"] if isinstance(row, dict) else row[0]
                        )
                        return str(existing), False, "idempotent"
                    cursor.execute(
                        "SELECT l.operation_id, o.payload_json->>'status' AS status "
                        "FROM authoring_generation_leases l "
                        "JOIN authoring_operations o ON o.id = l.operation_id "
                        "WHERE l.lane_key = %s FOR UPDATE",
                        (lane_key,),
                    )
                    lease = cursor.fetchone()
                    lease_status = (
                        lease["status"]
                        if isinstance(lease, dict)
                        else lease[1]
                    ) if lease is not None else None
                    if lease is not None and lease_status not in {
                        "succeeded",
                        "failed",
                        "cancelled",
                        "awaiting_input",
                        "credential_blocked",
                    }:
                        lease_operation_id = (
                            lease["operation_id"]
                            if isinstance(lease, dict)
                            else lease[0]
                        )
                        return str(lease_operation_id), False, "active"
                    if lease is not None:
                        cursor.execute(
                            "DELETE FROM authoring_generation_leases WHERE lane_key = %s",
                            (lane_key,),
                        )
                    cursor.execute(
                        "INSERT INTO authoring_operations(id, payload_json) "
                        "VALUES (%s, %s::jsonb)",
                        (operation.operation_id, self._payload(operation)),
                    )
                    if idempotency_key:
                        cursor.execute(
                            "INSERT INTO authoring_idempotency(id, operation_id) "
                            "VALUES (%s, %s)",
                            (idempotency_key, operation.operation_id),
                        )
                    cursor.execute(
                        "INSERT INTO authoring_generation_leases(lane_key, operation_id) "
                        "VALUES (%s, %s)",
                        (lane_key, operation.operation_id),
                    )
                    return operation.operation_id, True, "claimed"

    async def release_generation(self, operation_id: str) -> None:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM authoring_generation_leases WHERE operation_id = %s",
                        (operation_id,),
                    )

    async def claim_idempotency(
        self, key: str, operation: AuthoringOperation
    ) -> tuple[str, bool]:
        # Kept for command paths outside the streaming Agent runtime.
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (key,),
                    )
                    cursor.execute(
                        "SELECT operation_id FROM authoring_idempotency WHERE id = %s",
                        (key,),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        return str(row["operation_id"] if isinstance(row, dict) else row[0]), False
                    cursor.execute(
                        "INSERT INTO authoring_operations(id, payload_json) VALUES (%s, %s::jsonb)",
                        (operation.operation_id, self._payload(operation)),
                    )
                    cursor.execute(
                        "INSERT INTO authoring_idempotency(id, operation_id) VALUES (%s, %s)",
                        (key, operation.operation_id),
                    )
                    return operation.operation_id, True

    async def get_operation(self, operation_id: str) -> AuthoringOperation | None:
        value = await self._read("authoring_operations", operation_id)
        return AuthoringOperation.model_validate(value) if value else None

    async def save_event(self, event: AuthoringEvent) -> None:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    # PostgreSQL's advisory transaction lock coordinates all
                    # BFF processes without adding a mutable sequence table.
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (event.operation_id,),
                    )
                    cursor.execute(
                        "SELECT COALESCE(MAX(sequence), 0) AS latest "
                        "FROM authoring_events WHERE operation_id = %s",
                        (event.operation_id,),
                    )
                    row = cursor.fetchone()
                    latest = int(
                        (row["latest"] if isinstance(row, dict) else row[0]) or 0
                    )
                    if event.sequence <= latest:
                        event = event.model_copy(update={"sequence": latest + 1})
                    cursor.execute(
                        """
                        INSERT INTO authoring_events(
                          id, operation_id, sequence, payload_json
                        )
                        VALUES (%s, %s, %s, %s::jsonb)
                        ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json
                        """,
                        (
                            event.event_id,
                            event.operation_id,
                            event.sequence,
                            self._payload(event),
                        ),
                    )

    async def list_events(self, operation_id: str) -> tuple[AuthoringEvent, ...]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload_json FROM authoring_events "
                    "WHERE operation_id = %s ORDER BY sequence",
                    (operation_id,),
                )
                rows = cursor.fetchall()
        return tuple(
            AuthoringEvent.model_validate(
                row["payload_json"] if isinstance(row, dict) else row[0]
            )
            for row in rows
        )

    async def list_events_after(
        self, operation_id: str, sequence: int, limit: int
    ) -> tuple[AuthoringEvent, ...]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload_json FROM authoring_events "
                    "WHERE operation_id = %s AND sequence > %s "
                    "ORDER BY sequence LIMIT %s",
                    (operation_id, sequence, limit),
                )
                rows = cursor.fetchall()
        return tuple(
            AuthoringEvent.model_validate(
                row["payload_json"] if isinstance(row, dict) else row[0]
            )
            for row in rows
        )

    async def save_draft(self, draft: DraftRevision) -> None:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO authoring_drafts(
                      id, draft_id, revision, workspace_id, owner_id, scope,
                      updated_at, payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(draft_id, revision) DO UPDATE SET
                      updated_at=excluded.updated_at,
                      payload_json=excluded.payload_json
                    """,
                    (
                        f"{draft.draft_id}:{draft.revision}",
                        draft.draft_id,
                        draft.revision,
                        draft.workspace_id,
                        draft.owner_id,
                        draft.scope.value,
                        draft.updated_at.isoformat(),
                        self._payload(draft),
                    ),
                )

    async def get_draft(
        self, draft_id: str, revision: int | None = None
    ) -> DraftRevision | None:
        with self._lock:
            with self._connection.cursor() as cursor:
                if revision is None:
                    cursor.execute(
                        "SELECT payload_json FROM authoring_drafts "
                        "WHERE draft_id = %s ORDER BY revision DESC LIMIT 1",
                        (draft_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT payload_json FROM authoring_drafts "
                        "WHERE draft_id = %s AND revision = %s",
                        (draft_id, revision),
                    )
                row = cursor.fetchone()
        if not row:
            return None
        value = row["payload_json"] if isinstance(row, dict) else row[0]
        return DraftRevision.model_validate(value)

    async def list_drafts(
        self, workspace_id: str, caller_id: str
    ) -> tuple[DraftRevision, ...]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload_json FROM authoring_drafts "
                    "WHERE workspace_id = %s AND (owner_id = %s OR scope = 'team') "
                    "ORDER BY updated_at DESC",
                    (workspace_id, caller_id),
                )
                rows = cursor.fetchall()
        return tuple(
            DraftRevision.model_validate(
                row["payload_json"] if isinstance(row, dict) else row[0]
            )
            for row in rows
        )

    async def save_authoring_request(
        self,
        operation_id: str,
        request: AgentTurnRequest | CreateDraftRequest,
    ) -> None:
        await self._write(
            "authoring_requests",
            operation_id,
            {
                "request_type": (
                    "agent_turn"
                    if isinstance(request, AgentTurnRequest)
                    else "create_draft"
                ),
                "request": request.model_dump(mode="json"),
            },
        )

    async def get_authoring_request(
        self, operation_id: str
    ) -> AgentTurnRequest | CreateDraftRequest | None:
        value = await self._read("authoring_requests", operation_id)
        if not value:
            return None
        if value.get("request_type") == "agent_turn":
            return AgentTurnRequest.model_validate(value.get("request"))
        if value.get("request_type") == "create_draft":
            return CreateDraftRequest.model_validate(value.get("request"))
        return CreateDraftRequest.model_validate(value)

    async def save_patch(self, proposal: PatchProposal) -> None:
        await self._write("authoring_patches", proposal.patch_id, proposal)

    async def get_patch(self, patch_id: str) -> PatchProposal | None:
        value = await self._read("authoring_patches", patch_id)
        return PatchProposal.model_validate(value) if value else None

    async def save_idempotency(self, key: str, operation_id: str) -> None:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO authoring_idempotency(id, operation_id) VALUES (%s, %s) "
                    "ON CONFLICT(id) DO UPDATE SET operation_id=excluded.operation_id",
                    (key, operation_id),
                )

    async def get_idempotency(self, key: str) -> str | None:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT operation_id FROM authoring_idempotency WHERE id = %s",
                    (key,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return str(row["operation_id"] if isinstance(row, dict) else row[0])
