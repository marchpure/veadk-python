from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from frontend.server.knowledge_assets.contract_base import (
    OwnerRef,
    PermissionRef,
    SchemaRef,
    StorageRef,
    empty_knowledge_manifest,
)
from frontend.server.knowledge_assets.contract_data import (
    GoldenAssetRevision,
    SkillDraftRevision,
)
from frontend.server.knowledge_assets.kind_runtime import (
    ExecutionBudget,
    KindExecutionRequest,
)
from frontend.server.knowledge_assets.kind_runtime.handlers import KnowledgeHandler
from frontend.server.knowledge_assets.kind_runtime.tabular import (
    infer_fields,
    parse_rows,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _digest(value: bytes | str) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else value.encode()
    ).hexdigest()


def _chunks(text: str, strategy: str) -> list[str]:
    clean = text.replace("\r\n", "\n").strip()
    if not clean:
        return []
    if strategy == "heading":
        parts = re.split(r"(?=^#{1,6}\s)", clean, flags=re.MULTILINE)
    elif strategy == "fixed":
        parts = [clean[index : index + 2000] for index in range(0, len(clean), 2000)]
    else:
        parts = re.split(r"\n\s*\n", clean)
    return [part.strip() for part in parts if part.strip()]


def _extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        extraction_errors: list[Exception] = []
        try:
            from pypdf import PdfReader

            import io

            return "\n\n".join(
                page.extract_text() or ""
                for page in PdfReader(io.BytesIO(content)).pages
            ).strip()
        except Exception as exc:
            extraction_errors.append(exc)
        try:
            import pypdfium2

            document = pypdfium2.PdfDocument(content)
            pages = []
            for page in document:
                pages.append(page.get_textpage().get_text_range())
            return "\n\n".join(pages).strip()
        except Exception as exc:
            extraction_errors.append(exc)
        raise ValueError(
            "PDF 文本提取失败，请检查文件内容或服务端 PDF 依赖。"
        ) from extraction_errors[-1]
    decoded = content.decode("utf-8")
    if suffix in {".html", ".htm"}:
        return html.unescape(re.sub(r"<[^>]+>", " ", decoded))
    return decoded


FeishuFetcher = Callable[[str, str], dict[str, Any]]


def _feishu_document_token(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "feishu.cn"
        or hostname.endswith(".feishu.cn")
        or hostname == "larksuite.com"
        or hostname.endswith(".larksuite.com")
    ):
        raise ValueError("飞书文档 URL 必须来自受支持的 HTTPS 飞书域名。")
    segments = [
        urllib.parse.unquote(segment) for segment in parsed.path.split("/") if segment
    ]
    for index, kind in enumerate(segments[:-1]):
        if kind in {"docx", "docs"} and segments[index + 1]:
            return kind, segments[index + 1]
    raise ValueError("无法从飞书文档 URL 解析文档标识。")


def fetch_feishu_document(url: str, credential: str) -> dict[str, Any]:
    """Read one Feishu/Lark docx through the server-side Open API."""

    _kind, document_token = _feishu_document_token(url)
    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    api_host = (
        "open.larksuite.com" if hostname.endswith("larksuite.com") else "open.feishu.cn"
    )
    endpoint = (
        f"https://{api_host}/open-apis/docx/v1/documents/"
        f"{urllib.parse.quote(document_token, safe='')}/raw_content"
    )
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {credential}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as exc:
        raise ValueError("飞书文档读取失败，请检查文档权限或服务端凭证。") from exc
    if payload.get("code") not in (None, 0):
        raise ValueError("飞书文档读取失败，请检查文档权限或服务端凭证。")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("飞书文档没有可同步的正文内容。")
    return {
        "documentId": document_token,
        "title": str(data.get("title") or f"飞书文档 {document_token[:8]}"),
        "content": content,
        "filename": f"feishu-{document_token}.md",
        "url": url,
    }


