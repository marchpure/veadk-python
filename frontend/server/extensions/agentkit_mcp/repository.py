"""Durable metadata repository for MCP publications."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .models import AgentKitMcpPublication


class AgentKitMcpPublicationRepository:
    def __init__(self, database: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(database), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS agentkit_mcp_publications (
            publication_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(tenant_id, workspace_id, idempotency_key))"""
        )
        self._db.commit()

    def get(self, publication_id: str, *, tenant_id: str, workspace_id: str):
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM agentkit_mcp_publications WHERE publication_id=? AND tenant_id=? AND workspace_id=?",
                (publication_id, tenant_id, workspace_id),
            ).fetchone()
        return AgentKitMcpPublication.model_validate(json.loads(row["payload"])) if row else None

    def get_by_key(self, key: str, *, tenant_id: str, workspace_id: str):
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM agentkit_mcp_publications WHERE idempotency_key=? AND tenant_id=? AND workspace_id=?",
                (key, tenant_id, workspace_id),
            ).fetchone()
        return AgentKitMcpPublication.model_validate(json.loads(row["payload"])) if row else None

    def save(self, publication: AgentKitMcpPublication, *, idempotency_key: str) -> None:
        payload = publication.model_dump_json(by_alias=True)
        with self._lock:
            self._db.execute(
                """INSERT INTO agentkit_mcp_publications
                (publication_id,tenant_id,workspace_id,idempotency_key,payload)
                VALUES(?,?,?,?,?)
                ON CONFLICT(publication_id) DO UPDATE SET payload=excluded.payload""",
                (
                    publication.publication_id,
                    publication.tenant_id,
                    publication.workspace_id,
                    idempotency_key,
                    payload,
                ),
            )
            self._db.commit()
