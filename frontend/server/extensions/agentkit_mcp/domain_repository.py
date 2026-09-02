"""Normalized, tenant-scoped persistence for managed MCP publications."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .domain import (
    ActionPolicy,
    ManagedPublication,
    ManagedRevision,
    PublicationAuditEvent,
    PublicationOperation,
    PublicationSubject,
    RevisionState,
)


class ManagedPublicationRepository:
    def __init__(self, database: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(database), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS mcp_publications (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
            name TEXT NOT NULL, status TEXT NOT NULL, active_revision_id TEXT,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE INDEX IF NOT EXISTS idx_mcp_publications_scope
            ON mcp_publications(tenant_id, workspace_id, updated_at)""",
            """CREATE TABLE IF NOT EXISTS mcp_publication_revisions (
            id TEXT PRIMARY KEY, publication_id TEXT NOT NULL, version INTEGER NOT NULL,
            payload TEXT NOT NULL, UNIQUE(publication_id, version))""",
            """CREATE TABLE IF NOT EXISTS publication_subjects (
            publication_id TEXT NOT NULL, revision_id TEXT NOT NULL,
            subject_type TEXT NOT NULL, subject_ref TEXT NOT NULL,
            PRIMARY KEY(revision_id, subject_type, subject_ref))""",
            """CREATE TABLE IF NOT EXISTS publication_operations (
            operation_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
            revision_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            request_digest TEXT NOT NULL, payload TEXT NOT NULL,
            UNIQUE(publication_id, idempotency_key))""",
            """CREATE TABLE IF NOT EXISTS publication_audit_events (
            id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
            revision_id TEXT, payload TEXT NOT NULL)""",
        )
        with self._lock:
            for statement in statements:
                self._db.execute(statement)
            self._adopt_legacy_records()
            self._db.commit()

    def _adopt_legacy_records(self) -> None:
        legacy = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agentkit_mcp_publications'"
        ).fetchone()
        if legacy is None:
            return
        for row in self._db.execute(
            "SELECT publication_id,tenant_id,workspace_id,payload FROM agentkit_mcp_publications"
        ).fetchall():
            publication_id = f"external-{row['publication_id']}"
            exists = self._db.execute(
                "SELECT 1 FROM mcp_publications WHERE id=?", (publication_id,)
            ).fetchone()
            if exists:
                continue
            payload = json.loads(row["payload"])
            timestamp = str(
                payload.get("updatedAt")
                or payload.get("createdAt")
                or "1970-01-01T00:00:00+00:00"
            )
            revision = ManagedRevision(
                id=f"external-revision-{row['publication_id']}",
                publication_id=publication_id,
                version=1,
                endpoint_ref=payload.get("backendEndpointRef"),
                connection_scope=(),
                resolved_action_scope=(),
                action_policy_source=ActionPolicy(
                    preset="custom", actionIds=("external-managed",)
                ),
                audience_type="applications",
                mcp_service_id=payload.get("mcpServiceId"),
                toolset_id=payload.get("toolsetId"),
                gateway_endpoint=payload.get("gatewayEndpoint"),
                state=RevisionState.DISABLED,
            )
            self._db.execute(
                """INSERT INTO mcp_publications
                (id,tenant_id,workspace_id,name,status,active_revision_id,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    publication_id,
                    row["tenant_id"],
                    row["workspace_id"],
                    f"External publication {row['publication_id']}",
                    "external-managed",
                    revision.id,
                    "migration",
                    timestamp,
                    timestamp,
                ),
            )
            self._db.execute(
                """INSERT INTO mcp_publication_revisions(id,publication_id,version,payload)
                VALUES(?,?,?,?)""",
                (revision.id, publication_id, 1, revision.model_dump_json()),
            )

    def transaction(self):
        return self._db

    def save_publication(self, value: ManagedPublication) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO mcp_publications
                (id,tenant_id,workspace_id,name,status,active_revision_id,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,status=excluded.status,
                active_revision_id=excluded.active_revision_id,updated_at=excluded.updated_at""",
                (
                    value.id,
                    value.tenant_id,
                    value.workspace_id,
                    value.name,
                    value.status,
                    value.active_revision_id,
                    value.created_by,
                    value.created_at.isoformat(),
                    value.updated_at.isoformat(),
                ),
            )
            self._db.commit()

    def get_publication(
        self, publication_id: str, *, tenant_id: str, workspace_id: str
    ) -> ManagedPublication | None:
        with self._lock:
            row = self._db.execute(
                """SELECT * FROM mcp_publications
                WHERE id=? AND tenant_id=? AND workspace_id=?""",
                (publication_id, tenant_id, workspace_id),
            ).fetchone()
        return ManagedPublication.model_validate(dict(row)) if row else None

    def list_publications(
        self, *, tenant_id: str, workspace_id: str
    ) -> tuple[ManagedPublication, ...]:
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM mcp_publications
                WHERE tenant_id=? AND workspace_id=? ORDER BY updated_at DESC""",
                (tenant_id, workspace_id),
            ).fetchall()
        return tuple(ManagedPublication.model_validate(dict(row)) for row in rows)

    def get_publication_unscoped(
        self, publication_id: str
    ) -> ManagedPublication | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM mcp_publications WHERE id=?", (publication_id,)
            ).fetchone()
        return ManagedPublication.model_validate(dict(row)) if row else None

    def save_revision(self, value: ManagedRevision) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO mcp_publication_revisions(id,publication_id,version,payload)
                VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload""",
                (
                    value.id,
                    value.publication_id,
                    value.version,
                    value.model_dump_json(),
                ),
            )
            self._db.commit()

    def get_revision(self, revision_id: str) -> ManagedRevision | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM mcp_publication_revisions WHERE id=?",
                (revision_id,),
            ).fetchone()
        return ManagedRevision.model_validate_json(row["payload"]) if row else None

    def list_revisions(self, publication_id: str) -> tuple[ManagedRevision, ...]:
        with self._lock:
            rows = self._db.execute(
                """SELECT payload FROM mcp_publication_revisions
                WHERE publication_id=? ORDER BY version DESC""",
                (publication_id,),
            ).fetchall()
        return tuple(
            ManagedRevision.model_validate_json(row["payload"]) for row in rows
        )

    def replace_subjects(
        self, revision_id: str, subjects: tuple[PublicationSubject, ...]
    ) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM publication_subjects WHERE revision_id=?", (revision_id,)
            )
            self._db.executemany(
                """INSERT INTO publication_subjects
                (publication_id,revision_id,subject_type,subject_ref) VALUES(?,?,?,?)""",
                [
                    (
                        item.publication_id,
                        item.revision_id,
                        item.subject_type,
                        item.subject_ref,
                    )
                    for item in subjects
                ],
            )
            self._db.commit()

    def list_subjects(self, publication_id: str) -> tuple[PublicationSubject, ...]:
        with self._lock:
            rows = self._db.execute(
                """SELECT * FROM publication_subjects
                WHERE publication_id=? ORDER BY revision_id,subject_type,subject_ref""",
                (publication_id,),
            ).fetchall()
        return tuple(PublicationSubject.model_validate(dict(row)) for row in rows)

    def reserve_operation(self, value: PublicationOperation) -> PublicationOperation:
        payload = value.model_dump_json()
        with self._lock:
            self._db.execute(
                """INSERT OR IGNORE INTO publication_operations
                (operation_id,publication_id,revision_id,idempotency_key,request_digest,payload)
                VALUES(?,?,?,?,?,?)""",
                (
                    value.operation_id,
                    value.publication_id,
                    value.revision_id,
                    value.idempotency_key,
                    value.request_digest,
                    payload,
                ),
            )
            row = self._db.execute(
                """SELECT payload FROM publication_operations
                WHERE publication_id=? AND idempotency_key=?""",
                (value.publication_id, value.idempotency_key),
            ).fetchone()
            self._db.commit()
        assert row is not None
        return PublicationOperation.model_validate_json(row["payload"])

    def save_operation(self, value: PublicationOperation) -> None:
        with self._lock:
            self._db.execute(
                """UPDATE publication_operations SET payload=?,request_digest=?
                WHERE operation_id=?""",
                (value.model_dump_json(), value.request_digest, value.operation_id),
            )
            self._db.commit()

    def list_operations(self, publication_id: str) -> tuple[PublicationOperation, ...]:
        with self._lock:
            rows = self._db.execute(
                """SELECT payload FROM publication_operations
                WHERE publication_id=? ORDER BY rowid DESC""",
                (publication_id,),
            ).fetchall()
        return tuple(
            PublicationOperation.model_validate_json(row["payload"]) for row in rows
        )

    def find_operation(
        self, *, tenant_id: str, workspace_id: str, idempotency_key: str
    ) -> PublicationOperation | None:
        with self._lock:
            row = self._db.execute(
                """SELECT o.payload FROM publication_operations o
                JOIN mcp_publications p ON p.id=o.publication_id
                WHERE p.tenant_id=? AND p.workspace_id=? AND o.idempotency_key=?""",
                (tenant_id, workspace_id, idempotency_key),
            ).fetchone()
        return PublicationOperation.model_validate_json(row["payload"]) if row else None

    def save_audit(self, value: PublicationAuditEvent) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO publication_audit_events
                (id,publication_id,revision_id,payload) VALUES(?,?,?,?)""",
                (
                    value.id,
                    value.publication_id,
                    value.revision_id,
                    value.model_dump_json(),
                ),
            )
            self._db.commit()

    def list_audit(self, publication_id: str) -> tuple[PublicationAuditEvent, ...]:
        with self._lock:
            rows = self._db.execute(
                """SELECT payload FROM publication_audit_events
                WHERE publication_id=? ORDER BY rowid DESC""",
                (publication_id,),
            ).fetchall()
        return tuple(
            PublicationAuditEvent.model_validate_json(row["payload"]) for row in rows
        )
