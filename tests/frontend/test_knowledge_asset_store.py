from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from typing import Any, cast

import pytest

from frontend.server.knowledge_assets import KnowledgeAssetStore
from frontend.server.knowledge_assets.crypto import (
    CredentialCipher,
    CredentialCryptoError,
    default_key_path,
)
from frontend.server.knowledge_assets.models import (
    CreateSourceBody,
    CreateSourceResourceBody,
    CreateSpaceBody,
    ImportSourceBody,
    RecordBuildJobBody,
    RecordIndexedDocumentBody,
    RecordSkillPackageBody,
    SaveCredentialBody,
    SemanticInstructionBody,
    SemanticQuestionSqlPairBody,
    UpdateBuildJobBody,
    UpdateSemanticInstructionBody,
    UpdateSemanticQuestionSqlPairBody,
    UpdateSourceResourceBody,
    UpdateSourceStatusBody,
)
from frontend.server.knowledge_assets.service import (
    KnowledgeAssetCredentialError,
    KnowledgeAssetServiceError,
)


@pytest.fixture()
def store_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(
        "VEADK_STUDIO_ASSET_DB",
        str(tmp_path / "knowledge-assets.db"),
    )
    monkeypatch.delenv("VEADK_STUDIO_ASSET_SECRET", raising=False)
    return tmp_path


def test_default_paths_resolve_under_studio_home(store_env, monkeypatch) -> None:
    assert (
        default_key_path()
        == store_env / "home" / ".veadk" / "studio" / "asset-store.key"
    )
    from frontend.server.knowledge_assets.repository import default_db_path

    assert default_db_path() == store_env / "knowledge-assets.db"


