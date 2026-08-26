"""Repository ports and a durable local SQL implementation for STEP 1.

The repository deliberately stores metadata and operation history only. Large
artifacts are represented by refs and belong in the Artifact Store port added
in the next contract wave.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Protocol

from ..contracts import (
    BootstrapResponse,
    BootstrapConnection,
    ErrorEnvelope,
    OperationEvent,
    OperationResponse,
    ResourceSummary,
    SkillDraft,
    SkillDraftRevision,
    SkillManifest,
    CleanRun,
    CleaningRecipe,
    GoldenAssetRevision,
    ProfileRun,
    RefreshRun,
    SkillResult,
    SkillViewRevision,
    SkillViewShareGrant,
    EvaluationSuite,
    EvaluationRun,
    PolicyGateResult,
    Invocation,
    PublishedSkillVersion,
    SourceRevision,
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
    def skill_draft_revision(
        self, draft_id: str, revision: int
    ) -> SkillDraftRevision | None: ...

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

    def sync_authoring_draft(self, *, draft: SkillDraft, status: str) -> None: ...

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

    def cancel_operation(
        self, operation_id: str, request_id: str
    ) -> OperationResponse: ...

    def source_revision(self, source_revision_id: str) -> SourceRevision | None: ...
    def save_source_revision(
        self, revision: SourceRevision, workspace_id: str, source_path: str
    ) -> None: ...
    def source_revisions_for_workspace(
        self, workspace_id: str
    ) -> list[SourceRevision]: ...
    def save_profile_run(self, run: ProfileRun) -> None: ...
    def save_cleaning_recipe(self, recipe: CleaningRecipe) -> None: ...
    def save_clean_run(self, run: CleanRun) -> None: ...
    def save_golden_asset_revision(
        self, revision: GoldenAssetRevision
    ) -> GoldenAssetRevision: ...
    def latest_golden_asset_revision(
        self, workspace_id: str
    ) -> GoldenAssetRevision | None: ...
    def revoke_asset(
        self, asset_id: str, workspace_id: str, request_id: str, reason: str
    ) -> None: ...
    def save_refresh_run(self, run: RefreshRun) -> None: ...
    def save_skill_result(self, result: SkillResult) -> None: ...
    def latest_skill_result(
        self, skill_id: str, skill_revision: int
    ) -> SkillResult | None: ...
    def latest_skill_view_revision(
        self, skill_revision_id: str
    ) -> SkillViewRevision | None: ...
    def latest_dashboard_view(self, workspace_id: str) -> SkillViewRevision | None: ...
    def save_skill_view_revision(self, revision: SkillViewRevision) -> None: ...
    def skill_view_revision(self, revision_id: str) -> SkillViewRevision | None: ...
    def update_skill_draft_revision_status(
        self, draft_id: str, revision: int, status: str
    ) -> None: ...
    def save_evaluation_suite(self, suite: EvaluationSuite) -> None: ...
    def save_evaluation_run(self, run: EvaluationRun) -> None: ...
    def evaluation_run(self, run_id: str) -> EvaluationRun | None: ...
    def latest_evaluation_run(self, skill_revision_id: str) -> EvaluationRun | None: ...
    def save_policy_gate_result(self, result: PolicyGateResult) -> None: ...
    def policy_gate_result(self, result_id: str) -> PolicyGateResult | None: ...
    def save_published_skill_version(self, version: PublishedSkillVersion) -> None: ...
    def published_skill_version(
        self, version_id: str
    ) -> PublishedSkillVersion | None: ...
    def published_skill_versions_for_workspace(
        self, workspace_id: str
    ) -> list[PublishedSkillVersion]: ...
    def save_invocation(self, invocation: Invocation) -> None: ...
    def save_skill_view_share(self, grant: SkillViewShareGrant) -> None: ...
    def save_patch_history(
        self,
        patch_id: str,
        undo_token: str,
        skill_id: str,
        base_revision: int,
        operation: str,
        before: str,
        after: str,
    ) -> None: ...
    def patch_history(self, undo_token: str) -> dict[str, object] | None: ...


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
        migration_dir = Path(__file__).parents[1].joinpath("migrations")
        self._connection.executescript(
            (migration_dir / "001_knowledge_assets.sql").read_text(encoding="utf-8")
        )
        applied = {
            row["version"]
            for row in self._connection.execute("SELECT version FROM schema_migrations")
        }
        for migration in sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql")):
            if migration.name.endswith(".postgresql.sql"):
                continue
            version = migration.stem
            if version in applied:
                continue
            self._connection.executescript(migration.read_text(encoding="utf-8"))
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(profile_runs)")
        }
        additions = {
            "structure_ref_json": "TEXT",
            "sensitive_classification_json": "TEXT NOT NULL DEFAULT '[]'",
            "estimated_cost_ref_json": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                self._connection.execute(
                    f"ALTER TABLE profile_runs ADD COLUMN {name} {definition}"
                )

    def bootstrap(self, workspace_id: str, role: str) -> BootstrapResponse:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, workspace_id, name, revision, created_at, updated_at
                FROM skill_drafts WHERE workspace_id = ? ORDER BY created_at
                """,
                (workspace_id,),
            ).fetchall()
            published_rows = self._connection.execute(
                """
                SELECT p.version_json
                FROM published_skill_versions AS p
                JOIN skill_drafts AS d ON d.id = p.skill_id
                WHERE d.workspace_id = ? AND json_extract(p.version_json, '$.status') = 'published'
                ORDER BY p.created_at
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
        resources.extend(
            ResourceSummary(
                id=version.id,
                display_name=version.manifest.metadata.display_name,
                resource_kind="published_skill",
                subtype="skill",
                space="team" if role == "admin" else "personal",
                lifecycle="ready",
                version=version.semver,
                revision=int(version.skill_revision_id.rsplit(":", 1)[-1]),
                permission=True,
            )
            for row in published_rows
            for version in [
                PublishedSkillVersion.model_validate(json.loads(row["version_json"]))
            ]
        )
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
            resources=resources,
            connections=[
                BootstrapConnection(
                    id="local-markdown",
                    workspace_id=workspace_id,
                    connector_key="markdown",
                    display_name="Local Markdown",
                    scope="team" if role == "admin" else "personal",
                    owner_id=workspace_id,
                    status="ready",
                    sync_mode="local",
                    created_at=now_iso(),
                    updated_at=now_iso(),
                ),
                BootstrapConnection(
                    id="local-csv",
                    workspace_id=workspace_id,
                    connector_key="csv",
                    display_name="Local CSV",
                    scope="team" if role == "admin" else "personal",
                    owner_id=workspace_id,
                    status="ready",
                    sync_mode="local",
                    created_at=now_iso(),
                    updated_at=now_iso(),
                ),
            ],
            publications=[
                {
                    "id": version.id,
                    "skillId": version.skill_id,
                    "revision": version.skill_revision_id.rsplit(":", 1)[-1],
                    "version": version.semver,
                    "status": version.status,
                }
                for row in published_rows
                for version in [
                    PublishedSkillVersion.model_validate(
                        json.loads(row["version_json"])
                    )
                ]
            ],
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
                "capabilities": [
                    "skill-draft.create",
                    "skill-draft.save-manifest",
                    "source.profile",
                    "source.clean",
                    "skill-draft.run",
                ],
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
        with self._lock:
            existing = self._connection.execute(
                """
                SELECT result_json FROM idempotency_keys
                WHERE scope = 'skill-draft.create' AND key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                return SkillDraft.model_validate(
                    json.loads(existing["result_json"])
                ), True
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
            for source_ref in source_refs:
                self._connection.execute(
                    "INSERT OR IGNORE INTO contract_objects "
                    "(object_type, object_id, metadata_json, relation_json, status) "
                    "VALUES ('source_ref', ?, ?, ?, 'attached')",
                    (draft.id, json.dumps({"sourceRef": source_ref}), "{}"),
                )
        return draft, False

    def sync_authoring_draft(self, *, draft: SkillDraft, status: str) -> None:
        """Idempotently bridge the W2 typed draft into MAIN lifecycle storage."""
        with self._lock:
            manifest_json = draft.manifest.model_dump_json(by_alias=True)
            self._connection.execute(
                """
                INSERT INTO skill_drafts
                (id, workspace_id, name, description, revision, created_at, updated_at, manifest_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    workspace_id=excluded.workspace_id, name=excluded.name,
                    description=excluded.description, revision=excluded.revision,
                    updated_at=excluded.updated_at, manifest_json=excluded.manifest_json
                """,
                (
                    draft.id,
                    draft.workspace_id,
                    draft.name,
                    draft.description,
                    draft.revision,
                    draft.created_at,
                    draft.updated_at,
                    manifest_json,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO skill_draft_revisions
                (draft_id, skill_id, revision, manifest_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id, revision) DO UPDATE SET
                    manifest_json=excluded.manifest_json, status=excluded.status
                """,
                (
                    draft.id,
                    draft.id,
                    draft.revision,
                    manifest_json,
                    status,
                    draft.updated_at,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO object_pointers
                (object_type, object_id, current_revision, last_good_revision)
                VALUES ('skill_draft', ?, ?, ?)
                ON CONFLICT(object_type, object_id) DO UPDATE SET
                    current_revision=excluded.current_revision,
                    last_good_revision=excluded.last_good_revision
                """,
                (draft.id, draft.revision, draft.revision),
            )

    def save_source_revision(
        self, revision: SourceRevision, workspace_id: str, source_path: str
    ) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT INTO source_revisions
                (id, workspace_id, source_type, content_ref_json, schema_ref_json,
                 permission_ref_json, source_digest, source_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING""",
                (
                    revision.id,
                    workspace_id,
                    revision.source_type,
                    revision.content_ref.model_dump_json(by_alias=True),
                    revision.schema_ref.model_dump_json(by_alias=True)
                    if revision.schema_ref
                    else None,
                    revision.permission_ref.model_dump_json(by_alias=True),
                    revision.source_digest,
                    source_path,
                    revision.created_at,
                ),
            )

    def source_revision(self, source_revision_id: str) -> SourceRevision | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM source_revisions WHERE id = ?", (source_revision_id,)
            ).fetchone()
        if row is None:
            return None
        return SourceRevision(
            id=row["id"],
            source_type=row["source_type"],
            content_ref=json.loads(row["content_ref_json"]),
            schema_ref=json.loads(row["schema_ref_json"])
            if row["schema_ref_json"]
            else None,
            permission_ref=json.loads(row["permission_ref_json"]),
            source_digest=row["source_digest"],
            created_at=row["created_at"],
        )

    def source_path(self, source_revision_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT source_path FROM source_revisions WHERE id = ?",
                (source_revision_id,),
            ).fetchone()
        return row["source_path"] if row else None

    def source_workspace(self, source_revision_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT workspace_id FROM source_revisions WHERE id = ?",
                (source_revision_id,),
            ).fetchone()
        return row["workspace_id"] if row else None

    def source_revisions_for_workspace(self, workspace_id: str) -> list[SourceRevision]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM source_revisions WHERE workspace_id = ? ORDER BY created_at",
                (workspace_id,),
            ).fetchall()
        return [
            SourceRevision(
                id=row["id"],
                source_type=row["source_type"],
                content_ref=json.loads(row["content_ref_json"]),
                schema_ref=json.loads(row["schema_ref_json"])
                if row["schema_ref_json"]
                else None,
                permission_ref=json.loads(row["permission_ref_json"]),
                source_digest=row["source_digest"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_profile_run(self, run: ProfileRun) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO profile_runs
                (id, source_revision_id, status, sample_ref_json, report_ref_json,
                 structure_ref_json, quality_score, sensitive_classification_json,
                 estimated_cost_ref_json, error_code, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.source_revision_id,
                    run.status,
                    run.sample_ref.model_dump_json(by_alias=True)
                    if run.sample_ref
                    else None,
                    run.report_ref.model_dump_json(by_alias=True)
                    if run.report_ref
                    else None,
                    run.structure_ref.model_dump_json(by_alias=True)
                    if run.structure_ref
                    else None,
                    run.quality_score,
                    json.dumps(run.sensitive_classification),
                    run.estimated_cost_ref.model_dump_json(by_alias=True)
                    if run.estimated_cost_ref
                    else None,
                    run.error_code,
                    run.started_at,
                    run.finished_at,
                ),
            )

    def save_refresh_run(self, run: RefreshRun) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO refresh_runs
                (id, skill_id, trigger, status, staging_ref_json, current_revision,
                 last_good_revision, error_code, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.skill_id,
                    run.trigger,
                    run.status,
                    run.staging_ref.model_dump_json(by_alias=True)
                    if run.staging_ref
                    else None,
                    run.current_revision,
                    run.last_good_revision,
                    run.error_code,
                    run.started_at,
                    run.finished_at,
                ),
            )

    def save_skill_result(self, result: SkillResult) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO skill_results
                (id, skill_id, skill_revision, result_json, result_ref_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
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
        with self._lock:
            row = self._connection.execute(
                """
                SELECT result_json FROM skill_results
                WHERE skill_id = ? AND skill_revision = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (skill_id, skill_revision),
            ).fetchone()
        return (
            SkillResult.model_validate(json.loads(row["result_json"]))
            if row is not None
            else None
        )

    def latest_skill_view_revision(
        self, skill_revision_id: str
    ) -> SkillViewRevision | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT view_json FROM skill_view_revisions
                WHERE skill_revision_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (skill_revision_id,),
            ).fetchone()
        return (
            SkillViewRevision.model_validate(json.loads(row["view_json"]))
            if row is not None
            else None
        )

    def latest_dashboard_view(self, workspace_id: str) -> SkillViewRevision | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT v.view_json
                FROM skill_view_revisions AS v
                JOIN skill_drafts AS d
                  ON d.id = substr(v.skill_revision_id, 1, instr(v.skill_revision_id, ':') - 1)
                WHERE d.workspace_id = ?
                  AND json_extract(v.view_json, '$.viewModel.template') IN ('dashboard', 'chart')
                ORDER BY v.created_at DESC LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        return (
            SkillViewRevision.model_validate(json.loads(row["view_json"]))
            if row is not None
            else None
        )

    def save_skill_view_revision(self, revision: SkillViewRevision) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO skill_view_revisions
                (id, skill_revision_id, revision, view_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    revision.id,
                    revision.skill_revision_id,
                    revision.revision,
                    revision.model_dump_json(by_alias=True),
                    revision.created_at,
                ),
            )

    def update_skill_draft_revision_status(
        self, draft_id: str, revision: int, status: str
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE skill_draft_revisions
                SET status = ?
                WHERE draft_id = ? AND revision = ?
                """,
                (status, draft_id, revision),
            )

    def save_evaluation_suite(self, suite: EvaluationSuite) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO evaluation_suites
                (id, version, skill_id, suite_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    suite.id,
                    suite.version,
                    suite.skill_id,
                    suite.model_dump_json(by_alias=True),
                ),
            )

    def save_evaluation_run(self, run: EvaluationRun) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO evaluation_runs
                (id, skill_revision_id, run_json)
                VALUES (?, ?, ?)
                """,
                (run.id, run.skill_revision_id, run.model_dump_json(by_alias=True)),
            )

    def evaluation_run(self, run_id: str) -> EvaluationRun | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT run_json FROM evaluation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return (
            EvaluationRun.model_validate(json.loads(row["run_json"]))
            if row is not None
            else None
        )

    def latest_evaluation_run(self, skill_revision_id: str) -> EvaluationRun | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT run_json FROM evaluation_runs
                WHERE skill_revision_id = ?
                ORDER BY rowid DESC LIMIT 1
                """,
                (skill_revision_id,),
            ).fetchone()
        return (
            EvaluationRun.model_validate(json.loads(row["run_json"]))
            if row is not None
            else None
        )

    def save_policy_gate_result(self, result: PolicyGateResult) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO policy_gate_results
                (id, skill_revision_id, result_json)
                VALUES (?, ?, ?)
                """,
                (
                    result.id,
                    result.skill_revision_id,
                    result.model_dump_json(by_alias=True),
                ),
            )

    def save_invocation(self, invocation: Invocation) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO invocations
                (id, skill_version_id, skill_view_revision_id, workspace_id,
                 invocation_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
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

    def policy_gate_result(self, result_id: str) -> PolicyGateResult | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT result_json FROM policy_gate_results WHERE id = ?",
                (result_id,),
            ).fetchone()
        return (
            PolicyGateResult.model_validate(json.loads(row["result_json"]))
            if row is not None
            else None
        )

    def save_published_skill_version(self, version: PublishedSkillVersion) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO published_skill_versions
                (id, skill_id, skill_revision_id, semver, version_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version.id,
                    version.skill_id,
                    version.skill_revision_id,
                    version.semver,
                    version.model_dump_json(by_alias=True),
                    version.published_at,
                ),
            )

    def published_skill_version(self, version_id: str) -> PublishedSkillVersion | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT version_json FROM published_skill_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
        return (
            PublishedSkillVersion.model_validate(json.loads(row["version_json"]))
            if row is not None
            else None
        )

    def save_skill_view_share(self, grant: SkillViewShareGrant) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO skill_view_shares
                (id, resource_id, skill_view_revision_id, workspace_id, grant_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
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

    def skill_view_revision(self, revision_id: str) -> SkillViewRevision | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT view_json FROM skill_view_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        if row is None:
            return None
        return SkillViewRevision.model_validate(json.loads(row["view_json"]))

    def save_patch_history(
        self,
        patch_id: str,
        undo_token: str,
        skill_id: str,
        base_revision: int,
        operation: str,
        before: str,
        after: str,
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO assistant_patch_history
                (patch_id, undo_token, skill_id, base_revision, operation, before_value, after_value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patch_id,
                    undo_token,
                    skill_id,
                    base_revision,
                    operation,
                    before,
                    after,
                ),
            )

    def patch_history(self, undo_token: str) -> dict[str, object] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM assistant_patch_history WHERE undo_token = ?",
                (undo_token,),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_cleaning_recipe(self, recipe: CleaningRecipe) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO cleaning_recipes
                (id, version, operations_json, source_revision_id, recipe_digest)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    recipe.id,
                    recipe.version,
                    json.dumps(recipe.operations),
                    recipe.source_revision_id,
                    recipe.recipe_digest,
                ),
            )

    def save_clean_run(self, run: CleanRun) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO clean_runs
                (id, source_revision_id, recipe_id, status, output_ref_json,
                 quality_report_ref_json, error_code, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.source_revision_id,
                    run.recipe_id,
                    run.status,
                    run.output_ref.model_dump_json(by_alias=True)
                    if run.output_ref
                    else None,
                    run.quality_report_ref.model_dump_json(by_alias=True)
                    if run.quality_report_ref
                    else None,
                    run.error_code,
                    run.started_at,
                    run.finished_at,
                ),
            )

    def save_golden_asset_revision(
        self, revision: GoldenAssetRevision
    ) -> GoldenAssetRevision:
        with self._lock:
            next_revision = self._connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM golden_asset_revisions "
                "WHERE workspace_id = ? AND asset_kind = ?",
                (revision.owner.workspace_id, revision.asset_kind),
            ).fetchone()[0]
            revision = revision.model_copy(update={"revision": next_revision})
            existing_id = self._connection.execute(
                "SELECT 1 FROM golden_asset_revisions WHERE id = ?", (revision.id,)
            ).fetchone()
            if existing_id is not None:
                revision = revision.model_copy(
                    update={"id": f"{revision.id}-r{next_revision}"}
                )
            self._connection.execute(
                """INSERT INTO golden_asset_revisions
                (id, workspace_id, asset_kind, revision, schema_ref_json,
                 storage_ref_json, source_revision_refs_json, recipe_ref,
                 quality_run_ref, owner_json, permissions_ref_json, lineage_digest,
                 freshness_at, last_good)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    revision.id,
                    revision.owner.workspace_id,
                    revision.asset_kind,
                    revision.revision,
                    revision.schema_ref.model_dump_json(by_alias=True),
                    revision.storage_ref.model_dump_json(by_alias=True),
                    json.dumps(revision.source_revision_refs),
                    revision.recipe_ref,
                    revision.quality_run_ref,
                    revision.owner.model_dump_json(by_alias=True),
                    revision.permissions_ref.model_dump_json(by_alias=True),
                    revision.lineage_digest,
                    revision.freshness_at,
                    int(revision.last_good),
                ),
            )
        return revision

    def latest_golden_asset_revision(
        self, workspace_id: str
    ) -> GoldenAssetRevision | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM golden_asset_revisions WHERE workspace_id = ? "
                "AND id NOT IN (SELECT asset_id FROM asset_tombstones) "
                "ORDER BY revision DESC LIMIT 1",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return GoldenAssetRevision(
            id=row["id"],
            asset_kind=row["asset_kind"],
            revision=row["revision"],
            schema_ref=json.loads(row["schema_ref_json"]),
            storage_ref=json.loads(row["storage_ref_json"]),
            source_revision_refs=json.loads(row["source_revision_refs_json"]),
            recipe_ref=row["recipe_ref"],
            quality_run_ref=row["quality_run_ref"],
            owner=json.loads(row["owner_json"]),
            permissions_ref=json.loads(row["permissions_ref_json"]),
            lineage_digest=row["lineage_digest"],
            freshness_at=row["freshness_at"],
            last_good=bool(row["last_good"]),
        )

    def revoke_asset(
        self, asset_id: str, workspace_id: str, request_id: str, reason: str
    ) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO asset_tombstones
                (asset_id, workspace_id, reason, revoked_at, request_id)
                VALUES (?, ?, ?, ?, ?)""",
                (asset_id, workspace_id, reason, now_iso(), request_id),
            )

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

    def skill_draft_revision(
        self, draft_id: str, revision: int
    ) -> SkillDraftRevision | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT draft_id, skill_id, revision, manifest_json, status, created_at
                FROM skill_draft_revisions
                WHERE draft_id = ? AND revision = ?
                """,
                (draft_id, revision),
            ).fetchone()
        if row is None:
            return None
        return SkillDraftRevision(
            id=f"{row['draft_id']}:{row['revision']}",
            skill_id=row["skill_id"],
            revision=row["revision"],
            manifest=SkillManifest.model_validate(json.loads(row["manifest_json"])),
            status=row["status"],
            created_at=row["created_at"],
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
                return SkillDraft.model_validate(
                    json.loads(existing["result_json"])
                ), True
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
            current = self._connection.execute(
                "SELECT status FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if current is None:
                raise KeyError(operation_id)
            if current["status"] in {"succeeded", "failed", "cancelled"}:
                return
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
