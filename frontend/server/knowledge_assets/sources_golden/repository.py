"""Durable SQLite persistence private to the sources/Golden Data module."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .models import (
    CleaningRecipeRecord,
    CleanRunRecord,
    ConnectionInstance,
    GoldenAssetRevisionRecord,
    McpProcessTrace,
    ProfileRunRecord,
    RefreshRunRecord,
    SourceRevisionRecord,
)
from .repository_traces import ConnectorTraceRepositoryMixin


class SourcesGoldenRepository(ConnectorTraceRepositoryMixin):
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS source_connections (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    connector_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_source_connections_workspace
                    ON source_connections(workspace_id);
                CREATE TABLE IF NOT EXISTS source_connection_idempotency (
                    workspace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, idempotency_key),
                    FOREIGN KEY (connection_id) REFERENCES source_connections(id)
                );
                CREATE TABLE IF NOT EXISTS source_connector_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (connection_id) REFERENCES source_connections(id)
                );
                CREATE TABLE IF NOT EXISTS source_ingest_idempotency (
                    workspace_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    golden_revision_id TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS source_revision_records (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (workspace_id, connection_id, resource_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_source_revision_records_asset
                    ON source_revision_records(workspace_id, connection_id, resource_id);
                CREATE TABLE IF NOT EXISTS source_profile_runs (
                    id TEXT PRIMARY KEY,
                    source_revision_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_cleaning_recipes (
                    id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    asset_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (id, version)
                );
                CREATE TABLE IF NOT EXISTS source_clean_runs (
                    id TEXT PRIMARY KEY,
                    source_revision_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_golden_revisions (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    revoked_at TEXT,
                    UNIQUE (workspace_id, asset_id, revision)
                );
                CREATE INDEX IF NOT EXISTS idx_source_golden_current
                    ON source_golden_revisions(workspace_id, asset_id, revision DESC);
                CREATE TABLE IF NOT EXISTS source_refresh_runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (workspace_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS source_mcp_process_traces (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_mcp_trace_connection
                    ON source_mcp_process_traces(workspace_id, connection_id);
                CREATE TABLE IF NOT EXISTS source_connector_traces (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_source_connector_trace_connection
                    ON source_connector_traces(workspace_id, connection_id);
                CREATE TABLE IF NOT EXISTS source_connector_events (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (workspace_id, connection_id, sequence),
                    FOREIGN KEY (connection_id) REFERENCES source_connections(id)
                );
                CREATE INDEX IF NOT EXISTS idx_source_connector_events
                    ON source_connector_events(workspace_id, connection_id, sequence);
                """
            )

    def connection_for_idempotency(
        self, workspace_id: str, idempotency_key: str
    ) -> ConnectionInstance | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT c.payload_json
                FROM source_connection_idempotency i
                JOIN source_connections c ON c.id = i.connection_id
                WHERE i.workspace_id = ? AND i.idempotency_key = ?
                """,
                (workspace_id, idempotency_key),
            ).fetchone()
        return (
            ConnectionInstance.model_validate_json(row["payload_json"])
            if row is not None
            else None
        )

    def save_connection(
        self, connection: ConnectionInstance, *, idempotency_key: str
    ) -> None:
        payload = connection.model_dump_json(by_alias=True)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT INTO source_connections
                    (id, workspace_id, connector_key, payload_json, revoked_at)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (
                        connection.id,
                        connection.workspace_id,
                        connection.connector_key,
                        payload,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_connection_idempotency
                    (workspace_id, idempotency_key, connection_id)
                    VALUES (?, ?, ?)
                    """,
                    (
                        connection.workspace_id,
                        idempotency_key,
                        connection.id,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def connection(
        self, workspace_id: str, connection_id: str
    ) -> ConnectionInstance | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_connections
                WHERE workspace_id = ? AND id = ? AND revoked_at IS NULL
                """,
                (workspace_id, connection_id),
            ).fetchone()
        return (
            ConnectionInstance.model_validate_json(row["payload_json"])
            if row is not None
            else None
        )

    def connection_including_revoked(
        self, workspace_id: str, connection_id: str
    ) -> ConnectionInstance | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_connections
                WHERE workspace_id = ? AND id = ?
                """,
                (workspace_id, connection_id),
            ).fetchone()
        return (
            ConnectionInstance.model_validate_json(row["payload_json"])
            if row is not None
            else None
        )

    def update_connection(self, connection: ConnectionInstance) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE source_connections SET payload_json = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (
                    connection.model_dump_json(by_alias=True),
                    connection.workspace_id,
                    connection.id,
                ),
            )

    def connections(self, workspace_id: str) -> list[ConnectionInstance]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json FROM source_connections
                WHERE workspace_id = ? AND revoked_at IS NULL
                ORDER BY rowid
                """,
                (workspace_id,),
            ).fetchall()
        return [
            ConnectionInstance.model_validate_json(row["payload_json"]) for row in rows
        ]

    def record_operation(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        trace_id: str,
        operation: str,
        status: str,
        payload: dict[str, object],
        created_at: str,
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO source_connector_operations
                (workspace_id, connection_id, trace_id, operation, status,
                 payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    connection_id,
                    trace_id,
                    operation,
                    status,
                    json.dumps(payload, sort_keys=True),
                    created_at,
                ),
            )

    def ingest_for_idempotency(
        self, workspace_id: str, idempotency_key: str
    ) -> (
        tuple[
            SourceRevisionRecord,
            ProfileRunRecord,
            CleaningRecipeRecord,
            CleanRunRecord,
            GoldenAssetRevisionRecord,
        ]
        | None
    ):
        with self._lock:
            row = self._connection.execute(
                """
                SELECT golden_revision_id FROM source_ingest_idempotency
                WHERE workspace_id = ? AND idempotency_key = ?
                """,
                (workspace_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        golden = self.golden_revision(workspace_id, row["golden_revision_id"])
        if golden is None:
            return None
        source = self.source_revision(workspace_id, golden.lineage.source_revision_id)
        profile = self.profile_run(golden.lineage.profile_run_id)
        recipe = self.cleaning_recipe(
            golden.lineage.recipe_id, golden.lineage.recipe_version
        )
        clean = self.clean_run(golden.lineage.clean_run_id)
        assert source and profile and recipe and clean
        return source, profile, recipe, clean, golden

    def next_recipe_version(self, asset_id: str) -> int:
        with self._lock:
            return int(
                self._connection.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM source_cleaning_recipes WHERE asset_id = ?
                    """,
                    (asset_id,),
                ).fetchone()[0]
            )

    def next_golden_revision(self, workspace_id: str, asset_id: str) -> int:
        with self._lock:
            return int(
                self._connection.execute(
                    """
                    SELECT COALESCE(MAX(revision), 0) + 1
                    FROM source_golden_revisions
                    WHERE workspace_id = ? AND asset_id = ?
                    """,
                    (workspace_id, asset_id),
                ).fetchone()[0]
            )

    def save_ingest(
        self,
        *,
        source: SourceRevisionRecord,
        profile: ProfileRunRecord,
        recipe: CleaningRecipeRecord,
        clean: CleanRunRecord,
        golden: GoldenAssetRevisionRecord,
        idempotency_key: str,
    ) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO source_revision_records
                    (id, workspace_id, connection_id, resource_id, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source.id,
                        source.workspace_id,
                        source.connection_id,
                        source.resource_id,
                        source.model_dump_json(by_alias=True),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_profile_runs
                    (id, source_revision_id, payload_json) VALUES (?, ?, ?)
                    """,
                    (
                        profile.id,
                        profile.source_revision_id,
                        profile.model_dump_json(by_alias=True),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_cleaning_recipes
                    (id, version, asset_id, payload_json) VALUES (?, ?, ?, ?)
                    """,
                    (
                        recipe.id,
                        recipe.version,
                        recipe.asset_id,
                        recipe.model_dump_json(by_alias=True),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_clean_runs
                    (id, source_revision_id, payload_json) VALUES (?, ?, ?)
                    """,
                    (
                        clean.id,
                        clean.source_revision_id,
                        clean.model_dump_json(by_alias=True),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_golden_revisions
                    (id, workspace_id, asset_id, revision, payload_json, revoked_at)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        golden.id,
                        golden.owner.workspace_id,
                        golden.asset_id,
                        golden.revision,
                        golden.model_dump_json(by_alias=True),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO source_ingest_idempotency
                    (workspace_id, idempotency_key, golden_revision_id)
                    VALUES (?, ?, ?)
                    """,
                    (
                        golden.owner.workspace_id,
                        idempotency_key,
                        golden.id,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def source_revision(
        self, workspace_id: str, source_revision_id: str
    ) -> SourceRevisionRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_revision_records
                WHERE workspace_id = ? AND id = ?
                  AND EXISTS (
                    SELECT 1 FROM source_connections c
                    WHERE c.id = source_revision_records.connection_id
                      AND c.workspace_id = source_revision_records.workspace_id
                      AND c.revoked_at IS NULL
                  )
                """,
                (workspace_id, source_revision_id),
            ).fetchone()
        return (
            SourceRevisionRecord.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def profile_run(self, run_id: str) -> ProfileRunRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM source_profile_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return (
            ProfileRunRecord.model_validate_json(row["payload_json"]) if row else None
        )

    def cleaning_recipe(
        self, recipe_id: str, version: int | None = None
    ) -> CleaningRecipeRecord | None:
        with self._lock:
            if version is None:
                row = self._connection.execute(
                    """
                    SELECT payload_json FROM source_cleaning_recipes
                    WHERE id = ? ORDER BY version DESC LIMIT 1
                    """,
                    (recipe_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    """
                    SELECT payload_json FROM source_cleaning_recipes
                    WHERE id = ? AND version = ?
                    """,
                    (recipe_id, version),
                ).fetchone()
        return (
            CleaningRecipeRecord.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def clean_run(self, run_id: str) -> CleanRunRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM source_clean_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return CleanRunRecord.model_validate_json(row["payload_json"]) if row else None

    def golden_revision(
        self, workspace_id: str, revision_id: str
    ) -> GoldenAssetRevisionRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_golden_revisions
                WHERE workspace_id = ? AND id = ? AND revoked_at IS NULL
                """,
                (workspace_id, revision_id),
            ).fetchone()
        return (
            GoldenAssetRevisionRecord.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def golden_revision_including_revoked(
        self, workspace_id: str, revision_id: str
    ) -> GoldenAssetRevisionRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_golden_revisions
                WHERE workspace_id = ? AND id = ?
                """,
                (workspace_id, revision_id),
            ).fetchone()
        return (
            GoldenAssetRevisionRecord.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def latest_golden(
        self, workspace_id: str, asset_id: str
    ) -> GoldenAssetRevisionRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_golden_revisions
                WHERE workspace_id = ? AND asset_id = ? AND revoked_at IS NULL
                ORDER BY revision DESC LIMIT 1
                """,
                (workspace_id, asset_id),
            ).fetchone()
        return (
            GoldenAssetRevisionRecord.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def latest_golden_assets(
        self, workspace_id: str
    ) -> list[GoldenAssetRevisionRecord]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT g.payload_json
                FROM source_golden_revisions g
                JOIN (
                    SELECT asset_id, MAX(revision) AS revision
                    FROM source_golden_revisions
                    WHERE workspace_id = ? AND revoked_at IS NULL
                    GROUP BY asset_id
                ) current
                  ON current.asset_id = g.asset_id
                 AND current.revision = g.revision
                WHERE g.workspace_id = ? AND g.revoked_at IS NULL
                ORDER BY g.rowid
                """,
                (workspace_id, workspace_id),
            ).fetchall()
        return [
            GoldenAssetRevisionRecord.model_validate_json(row["payload_json"])
            for row in rows
        ]

    def profile_for_golden(
        self, workspace_id: str, revision_id: str
    ) -> ProfileRunRecord | None:
        golden = self.golden_revision(workspace_id, revision_id)
        return self.profile_run(golden.lineage.profile_run_id) if golden else None

    def refresh_for_idempotency(
        self, workspace_id: str, idempotency_key: str
    ) -> RefreshRunRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_refresh_runs
                WHERE workspace_id = ? AND idempotency_key = ?
                """,
                (workspace_id, idempotency_key),
            ).fetchone()
        return (
            RefreshRunRecord.model_validate_json(row["payload_json"]) if row else None
        )

    def save_refresh(self, run: RefreshRunRecord, *, idempotency_key: str) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO source_refresh_runs
                (id, workspace_id, asset_id, idempotency_key, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.workspace_id,
                    run.asset_id,
                    idempotency_key,
                    run.model_dump_json(by_alias=True),
                ),
            )

    def refresh_run(self, workspace_id: str, run_id: str) -> RefreshRunRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json FROM source_refresh_runs
                WHERE workspace_id = ? AND id = ?
                """,
                (workspace_id, run_id),
            ).fetchone()
        return (
            RefreshRunRecord.model_validate_json(row["payload_json"]) if row else None
        )

    def revoke_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        revoked_at: str,
        replacement: ConnectionInstance,
    ) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    UPDATE source_connections
                    SET payload_json = ?, revoked_at = ?
                    WHERE workspace_id = ? AND id = ? AND revoked_at IS NULL
                    """,
                    (
                        replacement.model_dump_json(by_alias=True),
                        revoked_at,
                        workspace_id,
                        connection_id,
                    ),
                )
                self._connection.execute(
                    """
                    UPDATE source_golden_revisions SET revoked_at = ?
                    WHERE workspace_id = ?
                      AND json_extract(payload_json, '$.lineage.connectionId') = ?
                      AND revoked_at IS NULL
                    """,
                    (revoked_at, workspace_id, connection_id),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def save_mcp_trace(self, trace: McpProcessTrace) -> None:
        with self._lock:
            trace_id = trace.id
            suffix = 1
            while self._connection.execute(
                "SELECT 1 FROM source_mcp_process_traces WHERE id = ?",
                (trace_id,),
            ).fetchone():
                suffix += 1
                trace_id = f"{trace.id}-{suffix}"
            if trace_id != trace.id:
                trace = trace.model_copy(update={"id": trace_id})
            self._connection.execute(
                """
                INSERT INTO source_mcp_process_traces
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

    def mcp_traces(
        self, workspace_id: str, connection_id: str
    ) -> list[McpProcessTrace]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json FROM source_mcp_process_traces
                WHERE workspace_id = ? AND connection_id = ?
                ORDER BY rowid
                """,
                (workspace_id, connection_id),
            ).fetchall()
        return [
            McpProcessTrace.model_validate_json(row["payload_json"]) for row in rows
        ]

    def mcp_traces_for_workspace(self, workspace_id: str) -> list[McpProcessTrace]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT payload_json FROM source_mcp_process_traces
                WHERE workspace_id = ? ORDER BY rowid
                """,
                (workspace_id,),
            ).fetchall()
        return [
            McpProcessTrace.model_validate_json(row["payload_json"]) for row in rows
        ]