def test_store_records_assets_and_deduplicates_documents(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(
            CreateSpaceBody(name="Knowledge Center", metadata={"owner": "local"})
        )
        source = await store.create_source(
            CreateSourceBody(
                space_id=space["id"],
                source_type="web",
                name="Docs",
                uri="https://example.test/docs",
            )
        )
        first = await store.record_indexed_document(
            RecordIndexedDocumentBody(
                source_id=source["id"],
                content_hash="sha256:abc",
                title="First",
            )
        )
        second = await store.record_indexed_document(
            RecordIndexedDocumentBody(
                source_id=source["id"],
                content_hash="sha256:abc",
                title="Updated",
            )
        )
        assert first["id"] == second["id"]
        docs = await store.list_indexed_documents(source_id=source["id"])
        assert len(docs) == 1
        assert docs[0]["title"] == "Updated"

        skill = await store.record_skill_package(
            RecordSkillPackageBody(
                space_id=space["id"],
                asset_type="knowledge_resource",
                asset_id="kb_docs",
                capability_kind="retrieval_binding",
                name="Docs Retrieval",
                publish_state="published",
                status="ready",
                capability_package={
                    "binding": "kb_docs",
                    "headers": {"Authorization": "Bearer should-not-echo"},
                },
                query_url="/api/knowledge-assets/assets/knowledge_resource/kb_docs",
            )
        )
        assert skill["schema_version"] == "knowledge_asset.metadata.v1"
        assert skill["capability_package"]["headers"]["Authorization"] == "[REDACTED]"
        listed = await store.list_assets()
        assert listed["schema_version"] == "knowledge_asset.list.v1"
        assert listed["total"] == 1
        assert listed["mock"] is False
        loaded = await store.get_asset(
            asset_type="knowledge_resource",
            asset_id="kb_docs",
        )
        assert loaded["name"] == "Docs Retrieval"

    asyncio.run(scenario())


def test_source_status_machine_rejects_pending_patch(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        source = await store.create_source(
            CreateSourceBody(
                space_id=space["id"],
                source_type="web",
                name="Docs",
                status="pending",
            )
        )
        assert source["status"] == "needs_configuration"
        with pytest.raises(KnowledgeAssetServiceError, match="pending"):
            await store.update_source_status(
                source["id"],
                UpdateSourceStatusBody(status="pending"),
            )

    asyncio.run(scenario())


def test_build_job_status_machine_rejects_unknown_state(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        with pytest.raises(KnowledgeAssetServiceError, match="状态无效"):
            await store.record_build_job(RecordBuildJobBody(status="waiting_forever"))

    asyncio.run(scenario())


class _FakeKnowledgeService:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def create_document(self, knowledge_id, body, *, identity, region):
        self.created.append(
            {
                "knowledge_id": knowledge_id,
                "body": body,
                "identity": identity,
                "region": region,
            }
        )
        return {
            "id": "doc_1",
            "name": body.name,
            "metadata": body.metadata,
        }


def test_import_source_writes_indexed_document_and_terminal_job(store_env) -> None:
    store = KnowledgeAssetStore()
    knowledge_service = _FakeKnowledgeService()

    async def scenario() -> None:
        space = await store.create_space(
            CreateSpaceBody(name="KC", default_knowledge_base_id="kb-docs")
        )
        result = await store.import_source(
            ImportSourceBody(
                space_id=space["id"],
                source_type="local_web",
                name="政策页面",
                uri="https://internal.example/policy",
                content="# 政策页面\n\n可导入正文",
                content_format="markdown",
            ),
            knowledge_service=knowledge_service,
            identity=object(),
            region="cn-beijing",
        )

        assert result["source"]["status"] == "indexed"
        assert result["job"]["status"] == "succeeded"
        docs = await store.list_indexed_documents(source_id=result["source"]["id"])
        assert len(docs) == 1
        assert docs[0]["knowledge_base_id"] == "kb-docs"
        assert (
            docs[0]["metadata"]["_veadk_source_url"]
            == "https://internal.example/policy"
        )
        assert docs[0]["metadata"]["_veadk_source_title"] == "政策页面"
        assert docs[0]["metadata"]["asset_space_id"] == space["id"]
        assert docs[0]["metadata"]["source_id"] == result["source"]["id"]
        assert docs[0]["metadata"]["source_connection_id"] == result["source"]["id"]
        assert docs[0]["metadata"]["resource_id"].startswith("local_web_page:")
        assert docs[0]["metadata"]["source_type"] == "local_web"
        assert docs[0]["metadata"]["provider"] == "local_web"
        assert "retrieval_index" in docs[0]["metadata"]["tags"]
        assert docs[0]["metadata"]["permissions"] == {
            "scope": "sensitive_local_context",
            "policy_partition": "local-only",
        }
        assert docs[0]["metadata"]["permission_scope"] == "sensitive_local_context"
        resources = await store.list_source_resources(source_id=result["source"]["id"])
        assert len(resources) == 1
        assert resources[0]["asset_space_id"] == space["id"]
        assert resources[0]["resource_id"] == docs[0]["metadata"]["resource_id"]
        assert resources[0]["source_type"] == "local_web_page"
        assert resources[0]["sync_status"] == "indexed"
        assert resources[0]["permission_scope"] == "sensitive_local_context"
        assert resources[0]["metadata"]["asset_space_id"] == space["id"]
        assert resources[0]["metadata"]["resource_id"] == docs[0]["metadata"]["resource_id"]
        assert resources[0]["metadata"]["provider"] == "local_web"
        assert resources[0]["metadata"]["tags"] == docs[0]["metadata"]["tags"]
        assert resources[0]["metadata"]["permission_scope"] == "sensitive_local_context"
        assert knowledge_service.created[0]["knowledge_id"] == "kb-docs"
        assert knowledge_service.created[0]["body"].metadata["resource_id"] == docs[0]["metadata"]["resource_id"]
        assert knowledge_service.created[0]["body"].metadata["permissions"]["policy_partition"] == "local-only"

    asyncio.run(scenario())


def test_import_source_needs_configuration_without_target_kb(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        result = await store.import_source(
            ImportSourceBody(
                space_id=space["id"],
                source_type="web",
                name="Docs",
                uri="https://example.com/docs",
            )
        )
        assert result["source"]["status"] == "needs_configuration"
        assert result["job"]["status"] == "blocked"
        assert "Viking" in result["source"]["status_reason"]
        resources = await store.list_source_resources(source_id=result["source"]["id"])
        assert resources[0]["sync_status"] == "needs_configuration"
        assert "Viking" in resources[0]["error_summary"]

    asyncio.run(scenario())


def test_feishu_import_needs_configuration_without_mock_success(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        result = await store.import_source(
            ImportSourceBody(
                space_id=space["id"],
                source_type="feishu_doc",
                name="飞书文档",
                uri="https://example.feishu.cn/docx/doc_token",
            )
        )
        assert result["source"]["status"] == "needs_configuration"
        assert result["job"]["status"] == "blocked"
        assert "OAuth" in result["source"]["status_reason"]
        resources = await store.list_source_resources(source_id=result["source"]["id"])
        assert resources[0]["source_type"] == "feishu_doc"
        assert resources[0]["sync_status"] == "needs_configuration"
        assert resources[0]["permission_scope"] == "follow_source"

    asyncio.run(scenario())


def test_schema_snapshot_import_registers_ready_source_and_snapshot(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        imported = await store.import_source(
            ImportSourceBody(
                space_id=space["id"],
                source_type="schema_snapshot",
                name="销售 Schema",
                schema={
                    "models": [{"name": "orders"}],
                    "fields": [
                        {"model": "orders", "name": "order_id", "role": "dimension"},
                        {"model": "orders", "name": "gmv", "role": "measure"},
                    ],
                    "metrics": [{"name": "total_gmv", "formula": "sum(gmv)"}],
                },
            )
        )
        assert imported["source"]["status"] == "ready"
        assert imported["job"]["status"] == "succeeded"
        assert imported["document"]["kind"] == "schema_snapshot"
        snapshots = await store.list_snapshots(source_id=imported["source"]["id"])
        assert len(snapshots) == 1
        assert snapshots[0]["schema"]["models"][0]["name"] == "orders"
        assert imported["source"]["metadata"]["schema_status"] == "ready"
        resources = await store.list_source_resources(source_id=imported["source"]["id"])
        assert resources[0]["source_type"] == "database_schema"
        assert resources[0]["sync_status"] == "ready"
        assert resources[0]["content_hash"].startswith("sha256:")

    asyncio.run(scenario())


def test_connector_registry_manifest_is_authoritative_and_safe(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        registry = await store.list_connector_definitions()
        assert registry["schema_version"] == "knowledge_asset.connector_registry.v1"
        assert registry["mock"] is False
        by_id = {item["id"]: item for item in registry["items"]}
        assert by_id["web"]["availability"] == "available"
        assert "import_resource" in by_id["web"]["capabilities"]
        assert "retrieval_index" in by_id["file"]["capabilities"]
        assert by_id["feishu_doc"]["availability"] == "needs_auth"
        assert by_id["postgres"]["availability"] == "preview"
        assert by_id["custom_rest"]["availability"] == "planned"
        assert "password" in by_id["postgres"]["form_schema"]["secret_fields"]
        assert by_id["web"]["provider_name"] == "Public Web"
        assert by_id["web"]["copies_data"] is True
        assert by_id["web"]["requires_helper"] is False
        assert "资料" in by_id["web"]["intent_groups"]
        assert "需要授权" in by_id["feishu_doc"]["intent_groups"]
        assert "预览中" in by_id["postgres"]["intent_groups"]
        assert by_id["postgres"]["cost_hint"]
        assert "redact-me" not in json.dumps(registry).lower()

        database = await store.list_connector_definitions(category="database")
        assert {item["category"] for item in database["items"]} == {"database"}
        single = await store.get_connector_definition("schema_snapshot")
        assert single["resource_picker_schema"]["mode"] == "schema_payload"

    asyncio.run(scenario())


def test_source_resource_crud_redacts_metadata(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        source = await store.create_source(
            CreateSourceBody(space_id=space["id"], source_type="web", name="Docs")
        )
        resource = await store.create_source_resource(
            CreateSourceResourceBody(
                asset_space_id=space["id"],
                source_id=source["id"],
                resource_id="doc-1",
                source_type="web_page",
                provider="web",
                uri="https://example.com/docs?token=redact-me-resource",
                content_hash="sha256:abc",
                tags=["docs", " docs "],
                permission_scope="public",
                sync_status="indexed",
                last_synced_at="2026-08-18T12:00:00Z",
                metadata={"Authorization": "Bearer redact-me-resource-token"},
            )
        )
        assert resource["tags"] == ["docs", "docs"]
        assert resource["metadata"]["Authorization"] == "[REDACTED]"
        assert "redact-me-resource" not in json.dumps(resource)

        updated = await store.update_source_resource(
            resource["id"],
            UpdateSourceResourceBody(
                sync_status="partial",
                freshness={"state": "stale", "reason": "manual"},
                metadata={"password": "redact-me-update"},
            ),
        )
        assert updated["sync_status"] == "partial"
        assert updated["freshness"]["state"] == "stale"
        assert updated["metadata"]["password"] == "[REDACTED]"

        revoked = await store.update_source_resource(
            resource["id"],
            UpdateSourceResourceBody(sync_status="revoked"),
        )
        assert revoked["sync_status"] == "revoked"

        listed = await store.list_source_resources(asset_space_id=space["id"])
        assert [item["id"] for item in listed] == [resource["id"]]
        await store.delete_source_resource(resource["id"])
        assert await store.list_source_resources(asset_space_id=space["id"]) == []

    asyncio.run(scenario())


def test_schema_contains_target_knowledge_asset_columns(store_env) -> None:
    asyncio.run(KnowledgeAssetStore().list_spaces())
    with sqlite3.connect(store_env / "knowledge-assets.db") as conn:
        conn.execute("SELECT 1 FROM spaces LIMIT 0")
        columns = {
            table: {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for table in (
                "spaces",
                "sources",
                "source_resources",
                "credentials",
                "indexed_documents",
                "snapshots",
                "skill_packages",
                "build_jobs",
            )
        }

    assert {
        "id",
        "name",
        "description",
        "default_knowledge_base_id",
        "region",
        "created_at",
        "updated_at",
    }.issubset(columns["spaces"])
    assert {
        "id",
        "space_id",
        "source_type",
        "name",
        "locator",
        "status",
        "default_index_policy",
        "created_at",
        "updated_at",
    }.issubset(columns["sources"])
    assert {
        "id",
        "asset_space_id",
        "source_id",
        "resource_id",
        "source_type",
        "provider",
        "uri",
        "provider_ref",
        "content_hash",
        "tags_json",
        "permission_scope",
        "freshness_json",
        "sync_status",
        "last_synced_at",
        "error_summary",
        "metadata_json",
        "created_at",
        "updated_at",
    }.issubset(columns["source_resources"])
    assert {
        "id",
        "space_id",
        "provider",
        "auth_mode",
        "encrypted_credentials",
        "key_id",
        "algorithm",
        "status",
        "created_at",
        "updated_at",
    }.issubset(columns["credentials"])
    assert {
        "id",
        "source_id",
        "knowledge_base_id",
        "provider_doc_id",
        "metadata_json",
        "content_hash",
        "sync_status",
        "last_synced_at",
    }.issubset(columns["indexed_documents"])
    assert {
        "id",
        "source_id",
        "kind",
        "artifact_uri",
        "schema_json",
        "profile_json",
        "content_hash",
        "created_at",
    }.issubset(columns["snapshots"])
    assert {
        "id",
        "space_id",
        "type",
        "name",
        "version",
        "source_ids",
        "snapshot_ids",
        "artifact_uri",
        "created_at",
    }.issubset(columns["skill_packages"])
    assert {
        "id",
        "job_type",
        "input_json",
        "status",
        "logs_ref",
        "result_skill_id",
        "created_at",
        "updated_at",
    }.issubset(columns["build_jobs"])


def test_target_storage_fields_are_persisted_and_returned(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(
            CreateSpaceBody(
                name="KC",
                default_knowledge_base_id="kb-default",
                region="cn-beijing",
            )
        )
        assert space["default_knowledge_base_id"] == "kb-default"
        assert space["region"] == "cn-beijing"

        source = await store.create_source(
            CreateSourceBody(
                space_id=space["id"],
                source_type="pdf",
                name="Policy PDF",
                locator={"uri": "tos://bucket/key.pdf"},
                default_index_policy={"chunk_size": 800},
            )
        )
        assert source["locator"] == {"uri": "tos://bucket/key.pdf"}
        assert source["default_index_policy"] == {"chunk_size": 800}

        await store.save_credential(
            source["id"],
            SaveCredentialBody(
                provider="feishu",
                auth_mode="oauth",
                credentials={"access_token": "redact-me-delta"},
            ),
        )
        credential_status = await store.credential_status(source["id"])
        assert credential_status["space_id"] == space["id"]
        assert credential_status["provider"] == "feishu"
        assert credential_status["auth_mode"] == "oauth"
        assert credential_status["status"] == "connected"
        assert "algorithm" not in credential_status
        assert "key_id" not in credential_status
        assert "redact-me-delta" not in json.dumps(credential_status)

        document = await store.record_indexed_document(
            RecordIndexedDocumentBody(
                source_id=source["id"],
                knowledge_base_id="kb-default",
                provider_doc_id="provider-doc-1",
                content_hash="sha256:doc",
                sync_status="ready",
                last_synced_at="2026-08-18T12:00:00Z",
            )
        )
        assert document["knowledge_base_id"] == "kb-default"
        assert document["provider_doc_id"] == "provider-doc-1"
        assert document["sync_status"] == "ready"

        snapshot = await store.record_snapshot(
            RecordSkillPackageBody(
                space_id=space["id"],
                source_id=source["id"],
                asset_type="knowledge_resource",
                asset_id="asset-doc",
                capability_kind="retrieval_binding",
                name="Doc Skill",
                kind="source_snapshot",
                artifact_uri="tos://bucket/snapshot.json",
                schema={"fields": ["title"]},
                profile={"rows": 1},
                content_hash="sha256:snapshot",
            )
        )
        assert snapshot["kind"] == "source_snapshot"
        assert snapshot["artifact_uri"] == "tos://bucket/snapshot.json"
        assert snapshot["schema"] == {"fields": ["title"]}

        skill = await store.record_skill_package(
            RecordSkillPackageBody(
                space_id=space["id"],
                asset_type="knowledge_resource",
                asset_id="asset-doc",
                capability_kind="retrieval_binding",
                name="Doc Skill",
                type="retrieval_binding",
                source_ids=[source["id"]],
                snapshot_ids=[snapshot["id"]],
                artifact_uri="tos://bucket/skill.zip",
                publish_state="published",
            )
        )
        assert skill["asset_id"] == "asset-doc"

        with sqlite3.connect(store_env / "knowledge-assets.db") as conn:
            conn.row_factory = sqlite3.Row
            stored = conn.execute(
                "SELECT type, source_ids, snapshot_ids, artifact_uri "
                "FROM skill_packages WHERE asset_id = ?",
                ("asset-doc",),
            ).fetchone()
        assert stored["type"] == "retrieval_binding"
        assert json.loads(stored["source_ids"]) == [source["id"]]
        assert json.loads(stored["snapshot_ids"]) == [snapshot["id"]]
        assert stored["artifact_uri"] == "tos://bucket/skill.zip"

    asyncio.run(scenario())


def test_build_jobs_are_persisted_and_redacted(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        source = await store.create_source(
            CreateSourceBody(space_id=space["id"], source_type="web", name="Docs")
        )
        job = await store.record_build_job(
            RecordBuildJobBody(
                space_id=space["id"],
                source_id=source["id"],
                asset_type="knowledge_resource",
                asset_id="docs",
                job_type="retrieval_binding",
                status="running",
                input={"cookie": "redact-me-job-cookie"},
            )
        )
        assert job["status"] == "running"
        assert job["input"]["cookie"] == "[REDACTED]"

        updated = await store.update_build_job(
            job["id"],
            UpdateBuildJobBody(
                status="succeeded",
                result_skill_id="pkg_docs",
                output={"Authorization": "Bearer redact-me-job-token"},
            ),
        )
        assert updated["status"] == "succeeded"
        assert updated["result_skill_id"] == "pkg_docs"
        assert updated["output"]["Authorization"] == "[REDACTED]"

        listed = await store.list_build_jobs(space_id=space["id"])
        assert [item["id"] for item in listed] == [job["id"]]
        loaded = await store.get_build_job(job["id"])
        assert loaded["id"] == job["id"]
        assert "redact-me-job" not in json.dumps(loaded)

    asyncio.run(scenario())


def test_credentials_are_encrypted_and_key_file_is_private(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> tuple[str, dict[str, Any]]:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        source = await store.create_source(
            CreateSourceBody(space_id=space["id"], source_type="feishu", name="Feishu")
        )
        status = await store.save_credential(
            source["id"],
            SaveCredentialBody(
                credentials={
                    "access_token": "redact-me-alpha",
                    "nested": {"password": "redact-me-beta"},
                }
            ),
        )
        decrypted = await store.get_credential(source["id"])
        return source["id"], {"status": status, "decrypted": decrypted}

    source_id, result = asyncio.run(scenario())
    status_payload = result["status"]
    decrypted = result["decrypted"]
    assert status_payload["configured"] is True
    assert "redact-me-alpha" not in json.dumps(status_payload)
    assert decrypted["access_token"] == "redact-me-alpha"

    key_path = default_key_path()
    assert key_path.exists()
    assert os.stat(key_path).st_mode & 0o777 == 0o600

    db_text = store_env.joinpath("knowledge-assets.db").read_bytes()
    assert b"redact-me-alpha" not in db_text
    assert b"redact-me-beta" not in db_text

    with sqlite3.connect(store_env / "knowledge-assets.db") as conn:
        row = conn.execute(
            "SELECT envelope_json FROM credentials WHERE source_id = ?",
            (source_id,),
        ).fetchone()
    envelope = json.loads(row[0])
    assert envelope["algorithm"] == "AES-256-GCM"
    assert envelope["version"] == "knowledge_asset.credential.v1"
    assert envelope["key_id"].startswith("file:")
    assert envelope["nonce"]


def test_key_path_permission_problem_surfaces_cleanly(store_env, monkeypatch) -> None:
    from frontend.server.knowledge_assets import crypto as asset_crypto

    def deny_open(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("asset store key is not writable")

    monkeypatch.setattr(asset_crypto.os, "open", deny_open)
    with pytest.raises(PermissionError, match="not writable"):
        CredentialCipher().encrypt({"access_token": "redact-me-key-path"})


def test_v1_database_is_migrated_to_target_schema(store_env) -> None:
    db_path = store_env / "knowledge-assets.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1');
            CREATE TABLE spaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );
            CREATE TABLE sources (
                id TEXT PRIMARY KEY,
                space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                provider TEXT,
                name TEXT NOT NULL,
                description TEXT,
                uri TEXT,
                status TEXT NOT NULL,
                status_reason TEXT,
                capabilities_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );
            CREATE TABLE credentials (
                source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
                envelope_json TEXT NOT NULL,
                key_id TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );
            CREATE TABLE indexed_documents (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                document_id TEXT,
                title TEXT,
                uri TEXT,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_id, content_hash)
            );
            CREATE TABLE snapshots (
                id TEXT PRIMARY KEY,
                source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
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
                created_at TEXT NOT NULL
            );
            CREATE TABLE skill_packages (
                id TEXT PRIMARY KEY,
                space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(asset_type, asset_id)
            );
            CREATE TABLE build_jobs (
                id TEXT PRIMARY KEY,
                space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
                source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                asset_type TEXT,
                asset_id TEXT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                error_json TEXT,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO spaces (
                id, name, description, metadata_json, created_at, updated_at
            ) VALUES ('space_legacy', 'Legacy', NULL, '{}', 'now', 'now');
            INSERT INTO sources (
                id, space_id, source_type, provider, name, description, uri, status,
                status_reason, capabilities_json, metadata_json, created_at, updated_at
            ) VALUES (
                'src_legacy', 'space_legacy', 'web', 'web', 'Legacy Source', NULL,
                NULL, 'ready', NULL, '{}', '{}', 'now', 'now'
            );
            INSERT INTO credentials (
                source_id, envelope_json, key_id, algorithm, version, status,
                created_at, updated_at
            ) VALUES (
                'src_legacy', '{"version":"knowledge_asset.credential.v1"}',
                'file:legacy', 'AES-256-GCM', 'knowledge_asset.credential.v1',
                'connected', 'now', 'now'
            );
            """
        )

    store = KnowledgeAssetStore()
    spaces = asyncio.run(store.list_spaces())
    assert spaces[0]["id"] == "space_legacy"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        credential = conn.execute(
            "SELECT id, space_id, auth_mode, encrypted_credentials "
            "FROM credentials WHERE source_id = 'src_legacy'"
        ).fetchone()
        schema_version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert credential["id"].startswith("cred_")
    assert credential["space_id"] == "space_legacy"
    assert credential["auth_mode"] == "none"
    assert (
        credential["encrypted_credentials"]
        == '{"version":"knowledge_asset.credential.v1"}'
    )
    assert schema_version == "6"
    assert "knowledge_asset_eval_suites" in tables
    assert "knowledge_asset_eval_results" in tables
    assert "semantic_question_sql_pairs" in tables
    assert "semantic_instructions" in tables
    assert "semantic_graph_objects" in tables
    assert "semantic_alignments" in tables
    assert "askdata_conversations" in tables
    assert "askdata_messages" in tables
    assert "askdata_tool_events" in tables
    assert "dashboard_shares" in tables
    assert "source_resources" in tables


def test_semantic_few_shot_instruction_and_graph_records_persist(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        pair = await store.create_question_sql_pair(
            SemanticQuestionSqlPairBody(
                space_id=space["id"],
                semantic_pack_id="sales_semantic",
                question="top stores by ticket count",
                sql="SELECT store, COUNT(*) AS ticket_count FROM sales GROUP BY store",
                dialect="duckdb",
                tables=["sales"],
            )
        )
        edited_pair = await store.update_question_sql_pair(
            pair["id"],
            UpdateSemanticQuestionSqlPairBody(notes="canonical store ranking"),
        )
        assert edited_pair["notes"] == "canonical store ranking"
        assert (await store.list_question_sql_pairs(space_id=space["id"]))[0][
            "id"
        ] == pair["id"]

        instruction = await store.create_instruction(
            SemanticInstructionBody(
                space_id=space["id"],
                semantic_pack_id="sales_semantic",
                instruction="Use ticket_count for bill counts.",
                questions=["ticket count"],
                is_default=True,
                scope="metric",
            )
        )
        edited_instruction = await store.update_instruction(
            instruction["id"],
            UpdateSemanticInstructionBody(scope="global"),
        )
        assert edited_instruction["scope"] == "global"
        assert (await store.list_instructions(space_id=space["id"]))[0][
            "is_default"
        ] is True

        obj = await store.upsert_graph_object(
            object_id="docobj_ticket",
            space_id=space["id"],
            semantic_pack_id="sales_semantic",
            kind="metric_concept",
            name="Ticket Count",
            normalized_name="ticket_count",
            confidence=0.82,
            provenance={"source_id": "doc_1"},
            review_status="suggested",
        )
        assert obj["provenance"]["source_id"] == "doc_1"
        rel = await store.upsert_graph_relation(
            relation_id="docrel_ticket_sales",
            space_id=space["id"],
            semantic_pack_id="sales_semantic",
            source_object_id=obj["id"],
            target_object_id="docobj_sales",
            relation_type="defines",
            evidence=[{"text": "ticket count means distinct bills"}],
        )
        assert rel["evidence"][0]["text"].startswith("ticket count")
        alignment = await store.upsert_alignment(
            alignment_id="align_ticket_metric",
            space_id=space["id"],
            semantic_pack_id="sales_semantic",
            doc_object_id=obj["id"],
            mdl_object_ref="metric:ticket_count",
            alignment_type="doc_metric_to_metric",
            status="accepted",
            confidence=0.9,
        )
        assert alignment["status"] == "accepted"
        assert (
            len(await store.list_graph_objects(semantic_pack_id="sales_semantic")) == 1
        )
        assert (
            len(await store.list_graph_relations(semantic_pack_id="sales_semantic"))
            == 1
        )
        assert len(await store.list_alignments(semantic_pack_id="sales_semantic")) == 1

        await store.delete_question_sql_pair(pair["id"])
        await store.delete_instruction(instruction["id"])
        assert await store.list_question_sql_pairs(space_id=space["id"]) == []
        assert await store.list_instructions(space_id=space["id"]) == []

    asyncio.run(scenario())


def test_wrong_key_and_corrupt_ciphertext_fail_cleanly(store_env, monkeypatch) -> None:
    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "alpha local key material")
    store = KnowledgeAssetStore()

    async def create() -> str:
        space = await store.create_space(CreateSpaceBody(name="KC"))
        source = await store.create_source(
            CreateSourceBody(space_id=space["id"], source_type="database", name="DB")
        )
        await store.save_credential(
            source["id"],
            SaveCredentialBody(credentials={"password": "redact-me-gamma"}),
        )
        return source["id"]

    source_id = asyncio.run(create())

    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "beta local key material")
    wrong_key_store = KnowledgeAssetStore()
    with pytest.raises(KnowledgeAssetCredentialError, match="cannot be decrypted"):
        asyncio.run(wrong_key_store.get_credential(source_id))

    monkeypatch.setenv("VEADK_STUDIO_ASSET_SECRET", "alpha local key material")
    with sqlite3.connect(store_env / "knowledge-assets.db") as conn:
        envelope = json.loads(
            conn.execute(
                "SELECT envelope_json FROM credentials WHERE source_id = ?",
                (source_id,),
            ).fetchone()[0]
        )
        envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
        conn.execute(
            "UPDATE credentials SET envelope_json = ? WHERE source_id = ?",
            (json.dumps(envelope), source_id),
        )
    with pytest.raises(KnowledgeAssetCredentialError, match="cannot be decrypted"):
        asyncio.run(KnowledgeAssetStore().get_credential(source_id))


def test_query_url_rejects_cross_origin_paths(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        with pytest.raises(Exception, match="relative Studio path"):
            await store.record_skill_package(
                RecordSkillPackageBody(
                    asset_type="dashboard",
                    asset_id="sales",
                    capability_kind="dashboard_skill",
                    name="Sales",
                    query_url="https://evil.example/query",
                )
            )

    asyncio.run(scenario())


def test_query_url_rejects_ungoverned_web_paths(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> None:
        with pytest.raises(Exception, match="governed AgentKit query paths"):
            await store.record_skill_package(
                RecordSkillPackageBody(
                    asset_type="dashboard",
                    asset_id="sales",
                    capability_kind="dashboard_skill",
                    name="Sales",
                    query_url="/web/datastudio/assets/dashboard/sales",
                )
            )

    asyncio.run(scenario())


def test_cipher_rejects_malformed_envelope() -> None:
    with pytest.raises(CredentialCryptoError, match="missing required fields"):
        CredentialCipher().decrypt(
            cast(Any, {"version": "knowledge_asset.credential.v1"})
        )