class DomainService:
    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS knowledge_bases (
              id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
              description TEXT NOT NULL, scope TEXT NOT NULL, lifecycle TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
              id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL, filename TEXT NOT NULL,
              title TEXT NOT NULL, description TEXT NOT NULL, tags TEXT NOT NULL,
              media_type TEXT NOT NULL, content BLOB NOT NULL, content_text TEXT NOT NULL,
              source_type TEXT NOT NULL, source_digest TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id)
            );
            CREATE TABLE IF NOT EXISTS source_revisions (
              id TEXT PRIMARY KEY, source_id TEXT NOT NULL, revision INTEGER NOT NULL,
              source_digest TEXT NOT NULL, trace_id TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(source_id, revision), FOREIGN KEY (source_id) REFERENCES sources(id)
            );
            CREATE TABLE IF NOT EXISTS golden_asset_revisions (
              id TEXT PRIMARY KEY, source_revision_id TEXT NOT NULL, revision INTEGER NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(source_revision_id, revision)
            );
            CREATE TABLE IF NOT EXISTS chunks (
              id TEXT PRIMARY KEY, source_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
              text TEXT NOT NULL, locator TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY (source_id) REFERENCES sources(id)
            );
            CREATE TABLE IF NOT EXISTS skill_drafts (
              id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL, revision INTEGER NOT NULL,
              kind TEXT NOT NULL, status TEXT NOT NULL, manifest TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS semantic_models (
              resource_id TEXT PRIMARY KEY, mdl TEXT NOT NULL, revision INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS semantic_revisions (
              id TEXT PRIMARY KEY, resource_id TEXT NOT NULL, revision INTEGER NOT NULL,
              mdl TEXT NOT NULL, diff TEXT NOT NULL, impact TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS semantic_golden_revisions (
              id TEXT PRIMARY KEY, resource_id TEXT NOT NULL, revision INTEGER NOT NULL,
              golden_asset TEXT NOT NULL, schema_json TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(resource_id, revision)
            );
            CREATE TABLE IF NOT EXISTS graph_projections (
              resource_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, projection TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_query_results (
              id TEXT PRIMARY KEY, resource_id TEXT NOT NULL, mode TEXT NOT NULL,
              result_json TEXT NOT NULL, trace_id TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_query_results (
              id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL, question TEXT NOT NULL,
              answer TEXT NOT NULL, citations_json TEXT NOT NULL, session_id TEXT NOT NULL,
              trace_id TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS domain_resource_revisions (
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, object_id TEXT NOT NULL,
              revision INTEGER NOT NULL, workspace_id TEXT NOT NULL,
              scope TEXT NOT NULL DEFAULT 'personal',
              display_name TEXT NOT NULL, payload_json TEXT NOT NULL,
              digest TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(kind, object_id, revision)
            );
            CREATE TABLE IF NOT EXISTS domain_resource_owners (
              kind TEXT NOT NULL, object_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
              PRIMARY KEY (kind, object_id)
            );
            """
        )
        columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(domain_resource_revisions)"
            ).fetchall()
        }
        if "scope" not in columns:
            self.connection.execute(
                "ALTER TABLE domain_resource_revisions "
                "ADD COLUMN scope TEXT NOT NULL DEFAULT 'personal'"
            )
        self.connection.commit()

    def _record_revision(
        self,
        *,
        kind: str,
        object_id: str,
        revision: int,
        workspace_id: str,
        display_name: str,
        payload: dict[str, Any],
        scope: str = "personal",
    ) -> dict[str, Any]:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = _digest(encoded)
        identity_digest = _digest(
            f"{kind}:{workspace_id}:{scope}:{object_id}:{revision}:{encoded}"
        )
        revision_id = f"{kind}_revision_{identity_digest[:24]}"
        self.connection.execute(
            """
            INSERT OR IGNORE INTO domain_resource_owners(kind, object_id, workspace_id)
            VALUES (?, ?, ?)
            """,
            (kind, object_id, workspace_id),
        )
        owner = self.connection.execute(
            """
            SELECT workspace_id FROM domain_resource_owners
            WHERE kind = ? AND object_id = ?
            """,
            (kind, object_id),
        ).fetchone()
        if owner is None or owner["workspace_id"] != workspace_id:
            raise PermissionError("resource belongs to another workspace")
        self.connection.execute(
            """
            INSERT OR IGNORE INTO domain_resource_revisions
            (id, kind, object_id, revision, workspace_id, scope, display_name,
             payload_json, digest, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                kind,
                object_id,
                revision,
                workspace_id,
                scope,
                display_name,
                encoded,
                digest,
                _now(),
            ),
        )
        return {
            "kind": kind,
            "objectId": object_id,
            "revision": revision_id,
            "scope": scope,
            "digest": digest,
        }

    def _require_owner(self, kind: str, object_id: str, workspace_id: str) -> None:
        row = self.connection.execute(
            """
            SELECT workspace_id FROM domain_resource_owners
            WHERE kind = ? AND object_id = ?
            """,
            (kind, object_id),
        ).fetchone()
        if row is not None and row["workspace_id"] != workspace_id:
            raise PermissionError("resource belongs to another workspace")

    def _latest_context_ref(
        self, kind: str, object_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT id, digest, scope FROM domain_resource_revisions
            WHERE kind = ? AND object_id = ? AND workspace_id = ?
            ORDER BY revision DESC LIMIT 1
            """,
            (kind, object_id, workspace_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "kind": kind,
            "objectId": object_id,
            "revision": row["id"],
            "scope": row["scope"],
            "digest": row["digest"],
        }

    def resolve_authoring_resource(
        self, *, workspace_id: str, caller_id: str, ref: Any
    ) -> dict[str, Any]:
        del caller_id
        row = self.connection.execute(
            """
            SELECT * FROM domain_resource_revisions
            WHERE id = ? AND kind = ? AND object_id = ? AND workspace_id = ?
            """,
            (ref.revision, ref.kind, ref.object_id, workspace_id),
        ).fetchone()
        if row is None:
            raise KeyError("immutable domain revision not found")
        if ref.scope.value != row["scope"]:
            raise PermissionError("resource scope does not match immutable revision")
        payload = json.loads(row["payload_json"])
        semantic_fields: list[str] = []
        if ref.kind == "semantic":
            semantic_fields = list(payload.get("validation", {}).get("fields", []))
        return {
            "ref": ref,
            "display_name": row["display_name"],
            "provider_revision": row["id"],
            "schema_digest": row["digest"],
            "capabilities": [f"{ref.kind}.read", "lineage.read"],
            "semantic_fields": semantic_fields,
            "authorized": True,
        }

    def create_knowledge_base(
        self, workspace_id: str, name: str, description: str, scope: str
    ) -> dict[str, Any]:
        now = _now()
        kb_id = _id("kb")
        draft_id = _id("skill")
        manifest = {
            "apiVersion": "knowledge.veadk.io/v1alpha1",
            "kind": "SkillDraft",
            "metadata": {"displayName": name, "description": description},
            "spec": {
                "kind": "knowledge",
                "retrievalMode": "hybrid",
                "sourceRevisionRefs": [],
            },
        }
        self.connection.execute(
            "INSERT INTO knowledge_bases VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (kb_id, workspace_id, name, description, scope, "draft", now, now),
        )
        self.connection.execute(
            "INSERT INTO skill_drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (draft_id, kb_id, 1, "knowledge", "draft", json.dumps(manifest), now, now),
        )
        context_ref = self._record_revision(
            kind="knowledge",
            object_id=kb_id,
            revision=1,
            workspace_id=workspace_id,
            display_name=name,
            payload={"manifest": manifest, "lifecycle": "draft"},
            scope=scope,
        )
        self.connection.commit()
        return {
            "id": kb_id,
            "name": name,
            "description": description,
            "scope": scope,
            "lifecycle": "draft",
            "skillDraft": {
                "id": draft_id,
                "revision": 1,
                "kind": "knowledge",
                "status": "draft",
                "manifest": manifest,
            },
            "contextRef": context_ref,
        }

    def _knowledge_base(
        self, knowledge_base_id: str, workspace_id: str | None = None
    ) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)
        ).fetchone()
        if row is None or (
            workspace_id is not None and row["workspace_id"] != workspace_id
        ):
            raise KeyError("knowledge base not found")
        return row

    def knowledge_base_summary(
        self, knowledge_base_id: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        row = self._knowledge_base(knowledge_base_id, workspace_id)
        draft = self.connection.execute(
            "SELECT id, revision, kind, status, manifest, created_at, updated_at "
            "FROM skill_drafts WHERE knowledge_base_id = ? ORDER BY revision DESC LIMIT 1",
            (knowledge_base_id,),
        ).fetchone()
        sources = self.connection.execute(
            """SELECT s.id, s.filename, s.title, s.media_type, s.source_type, s.created_at,
                      sr.id AS source_revision_id, sr.revision AS source_revision,
                      sr.source_digest, sr.trace_id,
                      gar.id AS golden_asset_id
               FROM sources s
               JOIN source_revisions sr ON sr.source_id = s.id AND sr.revision = 1
               LEFT JOIN golden_asset_revisions gar
                 ON gar.source_revision_id = sr.id AND gar.revision = 1
               WHERE s.knowledge_base_id = ? ORDER BY s.created_at""",
            (knowledge_base_id,),
        ).fetchall()
        result = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "scope": row["scope"],
            "lifecycle": row["lifecycle"],
            "skillDraft": {
                "id": draft["id"],
                "revision": draft["revision"],
                "kind": draft["kind"],
                "status": draft["status"],
                "manifest": json.loads(draft["manifest"]),
                "createdAt": draft["created_at"],
                "updatedAt": draft["updated_at"],
            }
            if draft
            else None,
            "sources": [
                {
                    "id": item["id"],
                    "name": item["title"],
                    "filename": item["filename"],
                    "mediaType": item["media_type"],
                    "type": item["source_type"],
                    "createdAt": item["created_at"],
                    "sourceRevision": {
                        "id": item["source_revision_id"],
                        "revision": item["source_revision"],
                        "sourceDigest": item["source_digest"],
                        "traceId": item["trace_id"],
                        "status": "ready",
                    },
                    "sourceRevisionId": item["source_revision_id"],
                    "goldenAssetRevision": {
                        "id": item["golden_asset_id"],
                        "revision": 1,
                        "status": "ready",
                        "sourceRevisionId": item["source_revision_id"],
                    }
                    if item["golden_asset_id"]
                    else None,
                    "index": {
                        "status": "ready",
                        "chunkCount": self.connection.execute(
                            "SELECT COUNT(*) FROM chunks WHERE source_id = ?",
                            (item["id"],),
                        ).fetchone()[0],
                    },
                    "chunks": self.connection.execute(
                        "SELECT COUNT(*) FROM chunks WHERE source_id = ?", (item["id"],)
                    ).fetchone()[0],
                }
                for item in sources
            ],
        }
        context_ref = self._latest_context_ref(
            "knowledge", knowledge_base_id, row["workspace_id"]
        )
        if context_ref is not None:
            result["contextRef"] = context_ref
        return result

    def add_source(
        self,
        knowledge_base_id: str,
        *,
        filename: str,
        title: str,
        description: str,
        tags: str,
        media_type: str,
        content: bytes,
        chunk_strategy: str,
        source_type: str = "local",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._knowledge_base(knowledge_base_id)
        text = _extract_text(filename, content)
        source_id = _id("source")
        source_revision_id = _id("src_rev")
        golden_id = _id("golden")
        trace = trace_id or _id("trace")
        now = _now()
        digest = _digest(content)
        chunk_values = _chunks(text, chunk_strategy)
        self.connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                knowledge_base_id,
                filename,
                title or filename,
                description,
                tags,
                media_type,
                content,
                text,
                source_type,
                digest,
                now,
            ),
        )
        self.connection.execute(
            "INSERT INTO source_revisions VALUES (?, ?, 1, ?, ?, ?)",
            (source_revision_id, source_id, digest, trace, now),
        )
        self.connection.execute(
            "INSERT INTO golden_asset_revisions VALUES (?, ?, 1, 'ready', ?)",
            (golden_id, source_revision_id, now),
        )
        for index, chunk in enumerate(chunk_values):
            self.connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
                (_id("chunk"), source_id, index, chunk, f"chunk-{index + 1}", now),
            )
        draft = self.connection.execute(
            "SELECT * FROM skill_drafts WHERE knowledge_base_id = ? ORDER BY revision DESC LIMIT 1",
            (knowledge_base_id,),
        ).fetchone()
        if draft:
            manifest = json.loads(draft["manifest"])
            refs = manifest["spec"].setdefault("sourceRevisionRefs", [])
            refs.append(source_revision_id)
            self.connection.execute(
                "UPDATE skill_drafts SET manifest = ?, updated_at = ? WHERE id = ?",
                (json.dumps(manifest), now, draft["id"]),
            )
        self.connection.execute(
            "UPDATE knowledge_bases SET updated_at = ? WHERE id = ?",
            (now, knowledge_base_id),
        )
        knowledge_base = self._knowledge_base(knowledge_base_id)
        document_ref = self._record_revision(
            kind="document",
            object_id=source_id,
            revision=1,
            workspace_id=knowledge_base["workspace_id"],
            display_name=title or filename,
            payload={
                "sourceRevisionId": source_revision_id,
                "sourceDigest": digest,
                "mediaType": media_type,
                "traceId": trace,
            },
            scope=knowledge_base["scope"],
        )
        knowledge_ref = self._record_revision(
            kind="knowledge",
            object_id=knowledge_base_id,
            revision=len(self.knowledge_base_summary(knowledge_base_id)["sources"]) + 1,
            workspace_id=knowledge_base["workspace_id"],
            display_name=knowledge_base["name"],
            payload={
                "sourceRevisionId": source_revision_id,
                "sourceDigest": digest,
                "lifecycle": knowledge_base["lifecycle"],
            },
            scope=knowledge_base["scope"],
        )
        self.connection.commit()
        return {
            "document": {
                "id": source_id,
                "knowledgeBaseId": knowledge_base_id,
                "title": title or filename,
                "filename": filename,
                "content": text,
                "contentBytes": len(content),
            },
            "sourceRevision": {
                "id": source_revision_id,
                "revision": 1,
                "sourceDigest": digest,
                "traceId": trace,
                "status": "ready",
            },
            "goldenAssetRevision": {
                "id": golden_id,
                "revision": 1,
                "status": "ready",
                "sourceRevisionId": source_revision_id,
            },
            "index": {
                "status": "ready",
                "chunkCount": len(chunk_values),
                "indexedAt": now,
            },
            "chunks": [
                {"id": row["id"], "locator": row["locator"], "text": row["text"]}
                for row in self.connection.execute(
                    "SELECT id, locator, text FROM chunks WHERE source_id = ? ORDER BY chunk_index",
                    (source_id,),
                )
            ],
            "skillDraft": {"id": draft["id"], "revision": draft["revision"]}
            if draft
            else None,
            "documentContextRef": document_ref,
            "knowledgeContextRef": knowledge_ref,
        }

    def standalone_document(self, workspace_id: str, **kwargs: Any) -> dict[str, Any]:
        created = self.create_knowledge_base(
            workspace_id,
            kwargs["title"] or kwargs["filename"],
            kwargs["description"],
            kwargs["scope"],
        )
        result = self.add_source(created["id"], **kwargs)
        result["knowledgeBase"] = created
        return result

    def document(
        self, source_id: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT s.* FROM sources AS s
            JOIN knowledge_bases AS kb ON kb.id = s.knowledge_base_id
            WHERE s.id = ? AND (? IS NULL OR kb.workspace_id = ?)
            """,
            (source_id, workspace_id, workspace_id),
        ).fetchone()
        if row is None:
            raise KeyError("document not found")
        chunks = self.connection.execute(
            "SELECT id, locator, text FROM chunks WHERE source_id = ? ORDER BY chunk_index",
            (source_id,),
        ).fetchall()
        result = {
            "id": row["id"],
            "knowledgeBaseId": row["knowledge_base_id"],
            "title": row["title"],
            "filename": row["filename"],
            "description": row["description"],
            "tags": row["tags"],
            "mediaType": row["media_type"],
            "content": row["content_text"],
            "chunks": [
                {"id": item["id"], "locator": item["locator"], "text": item["text"]}
                for item in chunks
            ],
            "index": {"status": "ready", "chunkCount": len(chunks)},
        }
        owner = self._knowledge_base(row["knowledge_base_id"])["workspace_id"]
        context_ref = self._latest_context_ref("document", source_id, owner)
        if context_ref is not None:
            result["contextRef"] = context_ref
        return result

    def inspect_feishu(
        self,
        url: str,
        credential: str | None,
        fetcher: FeishuFetcher = fetch_feishu_document,
    ) -> dict[str, Any]:
        if not credential:
            return {
                "status": "credential_blocked",
                "url": url,
                "message": "飞书连接需要服务端凭证。",
            }
        document = fetcher(url, credential)
        return {
            "status": "ready",
            "url": url,
            "credentialRequired": True,
            "document": {
                "id": document["documentId"],
                "title": document["title"],
                "contentBytes": len(document["content"].encode("utf-8")),
            },
        }

    def sync_feishu(
        self,
        knowledge_base_id: str,
        url: str,
        credential: str | None,
        include_children: bool,
        fetcher: FeishuFetcher = fetch_feishu_document,
    ) -> dict[str, Any]:
        if not credential:
            return {
                "status": "credential_blocked",
                "url": url,
                "message": "飞书连接需要服务端凭证。",
            }
        document = fetcher(url, credential)
        result = self.add_source(
            knowledge_base_id,
            filename=document["filename"],
            title=document["title"],
            description="飞书文档同步",
            tags="feishu",
            media_type="text/markdown",
            content=document["content"].encode("utf-8"),
            chunk_strategy="auto",
            source_type="feishu",
        )
        result["connector"] = {
            "provider": "feishu",
            "documentId": document["documentId"],
            "url": url,
            "includeChildren": include_children,
        }
        return result

    def ask(
        self,
        knowledge_base_id: str,
        question: str,
        top_k: int,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        knowledge_base = self._knowledge_base(knowledge_base_id, workspace_id)
        terms = [term.lower() for term in re.findall(r"\w+", question) if len(term) > 1]
        rows = self.connection.execute(
            """SELECT c.id, c.text, c.locator, s.title, s.id AS source_id,
                      sr.id AS source_revision_id, sr.source_digest, s.media_type,
                      sr.trace_id
               FROM chunks c JOIN sources s ON s.id = c.source_id
               JOIN source_revisions sr ON sr.source_id = s.id AND sr.revision = 1
               WHERE s.knowledge_base_id = ? ORDER BY c.chunk_index""",
            (knowledge_base_id,),
        ).fetchall()
        ranked = sorted(
            rows,
            key=lambda row: sum(term in row["text"].lower() for term in terms),
            reverse=True,
        )
        selected = [
            row
            for row in ranked
            if not terms or any(term in row["text"].lower() for term in terms)
        ][: max(1, top_k)]
        trace = _id("trace")
        skill_answer = self._run_knowledge_skill(knowledge_base, question, rows, trace)
        citations = [
            {
                "id": row["id"],
                "sourceId": row["source_id"],
                "title": row["title"],
                "locator": row["locator"],
                "snippet": row["text"][:400],
            }
            for row in selected
        ]
        answer = skill_answer or "知识库中没有找到与问题匹配的内容。"
        session_id = _id("session")
        query_result_id = _id("knowledge_query")
        now = _now()
        self.connection.execute(
            "INSERT INTO knowledge_query_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                query_result_id,
                knowledge_base_id,
                question,
                answer,
                json.dumps(citations, ensure_ascii=False),
                session_id,
                trace,
                now,
            ),
        )
        self.connection.commit()
        return {
            "answer": answer,
            "citations": citations,
            "sessionId": session_id,
            "traceId": trace,
            "queryResultId": query_result_id,
            "skill": {
                "kind": "knowledge",
                "runtime": "worker3-knowledge",
                "sourceCount": len(selected),
            },
        }

    def knowledge_query_result(
        self,
        knowledge_base_id: str,
        query_result_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        self._knowledge_base(knowledge_base_id, workspace_id)
        row = self.connection.execute(
            "SELECT * FROM knowledge_query_results WHERE id = ? AND knowledge_base_id = ?",
            (query_result_id, knowledge_base_id),
        ).fetchone()
        if row is None:
            raise KeyError("knowledge query result not found")
        return {
            "queryResultId": row["id"],
            "knowledgeBaseId": row["knowledge_base_id"],
            "question": row["question"],
            "answer": row["answer"],
            "citations": json.loads(row["citations_json"]),
            "sessionId": row["session_id"],
            "traceId": row["trace_id"],
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _run_knowledge_skill(
        knowledge_base: sqlite3.Row,
        question: str,
        rows: list[sqlite3.Row],
        trace_id: str,
    ) -> str | None:
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["source_id"], []).append(row)
        golden_assets = []
        contents: dict[str, str] = {}
        source_refs: list[str] = []
        for source_id, source_rows in grouped.items():
            first = source_rows[0]
            golden_id = f"golden_{first['source_digest']}"
            source_revision_id = first["source_revision_id"]
            source_refs.append(source_revision_id)
            contents[golden_id] = "\n\n".join(item["text"] for item in source_rows)
            golden_assets.append(
                GoldenAssetRevision(
                    id=golden_id,
                    asset_kind="knowledge",
                    revision=1,
                    schema_ref=SchemaRef(
                        uri=f"local://schema/knowledge/{first['source_digest']}",
                        version="1",
                        sha256=first["source_digest"],
                    ),
                    storage_ref=StorageRef(
                        uri=f"local://knowledge/{first['source_digest']}",
                        kind="inline",
                        sha256=first["source_digest"],
                        media_type=first["media_type"],
                        bytes=len(contents[golden_id].encode("utf-8")),
                    ),
                    source_revision_refs=[source_revision_id],
                    owner=OwnerRef(
                        workspace_id=knowledge_base["workspace_id"],
                        principal_id="knowledge-domain",
                    ),
                    permissions_ref=PermissionRef(
                        uri=f"permission://workspace/{knowledge_base['workspace_id']}/read",
                        version="1",
                    ),
                    lineage_digest=first["source_digest"],
                    freshness_at=first["trace_id"],
                )
            )
        if not golden_assets:
            return None
        draft = SkillDraftRevision(
            id=f"skill-revision-{knowledge_base['id']}",
            skill_id=f"skill-{knowledge_base['id']}",
            revision=1,
            manifest=empty_knowledge_manifest(
                draft_id=f"skill-{knowledge_base['id']}",
                workspace_id=knowledge_base["workspace_id"],
                name=knowledge_base["name"],
                description=question,
            ),
            source_revision_refs=source_refs,
            golden_asset_revision_refs=[item.id for item in golden_assets],
            status="draft",
            created_at=_now(),
        )
        request = KindExecutionRequest(
            draft_revision=draft,
            caller_id="knowledge-domain",
            workspace_id=knowledge_base["workspace_id"],
            golden_asset_revisions=golden_assets,
            golden_asset_contents=contents,
            budget=ExecutionBudget(max_bytes=10_000_000),
            freshness_at=_now(),
            idempotency_key=f"knowledge-query-{trace_id}",
            trace_id=trace_id,
            now=_now(),
        )
        output = KnowledgeHandler().execute(request)
        view_model = output.view_model
        return (
            str(view_model.answer)
            if view_model is not None and hasattr(view_model, "answer")
            else None
        )

    def publish(
        self, knowledge_base_id: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        knowledge_base = self._knowledge_base(knowledge_base_id, workspace_id)
        now = _now()
        self.connection.execute(
            "UPDATE knowledge_bases SET lifecycle = 'published', updated_at = ? WHERE id = ?",
            (now, knowledge_base_id),
        )
        self.connection.execute(
            "UPDATE skill_drafts SET status = 'ready', updated_at = ? WHERE knowledge_base_id = ?",
            (now, knowledge_base_id),
        )
        self.connection.commit()
        context_ref = self._record_revision(
            kind="knowledge",
            object_id=knowledge_base_id,
            revision=len(self.knowledge_base_summary(knowledge_base_id)["sources"]) + 2,
            workspace_id=knowledge_base["workspace_id"],
            display_name=knowledge_base["name"],
            payload={"lifecycle": "published", "publishedAt": now},
            scope=knowledge_base["scope"],
        )
        self.connection.commit()
        return {
            "knowledgeBaseId": knowledge_base_id,
            "lifecycle": "published",
            "publishedAt": now,
            "contextRef": context_ref,
        }

    @staticmethod
    def validate_mdl(mdl: str) -> dict[str, Any]:
        if not mdl.strip():
            return {
                "valid": False,
                "errors": [{"line": 1, "message": "MDL 不能为空。"}],
            }
        lines = mdl.splitlines()
        models = re.findall(r"^\s*model\s+([A-Za-z_]\w*)\s*\{", mdl, re.MULTILINE)
        if not models:
            return {
                "valid": False,
                "errors": [{"line": 1, "message": "缺少 model 声明。"}],
            }
        errors: list[dict[str, Any]] = []
        depth = 0
        parsed_models: list[dict[str, Any]] = []
        current_model: dict[str, Any] | None = None
        fields: set[str] = set()
        field_lines: dict[str, int] = {}
        joins: list[dict[str, str]] = []

        for line_no, raw_line in enumerate(lines, 1):
            line = raw_line.split("//", 1)[0].strip()
            if not line:
                continue
            if line.startswith("model "):
                match = re.fullmatch(r"model\s+([A-Za-z_]\w*)\s*\{", line)
                if not match:
                    errors.append({"line": line_no, "message": "model 声明格式无效。"})
                    continue
                if current_model is not None:
                    errors.append(
                        {"line": line_no, "message": "上一个 model 缺少结束括号。"}
                    )
                current_model = {"name": match.group(1), "fields": [], "joins": []}
                parsed_models.append(current_model)
                depth += 1
                continue
            if line == "}":
                if current_model is None:
                    errors.append(
                        {"line": line_no, "message": "出现了未匹配的结束括号。"}
                    )
                else:
                    current_model = None
                depth -= 1
                continue
            if current_model is None:
                errors.append({"line": line_no, "message": "字段必须位于 model 块内。"})
                continue

            field_match = re.fullmatch(
                r"(primary_key|dimension|measure|time|calculated)\s+([A-Za-z_]\w*)"
                r"(?:\s*:\s*([A-Za-z_]\w*)(?:\s*=\s*(.+))?)?",
                line,
            )
            if field_match:
                role, name, field_type, expression = field_match.groups()
                if name in fields:
                    errors.append(
                        {"line": line_no, "message": f"字段 {name} 重复定义。"}
                    )
                if field_type and field_type not in {
                    "string",
                    "number",
                    "integer",
                    "boolean",
                    "date",
                    "datetime",
                    "calculated",
                }:
                    errors.append(
                        {"line": line_no, "message": f"字段类型 {field_type} 未注册。"}
                    )
                fields.add(name)
                field_lines[name] = line_no
                field = {
                    "name": name,
                    "role": "primary_key" if role == "primary_key" else role,
                    "type": field_type or ("string" if role == "primary_key" else None),
                }
                if expression:
                    field["expression"] = expression.strip()
                current_model["fields"].append(field)
                continue

            join_match = re.fullmatch(
                r"join\s+([A-Za-z_]\w*)\s+on\s+([A-Za-z_]\w*)\.([A-Za-z_]\w*)"
                r"\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)"
                r"(?:\s*\(([^)]+)\))?",
                line,
            )
            if join_match:
                (
                    target,
                    left_model,
                    left_field,
                    right_model,
                    right_field,
                    cardinality,
                ) = join_match.groups()
                join = {
                    "target": target,
                    "left": f"{left_model}.{left_field}",
                    "right": f"{right_model}.{right_field}",
                    "cardinality": (cardinality or "").strip(),
                }
                joins.append(join)
                current_model["joins"].append(join)
                continue

            errors.append({"line": line_no, "message": "字段或关系声明格式无效。"})

        if depth != 0 or current_model is not None:
            errors.append({"line": len(lines), "message": "model 括号不平衡。"})

        model_names = set(models)
        for join in joins:
            target_model = join["target"]
            left_model = join["left"].split(".", 1)[0]
            right_model = join["right"].split(".", 1)[0]
            if (
                target_model not in model_names
                or left_model not in model_names
                or right_model not in model_names
            ):
                errors.append({"line": 1, "message": "关系引用了未知 model。"})

        for model in parsed_models:
            local_fields = {field["name"] for field in model["fields"]}
            for field in model["fields"]:
                expression = field.get("expression")
                if not expression:
                    continue
                identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", expression))
                allowed = local_fields | {
                    "true",
                    "false",
                    "null",
                    "sum",
                    "count",
                    "min",
                    "max",
                    "avg",
                }
                unknown = sorted(
                    identifier
                    for identifier in identifiers
                    if identifier not in allowed
                )
                for identifier in unknown:
                    errors.append(
                        {
                            "line": field_lines.get(field["name"], 1),
                            "message": f"计算字段引用了未知字段 {identifier}。",
                        }
                    )

        schema = {
            "models": parsed_models,
            "fields": sorted(fields),
            "joins": joins,
        }
        return {
            "valid": not errors,
            "errors": errors,
            "models": models,
            "fields": sorted(fields),
            "schema": schema,
        }

    def get_semantic(
        self, resource_id: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        if workspace_id is not None:
            self._require_owner("semantic", resource_id, workspace_id)
        row = self.connection.execute(
            "SELECT * FROM semantic_models WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if row is None:
            return {
                "resourceId": resource_id,
                "revision": 0,
                "mdl": "",
                "schema": {"models": [], "fields": []},
                "goldenAssetRevision": None,
            }
        golden = self.connection.execute(
            "SELECT golden_asset, schema_json FROM semantic_golden_revisions "
            "WHERE resource_id = ? AND revision = ?",
            (resource_id, row["revision"]),
        ).fetchone()
        result = {
            "resourceId": resource_id,
            "revision": row["revision"],
            "mdl": row["mdl"],
            "schema": self.validate_mdl(row["mdl"]),
        }
        if golden:
            golden_asset = json.loads(golden["golden_asset"])
            result["goldenAssetRevision"] = golden_asset
            source_refs = golden_asset.get("sourceRevisionRefs", [])
            if source_refs:
                result["sourceRevisionId"] = source_refs[0]
            result["goldenSchema"] = json.loads(golden["schema_json"])
        else:
            result["goldenAssetRevision"] = None
        context_ref = self._latest_context_ref(
            "semantic", resource_id, workspace_id or "workspace-worker-b"
        )
        if context_ref is not None:
            result["contextRef"] = context_ref
        return result

    def validate_semantic(
        self, mdl: str, source_revision_id: str | None = None
    ) -> dict[str, Any]:
        result = self.validate_mdl(mdl)
        if not result["valid"] or not source_revision_id:
            return result
        try:
            _golden, source_schema = self._source_golden_asset(
                "semantic-validation", source_revision_id, 1
            )
        except ValueError as exc:
            return {
                **result,
                "valid": False,
                "errors": [*result["errors"], {"line": 1, "message": str(exc)}],
            }
        unknown = sorted(set(result["fields"]) - set(source_schema["columns"]))
        if unknown:
            return {
                **result,
                "valid": False,
                "errors": [
                    *result["errors"],
                    *[
                        {
                            "line": 1,
                            "message": f"语义模型字段不在 Golden data schema 中：{field}。",
                        }
                        for field in unknown
                    ],
                ],
            }
        return result

    def source_revisions(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT sr.id, sr.revision, sr.source_digest, sr.trace_id, sr.created_at,
                      s.id AS source_id, s.title, s.filename, s.media_type,
                      s.knowledge_base_id
               FROM source_revisions sr
               JOIN sources s ON s.id = sr.source_id
               JOIN knowledge_bases kb ON kb.id = s.knowledge_base_id
               WHERE sr.revision = 1 AND (? IS NULL OR kb.workspace_id = ?)
               ORDER BY sr.created_at DESC""",
            (workspace_id, workspace_id),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "revision": row["revision"],
                "sourceId": row["source_id"],
                "title": row["title"],
                "filename": row["filename"],
                "mediaType": row["media_type"],
                "knowledgeBaseId": row["knowledge_base_id"],
                "sourceDigest": row["source_digest"],
                "traceId": row["trace_id"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def _source_golden_asset(
        self, resource_id: str, source_revision_id: str, semantic_revision: int
    ) -> tuple[GoldenAssetRevision, dict[str, Any]]:
        row = self.connection.execute(
            """SELECT sr.id, sr.source_id, sr.source_digest, sr.trace_id, sr.created_at,
                      s.content_text, s.media_type, s.knowledge_base_id
               FROM source_revisions sr JOIN sources s ON s.id = sr.source_id
               WHERE sr.id = ?""",
            (source_revision_id,),
        ).fetchone()
        if row is None:
            raise ValueError("语义模型引用的 SourceRevision 不存在。")
        digest = row["source_digest"]
        golden = GoldenAssetRevision(
            id=f"golden_source_{resource_id}_{source_revision_id}_{semantic_revision}",
            asset_kind="dataset",
            revision=1,
            schema_ref=SchemaRef(
                uri=f"local://schema/source/{source_revision_id}",
                version="1",
                sha256=digest,
            ),
            storage_ref=StorageRef(
                uri=f"local://source/{source_revision_id}",
                kind="inline",
                sha256=digest,
                media_type=row["media_type"],
                bytes=len(row["content_text"].encode("utf-8")),
            ),
            source_revision_refs=[source_revision_id],
            owner=OwnerRef(
                workspace_id=row["knowledge_base_id"],
                principal_id="knowledge-domain",
            ),
            permissions_ref=PermissionRef(
                uri=f"permission://workspace/{row['knowledge_base_id']}/read",
                version="1",
            ),
            lineage_digest=digest,
            freshness_at=row["trace_id"],
        )
        rows = parse_rows(row["content_text"])
        numeric, dimensions, dates = infer_fields(rows)
        return golden, {
            "sourceRevisionId": source_revision_id,
            "columns": list(rows[0].keys()) if rows else [],
            "numeric": numeric,
            "dimensions": dimensions,
            "dates": dates,
            "rowCount": len(rows),
        }

    @staticmethod
    def _semantic_golden_asset(
        resource_id: str,
        revision: int,
        mdl: str,
        validation: dict[str, Any],
        now: str,
    ) -> GoldenAssetRevision:
        digest = _digest(mdl)
        return GoldenAssetRevision(
            id=f"golden_semantic_{resource_id}_{revision}",
            asset_kind="semantic",
            revision=revision,
            schema_ref=SchemaRef(
                uri=f"local://schema/semantic/{resource_id}/{revision}",
                version=str(revision),
                sha256=digest,
            ),
            storage_ref=StorageRef(
                uri=f"local://semantic/{resource_id}/{revision}",
                kind="inline",
                sha256=digest,
                media_type="text/x-mdl",
                bytes=len(mdl.encode("utf-8")),
            ),
            source_revision_refs=[],
            owner=OwnerRef(
                workspace_id="workspace-semantic", principal_id="knowledge-domain"
            ),
            permissions_ref=PermissionRef(
                uri="permission://workspace/semantic/read", version="1"
            ),
            lineage_digest=digest,
            freshness_at=now,
        )

    def save_semantic(
        self,
        resource_id: str,
        mdl: str,
        expected_revision: int,
        source_revision_id: str | None = None,
        workspace_id: str = "workspace-worker-b",
    ) -> dict[str, Any]:
        self._require_owner("semantic", resource_id, workspace_id)
        validation = self.validate_semantic(mdl, source_revision_id)
        if not validation["valid"]:
            raise ValueError(json.dumps(validation["errors"], ensure_ascii=False))
        source_golden = None
        source_schema = None
        if source_revision_id:
            source_golden, source_schema = self._source_golden_asset(
                resource_id, source_revision_id, expected_revision + 1
            )
        current = self.connection.execute(
            "SELECT * FROM semantic_models WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        current_revision = current["revision"] if current else 0
        if current_revision != expected_revision:
            raise RuntimeError("semantic revision conflict")
        revision = current_revision + 1
        old_fields = (
            set(self.validate_mdl(current["mdl"])["fields"]) if current else set()
        )
        new_fields = set(validation["fields"])
        diff = {
            "addedFields": sorted(new_fields - old_fields),
            "removedFields": sorted(old_fields - new_fields),
        }
        impact = {
            "affectedAssets": [],
            "warnings": ["下游影响分析基于当前服务端注册资产。"],
        }
        now = _now()
        golden_asset = source_golden or self._semantic_golden_asset(
            resource_id, revision, mdl, validation, now
        )
        self.connection.execute(
            "INSERT INTO semantic_models(resource_id, mdl, revision, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(resource_id) DO UPDATE SET mdl = excluded.mdl, revision = excluded.revision, updated_at = excluded.updated_at",
            (resource_id, mdl, revision, now),
        )
        self.connection.execute(
            "INSERT INTO semantic_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _id("sem_rev"),
                resource_id,
                revision,
                mdl,
                json.dumps(diff),
                json.dumps(impact),
                now,
            ),
        )
        self.connection.execute(
            "INSERT INTO semantic_golden_revisions VALUES (?, ?, ?, ?, ?, ?)",
            (
                golden_asset.id,
                resource_id,
                revision,
                json.dumps(
                    golden_asset.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                ),
                json.dumps(source_schema or validation["schema"], ensure_ascii=False),
                now,
            ),
        )
        context_ref = self._record_revision(
            kind="semantic",
            object_id=resource_id,
            revision=revision,
            workspace_id=workspace_id,
            display_name=resource_id,
            payload={
                "mdl": mdl,
                "validation": validation,
                "diff": diff,
                "impact": impact,
                "goldenAssetRevision": golden_asset.model_dump(
                    mode="json", by_alias=True
                ),
            },
        )
        self.connection.commit()
        return {
            "resourceId": resource_id,
            "revision": revision,
            "mdl": mdl,
            "validation": validation,
            "diff": diff,
            "impact": impact,
            "goldenAssetRevision": golden_asset.model_dump(mode="json", by_alias=True),
            "goldenSchema": source_schema or validation["schema"],
            "contextRef": context_ref,
        }

    def graph(
        self, resource_id: str, workspace_id: str | None = None
    ) -> dict[str, Any]:
        if workspace_id is not None:
            self._require_owner("graph", resource_id, workspace_id)
        row = self.connection.execute(
            "SELECT * FROM graph_projections WHERE resource_id = ?", (resource_id,)
        ).fetchone()
        if row is None:
            return {
                "resourceId": resource_id,
                "revision": 0,
                "entities": [],
                "relationships": [],
                "constraints": [],
                "lineage": [],
            }
        projection = json.loads(row["projection"])
        result = {"resourceId": resource_id, "revision": row["revision"], **projection}
        context_ref = self._latest_context_ref(
            "graph", resource_id, workspace_id or "workspace-worker-b"
        )
        if context_ref is not None:
            result["contextRef"] = context_ref
        return result

    def mutate_graph(
        self,
        resource_id: str,
        mutation: dict[str, Any],
        workspace_id: str = "workspace-worker-b",
    ) -> dict[str, Any]:
        self._require_owner("graph", resource_id, workspace_id)
        current = self.graph(resource_id, workspace_id)
        entities = list(current["entities"])
        relationships = list(current["relationships"])
        operation = mutation.get("operation")
        if operation == "upsert_entity":
            entity = mutation.get("entity")
            if (
                not isinstance(entity, dict)
                or not entity.get("id")
                or not entity.get("type")
            ):
                raise ValueError("实体必须包含 id 和 type。")
            entities = [item for item in entities if item.get("id") != entity["id"]] + [
                entity
            ]
        elif operation == "upsert_relationship":
            relationship = mutation.get("relationship")
            if (
                not isinstance(relationship, dict)
                or not relationship.get("id")
                or not relationship.get("from")
                or not relationship.get("to")
                or not relationship.get("type")
            ):
                raise ValueError("关系必须包含 id、from、to 和 type。")
            entity_ids = {item.get("id") for item in entities}
            if (
                relationship["from"] not in entity_ids
                or relationship["to"] not in entity_ids
            ):
                raise ValueError("关系必须引用已存在的实体。")
            relationships = [
                item for item in relationships if item.get("id") != relationship["id"]
            ] + [relationship]
        else:
            raise ValueError("不支持的图谱变更。")
        revision = int(current["revision"]) + 1
        projection = {
            "entities": entities,
            "relationships": relationships,
            "constraints": current.get("constraints", []),
            "lineage": current.get("lineage", []),
        }
        if operation == "upsert_entity":
            for constraint in entity.get("constraints", []):
                projection["constraints"].append(
                    {"entityId": entity["id"], "constraint": constraint}
                )
            target_id = entity["id"]
        else:
            target_id = relationship["id"]
        now = _now()
        projection["lineage"].append(
            {
                "revision": revision,
                "operation": operation,
                "targetId": target_id,
                "recordedAt": now,
            }
        )
        self.connection.execute(
            "INSERT INTO graph_projections VALUES (?, ?, ?, ?) ON CONFLICT(resource_id) DO UPDATE SET revision = excluded.revision, projection = excluded.projection, updated_at = excluded.updated_at",
            (resource_id, revision, json.dumps(projection), now),
        )
        context_ref = self._record_revision(
            kind="graph",
            object_id=resource_id,
            revision=revision,
            workspace_id=workspace_id,
            display_name=resource_id,
            payload=projection,
        )
        self.connection.commit()
        return {
            "resourceId": resource_id,
            "revision": revision,
            **projection,
            "contextRef": context_ref,
        }

    def query_graph(
        self,
        resource_id: str,
        query: dict[str, Any],
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        projection = self.graph(resource_id, workspace_id)
        mode = query.get("mode", "neighbors")
        if mode not in {"neighbors", "path"}:
            raise ValueError("不支持的图查询模式。")
        if mode == "path":
            start = query.get("from")
            end = query.get("to")
            if (
                not isinstance(start, str)
                or not isinstance(end, str)
                or not start
                or not end
            ):
                raise ValueError("路径查询必须包含 from 和 to。")
            adjacency: dict[str, list[dict[str, Any]]] = {}
            for relationship in projection["relationships"]:
                source = relationship.get("from")
                target = relationship.get("to")
                if isinstance(source, str) and isinstance(target, str):
                    adjacency.setdefault(source, []).append(relationship)
            queue: list[tuple[str, list[dict[str, Any]]]] = [(start, [])]
            visited = {start}
            path: list[dict[str, Any]] = []
            while queue:
                node, candidate = queue.pop(0)
                if node == end:
                    path = candidate
                    break
                for relationship in adjacency.get(node, []):
                    target = relationship.get("to")
                    if isinstance(target, str) and target not in visited:
                        visited.add(target)
                        queue.append((target, [*candidate, relationship]))
            path_nodes = [start]
            path_nodes.extend(
                relationship["to"]
                for relationship in path
                if isinstance(relationship.get("to"), str)
            )
            result = {
                "queryResultId": _id("graph_query"),
                "mode": "path",
                "from": start,
                "to": end,
                "entities": path_nodes if path else [],
                "relationships": path,
                "traceId": _id("trace"),
            }
            self._persist_graph_query(resource_id, result)
            return result
        entity_id = query.get("entityId")
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("邻居查询必须包含 entityId。")
        neighbors = [
            item
            for item in projection["relationships"]
            if item.get("from") == entity_id or item.get("to") == entity_id
        ]
        result = {
            "queryResultId": _id("graph_query"),
            "mode": "neighbors",
            "entityId": entity_id,
            "relationships": neighbors,
            "entities": sorted(
                {
                    entity_id,
                    *[
                        endpoint
                        for relationship in neighbors
                        for endpoint in (
                            relationship.get("from"),
                            relationship.get("to"),
                        )
                        if isinstance(endpoint, str)
                    ],
                }
            ),
            "traceId": _id("trace"),
        }
        self._persist_graph_query(resource_id, result)
        return result

    def _persist_graph_query(self, resource_id: str, result: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO graph_query_results VALUES (?, ?, ?, ?, ?, ?)",
            (
                result["queryResultId"],
                resource_id,
                result["mode"],
                json.dumps(result, ensure_ascii=False),
                result["traceId"],
                _now(),
            ),
        )
        self.connection.commit()

    def graph_query_result(
        self,
        resource_id: str,
        query_result_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        self.graph(resource_id, workspace_id)
        row = self.connection.execute(
            "SELECT result_json FROM graph_query_results WHERE id = ? AND resource_id = ?",
            (query_result_id, resource_id),
        ).fetchone()
        if row is None:
            raise KeyError("graph query result not found")
        return json.loads(row["result_json"])
