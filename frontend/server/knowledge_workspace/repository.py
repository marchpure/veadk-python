"""SQLite metadata plus immutable local object storage for the workspace slice."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import (
    Artifact,
    AuthoringSession,
    DraftStatus,
    Invocation,
    Publication,
    SkillDraft,
    SkillRevision,
    WorkspaceResource,
    WorkspaceUpload,
)


class KnowledgeWorkspaceRepository:
    """Durable repository used by local Studio and integration tests.

    Object keys are content-addressed and written with exclusive creation.
    Metadata rows are insert-once for revisions and artifacts.
    """

    def __init__(
        self,
        database: str | Path = ":memory:",
        object_root: str | Path = ".veadk/knowledge-workspace-objects",
    ) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            str(database), check_same_thread=False, isolation_level=None
        )
        self._db.row_factory = sqlite3.Row
        self._objects = Path(object_root)
        self._objects.mkdir(parents=True, exist_ok=True)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS kw_drafts (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_sessions (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_invocations (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, draft_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_events (invocation_id TEXT NOT NULL, sequence INTEGER NOT NULL, raw_payload TEXT NOT NULL, normalized_payload TEXT, upstream_id TEXT, PRIMARY KEY(invocation_id, sequence));
            CREATE TABLE IF NOT EXISTS kw_revisions (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, draft_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_artifacts (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_publications (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_uploads (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_resources (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kw_idempotency (scope TEXT NOT NULL, key TEXT NOT NULL, request_digest TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(scope, key));
            """
        )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _model(row: sqlite3.Row | None, model: Any) -> Any:
        return model.model_validate(json.loads(row["payload"])) if row else None

    def save_draft(self, draft: SkillDraft) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kw_drafts(id,tenant_id,workspace_id,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (
                    draft.draft_id,
                    draft.tenant_id,
                    draft.workspace_id,
                    self._json(draft),
                ),
            )

    def get_draft(
        self, draft_id: str, *, tenant_id: str, workspace_id: str
    ) -> SkillDraft | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_drafts WHERE id=? AND tenant_id=? AND workspace_id=?",
                (draft_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, SkillDraft)

    def list_drafts(
        self, *, tenant_id: str, workspace_id: str
    ) -> tuple[SkillDraft, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_drafts WHERE tenant_id=? AND workspace_id=? ORDER BY id",
                (tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            SkillDraft.model_validate(json.loads(row["payload"])) for row in rows
        )

    def save_upload(self, upload: WorkspaceUpload) -> WorkspaceUpload:
        with self._lock:
            payload = self._json(upload)
            row = self._db.execute(
                "SELECT payload FROM kw_uploads WHERE id=?", (upload.upload_id,)
            ).fetchone()
            if row:
                if row["payload"] != payload:
                    raise ValueError("immutable upload mutation")
                return upload
            self._db.execute(
                "INSERT INTO kw_uploads(id,tenant_id,workspace_id,payload) VALUES(?,?,?,?)",
                (upload.upload_id, upload.tenant_id, upload.workspace_id, payload),
            )
        return upload

    def get_upload(
        self, upload_id: str, *, tenant_id: str, workspace_id: str
    ) -> WorkspaceUpload | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_uploads WHERE id=? AND tenant_id=? AND workspace_id=?",
                (upload_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, WorkspaceUpload)

    def save_resource(self, resource: WorkspaceResource) -> WorkspaceResource:
        with self._lock:
            payload = self._json(resource)
            row = self._db.execute(
                "SELECT payload FROM kw_resources WHERE id=?", (resource.resource_id,)
            ).fetchone()
            if row:
                if row["payload"] != payload:
                    raise ValueError("immutable resource mutation")
                return resource
            self._db.execute(
                "INSERT INTO kw_resources(id,tenant_id,workspace_id,payload) VALUES(?,?,?,?)",
                (
                    resource.resource_id,
                    resource.tenant_id,
                    resource.workspace_id,
                    payload,
                ),
            )
        return resource

    def get_resource(
        self, resource_id: str, *, tenant_id: str, workspace_id: str
    ) -> WorkspaceResource | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_resources WHERE id=? AND tenant_id=? AND workspace_id=?",
                (resource_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, WorkspaceResource)

    def list_resources(
        self, *, tenant_id: str, workspace_id: str
    ) -> tuple[WorkspaceResource, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_resources WHERE tenant_id=? AND workspace_id=? ORDER BY json_extract(payload, '$.created_at'), id",
                (tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            WorkspaceResource.model_validate(json.loads(row["payload"]))
            for row in rows
        )

    def save_session(self, session: AuthoringSession) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kw_sessions(id,draft_id,tenant_id,workspace_id,payload) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (
                    session.authoring_session_id,
                    session.draft_id,
                    session.tenant_id,
                    session.workspace_id,
                    self._json(session),
                ),
            )

    def get_session(
        self, draft_id: str, *, tenant_id: str, workspace_id: str
    ) -> AuthoringSession | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_sessions WHERE draft_id=? AND tenant_id=? AND workspace_id=? ORDER BY id LIMIT 1",
                (draft_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, AuthoringSession)

    def save_invocation(self, invocation: Invocation) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kw_invocations(id,tenant_id,workspace_id,draft_id,payload) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (
                    invocation.invocation_id,
                    invocation.tenant_id,
                    invocation.workspace_id,
                    invocation.draft_id,
                    self._json(invocation),
                ),
            )

    def get_invocation(
        self, invocation_id: str, *, tenant_id: str, workspace_id: str
    ) -> Invocation | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_invocations WHERE id=? AND tenant_id=? AND workspace_id=?",
                (invocation_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, Invocation)

    def active_invocations(self) -> tuple[Invocation, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_invocations ORDER BY id"
            ).fetchall()
        return tuple(
            Invocation.model_validate(json.loads(row["payload"]))
            for row in rows
            if json.loads(row["payload"]).get("status") in {"queued", "running"}
        )

    def invocations_for_draft(
        self,
        draft_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> tuple[Invocation, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_invocations WHERE draft_id=? AND tenant_id=? AND workspace_id=?",
                (draft_id, tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            sorted(
                (
                    Invocation.model_validate(json.loads(row["payload"]))
                    for row in rows
                ),
                key=lambda item: (item.created_at, item.invocation_id),
            )
        )

    def invocations_for_revision(
        self,
        revision_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> tuple[Invocation, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_invocations WHERE tenant_id=? AND workspace_id=? ORDER BY id",
                (tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            invocation
            for row in rows
            for invocation in (Invocation.model_validate(json.loads(row["payload"])),)
            if invocation.revision_id == revision_id
        )

    def append_event(
        self,
        invocation_id: str,
        raw: MappingLike,
        normalized: MappingLike | None,
        upstream_id: str | None,
    ) -> int:
        with self._lock:
            if upstream_id is not None:
                existing = self._db.execute(
                    "SELECT sequence FROM kw_events WHERE invocation_id=? AND upstream_id=? ORDER BY sequence LIMIT 1",
                    (invocation_id, upstream_id),
                ).fetchone()
                if existing:
                    return int(existing["sequence"])
            row = self._db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 AS n FROM kw_events WHERE invocation_id=?",
                (invocation_id,),
            ).fetchone()
            sequence = int(row["n"])
            self._db.execute(
                "INSERT INTO kw_events(invocation_id,sequence,raw_payload,normalized_payload,upstream_id) VALUES(?,?,?,?,?)",
                (
                    invocation_id,
                    sequence,
                    self._json(raw),
                    self._json(normalized) if normalized is not None else None,
                    upstream_id,
                ),
            )
            return sequence

    def events_after(
        self, invocation_id: str, after: int = 0
    ) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT sequence,normalized_payload FROM kw_events WHERE invocation_id=? AND sequence>? ORDER BY sequence",
                (invocation_id, after),
            ).fetchall()
        return tuple(
            {
                "sequence": int(row["sequence"]),
                "event": {
                    **json.loads(row["normalized_payload"]),
                    "cursor": str(int(row["sequence"])),
                },
            }
            for row in rows
            if row["normalized_payload"]
        )

    def raw_events(self, invocation_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT sequence,raw_payload,upstream_id FROM kw_events WHERE invocation_id=? ORDER BY sequence",
                (invocation_id,),
            ).fetchall()
        return tuple(
            {
                "sequence": row["sequence"],
                "raw": json.loads(row["raw_payload"]),
                "upstream_id": row["upstream_id"],
            }
            for row in rows
        )

    def freeze_revision(self, revision: SkillRevision) -> SkillRevision:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO kw_revisions(id,tenant_id,workspace_id,draft_id,payload) VALUES(?,?,?,?,?)",
                    (
                        revision.revision_id,
                        revision.tenant_id,
                        revision.workspace_id,
                        revision.draft_id,
                        self._json(revision),
                    ),
                )
                draft = self.get_draft(
                    revision.draft_id,
                    tenant_id=revision.tenant_id,
                    workspace_id=revision.workspace_id,
                )
                if draft is None:
                    raise ValueError("draft disappeared during revision transaction")
                updated = draft.model_copy(
                    update={
                        "current_revision_id": revision.revision_id,
                        "status": DraftStatus.READY_TO_PUBLISH,
                        "etag": revision.revision_id,
                        "updated_at": revision.created_at,
                    }
                )
                self._db.execute(
                    "UPDATE kw_drafts SET payload=? WHERE id=?",
                    (self._json(updated), draft.draft_id),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return revision

    def revisions(
        self, draft_id: str, *, tenant_id: str, workspace_id: str
    ) -> tuple[SkillRevision, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_revisions WHERE draft_id=? AND tenant_id=? AND workspace_id=? ORDER BY rowid",
                (draft_id, tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            SkillRevision.model_validate(json.loads(row["payload"])) for row in rows
        )

    def get_revision(
        self, revision_id: str, *, tenant_id: str, workspace_id: str
    ) -> SkillRevision | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_revisions WHERE id=? AND tenant_id=? AND workspace_id=?",
                (revision_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, SkillRevision)

    def save_artifact(self, artifact: Artifact) -> Artifact:
        with self._lock:
            payload = self._json(artifact)
            row = self._db.execute(
                "SELECT payload FROM kw_artifacts WHERE id=?", (artifact.artifact_id,)
            ).fetchone()
            if row:
                if row["payload"] != payload:
                    raise ValueError("immutable artifact mutation")
                return artifact
            self._db.execute(
                "INSERT INTO kw_artifacts(id,tenant_id,workspace_id,revision_id,payload) VALUES(?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    artifact.tenant_id,
                    artifact.workspace_id,
                    artifact.revision_id,
                    payload,
                ),
            )
        return artifact

    def get_artifact(
        self, artifact_id: str, *, tenant_id: str, workspace_id: str
    ) -> Artifact | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_artifacts WHERE id=? AND tenant_id=? AND workspace_id=?",
                (artifact_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, Artifact)

    def artifacts_for_revision(
        self,
        revision_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> tuple[Artifact, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_artifacts WHERE revision_id=? AND tenant_id=? AND workspace_id=? ORDER BY id",
                (revision_id, tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            Artifact.model_validate(json.loads(row["payload"])) for row in rows
        )

    def save_publication(self, publication: Publication) -> Publication:
        with self._lock:
            payload = self._json(publication)
            row = self._db.execute(
                "SELECT payload FROM kw_publications WHERE id=?",
                (publication.publication_id,),
            ).fetchone()
            if row:
                if row["payload"] != payload:
                    raise ValueError("immutable publication mutation")
                return publication
            self._db.execute(
                "INSERT INTO kw_publications(id,tenant_id,workspace_id,revision_id,payload) VALUES(?,?,?,?,?)",
                (
                    publication.publication_id,
                    publication.tenant_id,
                    publication.workspace_id,
                    publication.revision_id,
                    payload,
                ),
            )
        return publication

    def get_publication(
        self, publication_id: str, *, tenant_id: str, workspace_id: str
    ) -> Publication | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM kw_publications WHERE id=? AND tenant_id=? AND workspace_id=?",
                (publication_id, tenant_id, workspace_id),
            ).fetchone()
        return self._model(row, Publication)

    def list_publications(
        self, *, tenant_id: str, workspace_id: str
    ) -> tuple[Publication, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM kw_publications WHERE tenant_id=? AND workspace_id=? ORDER BY id",
                (tenant_id, workspace_id),
            ).fetchall()
        return tuple(
            Publication.model_validate(json.loads(row["payload"])) for row in rows
        )

    def put_object(self, digest: str, content: bytes, *, suffix: str = ".bin") -> str:
        # The digest is the complete object key.  A caller cannot create two
        # mutable aliases for the same content by changing a filename suffix.
        if digest != __import__("hashlib").sha256(content).hexdigest():
            raise ValueError("object digest does not match content")
        target = self._objects / digest
        if target.is_symlink():
            raise ValueError("immutable object path is a symlink")
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ValueError("immutable object digest collision")
        return str(target)

    def read_object(self, uri: str) -> bytes:
        target = Path(uri)
        root = self._objects.resolve()
        if target.parent.resolve() != root or target.is_symlink():
            raise ValueError("object URI is outside immutable object storage")
        return target.read_bytes()

    def idempotent(self, scope: str, key: str, request_digest: str, value: str) -> str:
        with self._lock:
            row = self._db.execute(
                "SELECT request_digest,value FROM kw_idempotency WHERE scope=? AND key=?",
                (scope, key),
            ).fetchone()
            if row:
                if row["request_digest"] != request_digest:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return str(row["value"])
            self._db.execute(
                "INSERT INTO kw_idempotency(scope,key,request_digest,value) VALUES(?,?,?,?)",
                (scope, key, request_digest, value),
            )
            return value

    def idempotency_value(
        self, scope: str, key: str, request_digest: str
    ) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT request_digest,value FROM kw_idempotency WHERE scope=? AND key=?",
                (scope, key),
            ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != request_digest:
            raise ValueError("IDEMPOTENCY_CONFLICT")
        return str(row["value"])


class MappingLike(dict):
    """Typing helper for JSON-shaped raw event payloads."""
