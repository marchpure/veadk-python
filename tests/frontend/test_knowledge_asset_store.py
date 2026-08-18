from __future__ import annotations

import asyncio
import json
import os
import sqlite3

import pytest

from frontend.server.knowledge_assets import KnowledgeAssetStore
from frontend.server.knowledge_assets.crypto import (
    CredentialCipher,
    CredentialCryptoError,
    default_key_path,
)
from frontend.server.knowledge_assets.models import (
    CreateSourceBody,
    CreateSpaceBody,
    RecordIndexedDocumentBody,
    RecordSkillPackageBody,
    SaveCredentialBody,
)
from frontend.server.knowledge_assets.service import KnowledgeAssetCredentialError


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
    assert default_key_path() == store_env / "home" / ".veadk" / "studio" / "asset-store.key"
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


def test_credentials_are_encrypted_and_key_file_is_private(store_env) -> None:
    store = KnowledgeAssetStore()

    async def scenario() -> tuple[str, dict[str, object]]:
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
    assert status_payload["configured"] is True
    assert "redact-me-alpha" not in json.dumps(status_payload)
    assert result["decrypted"]["access_token"] == "redact-me-alpha"

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


def test_cipher_rejects_malformed_envelope() -> None:
    with pytest.raises(CredentialCryptoError, match="missing required fields"):
        CredentialCipher().decrypt({"version": "knowledge_asset.credential.v1"})
