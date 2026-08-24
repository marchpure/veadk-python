"""PostgreSQL repository adapter for durable Knowledge Asset metadata.

The local SQLite adapter remains the isolated test/demo implementation. This
adapter uses psycopg and the PostgreSQL migration for production metadata,
operations, idempotency, and audit state.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .contracts import (
    BootstrapResponse,
    ErrorEnvelope,
    OperationEvent,
    OperationResponse,
    ResourceSummary,
    SkillDraft,
    SkillManifest,
    now_iso,
)
from .repository import KnowledgeAssetRepositoryError


class PostgresKnowledgeAssetRepository:
    """Production PostgreSQL implementation of the Knowledge Asset repository."""

    def __init__(self, dsn: str) -> None:
        self._connection = psycopg.connect(dsn, row_factory=dict_row)
        self._connection.autocommit = True
        self._lock = threading.RLock()
        migration = Path(__file__).with_name("migrations").joinpath(
            "001_knowledge_assets.postgresql.sql"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8"))

    def bootstrap(self, workspace_id: str, role: str) -> BootstrapResponse:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, revision FROM skill_drafts
                WHERE workspace_id = %s ORDER BY created_at
                """,
                (workspace_id,),
            )
            rows = cursor.fetchall()
        return BootstrapResponse(
            resources=[
                ResourceSummary(
                    id=row["id"],
                    display_name=row["name"],
                    space="team" if role == "admin" else "personal",
                    revision=row["revision"],
                )
                for row in rows
            ],
            connections=[],
            publications=[],
            routes=["welcome", "add_kb", "skill_builder"],
            workspace_data={
                "connectorCatalog": [],
                "datasetFields": [],
                "dashboard": {"kpis": [], "trendData": []},
                "knowledgeGraph": {"entities": [], "mappings": []},
            },
            action_loop={
                "signals": [],
                "policies": [],
                "todos": [],
                "reviews": [],
                "briefs": [],
            },
            access={
                "spaceId": workspace_id,
                "role": role,
                "capabilities": ["skill-draft.create", "skill-draft.save-manifest"],
            },
            server_time=now_iso(),
        )

    def create_skill_draft(
        self, *, workspace_id: str, name: str, description: str,
        source_refs: list[str], request_id: str, idempotency_key: str,
    ) -> tuple[SkillDraft, bool]:
        del source_refs, request_id
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT result_json FROM idempotency_keys WHERE scope = %s AND key = %s",
                ("skill-draft.create", idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                return SkillDraft.model_validate(existing["result_json"]), True
            draft_id = f"skill-draft-{uuid.uuid4()}"
            timestamp = now_iso()
            draft = SkillDraft(
                id=draft_id, workspace_id=workspace_id, name=name.strip(),
                description=description.strip(), revision=1, created_at=timestamp,
                updated_at=timestamp,
                manifest=SkillManifest(
                    name=name.strip(), version="1.0.0",
                    description=description.strip(), actions=[],
                ),
            )
            cursor.execute(
                """
                INSERT INTO skill_drafts
                (id, workspace_id, name, description, revision, created_at,
                 updated_at, manifest_json)
                VALUES (%s, %s, %s, %s, 1, %s, %s, %s::jsonb)
                """,
                (draft.id, draft.workspace_id, draft.name, draft.description,
                 timestamp, timestamp, json.dumps(draft.manifest.model_dump(mode="json"))),
            )
            cursor.execute(
                """
                INSERT INTO idempotency_keys (scope, key, result_json)
                VALUES (%s, %s, %s::jsonb)
                """,
                ("skill-draft.create", idempotency_key,
                 json.dumps(draft.model_dump(mode="json"))),
            )
        return draft, False

    def save_manifest(
        self, *, draft_id: str, base_revision: int, manifest: SkillManifest,
        request_id: str, idempotency_key: str,
    ) -> tuple[SkillDraft, bool]:
        del request_id
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT result_json FROM idempotency_keys WHERE scope = %s AND key = %s",
                ("skill-draft.save-manifest", idempotency_key),
            )
            existing = cursor.fetchone()
            if existing:
                return SkillDraft.model_validate(existing["result_json"]), True
            cursor.execute(
                """
                SELECT id, workspace_id, name, description, revision,
                       created_at, updated_at
                FROM skill_drafts WHERE id = %s FOR UPDATE
                """,
                (draft_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KnowledgeAssetRepositoryError("DRAFT_NOT_FOUND", "Skill 草稿不存在。")
            if row["revision"] != base_revision:
                raise KnowledgeAssetRepositoryError(
                    "CONFLICT", "Skill 草稿版本已变化，请刷新后重试。",
                    details={
                        "draftId": draft_id,
                        "expectedRevision": str(base_revision),
                        "actualRevision": str(row["revision"]),
                    },
                )
            timestamp = now_iso()
            next_revision = row["revision"] + 1
            cursor.execute(
                """
                UPDATE skill_drafts
                SET name = %s, description = %s, revision = %s,
                    updated_at = %s, manifest_json = %s::jsonb
                WHERE id = %s
                """,
                (manifest.name, manifest.description, next_revision, timestamp,
                 json.dumps(manifest.model_dump(mode="json")), draft_id),
            )
            draft = SkillDraft(
                id=row["id"], workspace_id=row["workspace_id"], name=manifest.name,
                description=manifest.description, revision=next_revision,
                created_at=row["created_at"].isoformat(),
                updated_at=timestamp, manifest=manifest,
            )
            cursor.execute(
                """
                INSERT INTO idempotency_keys (scope, key, result_json)
                VALUES (%s, %s, %s::jsonb)
                """,
                ("skill-draft.save-manifest", idempotency_key,
                 json.dumps(draft.model_dump(mode="json"))),
            )
        return draft, False

    def record_audit(self, *, request_id: str, operation_id: str,
                     workspace_id: str, action: str, resource_id: str,
                     outcome: str, details: dict[str, str] | None = None) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events
                (request_id, operation_id, workspace_id, action, resource_id,
                 outcome, details_json, occurred_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (request_id, operation_id, workspace_id, action, resource_id,
                 outcome, json.dumps(details or {}), now_iso()),
            )

    def audit_events(self, operation_id: str) -> list[dict[str, object]]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, operation_id, workspace_id, action,
                       resource_id, outcome, details_json, occurred_at
                FROM audit_events WHERE operation_id = %s ORDER BY id
                """,
                (operation_id,),
            )
            rows = cursor.fetchall()
        return [
            {
                "requestId": row["request_id"], "operationId": row["operation_id"],
                "workspaceId": row["workspace_id"], "action": row["action"],
                "resourceId": row["resource_id"], "outcome": row["outcome"],
                "details": row["details_json"], "occurredAt": row["occurred_at"].isoformat(),
            }
            for row in rows
        ]

    def operation(self, operation_id: str) -> OperationResponse | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT operation_id, status, version, result_json, error_json "
                "FROM operations WHERE operation_id = %s",
                (operation_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                "SELECT event_json FROM operation_events WHERE operation_id = %s "
                "ORDER BY sequence",
                (operation_id,),
            )
            events = cursor.fetchall()
        return OperationResponse(
            operation_id=row["operation_id"], status=row["status"],
            version=row["version"],
            events=[OperationEvent.model_validate(item["event_json"]) for item in events],
            result=row["result_json"], error=(
                ErrorEnvelope.model_validate(row["error_json"])
                if row["error_json"] else None
            ),
            audit=self.audit_events(operation_id),
        )

    def create_operation(self, operation_id: str, request_id: str) -> None:
        del request_id
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operations (operation_id, status, version)
                VALUES (%s, 'accepted', 1) ON CONFLICT (operation_id) DO NOTHING
                """,
                (operation_id,),
            )

    def append_operation_event(self, operation_id: str, event: OperationEvent,
                               *, status: str,
                               result: dict[str, object] | None = None,
                               error: ErrorEnvelope | None = None) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operation_events
                (operation_id, sequence, event_json) VALUES (%s, %s, %s::jsonb)
                """,
                (operation_id, event.sequence, event.model_dump_json()),
            )
            cursor.execute(
                """
                UPDATE operations SET status = %s, version = version + 1,
                    result_json = %s::jsonb, error_json = %s::jsonb
                WHERE operation_id = %s
                """,
                (status, json.dumps(result) if result is not None else None,
                 error.model_dump_json() if error else None, operation_id),
            )

    def cancel_operation(self, operation_id: str, request_id: str) -> OperationResponse:
        del request_id
        operation = self.operation(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status in {"succeeded", "failed", "cancelled"}:
            return operation
        event = OperationEvent(
            operation_id=operation_id, event_id=f"{operation_id}:cancelled",
            sequence=len(operation.events) + 1, occurred_at=now_iso(),
            type="cancelled", terminal=True,
        )
        self.append_operation_event(operation_id, event, status="cancelled")
        result = self.operation(operation_id)
        assert result is not None
        return result
