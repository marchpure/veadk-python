"""Repository ports and a durable local SQL implementation for STEP 1.

The repository deliberately stores metadata and operation history only. Large
artifacts are represented by refs and belong in the Artifact Store port added
in the next contract wave.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Protocol

from .contracts import (
    BootstrapResponse,
    ErrorEnvelope,
    OperationEvent,
    OperationResponse,
    ResourceSummary,
    SkillDraft,
    SkillManifest,
    empty_knowledge_manifest,
    now_iso,
)


class KnowledgeAssetRepositoryError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, str] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable


class KnowledgeAssetRepository(Protocol):
    def bootstrap(self, workspace_id: str, role: str) -> BootstrapResponse: ...

    def draft(self, draft_id: str) -> SkillDraft | None: ...

    def current_pointer(self, *, object_type: str, object_id: str) -> int | None: ...

    def last_good_pointer(self, *, object_type: str, object_id: str) -> int | None: ...

    def create_skill_draft(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str,
        source_refs: list[str],
        request_id: str,
        idempotency_key: str,
    ) -> tuple[SkillDraft, bool]: ...

    def save_manifest(
        self,
        *,
        draft_id: str,
        base_revision: int,
        manifest: SkillManifest,
        request_id: str,
        idempotency_key: str,
    ) -> tuple[SkillDraft, bool]: ...

    def record_audit(
        self,
        *,
        request_id: str,
        operation_id: str,
        workspace_id: str,
        action: str,
        resource_id: str,
        outcome: str,
        details: dict[str, str] | None = None,
    ) -> None: ...

    def audit_events(self, operation_id: str) -> list[dict[str, object]]: ...

    def create_operation(self, operation_id: str, request_id: str) -> None: ...

    def operation(self, operation_id: str) -> OperationResponse | None: ...

    def append_operation_event(
        self,
        operation_id: str,
        event: OperationEvent,
        *,
        status: str,
        result: dict[str, object] | None = None,
        error: ErrorEnvelope | None = None,
    ) -> None: ...

    def cancel_operation(self, operation_id: str, request_id: str) -> OperationResponse: ...


class SqliteKnowledgeAssetRepository:
    """SQL-backed repository used by local Studio and contract environments."""

    def __init__(self, path: str | Path = ".veadk/knowledge-assets.sqlite3") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        migration = Path(__file__).with_name("migrations").joinpath(
            "001_knowledge_assets.sql"
        )
        self._connection.executescript(migration.read_text(encoding="utf-8"))

    def bootstrap(self, workspace_id: str, role: str) -> BootstrapResponse:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, workspace_id, name, revision, created_at, updated_at
                FROM skill_drafts WHERE workspace_id = ? ORDER BY created_at
                """,
                (workspace_id,),
            ).fetchall()
        resources = [
            ResourceSummary(
                id=row["id"],
                display_name=row["name"],
                space="team" if role == "admin" else "personal",
                revision=row["revision"],
            )
            for row in rows
        ]
        return BootstrapResponse(
            resources=resources,
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
        self,
        *,
        workspace_id: str,
        name: str,
        description: str,
        source_refs: list[str],
        request_id: str,
        idempotency_key: str,
    ) -> tuple[SkillDraft, bool]:
        del source_refs
        with self._lock:
            existing = self._connection.execute(
                """
                SELECT result_json FROM idempotency_keys
                WHERE scope = 'skill-draft.create' AND key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                return SkillDraft.model_validate(json.loads(existing["result_json"])), True
            draft_id = f"skill-draft-{uuid.uuid4()}"
            timestamp = now_iso()
            draft = SkillDraft(
                id=draft_id,
                workspace_id=workspace_id,
                name=name.strip(),
                description=description.strip(),
                revision=1,
                created_at=timestamp,
                updated_at=timestamp,
                manifest=empty_knowledge_manifest(
                    draft_id=draft_id,
                    workspace_id=workspace_id,
                    name=name.strip(),
                    description=description.strip(),
                ),
            )
            self._connection.execute(
                """
                INSERT INTO skill_drafts
                (id, workspace_id, name, description, revision, created_at, updated_at, manifest_json)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.workspace_id,
                    draft.name,
                    draft.description,
                    timestamp,
                    timestamp,
                    draft.manifest.model_dump_json(by_alias=True),
                ),
            )
            self._connection.execute(
                """
                INSERT INTO skill_draft_revisions
                (draft_id, skill_id, revision, manifest_json, status, created_at)
                VALUES (?, ?, 1, ?, 'draft', ?)
                """,
                (
                    draft.id,
                    draft.id,
                    draft.manifest.model_dump_json(by_alias=True),
                    timestamp,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO object_pointers
                (object_type, object_id, current_revision, last_good_revision)
                VALUES ('skill_draft', ?, 1, 1)
                """,
                (draft.id,),
            )
            self._connection.execute(
                """
                INSERT INTO idempotency_keys (scope, key, result_json)
                VALUES ('skill-draft.create', ?, ?)
                """,
                (idempotency_key, draft.model_dump_json(by_alias=True)),
            )
        return draft, False

    def draft(self, draft_id: str) -> SkillDraft | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, workspace_id, name, description, revision,
                       created_at, updated_at, manifest_json
                FROM skill_drafts WHERE id = ?
                """,
                (draft_id,),
            ).fetchone()
        if row is None:
            return None
        return SkillDraft(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row["description"],
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            manifest=SkillManifest.model_validate(json.loads(row["manifest_json"])),
        )

    def save_manifest(
        self,
        *,
        draft_id: str,
        base_revision: int,
        manifest: SkillManifest,
        request_id: str,
        idempotency_key: str,
    ) -> tuple[SkillDraft, bool]:
        del request_id
        with self._lock:
            existing = self._connection.execute(
                """
                SELECT result_json FROM idempotency_keys
                WHERE scope = 'skill-draft.save-manifest' AND key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                return SkillDraft.model_validate(json.loads(existing["result_json"])), True
            row = self._connection.execute(
                """
                SELECT id, workspace_id, name, description, revision,
                       created_at, updated_at, manifest_json
                FROM skill_drafts WHERE id = ?
                """,
                (draft_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetRepositoryError(
                    "DRAFT_NOT_FOUND",
                    "Skill 草稿不存在。",
                    details={"draftId": draft_id},
                )
            if row["revision"] != base_revision:
                raise KnowledgeAssetRepositoryError(
                    "CONFLICT",
                    "Skill 草稿版本已变化，请刷新后重试。",
                    details={
                        "draftId": draft_id,
                        "expectedRevision": str(base_revision),
                        "actualRevision": str(row["revision"]),
                    },
                )
            timestamp = now_iso()
            next_revision = row["revision"] + 1
            self._connection.execute(
                """
                UPDATE skill_drafts
                SET name = ?, description = ?, revision = ?, updated_at = ?,
                    manifest_json = ?
                WHERE id = ?
                """,
                (
                    manifest.metadata.display_name,
                    manifest.metadata.description,
                    next_revision,
                    timestamp,
                    manifest.model_dump_json(by_alias=True),
                    draft_id,
                ),
            )
            draft = SkillDraft(
                id=row["id"],
                workspace_id=row["workspace_id"],
                name=manifest.metadata.display_name,
                description=manifest.metadata.description,
                revision=next_revision,
                created_at=row["created_at"],
                updated_at=timestamp,
                manifest=manifest,
            )
            self._connection.execute(
                """
                INSERT INTO idempotency_keys (scope, key, result_json)
                VALUES ('skill-draft.save-manifest', ?, ?)
                """,
                (idempotency_key, draft.model_dump_json(by_alias=True)),
            )
            self._connection.execute(
                """
                INSERT INTO skill_draft_revisions
                (draft_id, skill_id, revision, manifest_json, status, created_at)
                VALUES (?, ?, ?, ?, 'draft', ?)
                """,
                (
                    draft_id,
                    draft_id,
                    next_revision,
                    manifest.model_dump_json(by_alias=True),
                    timestamp,
                ),
            )
            self._connection.execute(
                """
                UPDATE object_pointers
                SET current_revision = ?, last_good_revision = ?
                WHERE object_type = 'skill_draft' AND object_id = ?
                """,
                (next_revision, next_revision, draft_id),
            )
        return draft, False

    def current_pointer(self, *, object_type: str, object_id: str) -> int | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT current_revision FROM object_pointers
                WHERE object_type = ? AND object_id = ?
                """,
                (object_type, object_id),
            ).fetchone()
        return row["current_revision"] if row else None

    def last_good_pointer(self, *, object_type: str, object_id: str) -> int | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT last_good_revision FROM object_pointers
                WHERE object_type = ? AND object_id = ?
                """,
                (object_type, object_id),
            ).fetchone()
        return row["last_good_revision"] if row else None

    def record_audit(
        self,
        *,
        request_id: str,
        operation_id: str,
        workspace_id: str,
        action: str,
        resource_id: str,
        outcome: str,
        details: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO audit_events
                (request_id, operation_id, workspace_id, action, resource_id,
                 outcome, details_json, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    operation_id,
                    workspace_id,
                    action,
                    resource_id,
                    outcome,
                    json.dumps(details or {}, sort_keys=True),
                    now_iso(),
                ),
            )

    def audit_events(self, operation_id: str) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT request_id, operation_id, workspace_id, action,
                       resource_id, outcome, details_json, occurred_at
                FROM audit_events WHERE operation_id = ? ORDER BY id
                """,
                (operation_id,),
            ).fetchall()
        return [
            {
                "requestId": row["request_id"],
                "operationId": row["operation_id"],
                "workspaceId": row["workspace_id"],
                "action": row["action"],
                "resourceId": row["resource_id"],
                "outcome": row["outcome"],
                "details": json.loads(row["details_json"]),
                "occurredAt": row["occurred_at"],
            }
            for row in rows
        ]

    def operation(self, operation_id: str) -> OperationResponse | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT operation_id, status, version, result_json, error_json
                FROM operations WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if not row:
                return None
            event_rows = self._connection.execute(
                """
                SELECT event_json FROM operation_events
                WHERE operation_id = ? ORDER BY sequence
                """,
                (operation_id,),
            ).fetchall()
        return OperationResponse(
            operation_id=row["operation_id"],
            status=row["status"],
            version=row["version"],
            events=[
                OperationEvent.model_validate(json.loads(item["event_json"]))
                for item in event_rows
            ],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=(
                ErrorEnvelope.model_validate(json.loads(row["error_json"]))
                if row["error_json"]
                else None
            ),
            audit=self.audit_events(operation_id),
        )

    def create_operation(self, operation_id: str, request_id: str) -> None:
        del request_id
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO operations (operation_id, status, version)
                VALUES (?, 'accepted', 1)
                """,
                (operation_id,),
            )

    def append_operation_event(
        self,
        operation_id: str,
        event: OperationEvent,
        *,
        status: str,
        result: dict[str, object] | None = None,
        error: ErrorEnvelope | None = None,
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO operation_events
                (operation_id, sequence, event_json) VALUES (?, ?, ?)
                """,
                (operation_id, event.sequence, event.model_dump_json()),
            )
            self._connection.execute(
                """
                UPDATE operations SET status = ?, version = version + 1,
                result_json = ?, error_json = ? WHERE operation_id = ?
                """,
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    error.model_dump_json() if error else None,
                    operation_id,
                ),
            )

    def cancel_operation(self, operation_id: str, request_id: str) -> OperationResponse:
        operation = self.operation(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        if operation.status in {"succeeded", "failed", "cancelled"}:
            return operation
        event = OperationEvent(
            operation_id=operation_id,
            event_id=f"{operation_id}:cancelled",
            sequence=len(operation.events) + 1,
            occurred_at=now_iso(),
            type="cancelled",
            terminal=True,
        )
        self.append_operation_event(
            operation_id,
            event,
            status="cancelled",
        )
        result = self.operation(operation_id)
        assert result is not None
        return result
