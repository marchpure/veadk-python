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
    SkillResult,
    SkillViewRevision,
    SkillViewShareGrant,
    EvaluationSuite,
    EvaluationRun,
    PolicyGateResult,
    Invocation,
    empty_knowledge_manifest,
    now_iso,
)
from .repository import KnowledgeAssetRepositoryError


class PostgresKnowledgeAssetRepository:
    """Production PostgreSQL implementation of the Knowledge Asset repository."""

    def __init__(self, dsn: str) -> None:
        self._connection = psycopg.connect(dsn, row_factory=dict_row)
        self._connection.autocommit = True
        self._lock = threading.RLock()
        migration_dir = Path(__file__).with_name("migrations")
        with self._connection.cursor() as cursor:
            cursor.execute(
                (migration_dir / "001_knowledge_assets.postgresql.sql").read_text(
                    encoding="utf-8"
                )
            )
            cursor.execute("SELECT version FROM schema_migrations")
            applied = {row["version"] for row in cursor.fetchall()}
            for migration in sorted(
                migration_dir.glob("[0-9][0-9][0-9]_*.postgresql.sql")
            ):
                version = migration.stem.removesuffix(".postgresql")
                if version in applied:
                    continue
                cursor.execute(migration.read_text(encoding="utf-8"))

    def save_skill_result(self, result: SkillResult) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO skill_results
                (id, skill_id, skill_revision, result_json, result_ref_json, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    result.id,
                    result.skill_id,
                    result.skill_revision,
                    result.model_dump_json(by_alias=True),
                    result.result_ref.model_dump_json(by_alias=True),
                    result.freshness_at or now_iso(),
                ),
            )

    def latest_skill_result(
        self, skill_id: str, skill_revision: int
    ) -> SkillResult | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_json FROM skill_results
                WHERE skill_id = %s AND skill_revision = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (skill_id, skill_revision),
            )
            row = cursor.fetchone()
        return (
            SkillResult.model_validate(row["result_json"])
            if row is not None
            else None
        )

    def latest_skill_view_revision(
        self, skill_revision_id: str
    ) -> SkillViewRevision | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT view_json FROM skill_view_revisions
                WHERE skill_revision_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (skill_revision_id,),
            )
            row = cursor.fetchone()
        return (
            SkillViewRevision.model_validate(row["view_json"])
            if row is not None
            else None
        )

    def latest_dashboard_view(self, workspace_id: str) -> SkillViewRevision | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT v.view_json
                FROM skill_view_revisions AS v
                JOIN skill_drafts AS d
                  ON d.id = split_part(v.skill_revision_id, ':', 1)
                WHERE d.workspace_id = %s
                ORDER BY v.created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = cursor.fetchone()
        return (
            SkillViewRevision.model_validate(row["view_json"])
            if row is not None
            else None
        )

    def save_skill_view_revision(self, revision: SkillViewRevision) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO skill_view_revisions
                (id, skill_revision_id, revision, view_json, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                (
                    revision.id,
                    revision.skill_revision_id,
                    revision.revision,
                    revision.model_dump_json(by_alias=True),
                    revision.created_at,
                ),
            )

    def skill_view_revision(self, revision_id: str) -> SkillViewRevision | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT view_json FROM skill_view_revisions WHERE id = %s",
                (revision_id,),
            )
            row = cursor.fetchone()
        return (
            SkillViewRevision.model_validate(row["view_json"])
            if row is not None
            else None
        )

    def update_skill_draft_revision_status(
        self, draft_id: str, revision: int, status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE skill_draft_revisions
                SET status = %s
                WHERE draft_id = %s AND revision = %s
                """,
                (status, draft_id, revision),
            )

    def save_evaluation_suite(self, suite: EvaluationSuite) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO evaluation_suites (id, version, skill_id, suite_json)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (id, version) DO UPDATE SET suite_json = EXCLUDED.suite_json
                """,
                (
                    suite.id,
                    suite.version,
                    suite.skill_id,
                    suite.model_dump_json(by_alias=True),
                ),
            )

    def save_evaluation_run(self, run: EvaluationRun) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO evaluation_runs (id, skill_revision_id, run_json)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET run_json = EXCLUDED.run_json
                """,
                (run.id, run.skill_revision_id, run.model_dump_json(by_alias=True)),
            )

    def save_policy_gate_result(self, result: PolicyGateResult) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO policy_gate_results (id, skill_revision_id, result_json)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET result_json = EXCLUDED.result_json
                """,
                (
                    result.id,
                    result.skill_revision_id,
                    result.model_dump_json(by_alias=True),
                ),
            )

    def save_invocation(self, invocation: Invocation) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO invocations
                (id, skill_version_id, skill_view_revision_id, workspace_id,
                 invocation_json, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET invocation_json = EXCLUDED.invocation_json
                """,
                (
                    invocation.id,
                    invocation.skill_version_id,
                    invocation.skill_view_revision_id,
                    invocation.workspace_id,
                    invocation.model_dump_json(by_alias=True),
                    invocation.started_at,
                ),
            )

    def save_skill_view_share(self, grant: SkillViewShareGrant) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO skill_view_shares
                (id, resource_id, skill_view_revision_id, workspace_id, grant_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET grant_json = EXCLUDED.grant_json
                """,
                (
                    grant.id,
                    grant.resource_id,
                    grant.skill_view_revision_id,
                    grant.workspace_id,
                    grant.model_dump_json(by_alias=True),
                    grant.created_at,
                ),
            )

    def save_patch_history(
        self, patch_id: str, undo_token: str, skill_id: str, base_revision: int,
        operation: str, before: str, after: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assistant_patch_history
                (patch_id, undo_token, skill_id, base_revision, operation, before_value, after_value)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (patch_id) DO UPDATE SET
                  undo_token = EXCLUDED.undo_token,
                  after_value = EXCLUDED.after_value
                """,
                (patch_id, undo_token, skill_id, base_revision, operation, before, after),
            )

    def patch_history(self, undo_token: str) -> dict[str, object] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM assistant_patch_history WHERE undo_token = %s",
                (undo_token,),
            )
            return cursor.fetchone()

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
        latest_view = self.latest_dashboard_view(workspace_id)
        workspace_data = {
            "connectorCatalog": [],
            "datasetFields": [],
            "dashboard": {"kpis": [], "trendData": []},
            "knowledgeGraph": {"entities": [], "mappings": []},
        }
        if latest_view is not None:
            workspace_data["skillViewRevision"] = latest_view.model_dump(
                mode="json", by_alias=True
            )
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
            workspace_data=workspace_data,
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

    def draft(self, draft_id: str) -> SkillDraft | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, workspace_id, name, description, revision,
                       created_at, updated_at, manifest_json
                FROM skill_drafts WHERE id = %s
                """,
                (draft_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return SkillDraft(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row["description"],
            revision=row["revision"],
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
            manifest=SkillManifest.model_validate(row["manifest_json"]),
        )

    def current_pointer(self, *, object_type: str, object_id: str) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_revision FROM object_pointers
                WHERE object_type = %s AND object_id = %s
                """,
                (object_type, object_id),
            )
            row = cursor.fetchone()
        return row["current_revision"] if row else None

    def last_good_pointer(self, *, object_type: str, object_id: str) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT last_good_revision FROM object_pointers
                WHERE object_type = %s AND object_id = %s
                """,
                (object_type, object_id),
            )
            row = cursor.fetchone()
        return row["last_good_revision"] if row else None

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
                manifest=empty_knowledge_manifest(
                    draft_id=draft_id,
                    workspace_id=workspace_id,
                    name=name.strip(),
                    description=description.strip(),
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
                 timestamp, timestamp,
                 json.dumps(draft.manifest.model_dump(mode="json", by_alias=True))),
            )
            cursor.execute(
                """
                INSERT INTO idempotency_keys (scope, key, result_json)
                VALUES (%s, %s, %s::jsonb)
                """,
                ("skill-draft.create", idempotency_key,
                 json.dumps(draft.model_dump(mode="json", by_alias=True))),
            )
            cursor.execute(
                """
                INSERT INTO skill_draft_revisions
                (draft_id, skill_id, revision, manifest_json, status, created_at)
                VALUES (%s, %s, 1, %s::jsonb, 'draft', %s)
                """,
                (
                    draft.id,
                    draft.id,
                    json.dumps(draft.manifest.model_dump(mode="json", by_alias=True)),
                    timestamp,
                ),
            )
            cursor.execute(
                """
                INSERT INTO object_pointers
                (object_type, object_id, current_revision, last_good_revision)
                VALUES ('skill_draft', %s, 1, 1)
                """,
                (draft.id,),
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
                (manifest.metadata.display_name, manifest.metadata.description,
                 next_revision, timestamp,
                 json.dumps(manifest.model_dump(mode="json", by_alias=True)), draft_id),
            )
            draft = SkillDraft(
                id=row["id"], workspace_id=row["workspace_id"],
                name=manifest.metadata.display_name,
                description=manifest.metadata.description, revision=next_revision,
                created_at=row["created_at"].isoformat(),
                updated_at=timestamp, manifest=manifest,
            )
            cursor.execute(
                """
                INSERT INTO idempotency_keys (scope, key, result_json)
                VALUES (%s, %s, %s::jsonb)
                """,
                ("skill-draft.save-manifest", idempotency_key,
                 json.dumps(draft.model_dump(mode="json", by_alias=True))),
            )
            cursor.execute(
                """
                INSERT INTO skill_draft_revisions
                (draft_id, skill_id, revision, manifest_json, status, created_at)
                VALUES (%s, %s, %s, %s::jsonb, 'draft', %s)
                """,
                (
                    draft_id,
                    draft_id,
                    next_revision,
                    json.dumps(manifest.model_dump(mode="json", by_alias=True)),
                    timestamp,
                ),
            )
            cursor.execute(
                """
                UPDATE object_pointers
                SET current_revision = %s, last_good_revision = %s
                WHERE object_type = 'skill_draft' AND object_id = %s
                """,
                (next_revision, next_revision, draft_id),
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
                "SELECT status FROM operations WHERE operation_id = %s FOR UPDATE",
                (operation_id,),
            )
            current = cursor.fetchone()
            if current is None:
                raise KeyError(operation_id)
            if current["status"] in {"succeeded", "failed", "cancelled"}:
                return
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
