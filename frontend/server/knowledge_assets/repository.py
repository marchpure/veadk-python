# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""SQLite repository for the Studio knowledge asset store."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 5


class KnowledgeAssetRepositoryError(RuntimeError):
    status_code = 500
    code = "KNOWLEDGE_ASSET_STORE_ERROR"


class KnowledgeAssetNotFound(LookupError):
    status_code = 404
    code = "KNOWLEDGE_ASSET_NOT_FOUND"


class KnowledgeAssetConflict(RuntimeError):
    status_code = 409
    code = "KNOWLEDGE_ASSET_CONFLICT"


def default_db_path() -> Path:
    configured = os.getenv("VEADK_STUDIO_ASSET_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".veadk" / "studio" / "knowledge-assets.db"


def utc_now_sql() -> str:
    return "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


class KnowledgeAssetRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else default_db_path()
        self._lock = threading.RLock()
        self._initialized = False

    def create_space(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO spaces (
                        id, name, description, default_knowledge_base_id, region,
                        metadata_json
                    )
                    VALUES (
                        :id, :name, :description, :default_knowledge_base_id,
                        :region, :metadata_json
                    )
                    """,
                    row,
                )
            except sqlite3.IntegrityError as error:
                raise KnowledgeAssetConflict(
                    "Knowledge asset space already exists."
                ) from error
            return self.get_space(row["id"], conn=conn)

    def list_spaces(self) -> list[dict[str, Any]]:
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM spaces WHERE deleted_at IS NULL ORDER BY updated_at DESC, id"
                )
            )

    def get_space(
        self, space_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM spaces WHERE id = ? AND deleted_at IS NULL",
                (space_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset space not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def update_space(self, space_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not patch:
            return self.get_space(space_id)
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "id": space_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE spaces SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE id = :id AND deleted_at IS NULL",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Knowledge asset space not found.")
            return self.get_space(space_id, conn=conn)

    def create_source(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_space(row["space_id"], conn=conn)
            try:
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, space_id, source_type, provider, name, description, uri,
                        locator, status, status_reason, default_index_policy,
                        capabilities_json, metadata_json
                    )
                    VALUES (
                        :id, :space_id, :source_type, :provider, :name, :description,
                        :uri, :locator, :status, :status_reason,
                        :default_index_policy, :capabilities_json, :metadata_json
                    )
                    """,
                    row,
                )
            except sqlite3.IntegrityError as error:
                raise KnowledgeAssetConflict(
                    "Knowledge asset source already exists."
                ) from error
            return self.get_source(row["id"], conn=conn)

    def list_sources(self, *, space_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE deleted_at IS NULL"
        params: tuple[str, ...] = ()
        if space_id:
            where += " AND space_id = ?"
            params = (space_id,)
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM sources {where} ORDER BY updated_at DESC, id",
                    params,
                )
            )

    def get_source(
        self, source_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM sources WHERE id = ? AND deleted_at IS NULL",
                (source_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset source not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def update_source_status(
        self, source_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "id": source_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE sources SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE id = :id AND deleted_at IS NULL",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Knowledge asset source not found.")
            return self.get_source(source_id, conn=conn)

    def save_credential(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_source(row["source_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO credentials (
                    id, source_id, space_id, provider, auth_mode,
                    encrypted_credentials, envelope_json, key_id, algorithm, version,
                    status, expires_at
                )
                VALUES (
                    :id, :source_id, :space_id, :provider, :auth_mode,
                    :encrypted_credentials, :envelope_json, :key_id, :algorithm,
                    :version, :status, :expires_at
                )
                ON CONFLICT(source_id) DO UPDATE SET
                    space_id = excluded.space_id,
                    provider = excluded.provider,
                    auth_mode = excluded.auth_mode,
                    encrypted_credentials = excluded.encrypted_credentials,
                    envelope_json = excluded.envelope_json,
                    key_id = excluded.key_id,
                    algorithm = excluded.algorithm,
                    version = excluded.version,
                    status = excluded.status,
                    expires_at = excluded.expires_at,
                    deleted_at = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_credential_status(row["source_id"], conn=conn)

    def get_credential_row(
        self, source_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM credentials WHERE source_id = ? AND deleted_at IS NULL",
                (source_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset credential not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def get_credential_status(
        self, source_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        row = self.get_credential_row(source_id, conn=conn)
        return {
            key: row[key]
            for key in (
                "source_id",
                "space_id",
                "provider",
                "auth_mode",
                "key_id",
                "algorithm",
                "version",
                "status",
                "expires_at",
                "created_at",
                "updated_at",
            )
        }

    def delete_credential(self, source_id: str) -> None:
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE credentials SET deleted_at = "
                f"{utc_now_sql()}, updated_at = {utc_now_sql()} "
                "WHERE source_id = ? AND deleted_at IS NULL",
                (source_id,),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Knowledge asset credential not found.")

    def record_indexed_document(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_source(row["source_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO indexed_documents (
                    id, source_id, knowledge_base_id, provider_doc_id, document_id,
                    title, uri, content_hash, sync_status, status, last_synced_at,
                    metadata_json
                )
                VALUES (
                    :id, :source_id, :knowledge_base_id, :provider_doc_id,
                    :document_id, :title, :uri, :content_hash, :sync_status,
                    :status, :last_synced_at, :metadata_json
                )
                ON CONFLICT(source_id, content_hash) DO UPDATE SET
                    knowledge_base_id = excluded.knowledge_base_id,
                    provider_doc_id = excluded.provider_doc_id,
                    document_id = excluded.document_id,
                    title = excluded.title,
                    uri = excluded.uri,
                    sync_status = excluded.sync_status,
                    status = excluded.status,
                    last_synced_at = excluded.last_synced_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_indexed_document_by_hash(
                row["source_id"], row["content_hash"], conn=conn
            )

    def get_indexed_document_by_hash(
        self,
        source_id: str,
        content_hash: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM indexed_documents "
                "WHERE source_id = ? AND content_hash = ?",
                (source_id, content_hash),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Indexed document not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_indexed_documents(
        self, *, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        where = ""
        params: tuple[str, ...] = ()
        if source_id:
            where = "WHERE source_id = ?"
            params = (source_id,)
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM indexed_documents {where} "
                    "ORDER BY updated_at DESC, id",
                    params,
                )
            )

    def record_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    id, source_id, kind, artifact_uri, schema_json, profile_json,
                    content_hash, asset_type, asset_id, capability_kind, name,
                    description, status, publish_state, version, gate_json,
                    consumers_json, capabilities_json, capability_package_json,
                    query_url, freshness_json, provenance_json, usage_policy_json,
                    sample_evidence_json, metadata_json
                )
                VALUES (
                    :id, :source_id, :kind, :artifact_uri, :schema_json,
                    :profile_json, :content_hash, :asset_type, :asset_id,
                    :capability_kind, :name, :description, :status,
                    :publish_state, :version,
                    :gate_json, :consumers_json, :capabilities_json,
                    :capability_package_json, :query_url, :freshness_json,
                    :provenance_json, :usage_policy_json, :sample_evidence_json,
                    :metadata_json
                )
                """,
                row,
            )
            return self.get_snapshot(row["id"], conn=conn)

    def get_snapshot(
        self, snapshot_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset snapshot not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_snapshots(
        self, *, asset_id: str | None = None, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[str] = []
        if asset_id:
            clauses.append("asset_id = ?")
            params.append(asset_id)
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM snapshots {where} ORDER BY created_at DESC, id",
                    tuple(params),
                )
            )

    def record_skill_package(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            if row.get("space_id"):
                self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO skill_packages (
                    id, space_id, type, source_ids, snapshot_ids, artifact_uri,
                    asset_type, asset_id, capability_kind, name, description, status,
                    publish_state, version, gate_json, consumers_json,
                    capabilities_json, capability_package_json, query_url,
                    freshness_json, provenance_json, usage_policy_json,
                    sample_evidence_json, metadata_json
                )
                VALUES (
                    :id, :space_id, :type, :source_ids, :snapshot_ids,
                    :artifact_uri, :asset_type, :asset_id, :capability_kind,
                    :name, :description, :status, :publish_state, :version,
                    :gate_json, :consumers_json, :capabilities_json,
                    :capability_package_json, :query_url, :freshness_json,
                    :provenance_json, :usage_policy_json, :sample_evidence_json,
                    :metadata_json
                )
                ON CONFLICT(asset_type, asset_id) DO UPDATE SET
                    space_id = excluded.space_id,
                    type = excluded.type,
                    source_ids = excluded.source_ids,
                    snapshot_ids = excluded.snapshot_ids,
                    artifact_uri = excluded.artifact_uri,
                    capability_kind = excluded.capability_kind,
                    name = excluded.name,
                    description = excluded.description,
                    status = excluded.status,
                    publish_state = excluded.publish_state,
                    version = excluded.version,
                    gate_json = excluded.gate_json,
                    consumers_json = excluded.consumers_json,
                    capabilities_json = excluded.capabilities_json,
                    capability_package_json = excluded.capability_package_json,
                    query_url = excluded.query_url,
                    freshness_json = excluded.freshness_json,
                    provenance_json = excluded.provenance_json,
                    usage_policy_json = excluded.usage_policy_json,
                    sample_evidence_json = excluded.sample_evidence_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_skill_package_by_asset(
                row["asset_type"], row["asset_id"], conn=conn
            )

    def get_skill_package(
        self, package_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM skill_packages WHERE id = ?",
                (package_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset skill package not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def get_skill_package_by_asset(
        self,
        asset_type: str,
        asset_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM skill_packages WHERE asset_type = ? AND asset_id = ?",
                (asset_type, asset_id),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset skill package not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def update_skill_package_by_asset(
        self,
        asset_type: str,
        asset_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        if not patch:
            return self.get_skill_package_by_asset(asset_type, asset_id)
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "asset_type": asset_type, "asset_id": asset_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE skill_packages SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE asset_type = :asset_type AND asset_id = :asset_id",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Knowledge asset skill package not found.")
            return self.get_skill_package_by_asset(asset_type, asset_id, conn=conn)

    def list_skill_packages(
        self,
        *,
        space_id: str | None = None,
        asset_types: Iterable[str] = (),
        capability_kinds: Iterable[str] = (),
        query: str = "",
        published_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if space_id:
            clauses.append("space_id = ?")
            params.append(space_id)
        asset_types = tuple(asset_types)
        if asset_types:
            clauses.append(f"asset_type IN ({','.join('?' for _ in asset_types)})")
            params.extend(asset_types)
        capability_kinds = tuple(capability_kinds)
        if capability_kinds:
            clauses.append(
                f"capability_kind IN ({','.join('?' for _ in capability_kinds)})"
            )
            params.extend(capability_kinds)
        if published_only:
            clauses.append("publish_state = 'published'")
        q = query.strip().casefold()
        if q:
            clauses.append(
                "(lower(name) LIKE ? OR lower(coalesce(description,'')) LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._read() as conn:
            total = int(
                conn.execute(
                    f"SELECT count(*) FROM skill_packages {where}",
                    tuple(params),
                ).fetchone()[0]
            )
            sql = f"SELECT * FROM skill_packages {where} ORDER BY updated_at DESC, id"
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])
            return _rows(conn.execute(sql, tuple(params))), total

    def create_dashboard_share(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_skill_package_by_asset(
                row["asset_type"],
                row["asset_id"],
                conn=conn,
            )
            conn.execute(
                """
                INSERT INTO dashboard_shares (
                    share_id, asset_type, asset_id, asset_version, title,
                    expires_at, visibility, sanitized_snapshot_json
                )
                VALUES (
                    :share_id, :asset_type, :asset_id, :asset_version, :title,
                    :expires_at, :visibility, :sanitized_snapshot_json
                )
                """,
                row,
            )
            return self.get_dashboard_share(row["share_id"], conn=conn)

    def get_dashboard_share(
        self,
        share_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM dashboard_shares WHERE share_id = ?",
                (share_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset dashboard share not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def revoke_dashboard_share(self, share_id: str) -> dict[str, Any]:
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE dashboard_shares SET revoked_at = COALESCE(revoked_at, "
                f"{utc_now_sql()}) WHERE share_id = ?",
                (share_id,),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Knowledge asset dashboard share not found.")
            return self.get_dashboard_share(share_id, conn=conn)

    def record_build_job(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            if row.get("space_id"):
                self.get_space(row["space_id"], conn=conn)
            if row.get("source_id"):
                self.get_source(row["source_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO build_jobs (
                    id, space_id, source_id, asset_type, asset_id, job_type,
                    status, logs_ref, result_skill_id, error_json, input_json,
                    output_json
                )
                VALUES (
                    :id, :space_id, :source_id, :asset_type, :asset_id,
                    :job_type, :status, :logs_ref, :result_skill_id,
                    :error_json, :input_json, :output_json
                )
                """,
                row,
            )
            return self.get_build_job(row["id"], conn=conn)

    def update_build_job(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not patch:
            return self.get_build_job(job_id)
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "id": job_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE build_jobs SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE id = :id",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Knowledge asset build job not found.")
            return self.get_build_job(job_id, conn=conn)

    def get_build_job(
        self, job_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM build_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Knowledge asset build job not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_build_jobs(
        self,
        *,
        space_id: str | None = None,
        source_id: str | None = None,
        asset_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if space_id:
            clauses.append("space_id = ?")
            params.append(space_id)
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        if asset_id:
            clauses.append("asset_id = ?")
            params.append(asset_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded = max(1, min(int(limit), 100))
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM build_jobs {where} "
                    "ORDER BY updated_at DESC, id LIMIT ?",
                    (*params, bounded),
                )
            )

    def append_build_event(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_build_job(row["job_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_build_events (
                    id, job_id, space_id, semantic_pack_id, event_type,
                    sequence, payload_json
                )
                VALUES (
                    :id, :job_id, :space_id, :semantic_pack_id, :event_type,
                    :sequence, :payload_json
                )
                """,
                row,
            )
            return self.get_build_event(row["id"], conn=conn)

    def get_build_event(
        self, event_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_build_events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic build event not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_build_events(
        self, job_id: str, *, after_sequence: int | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["job_id = ?"]
        params: list[Any] = [job_id]
        if after_sequence is not None:
            clauses.append("sequence > ?")
            params.append(after_sequence)
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM semantic_build_events "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY sequence ASC, created_at ASC, id",
                    tuple(params),
                )
            )

    def next_build_event_sequence(self, job_id: str) -> int:
        with self._read() as conn:
            value = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM semantic_build_events "
                "WHERE job_id = ?",
                (job_id,),
            ).fetchone()[0]
            return int(value)

    def create_question_sql_pair(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_question_sql_pairs (
                    id, space_id, semantic_pack_id, question, sql, dialect,
                    tables_json, notes
                )
                VALUES (
                    :id, :space_id, :semantic_pack_id, :question, :sql,
                    :dialect, :tables_json, :notes
                )
                """,
                row,
            )
            return self.get_question_sql_pair(row["id"], conn=conn)

    def update_question_sql_pair(
        self, pair_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        if not patch:
            return self.get_question_sql_pair(pair_id)
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "id": pair_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE semantic_question_sql_pairs "
                f"SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE id = :id AND deleted_at IS NULL",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Question-SQL pair not found.")
            return self.get_question_sql_pair(pair_id, conn=conn)

    def delete_question_sql_pair(self, pair_id: str) -> None:
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE semantic_question_sql_pairs "
                f"SET deleted_at = {utc_now_sql()}, updated_at = {utc_now_sql()} "
                "WHERE id = ? AND deleted_at IS NULL",
                (pair_id,),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Question-SQL pair not found.")

    def get_question_sql_pair(
        self, pair_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_question_sql_pairs "
                "WHERE id = ? AND deleted_at IS NULL",
                (pair_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Question-SQL pair not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_question_sql_pairs(
        self, *, space_id: str, semantic_pack_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["space_id = ?", "deleted_at IS NULL"]
        params: list[Any] = [space_id]
        if semantic_pack_id:
            clauses.append("semantic_pack_id = ?")
            params.append(semantic_pack_id)
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM semantic_question_sql_pairs "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY updated_at DESC, id",
                    tuple(params),
                )
            )

    def create_instruction(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_instructions (
                    id, space_id, semantic_pack_id, instruction, questions_json,
                    is_default, scope
                )
                VALUES (
                    :id, :space_id, :semantic_pack_id, :instruction,
                    :questions_json, :is_default, :scope
                )
                """,
                row,
            )
            return self.get_instruction(row["id"], conn=conn)

    def update_instruction(
        self, instruction_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        if not patch:
            return self.get_instruction(instruction_id)
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "id": instruction_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE semantic_instructions "
                f"SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE id = :id AND deleted_at IS NULL",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Semantic instruction not found.")
            return self.get_instruction(instruction_id, conn=conn)

    def delete_instruction(self, instruction_id: str) -> None:
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE semantic_instructions "
                f"SET deleted_at = {utc_now_sql()}, updated_at = {utc_now_sql()} "
                "WHERE id = ? AND deleted_at IS NULL",
                (instruction_id,),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Semantic instruction not found.")

    def get_instruction(
        self, instruction_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_instructions "
                "WHERE id = ? AND deleted_at IS NULL",
                (instruction_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic instruction not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_instructions(
        self, *, space_id: str, semantic_pack_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["space_id = ?", "deleted_at IS NULL"]
        params: list[Any] = [space_id]
        if semantic_pack_id:
            clauses.append("semantic_pack_id = ?")
            params.append(semantic_pack_id)
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM semantic_instructions "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY is_default DESC, updated_at DESC, id",
                    tuple(params),
                )
            )

    def upsert_graph_object(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            if row.get("space_id"):
                self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_graph_objects (
                    id, space_id, semantic_pack_id, kind, name, normalized_name,
                    description, confidence, provenance_json, review_status
                )
                VALUES (
                    :id, :space_id, :semantic_pack_id, :kind, :name,
                    :normalized_name, :description, :confidence,
                    :provenance_json, :review_status
                )
                ON CONFLICT(id) DO UPDATE SET
                    space_id = excluded.space_id,
                    semantic_pack_id = excluded.semantic_pack_id,
                    kind = excluded.kind,
                    name = excluded.name,
                    normalized_name = excluded.normalized_name,
                    description = excluded.description,
                    confidence = excluded.confidence,
                    provenance_json = excluded.provenance_json,
                    review_status = excluded.review_status,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_graph_object(row["id"], conn=conn)

    def get_graph_object(
        self, object_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_graph_objects WHERE id = ?",
                (object_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic graph object not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_graph_objects(
        self, *, space_id: str | None = None, semantic_pack_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if space_id:
            clauses.append("space_id = ?")
            params.append(space_id)
        if semantic_pack_id:
            clauses.append("semantic_pack_id = ?")
            params.append(semantic_pack_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM semantic_graph_objects {where} "
                    "ORDER BY confidence DESC, updated_at DESC, id",
                    tuple(params),
                )
            )

    def update_graph_object_status(
        self, object_id: str, review_status: str
    ) -> dict[str, Any]:
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE semantic_graph_objects SET review_status = ?, "
                f"updated_at = {utc_now_sql()} WHERE id = ?",
                (review_status, object_id),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Semantic graph object not found.")
            return self.get_graph_object(object_id, conn=conn)

    def upsert_graph_relation(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            if row.get("space_id"):
                self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_graph_relations (
                    id, space_id, semantic_pack_id, source_object_id,
                    target_object_id, relation_type, predicate, condition,
                    confidence, evidence_json, review_status
                )
                VALUES (
                    :id, :space_id, :semantic_pack_id, :source_object_id,
                    :target_object_id, :relation_type, :predicate, :condition,
                    :confidence, :evidence_json, :review_status
                )
                ON CONFLICT(id) DO UPDATE SET
                    space_id = excluded.space_id,
                    semantic_pack_id = excluded.semantic_pack_id,
                    source_object_id = excluded.source_object_id,
                    target_object_id = excluded.target_object_id,
                    relation_type = excluded.relation_type,
                    predicate = excluded.predicate,
                    condition = excluded.condition,
                    confidence = excluded.confidence,
                    evidence_json = excluded.evidence_json,
                    review_status = excluded.review_status,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_graph_relation(row["id"], conn=conn)

    def get_graph_relation(
        self, relation_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_graph_relations WHERE id = ?",
                (relation_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic graph relation not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_graph_relations(
        self, *, space_id: str | None = None, semantic_pack_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if space_id:
            clauses.append("space_id = ?")
            params.append(space_id)
        if semantic_pack_id:
            clauses.append("semantic_pack_id = ?")
            params.append(semantic_pack_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM semantic_graph_relations {where} "
                    "ORDER BY confidence DESC, updated_at DESC, id",
                    tuple(params),
                )
            )

    def update_graph_relation_status(
        self, relation_id: str, review_status: str
    ) -> dict[str, Any]:
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE semantic_graph_relations SET review_status = ?, "
                f"updated_at = {utc_now_sql()} WHERE id = ?",
                (review_status, relation_id),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Semantic graph relation not found.")
            return self.get_graph_relation(relation_id, conn=conn)

    def upsert_alignment(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            if row.get("space_id"):
                self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_alignments (
                    id, space_id, semantic_pack_id, doc_object_id, mdl_object_ref,
                    alignment_type, confidence, evidence_json, status
                )
                VALUES (
                    :id, :space_id, :semantic_pack_id, :doc_object_id,
                    :mdl_object_ref, :alignment_type, :confidence,
                    :evidence_json, :status
                )
                ON CONFLICT(id) DO UPDATE SET
                    space_id = excluded.space_id,
                    semantic_pack_id = excluded.semantic_pack_id,
                    doc_object_id = excluded.doc_object_id,
                    mdl_object_ref = excluded.mdl_object_ref,
                    alignment_type = excluded.alignment_type,
                    confidence = excluded.confidence,
                    evidence_json = excluded.evidence_json,
                    status = excluded.status,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_alignment(row["id"], conn=conn)

    def get_alignment(
        self, alignment_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_alignments WHERE id = ?",
                (alignment_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic alignment not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_alignments(
        self, *, space_id: str | None = None, semantic_pack_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if space_id:
            clauses.append("space_id = ?")
            params.append(space_id)
        if semantic_pack_id:
            clauses.append("semantic_pack_id = ?")
            params.append(semantic_pack_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._read() as conn:
            return _rows(
                conn.execute(
                    f"SELECT * FROM semantic_alignments {where} "
                    "ORDER BY confidence DESC, updated_at DESC, id",
                    tuple(params),
                )
            )

    def update_alignment_status(self, alignment_id: str, status: str) -> dict[str, Any]:
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE semantic_alignments SET status = ?, "
                f"updated_at = {utc_now_sql()} WHERE id = ?",
                (status, alignment_id),
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Semantic alignment not found.")
            return self.get_alignment(alignment_id, conn=conn)

    def create_semantic_conversation(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_space(row["space_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_builder_conversations (
                    id, space_id, semantic_pack_id, draft_pack_id, title,
                    source_ids_json, document_source_ids_json, snapshot_ids_json,
                    metadata_json
                )
                VALUES (
                    :id, :space_id, :semantic_pack_id, :draft_pack_id, :title,
                    :source_ids_json, :document_source_ids_json, :snapshot_ids_json,
                    :metadata_json
                )
                """,
                row,
            )
            return self.get_semantic_conversation(row["id"], conn=conn)

    def update_semantic_conversation(
        self,
        conversation_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        if not patch:
            return self.get_semantic_conversation(conversation_id)
        fields = ", ".join(f"{key} = :{key}" for key in patch)
        params = {**patch, "id": conversation_id}
        with self._write() as conn:
            cursor = conn.execute(
                f"UPDATE semantic_builder_conversations "
                f"SET {fields}, updated_at = {utc_now_sql()} "
                "WHERE id = :id",
                params,
            )
            if cursor.rowcount == 0:
                raise KnowledgeAssetNotFound("Semantic builder conversation not found.")
            return self.get_semantic_conversation(conversation_id, conn=conn)

    def get_semantic_conversation(
        self,
        conversation_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_builder_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic builder conversation not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def append_semantic_revision(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_semantic_conversation(row["conversation_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO semantic_builder_revisions (
                    id, conversation_id, semantic_pack_id, revision_number,
                    author_role, message, patch_json, diff_json, status
                )
                VALUES (
                    :id, :conversation_id, :semantic_pack_id, :revision_number,
                    :author_role, :message, :patch_json, :diff_json, :status
                )
                """,
                row,
            )
            return self.get_semantic_revision(row["id"], conn=conn)

    def next_semantic_revision_number(self, conversation_id: str) -> int:
        with self._read() as conn:
            value = conn.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 "
                "FROM semantic_builder_revisions WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            return int(value)

    def get_semantic_revision(
        self,
        revision_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM semantic_builder_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("Semantic builder revision not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def list_semantic_revisions(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM semantic_builder_revisions "
                    "WHERE conversation_id = ? ORDER BY revision_number ASC, created_at ASC",
                    (conversation_id,),
                )
            )

    def list_semantic_conversations_for_pack(
        self,
        semantic_pack_id: str,
    ) -> list[dict[str, Any]]:
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM semantic_builder_conversations "
                    "WHERE semantic_pack_id = ? OR draft_pack_id = ? "
                    "ORDER BY updated_at DESC, created_at DESC",
                    (semantic_pack_id, semantic_pack_id),
                )
            )

    def upsert_askdata_conversation(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO askdata_conversations (
                    id, semantic_asset_id, session_id, title, status, mode,
                    metadata_json
                )
                VALUES (
                    :id, :semantic_asset_id, :session_id, :title, :status, :mode,
                    :metadata_json
                )
                ON CONFLICT(id) DO UPDATE SET
                    semantic_asset_id = excluded.semantic_asset_id,
                    session_id = excluded.session_id,
                    title = excluded.title,
                    status = excluded.status,
                    mode = excluded.mode,
                    metadata_json = excluded.metadata_json,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
                """,
                row,
            )
            return self.get_askdata_conversation(row["id"], conn=conn)

    def get_askdata_conversation(
        self,
        conversation_id: str,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        active = conn or self._connect()
        try:
            row = active.execute(
                "SELECT * FROM askdata_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise KnowledgeAssetNotFound("AskData conversation not found.")
            return dict(row)
        finally:
            if conn is None:
                active.close()

    def record_askdata_message(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_askdata_conversation(row["conversation_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO askdata_messages (
                    id, conversation_id, role, content_json
                )
                VALUES (:id, :conversation_id, :role, :content_json)
                """,
                row,
            )
            stored = conn.execute(
                "SELECT * FROM askdata_messages WHERE id = ?",
                (row["id"],),
            ).fetchone()
            if stored is None:
                raise KnowledgeAssetRepositoryError("AskData message was not stored.")
            return dict(stored)

    def record_askdata_tool_event(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._write() as conn:
            self.get_askdata_conversation(row["conversation_id"], conn=conn)
            conn.execute(
                """
                INSERT INTO askdata_tool_events (
                    id, conversation_id, message_id, tool_call_id, tool_name,
                    status, args_json, response_json
                )
                VALUES (
                    :id, :conversation_id, :message_id, :tool_call_id, :tool_name,
                    :status, :args_json, :response_json
                )
                """,
                row,
            )
            stored = conn.execute(
                "SELECT * FROM askdata_tool_events WHERE id = ?",
                (row["id"],),
            ).fetchone()
            if stored is None:
                raise KnowledgeAssetRepositoryError("AskData tool event was not stored.")
            return dict(stored)

    def list_askdata_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM askdata_messages WHERE conversation_id = ? "
                    "ORDER BY created_at ASC, id ASC",
                    (conversation_id,),
                )
            )

    def list_askdata_tool_events(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._read() as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM askdata_tool_events WHERE conversation_id = ? "
                    "ORDER BY created_at ASC, id ASC",
                    (conversation_id,),
                )
            )

    @contextmanager
    def _read(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        self._ensure_initialized()
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                pass
            conn = sqlite3.connect(self.path, timeout=30)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA busy_timeout = 5000")
                _create_schema(conn)
                _migrate_schema(conn)
                conn.execute(
                    """
                    INSERT INTO schema_meta (key, value)
                    VALUES ('schema_version', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (str(_SCHEMA_VERSION),),
                )
                conn.commit()
            finally:
                conn.close()
            self._initialized = True


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS spaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            default_knowledge_base_id TEXT,
            region TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            provider TEXT,
            name TEXT NOT NULL,
            description TEXT,
            uri TEXT,
            locator TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            status_reason TEXT,
            default_index_policy TEXT NOT NULL DEFAULT '{}',
            capabilities_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            deleted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_sources_space ON sources(space_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);

        CREATE TABLE IF NOT EXISTS credentials (
            id TEXT,
            source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
            space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
            provider TEXT,
            auth_mode TEXT NOT NULL DEFAULT 'none',
            encrypted_credentials TEXT,
            envelope_json TEXT NOT NULL,
            key_id TEXT NOT NULL,
            algorithm TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL,
            expires_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS indexed_documents (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            knowledge_base_id TEXT,
            provider_doc_id TEXT,
            document_id TEXT,
            title TEXT,
            uri TEXT,
            content_hash TEXT NOT NULL,
            sync_status TEXT,
            status TEXT NOT NULL,
            last_synced_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(source_id, content_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_indexed_documents_source
            ON indexed_documents(source_id, updated_at);

        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
            kind TEXT NOT NULL DEFAULT 'knowledge_asset',
            artifact_uri TEXT,
            schema_json TEXT NOT NULL DEFAULT '{}',
            profile_json TEXT NOT NULL DEFAULT '{}',
            content_hash TEXT,
            asset_type TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            capability_kind TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL,
            publish_state TEXT NOT NULL,
            version TEXT,
            gate_json TEXT,
            consumers_json TEXT NOT NULL DEFAULT '[]',
            capabilities_json TEXT NOT NULL DEFAULT '{}',
            capability_package_json TEXT NOT NULL DEFAULT '{}',
            query_url TEXT,
            freshness_json TEXT NOT NULL DEFAULT '{}',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            usage_policy_json TEXT NOT NULL DEFAULT '{}',
            sample_evidence_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_asset
            ON snapshots(asset_type, asset_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_snapshots_source
            ON snapshots(source_id, created_at);

        CREATE TABLE IF NOT EXISTS skill_packages (
            id TEXT PRIMARY KEY,
            space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
            type TEXT NOT NULL DEFAULT 'retrieval_binding',
            source_ids TEXT NOT NULL DEFAULT '[]',
            snapshot_ids TEXT NOT NULL DEFAULT '[]',
            artifact_uri TEXT,
            asset_type TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            capability_kind TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL,
            publish_state TEXT NOT NULL,
            version TEXT,
            gate_json TEXT,
            consumers_json TEXT NOT NULL DEFAULT '[]',
            capabilities_json TEXT NOT NULL DEFAULT '{}',
            capability_package_json TEXT NOT NULL DEFAULT '{}',
            query_url TEXT,
            freshness_json TEXT NOT NULL DEFAULT '{}',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            usage_policy_json TEXT NOT NULL DEFAULT '{}',
            sample_evidence_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(asset_type, asset_id)
        );
        CREATE INDEX IF NOT EXISTS idx_skill_packages_space
            ON skill_packages(space_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_skill_packages_publish
            ON skill_packages(publish_state, asset_type, capability_kind);

        CREATE TABLE IF NOT EXISTS dashboard_shares (
            share_id TEXT PRIMARY KEY,
            asset_type TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            asset_version TEXT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            expires_at TEXT,
            revoked_at TEXT,
            visibility TEXT NOT NULL DEFAULT 'local_link',
            sanitized_snapshot_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(asset_type, asset_id) REFERENCES skill_packages(asset_type, asset_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_dashboard_shares_asset
            ON dashboard_shares(asset_type, asset_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_dashboard_shares_visibility
            ON dashboard_shares(visibility, created_at);

        CREATE TABLE IF NOT EXISTS build_jobs (
            id TEXT PRIMARY KEY,
            space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
            source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
            asset_type TEXT,
            asset_id TEXT,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            logs_ref TEXT,
            result_skill_id TEXT,
            error_json TEXT,
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_build_jobs_status
            ON build_jobs(status, updated_at);

        CREATE TABLE IF NOT EXISTS askdata_conversations (
            id TEXT PRIMARY KEY,
            semantic_asset_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            mode TEXT NOT NULL DEFAULT 'production',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_askdata_conversations_asset
            ON askdata_conversations(semantic_asset_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_askdata_conversations_session
            ON askdata_conversations(session_id, updated_at);

        CREATE TABLE IF NOT EXISTS askdata_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES askdata_conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_askdata_messages_conversation
            ON askdata_messages(conversation_id, created_at);

        CREATE TABLE IF NOT EXISTS askdata_tool_events (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES askdata_conversations(id) ON DELETE CASCADE,
            message_id TEXT REFERENCES askdata_messages(id) ON DELETE SET NULL,
            tool_call_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            status TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '{}',
            response_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_askdata_tool_events_conversation
            ON askdata_tool_events(conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_askdata_tool_events_call
            ON askdata_tool_events(tool_call_id);

        CREATE TABLE IF NOT EXISTS knowledge_asset_eval_suites (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            target_kind TEXT NOT NULL,
            target_asset_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eval_suites_space
            ON knowledge_asset_eval_suites(space_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_eval_suites_target
            ON knowledge_asset_eval_suites(target_kind, target_asset_id, updated_at);

        CREATE TABLE IF NOT EXISTS knowledge_asset_eval_cases (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES knowledge_asset_eval_suites(id) ON DELETE CASCADE,
            target_kind TEXT NOT NULL,
            input TEXT NOT NULL DEFAULT '',
            question TEXT NOT NULL DEFAULT '',
            intent TEXT NOT NULL DEFAULT '',
            expected_metric TEXT NOT NULL DEFAULT '',
            expected_dimensions_json TEXT NOT NULL DEFAULT '[]',
            expected_sql_contains_json TEXT NOT NULL DEFAULT '[]',
            expected_policy_decision TEXT NOT NULL DEFAULT '',
            expected_dashboard_tiles_json TEXT NOT NULL DEFAULT '[]',
            expected_evidence_keys_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eval_cases_suite
            ON knowledge_asset_eval_cases(suite_id, created_at);

        CREATE TABLE IF NOT EXISTS knowledge_asset_eval_runs (
            id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL REFERENCES knowledge_asset_eval_suites(id) ON DELETE CASCADE,
            target_kind TEXT NOT NULL,
            target_asset_id TEXT NOT NULL,
            status TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            started_at TEXT,
            completed_at TEXT,
            model_status TEXT NOT NULL DEFAULT 'not_configured',
            generation_mode TEXT NOT NULL DEFAULT 'deterministic',
            result_summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eval_runs_suite
            ON knowledge_asset_eval_runs(suite_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_eval_runs_target
            ON knowledge_asset_eval_runs(target_kind, target_asset_id, updated_at);

        CREATE TABLE IF NOT EXISTS knowledge_asset_eval_results (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES knowledge_asset_eval_runs(id) ON DELETE CASCADE,
            case_id TEXT NOT NULL REFERENCES knowledge_asset_eval_cases(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            actual_output_json TEXT,
            actual_sql TEXT NOT NULL DEFAULT '',
            actual_rows_preview_json TEXT NOT NULL DEFAULT '[]',
            actual_policy_decision_json TEXT NOT NULL DEFAULT '{}',
            actual_freshness_json TEXT NOT NULL DEFAULT '{}',
            tool_calls_json TEXT NOT NULL DEFAULT '[]',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            dashboard_spec_diff_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eval_results_run
            ON knowledge_asset_eval_results(run_id, created_at);

        CREATE TABLE IF NOT EXISTS knowledge_asset_eval_optimizations (
            target_kind TEXT NOT NULL,
            target_asset_id TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            source_run_ids_json TEXT NOT NULL DEFAULT '[]',
            groups_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY(target_kind, target_asset_id)
        );

        CREATE TABLE IF NOT EXISTS semantic_build_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES build_jobs(id) ON DELETE CASCADE,
            space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
            semantic_pack_id TEXT,
            event_type TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(job_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_build_events_job
            ON semantic_build_events(job_id, sequence);

        CREATE TABLE IF NOT EXISTS semantic_question_sql_pairs (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            semantic_pack_id TEXT,
            question TEXT NOT NULL,
            sql TEXT NOT NULL,
            dialect TEXT NOT NULL DEFAULT 'ansi',
            tables_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            deleted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_qsql_space_pack
            ON semantic_question_sql_pairs(space_id, semantic_pack_id, updated_at);

        CREATE TABLE IF NOT EXISTS semantic_instructions (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            semantic_pack_id TEXT,
            instruction TEXT NOT NULL,
            questions_json TEXT NOT NULL DEFAULT '[]',
            is_default INTEGER NOT NULL DEFAULT 0,
            scope TEXT NOT NULL DEFAULT 'global',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            deleted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_instructions_space_pack
            ON semantic_instructions(space_id, semantic_pack_id, updated_at);

        CREATE TABLE IF NOT EXISTS semantic_graph_objects (
            id TEXT PRIMARY KEY,
            space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
            semantic_pack_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            review_status TEXT NOT NULL DEFAULT 'suggested',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_graph_objects_pack
            ON semantic_graph_objects(semantic_pack_id, kind, confidence);

        CREATE TABLE IF NOT EXISTS semantic_graph_relations (
            id TEXT PRIMARY KEY,
            space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
            semantic_pack_id TEXT NOT NULL,
            source_object_id TEXT NOT NULL,
            target_object_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            predicate TEXT NOT NULL DEFAULT '',
            condition TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            review_status TEXT NOT NULL DEFAULT 'suggested',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_graph_relations_pack
            ON semantic_graph_relations(semantic_pack_id, relation_type, confidence);

        CREATE TABLE IF NOT EXISTS semantic_alignments (
            id TEXT PRIMARY KEY,
            space_id TEXT REFERENCES spaces(id) ON DELETE CASCADE,
            semantic_pack_id TEXT NOT NULL,
            doc_object_id TEXT NOT NULL,
            mdl_object_ref TEXT NOT NULL,
            alignment_type TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'suggested',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_alignments_pack
            ON semantic_alignments(semantic_pack_id, status, confidence);

        CREATE TABLE IF NOT EXISTS semantic_builder_conversations (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            semantic_pack_id TEXT,
            draft_pack_id TEXT,
            title TEXT NOT NULL,
            source_ids_json TEXT NOT NULL DEFAULT '[]',
            document_source_ids_json TEXT NOT NULL DEFAULT '[]',
            snapshot_ids_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_builder_conversations_space
            ON semantic_builder_conversations(space_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_semantic_builder_conversations_pack
            ON semantic_builder_conversations(semantic_pack_id, updated_at);

        CREATE TABLE IF NOT EXISTS semantic_builder_revisions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES semantic_builder_conversations(id) ON DELETE CASCADE,
            semantic_pack_id TEXT,
            revision_number INTEGER NOT NULL,
            author_role TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            patch_json TEXT NOT NULL DEFAULT '{}',
            diff_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(conversation_id, revision_number)
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_builder_revisions_conversation
            ON semantic_builder_revisions(conversation_id, revision_number);
        """
    )


def _migrate_schema(conn: sqlite3.Connection) -> None:
    _ensure_columns(
        conn,
        "spaces",
        {
            "default_knowledge_base_id": "TEXT",
            "region": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "sources",
        {
            "locator": "TEXT NOT NULL DEFAULT '{}'",
            "default_index_policy": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    _ensure_columns(
        conn,
        "credentials",
        {
            "id": "TEXT",
            "space_id": "TEXT REFERENCES spaces(id) ON DELETE CASCADE",
            "provider": "TEXT",
            "auth_mode": "TEXT NOT NULL DEFAULT 'none'",
            "encrypted_credentials": "TEXT",
        },
    )
    conn.execute(
        "UPDATE credentials SET id = COALESCE(id, 'cred_' || lower(hex(randomblob(16)))) "
        "WHERE id IS NULL OR id = ''"
    )
    conn.execute(
        "UPDATE credentials SET encrypted_credentials = envelope_json "
        "WHERE encrypted_credentials IS NULL OR encrypted_credentials = ''"
    )
    conn.execute(
        """
        UPDATE credentials
        SET space_id = (
            SELECT sources.space_id FROM sources WHERE sources.id = credentials.source_id
        )
        WHERE space_id IS NULL OR space_id = ''
        """
    )
    _ensure_columns(
        conn,
        "indexed_documents",
        {
            "knowledge_base_id": "TEXT",
            "provider_doc_id": "TEXT",
            "sync_status": "TEXT",
            "last_synced_at": "TEXT",
        },
    )
    conn.execute(
        "UPDATE indexed_documents SET sync_status = status "
        "WHERE sync_status IS NULL OR sync_status = ''"
    )
    _ensure_columns(
        conn,
        "snapshots",
        {
            "kind": "TEXT NOT NULL DEFAULT 'knowledge_asset'",
            "artifact_uri": "TEXT",
            "schema_json": "TEXT NOT NULL DEFAULT '{}'",
            "profile_json": "TEXT NOT NULL DEFAULT '{}'",
            "content_hash": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "skill_packages",
        {
            "type": "TEXT NOT NULL DEFAULT 'retrieval_binding'",
            "source_ids": "TEXT NOT NULL DEFAULT '[]'",
            "snapshot_ids": "TEXT NOT NULL DEFAULT '[]'",
            "artifact_uri": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "build_jobs",
        {
            "logs_ref": "TEXT",
            "result_skill_id": "TEXT",
        },
    )
    _ensure_columns(
        conn,
        "semantic_builder_conversations",
        {
            "document_source_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    )


def _ensure_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: dict[str, str],
) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def dumps_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


__all__ = [
    "KnowledgeAssetConflict",
    "KnowledgeAssetNotFound",
    "KnowledgeAssetRepository",
    "KnowledgeAssetRepositoryError",
    "default_db_path",
    "dumps_json",
    "loads_json",
]
