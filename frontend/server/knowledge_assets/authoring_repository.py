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

from frontend.server.skill_authoring.models import (
    AuthoringEvent,
    AuthoringOperation,
    AuthoringReadModel,
    CreateDraftRequest,
    DraftRevision,
    PatchProposal,
)


class SqliteAuthoringRepository:
    def __init__(self, connection: sqlite3.Connection, lock: Any) -> None:
        self._connection = connection
        self._lock = lock

    async def _write(self, table: str, key: str, value: object) -> None:
        payload = json.dumps(
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
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

    async def get_operation(self, operation_id: str) -> AuthoringOperation | None:
        value = await self._read("authoring_operations", operation_id)
        return AuthoringOperation.model_validate(value) if value else None

    async def save_event(self, event: AuthoringEvent) -> None:
        payload = event.model_dump(mode="json")
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO authoring_events(id, operation_id, sequence, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (event.event_id, event.operation_id, event.sequence, json.dumps(
                    payload, ensure_ascii=False, sort_keys=True
                )),
            )

    async def list_events(self, operation_id: str) -> tuple[AuthoringEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM authoring_events WHERE operation_id = ? "
                "ORDER BY sequence",
                (operation_id,),
            ).fetchall()
        return tuple(AuthoringEvent.model_validate(json.loads(row["payload_json"])) for row in rows)

    async def save_draft(self, draft: DraftRevision) -> None:
        payload = json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
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

    async def get_draft(self, draft_id: str, revision: int | None = None) -> DraftRevision | None:
        with self._lock:
            if revision is None:
                row = self._connection.execute(
                    "SELECT payload_json FROM authoring_drafts WHERE draft_id = ? "
                    "ORDER BY revision DESC LIMIT 1", (draft_id,)
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT payload_json FROM authoring_drafts WHERE draft_id = ? AND revision = ?",
                    (draft_id, revision),
                ).fetchone()
        return DraftRevision.model_validate(json.loads(row["payload_json"])) if row else None

    async def list_drafts(self, workspace_id: str, caller_id: str) -> tuple[DraftRevision, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM authoring_drafts WHERE workspace_id = ? "
                "AND (owner_id = ? OR scope = 'team') ORDER BY updated_at DESC",
                (workspace_id, caller_id),
            ).fetchall()
        return tuple(DraftRevision.model_validate(json.loads(row["payload_json"])) for row in rows)

    async def save_create_request(self, operation_id: str, request: CreateDraftRequest) -> None:
        await self._write("authoring_requests", operation_id, request)

    async def get_create_request(self, operation_id: str) -> CreateDraftRequest | None:
        value = await self._read("authoring_requests", operation_id)
        return CreateDraftRequest.model_validate(value) if value else None

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
