# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Business service for Studio knowledge assets and Agent capabilities."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from .contract import (
    KnowledgeAssetListEnvelope,
    KnowledgeAssetMetadataEnvelope,
    KnowledgeAssetType,
    KnowledgeCapabilityKind,
)
from .crypto import CredentialCipher, CredentialCryptoError
from .models import (
    CreateSourceBody,
    CreateSpaceBody,
    ImportSourceBody,
    RecordBuildJobBody,
    RecordIndexedDocumentBody,
    RecordSkillPackageBody,
    RecordSnapshotBody,
    SaveCredentialBody,
    SemanticInstructionBody,
    SemanticQuestionSqlPairBody,
    UpdateBuildJobBody,
    UpdateSemanticInstructionBody,
    UpdateSemanticQuestionSqlPairBody,
    UpdateSourceStatusBody,
    UpdateSpaceBody,
)
from .repository import (
    KnowledgeAssetNotFound,
    KnowledgeAssetRepository,
    dumps_json,
    loads_json,
)

_REDACTED = "[REDACTED]"
_SENSITIVE_SUFFIXES = (
    "accesskey",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "sessiontoken",
    "signature",
    "token",
)
_SOURCE_STATUSES = {
    "registered",
    "needs_configuration",
    "auth_required",
    "importing",
    "indexed",
    "ready",
    "failed",
    "credential_expired",
}
_BUILD_JOB_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
}
_SCHEMA_SOURCE_TYPES = {"schema_snapshot", "database", "oracle", "mysql", "postgres"}


class KnowledgeAssetServiceError(RuntimeError):
    status_code = 400
    code = "KNOWLEDGE_ASSET_INVALID_REQUEST"


class KnowledgeAssetCredentialError(RuntimeError):
    status_code = 500
    code = "KNOWLEDGE_ASSET_CREDENTIAL_ERROR"


class KnowledgeAssetStore:
    def __init__(
        self,
        repository: KnowledgeAssetRepository | None = None,
        cipher: CredentialCipher | None = None,
    ) -> None:
        self._repository = repository or KnowledgeAssetRepository()
        self._cipher = cipher or CredentialCipher()

    async def create_space(self, body: CreateSpaceBody) -> dict[str, Any]:
        row = {
            "id": _new_id("space"),
            "name": body.name.strip(),
            "description": body.description,
            "default_knowledge_base_id": _sanitize_text(
                body.default_knowledge_base_id or ""
            )
            or None,
            "region": _sanitize_text(body.region or "") or None,
            "metadata_json": dumps_json(redact_sensitive(body.metadata)),
        }
        return _space_payload(await asyncio.to_thread(self._repository.create_space, row))

    async def list_spaces(self) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self._repository.list_spaces)
        return [_space_payload(row) for row in rows]

    async def get_space(self, space_id: str) -> dict[str, Any]:
        return _space_payload(await asyncio.to_thread(self._repository.get_space, space_id))

    async def update_space(
        self, space_id: str, body: UpdateSpaceBody
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        if body.name is not None:
            patch["name"] = body.name.strip()
        if body.description is not None:
            patch["description"] = body.description
        if body.default_knowledge_base_id is not None:
            patch["default_knowledge_base_id"] = _sanitize_text(
                body.default_knowledge_base_id
            )
        if body.region is not None:
            patch["region"] = _sanitize_text(body.region)
        if body.metadata is not None:
            patch["metadata_json"] = dumps_json(redact_sensitive(body.metadata))
        row = await asyncio.to_thread(self._repository.update_space, space_id, patch)
        return _space_payload(row)

    async def create_source(self, body: CreateSourceBody) -> dict[str, Any]:
        status = _normalize_source_status(body.status, body.source_type)
        row = {
            "id": _new_id("src"),
            "space_id": body.space_id,
            "source_type": body.source_type.strip(),
            "provider": _sanitize_text(body.provider or "") or None,
            "name": _sanitize_text(body.name.strip()),
            "description": _sanitize_text(body.description or "") or None,
            "uri": _sanitize_text(body.uri or "") or None,
            "locator": dumps_json(redact_sensitive(body.locator)),
            "status": status,
            "status_reason": None,
            "default_index_policy": dumps_json(
                redact_sensitive(body.default_index_policy)
            ),
            "capabilities_json": dumps_json(redact_sensitive(body.capabilities)),
            "metadata_json": dumps_json(redact_sensitive(body.metadata)),
        }
        return _source_payload(
            await asyncio.to_thread(self._repository.create_source, row)
        )

    async def import_source(
        self,
        body: ImportSourceBody,
        *,
        knowledge_service: Any = None,
        identity: Any = None,
        region: str = "",
    ) -> dict[str, Any]:
        space = await self.get_space(body.space_id)
        source_type = body.source_type.strip()
        target_kb = (
            _sanitize_text(body.target_knowledge_base_id or "")
            or space.get("default_knowledge_base_id")
            or ""
        )
        source = await self.create_source(
            CreateSourceBody(
                space_id=body.space_id,
                source_type=source_type,
                provider=body.provider,
                name=body.name,
                description=body.description,
                uri=body.uri,
                locator={
                    **body.locator,
                    **({"uri": body.uri} if body.uri else {}),
                },
                status=_initial_import_status(source_type, target_kb),
                default_index_policy={
                    "target_knowledge_base_id": target_kb,
                    "region": region or body.region or space.get("region") or "",
                },
                capabilities=_source_capabilities(source_type, body.schema_payload),
                metadata={
                    **body.metadata,
                    "schema": body.schema_payload,
                    "credential_ref": body.credential_ref or "",
                    "content_format": body.content_format or "",
                },
            )
        )
        job = await self.record_build_job(
            RecordBuildJobBody(
                space_id=body.space_id,
                source_id=source["id"],
                job_type="source_import",
                status="running",
                input={
                    "source_type": source_type,
                    "target_knowledge_base_id": target_kb,
                    "has_content": bool(body.content),
                },
            )
        )
        try:
            result = await self._execute_source_import(
                source,
                body,
                target_knowledge_base_id=target_kb,
                knowledge_service=knowledge_service,
                identity=identity,
                region=region or body.region or space.get("region") or "",
            )
        except KnowledgeAssetServiceError as error:
            failed_source = await self.update_source_status(
                source["id"],
                UpdateSourceStatusBody(
                    status="failed",
                    status_reason=str(error),
                    metadata={"last_error_code": error.code},
                ),
            )
            failed_job = await self.update_build_job(
                job["id"],
                UpdateBuildJobBody(
                    status="failed",
                    error={"code": error.code, "message": str(error)},
                    output={"source_status": failed_source["status"]},
                ),
            )
            return {"source": failed_source, "job": failed_job, "document": None}

        if result["status"] in {"needs_configuration", "auth_required", "registered"}:
            final_job_status = "blocked"
        else:
            final_job_status = "succeeded"
        updated_source = await self.update_source_status(
            source["id"],
            UpdateSourceStatusBody(
                status=result["status"],
                status_reason=result.get("status_reason"),
                metadata=result.get("source_metadata", {}),
            ),
        )
        updated_job = await self.update_build_job(
            job["id"],
            UpdateBuildJobBody(
                status=final_job_status,
                output={
                    "source_status": updated_source["status"],
                    "document_id": result.get("document", {}).get("id", ""),
                    "knowledge_base_id": target_kb,
                    "next_action": result.get("next_action", ""),
                },
                error=result.get("error"),
            ),
        )
        return {
            "source": updated_source,
            "job": updated_job,
            "document": result.get("document"),
        }

    async def _execute_source_import(
        self,
        source: dict[str, Any],
        body: ImportSourceBody,
        *,
        target_knowledge_base_id: str,
        knowledge_service: Any,
        identity: Any,
        region: str,
    ) -> dict[str, Any]:
        source_type = source["source_type"]
        if source_type in {"database", "oracle", "mysql", "postgres"}:
            return {
                "status": "needs_configuration",
                "status_reason": "数据库来源已登记，等待凭据与 schema introspection。",
                "next_action": "configure_credentials",
                "source_metadata": {
                    "connection_status": "needs_configuration",
                    "schema_status": "waiting_introspection",
                },
            }
        if source_type == "feishu_doc":
            return {
                "status": "needs_configuration",
                "status_reason": "飞书连接器未在知识资产工作台中配置，需管理员启用 OAuth。",
                "next_action": "configure_feishu",
                "source_metadata": {"auth_status": "not_configured"},
            }
        if source_type == "schema_snapshot":
            schema = _normalize_schema_payload(body.schema_payload)
            if not schema["models"] and not schema["fields"]:
                return {
                    "status": "needs_configuration",
                    "status_reason": "Schema Snapshot 需要表或字段定义。",
                    "next_action": "provide_schema",
                    "source_metadata": {"schema_status": "empty"},
                }
            content_hash = _content_hash(dumps_json(schema))
            snapshot = await self.record_snapshot(
                RecordSnapshotBody(
                    source_id=source["id"],
                    asset_type="semantic_model",
                    asset_id=_slug(body.name),
                    capability_kind="semantic_skill",
                    name=f"{body.name} Schema Snapshot",
                    description=body.description,
                    status="ready",
                    publish_state="draft",
                    kind="schema_snapshot",
                    schema=schema,
                    content_hash=content_hash,
                    metadata={"source_type": source_type},
                )
            )
            return {
                "status": "ready",
                "status_reason": "Schema Snapshot 已登记，可用于生成语义 Skill。",
                "next_action": "build_semantic_skill",
                "document": {"id": snapshot["id"], "kind": "schema_snapshot"},
                "source_metadata": {
                    "schema_status": "ready",
                    "schema_version": content_hash,
                    "snapshot_id": snapshot["id"],
                },
            }
        if not target_knowledge_base_id:
            return {
                "status": "needs_configuration",
                "status_reason": "需要先配置目标 Viking 知识库。",
                "next_action": "configure_viking",
                "source_metadata": {"target_knowledge_base_id": ""},
            }
        if knowledge_service is None or identity is None:
            return {
                "status": "needs_configuration",
                "status_reason": "Studio 知识库导入服务未接入，无法写入 Viking。",
                "next_action": "configure_backend",
                "source_metadata": {"target_knowledge_base_id": target_knowledge_base_id},
            }
        markdown, title, safe_url = await _source_markdown(body)
        content_hash = _content_hash(markdown)
        metadata = {
            **redact_sensitive(body.metadata),
            "space_id": source["space_id"],
            "source_id": source["id"],
            "source_type": source_type,
            "content_hash": content_hash,
            "captured_at": _utc_now(),
            "_veadk_source_url": safe_url,
            "_veadk_source_title": title,
        }
        try:
            document = await _write_knowledge_document(
                knowledge_service,
                target_knowledge_base_id=target_knowledge_base_id,
                identity=identity,
                region=region,
                source_type=source_type,
                body=body,
                title=title,
                safe_url=safe_url,
                markdown=markdown,
                metadata=metadata,
            )
        except Exception as error:
            raise KnowledgeAssetServiceError(
                f"写入 Viking 知识库失败：{_sanitize_text(str(error))}"
            ) from error
        indexed = await self.record_indexed_document(
            RecordIndexedDocumentBody(
                source_id=source["id"],
                content_hash=content_hash,
                knowledge_base_id=target_knowledge_base_id,
                provider_doc_id=str(document.get("id") or ""),
                document_id=str(document.get("id") or ""),
                title=title,
                uri=safe_url,
                status="indexed",
                sync_status="indexed",
                last_synced_at=_utc_now(),
                metadata=metadata,
            )
        )
        return {
            "status": "indexed",
            "status_reason": "内容已写入 Viking 并完成双写登记。",
            "next_action": "create_retrieval_binding",
            "document": {**indexed, "provider_result": redact_sensitive(document)},
            "source_metadata": {
                "target_knowledge_base_id": target_knowledge_base_id,
                "content_hash": content_hash,
                "last_synced_at": indexed["last_synced_at"],
            },
        }

    async def list_sources(self, *, space_id: str | None = None) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self._repository.list_sources, space_id=space_id)
        return [_source_payload(row) for row in rows]

    async def get_source(self, source_id: str) -> dict[str, Any]:
        return _source_payload(
            await asyncio.to_thread(self._repository.get_source, source_id)
        )

    async def update_source_status(
        self, source_id: str, body: UpdateSourceStatusBody
    ) -> dict[str, Any]:
        status = _normalize_source_status(body.status, "", allow_pending=False)
        patch: dict[str, Any] = {
            "status": status,
            "status_reason": _sanitize_text(body.status_reason or "") or None,
        }
        if body.metadata is not None:
            existing = await asyncio.to_thread(self._repository.get_source, source_id)
            merged = {
                **loads_json(existing.get("metadata_json"), {}),
                **redact_sensitive(body.metadata),
            }
            patch["metadata_json"] = dumps_json(merged)
        row = await asyncio.to_thread(
            self._repository.update_source_status, source_id, patch
        )
        return _source_payload(row)

    async def save_credential(
        self, source_id: str, body: SaveCredentialBody
    ) -> dict[str, Any]:
        source = await asyncio.to_thread(self._repository.get_source, source_id)
        envelope = self._cipher.encrypt(body.credentials)
        encrypted = dumps_json(envelope)
        row = {
            "id": _new_id("cred"),
            "source_id": source_id,
            "space_id": source["space_id"],
            "provider": _sanitize_text(body.provider or source.get("provider") or "")
            or None,
            "auth_mode": _sanitize_text(body.auth_mode),
            "encrypted_credentials": encrypted,
            "envelope_json": encrypted,
            "key_id": envelope["key_id"],
            "algorithm": envelope["algorithm"],
            "version": envelope["version"],
            "status": body.status.strip(),
            "expires_at": body.expires_at,
        }
        return _credential_status_payload(
            await asyncio.to_thread(self._repository.save_credential, row)
        )

    async def credential_status(self, source_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(
            self._repository.get_credential_status,
            source_id,
        )
        return _credential_status_payload(row)

    async def delete_credential(self, source_id: str) -> None:
        await asyncio.to_thread(self._repository.delete_credential, source_id)

    async def get_credential(self, source_id: str) -> dict[str, Any]:
        """Internal backend-only credential accessor. Do not expose via routes."""

        row = await asyncio.to_thread(self._repository.get_credential_row, source_id)
        try:
            return self._cipher.decrypt(row["envelope_json"])
        except CredentialCryptoError as error:
            raise KnowledgeAssetCredentialError(
                "Stored source credential cannot be decrypted."
            ) from error

    async def record_indexed_document(
        self, body: RecordIndexedDocumentBody
    ) -> dict[str, Any]:
        row = {
            "id": _new_id("doc"),
            "source_id": body.source_id,
            "knowledge_base_id": _sanitize_text(body.knowledge_base_id or "") or None,
            "provider_doc_id": _sanitize_text(
                body.provider_doc_id or body.document_id or ""
            )
            or None,
            "document_id": body.document_id,
            "title": body.title,
            "uri": body.uri,
            "content_hash": body.content_hash,
            "sync_status": body.sync_status or body.status,
            "status": body.status,
            "last_synced_at": body.last_synced_at,
            "metadata_json": dumps_json(redact_sensitive(body.metadata)),
        }
        return _indexed_document_payload(
            await asyncio.to_thread(self._repository.record_indexed_document, row)
        )

    async def list_indexed_documents(
        self, *, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_indexed_documents,
            source_id=source_id,
        )
        return [_indexed_document_payload(row) for row in rows]

    async def record_snapshot(self, body: RecordSnapshotBody) -> dict[str, Any]:
        row = _asset_row(_new_id("snap"), body.model_dump(by_alias=True))
        return _snapshot_payload(
            await asyncio.to_thread(self._repository.record_snapshot, row)
        )

    async def list_snapshots(
        self, *, asset_id: str | None = None, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_snapshots,
            asset_id=asset_id,
            source_id=source_id,
        )
        return [_snapshot_payload(row) for row in rows]

    async def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self._repository.get_snapshot, snapshot_id)
        return _snapshot_payload(row)

    async def record_skill_package(
        self, body: RecordSkillPackageBody
    ) -> KnowledgeAssetMetadataEnvelope:
        values = body.model_dump(by_alias=True)
        asset_id = values.get("asset_id") or values.get("package_id") or _new_id("asset")
        values["asset_id"] = asset_id
        package_id = values.pop("package_id") or _stable_package_id(
            values["asset_type"], asset_id
        )
        row = _asset_row(package_id, values)
        row["space_id"] = body.space_id
        stored = await asyncio.to_thread(self._repository.record_skill_package, row)
        return _metadata_envelope(stored)

    async def list_skill_packages(
        self,
        *,
        space_id: str | None = None,
        asset_types: Sequence[KnowledgeAssetType] = (),
        capability_kinds: Sequence[KnowledgeCapabilityKind] = (),
        query: str = "",
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        offset = _decode_cursor(cursor)
        rows, total = await asyncio.to_thread(
            self._repository.list_skill_packages,
            space_id=space_id,
            asset_types=asset_types,
            capability_kinds=capability_kinds,
            query=query,
            limit=limit,
            offset=offset,
        )
        next_cursor = str(offset + len(rows)) if offset + len(rows) < total else None
        return {
            "items": [_metadata_envelope(row) for row in rows],
            "total": total,
            "next_cursor": next_cursor,
            "mock": False,
        }

    async def get_skill_package(
        self, package_id: str
    ) -> KnowledgeAssetMetadataEnvelope:
        row = await asyncio.to_thread(
            self._repository.get_skill_package,
            package_id,
        )
        return _metadata_envelope(row)

    async def list_assets(
        self,
        *,
        query: str = "",
        asset_types: Sequence[KnowledgeAssetType] = (),
        capability_kinds: Sequence[KnowledgeCapabilityKind] = (),
        cursor: str | None = None,
        limit: int = 20,
    ) -> KnowledgeAssetListEnvelope:
        bounded_limit = max(1, min(int(limit), 100))
        offset = _decode_cursor(cursor)
        rows, total = await asyncio.to_thread(
            self._repository.list_skill_packages,
            asset_types=asset_types,
            capability_kinds=capability_kinds,
            query=query,
            published_only=True,
            limit=bounded_limit,
            offset=offset,
        )
        next_cursor = str(offset + len(rows)) if offset + len(rows) < total else None
        return {
            "schema_version": "knowledge_asset.list.v1",
            "items": [_metadata_envelope(row) for row in rows],
            "total": total,
            "next_cursor": next_cursor,
            "mock": False,
        }

    async def get_asset(
        self,
        *,
        asset_type: KnowledgeAssetType,
        asset_id: str,
    ) -> KnowledgeAssetMetadataEnvelope:
        row = await asyncio.to_thread(
            self._repository.get_skill_package_by_asset,
            asset_type,
            asset_id,
        )
        if row.get("publish_state") != "published":
            raise KnowledgeAssetNotFound("Knowledge asset is not published.")
        return _metadata_envelope(row)

    async def record_build_job(self, body: RecordBuildJobBody) -> dict[str, Any]:
        row = {
            "id": _new_id("job"),
            "space_id": body.space_id,
            "source_id": body.source_id,
            "asset_type": body.asset_type,
            "asset_id": _sanitize_text(body.asset_id or "") or None,
            "job_type": _sanitize_text(body.job_type),
            "status": _normalize_build_job_status(body.status),
            "logs_ref": _sanitize_text(body.logs_ref or "") or None,
            "result_skill_id": _sanitize_text(body.result_skill_id or "") or None,
            "error_json": dumps_json(redact_sensitive(body.error))
            if body.error
            else None,
            "input_json": dumps_json(redact_sensitive(body.input)),
            "output_json": dumps_json(redact_sensitive(body.output)),
        }
        return _build_job_payload(
            await asyncio.to_thread(self._repository.record_build_job, row)
        )

    async def update_build_job(
        self, job_id: str, body: UpdateBuildJobBody
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "status": _normalize_build_job_status(body.status),
            "logs_ref": _sanitize_text(body.logs_ref or "") or None,
            "result_skill_id": _sanitize_text(body.result_skill_id or "") or None,
            "error_json": dumps_json(redact_sensitive(body.error))
            if body.error
            else None,
        }
        if body.output is not None:
            patch["output_json"] = dumps_json(redact_sensitive(body.output))
        return _build_job_payload(
            await asyncio.to_thread(
                self._repository.update_build_job,
                job_id,
                patch,
            )
        )

    async def list_build_jobs(
        self,
        *,
        space_id: str | None = None,
        source_id: str | None = None,
        asset_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_build_jobs,
            space_id=space_id,
            source_id=source_id,
            asset_id=asset_id,
            limit=limit,
        )
        return [_build_job_payload(row) for row in rows]

    async def get_build_job(self, job_id: str) -> dict[str, Any]:
        return _build_job_payload(
            await asyncio.to_thread(self._repository.get_build_job, job_id)
        )

    async def append_build_event(
        self,
        *,
        job_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        space_id: str | None = None,
        semantic_pack_id: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": _new_id("evt"),
            "job_id": job_id,
            "space_id": space_id,
            "semantic_pack_id": _sanitize_text(semantic_pack_id or "") or None,
            "event_type": _sanitize_text(event_type),
            "sequence": await asyncio.to_thread(
                self._repository.next_build_event_sequence,
                job_id,
            ),
            "payload_json": dumps_json(redact_sensitive(dict(payload))),
        }
        return _semantic_build_event_payload(
            await asyncio.to_thread(self._repository.append_build_event, row)
        )

    async def list_build_events(
        self,
        job_id: str,
        *,
        after_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_build_events,
            job_id,
            after_sequence=after_sequence,
        )
        return [_semantic_build_event_payload(row) for row in rows]

    async def create_question_sql_pair(
        self,
        body: SemanticQuestionSqlPairBody,
    ) -> dict[str, Any]:
        row = {
            "id": _new_id("qsql"),
            "space_id": body.space_id,
            "semantic_pack_id": _sanitize_text(body.semantic_pack_id or "") or None,
            "question": _sanitize_text(body.question),
            "sql": _sanitize_text(body.sql),
            "dialect": _sanitize_text(body.dialect or "ansi"),
            "tables_json": dumps_json(redact_sensitive(body.tables)),
            "notes": _sanitize_text(body.notes or ""),
        }
        return _question_sql_pair_payload(
            await asyncio.to_thread(self._repository.create_question_sql_pair, row)
        )

    async def list_question_sql_pairs(
        self,
        *,
        space_id: str,
        semantic_pack_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_question_sql_pairs,
            space_id=space_id,
            semantic_pack_id=semantic_pack_id,
        )
        return [_question_sql_pair_payload(row) for row in rows]

    async def update_question_sql_pair(
        self,
        pair_id: str,
        body: UpdateSemanticQuestionSqlPairBody,
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        if body.question is not None:
            patch["question"] = _sanitize_text(body.question)
        if body.sql is not None:
            patch["sql"] = _sanitize_text(body.sql)
        if body.dialect is not None:
            patch["dialect"] = _sanitize_text(body.dialect or "ansi")
        if body.tables is not None:
            patch["tables_json"] = dumps_json(redact_sensitive(body.tables))
        if body.notes is not None:
            patch["notes"] = _sanitize_text(body.notes)
        return _question_sql_pair_payload(
            await asyncio.to_thread(
                self._repository.update_question_sql_pair,
                pair_id,
                patch,
            )
        )

    async def delete_question_sql_pair(self, pair_id: str) -> None:
        await asyncio.to_thread(self._repository.delete_question_sql_pair, pair_id)

    async def create_instruction(self, body: SemanticInstructionBody) -> dict[str, Any]:
        row = {
            "id": _new_id("ins"),
            "space_id": body.space_id,
            "semantic_pack_id": _sanitize_text(body.semantic_pack_id or "") or None,
            "instruction": _sanitize_text(body.instruction),
            "questions_json": dumps_json(redact_sensitive(body.questions)),
            "is_default": 1 if body.is_default else 0,
            "scope": _sanitize_text(body.scope or "global"),
        }
        return _instruction_payload(
            await asyncio.to_thread(self._repository.create_instruction, row)
        )

    async def list_instructions(
        self,
        *,
        space_id: str,
        semantic_pack_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_instructions,
            space_id=space_id,
            semantic_pack_id=semantic_pack_id,
        )
        return [_instruction_payload(row) for row in rows]

    async def update_instruction(
        self,
        instruction_id: str,
        body: UpdateSemanticInstructionBody,
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        if body.instruction is not None:
            patch["instruction"] = _sanitize_text(body.instruction)
        if body.questions is not None:
            patch["questions_json"] = dumps_json(redact_sensitive(body.questions))
        if body.is_default is not None:
            patch["is_default"] = 1 if body.is_default else 0
        if body.scope is not None:
            patch["scope"] = _sanitize_text(body.scope or "global")
        return _instruction_payload(
            await asyncio.to_thread(
                self._repository.update_instruction,
                instruction_id,
                patch,
            )
        )

    async def delete_instruction(self, instruction_id: str) -> None:
        await asyncio.to_thread(self._repository.delete_instruction, instruction_id)

    async def upsert_graph_object(
        self,
        *,
        object_id: str,
        space_id: str | None,
        semantic_pack_id: str,
        kind: str,
        name: str,
        normalized_name: str,
        description: str = "",
        confidence: float = 0,
        provenance: Mapping[str, Any] | None = None,
        review_status: str = "suggested",
    ) -> dict[str, Any]:
        row = {
            "id": object_id,
            "space_id": space_id,
            "semantic_pack_id": semantic_pack_id,
            "kind": _sanitize_text(kind),
            "name": _sanitize_text(name),
            "normalized_name": _sanitize_text(normalized_name),
            "description": _sanitize_text(description),
            "confidence": float(confidence),
            "provenance_json": dumps_json(redact_sensitive(dict(provenance or {}))),
            "review_status": _sanitize_text(review_status or "suggested"),
        }
        return _graph_object_payload(
            await asyncio.to_thread(self._repository.upsert_graph_object, row)
        )

    async def list_graph_objects(
        self,
        *,
        space_id: str | None = None,
        semantic_pack_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_graph_objects,
            space_id=space_id,
            semantic_pack_id=semantic_pack_id,
        )
        return [_graph_object_payload(row) for row in rows]

    async def update_graph_object_status(
        self,
        object_id: str,
        review_status: str,
    ) -> dict[str, Any]:
        return _graph_object_payload(
            await asyncio.to_thread(
                self._repository.update_graph_object_status,
                object_id,
                _sanitize_text(review_status or "suggested"),
            )
        )

    async def upsert_graph_relation(
        self,
        *,
        relation_id: str,
        space_id: str | None,
        semantic_pack_id: str,
        source_object_id: str,
        target_object_id: str,
        relation_type: str,
        predicate: str = "",
        condition: str = "",
        confidence: float = 0,
        evidence: Sequence[Mapping[str, Any]] = (),
        review_status: str = "suggested",
    ) -> dict[str, Any]:
        row = {
            "id": relation_id,
            "space_id": space_id,
            "semantic_pack_id": semantic_pack_id,
            "source_object_id": _sanitize_text(source_object_id),
            "target_object_id": _sanitize_text(target_object_id),
            "relation_type": _sanitize_text(relation_type),
            "predicate": _sanitize_text(predicate),
            "condition": _sanitize_text(condition),
            "confidence": float(confidence),
            "evidence_json": dumps_json(redact_sensitive(list(evidence))),
            "review_status": _sanitize_text(review_status or "suggested"),
        }
        return _graph_relation_payload(
            await asyncio.to_thread(self._repository.upsert_graph_relation, row)
        )

    async def list_graph_relations(
        self,
        *,
        space_id: str | None = None,
        semantic_pack_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_graph_relations,
            space_id=space_id,
            semantic_pack_id=semantic_pack_id,
        )
        return [_graph_relation_payload(row) for row in rows]

    async def update_graph_relation_status(
        self,
        relation_id: str,
        review_status: str,
    ) -> dict[str, Any]:
        return _graph_relation_payload(
            await asyncio.to_thread(
                self._repository.update_graph_relation_status,
                relation_id,
                _sanitize_text(review_status or "suggested"),
            )
        )

    async def upsert_alignment(
        self,
        *,
        alignment_id: str,
        space_id: str | None,
        semantic_pack_id: str,
        doc_object_id: str,
        mdl_object_ref: str,
        alignment_type: str,
        confidence: float = 0,
        evidence: Sequence[Mapping[str, Any]] = (),
        status: str = "suggested",
    ) -> dict[str, Any]:
        row = {
            "id": alignment_id,
            "space_id": space_id,
            "semantic_pack_id": semantic_pack_id,
            "doc_object_id": _sanitize_text(doc_object_id),
            "mdl_object_ref": _sanitize_text(mdl_object_ref),
            "alignment_type": _sanitize_text(alignment_type),
            "confidence": float(confidence),
            "evidence_json": dumps_json(redact_sensitive(list(evidence))),
            "status": _sanitize_text(status or "suggested"),
        }
        return _alignment_payload(
            await asyncio.to_thread(self._repository.upsert_alignment, row)
        )

    async def list_alignments(
        self,
        *,
        space_id: str | None = None,
        semantic_pack_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repository.list_alignments,
            space_id=space_id,
            semantic_pack_id=semantic_pack_id,
        )
        return [_alignment_payload(row) for row in rows]

    async def update_alignment_status(
        self,
        alignment_id: str,
        status: str,
    ) -> dict[str, Any]:
        return _alignment_payload(
            await asyncio.to_thread(
                self._repository.update_alignment_status,
                alignment_id,
                _sanitize_text(status or "suggested"),
            )
        )

    async def semantic_pack_detail(self, asset_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(
            self._repository.get_skill_package_by_asset,
            "semantic_model",
            asset_id,
        )
        pack = _metadata_envelope(row)
        space_id = row.get("space_id")
        package = pack.get("capability_package") or {}
        few_shot = (
            await self.list_question_sql_pairs(
                space_id=str(space_id or ""),
                semantic_pack_id=asset_id,
            )
            if space_id
            else []
        )
        instructions = (
            await self.list_instructions(
                space_id=str(space_id or ""),
                semantic_pack_id=asset_id,
            )
            if space_id
            else []
        )
        if not few_shot and isinstance(package.get("few_shot"), list):
            few_shot = list(package["few_shot"])
        if not instructions and isinstance(package.get("instructions"), list):
            instructions = list(package["instructions"])
        return {
            "schema": "agentkit.semantic_pack.detail.v1",
            "semantic_pack_id": asset_id,
            "asset": pack,
            "structured_mdl": package.get("mdl", {}),
            "doc_graph": package.get("doc_graph", {}),
            "alignments": await self.list_alignments(semantic_pack_id=asset_id),
            "few_shot": few_shot,
            "instructions": instructions,
            "graph_objects": await self.list_graph_objects(semantic_pack_id=asset_id),
            "graph_relations": await self.list_graph_relations(semantic_pack_id=asset_id),
            "provenance": pack.get("provenance") or {},
            "policy": pack.get("usage_policy") or {},
            "eval_seed": package.get("eval_seed", {}),
            "skill_runtime": package.get("skill_runtime", {}),
            "mock": False,
        }

    async def overview(self, *, space_id: str | None = None) -> dict[str, Any]:
        spaces = await self.list_spaces()
        target_space_id = space_id or (spaces[0]["id"] if spaces else "")
        sources = await self.list_sources(space_id=target_space_id or None)
        packages = await self.list_skill_packages(space_id=target_space_id or None)
        jobs = await self.list_build_jobs(space_id=target_space_id or None, limit=20)
        source_counts: dict[str, int] = {}
        for source in sources:
            source_counts[source["status"]] = source_counts.get(source["status"], 0) + 1
        capability_counts: dict[str, int] = {}
        for item in packages["items"]:
            kind = str(item.get("capability_kind") or "")
            capability_counts[kind] = capability_counts.get(kind, 0) + 1
        next_actions: list[dict[str, str]] = []
        if not spaces:
            next_actions.append({"kind": "space", "label": "创建资产空间"})
        elif not sources:
            next_actions.append({"kind": "source", "label": "添加数据源"})
        if any(source["status"] in {"ready", "indexed"} for source in sources):
            next_actions.append({"kind": "semantic_skill", "label": "生成语义 Skill"})
        if any(source["status"] == "needs_configuration" for source in sources):
            next_actions.append({"kind": "configuration", "label": "完成数据源配置"})
        return {
            "space_id": target_space_id,
            "spaces": spaces,
            "source_counts": source_counts,
            "capability_counts": capability_counts,
            "recent_jobs": jobs,
            "next_actions": next_actions,
            "mock": False,
        }


def redact_sensitive(value: Any, *, key: object = "", depth: int = 0) -> Any:
    if _is_sensitive_key(key):
        return _REDACTED
    if depth > 8:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_sensitive(
                item_value,
                key=item_key,
                depth=depth + 1,
            )
            for item_key, item_value in value.items()
            if not str(item_key).startswith("_") or str(item_key).startswith("_veadk_")
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item, depth=depth + 1) for item in value]
    return f"<{type(value).__name__}>"


def _space_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "default_knowledge_base_id": row.get("default_knowledge_base_id"),
        "region": row.get("region"),
        "metadata": loads_json(row.get("metadata_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _source_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row["space_id"],
        "source_type": row["source_type"],
        "provider": row.get("provider"),
        "name": row["name"],
        "description": row.get("description"),
        "uri": row.get("uri"),
        "locator": loads_json(row.get("locator"), {}),
        "status": row["status"],
        "status_reason": row.get("status_reason"),
        "default_index_policy": loads_json(row.get("default_index_policy"), {}),
        "capabilities": loads_json(row.get("capabilities_json"), {}),
        "metadata": loads_json(row.get("metadata_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _credential_status_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "space_id": row.get("space_id"),
        "provider": row.get("provider"),
        "auth_mode": row.get("auth_mode"),
        "configured": True,
        "status": row["status"],
        "expires_at": row.get("expires_at"),
        "algorithm": row["algorithm"],
        "version": row["version"],
        "key_id": row["key_id"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _indexed_document_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "knowledge_base_id": row.get("knowledge_base_id"),
        "provider_doc_id": row.get("provider_doc_id"),
        "document_id": row.get("document_id"),
        "title": row.get("title"),
        "uri": row.get("uri"),
        "content_hash": row["content_hash"],
        "sync_status": row.get("sync_status") or row["status"],
        "status": row["status"],
        "last_synced_at": row.get("last_synced_at"),
        "metadata": loads_json(row.get("metadata_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _build_job_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row.get("space_id"),
        "source_id": row.get("source_id"),
        "asset_type": row.get("asset_type"),
        "asset_id": row.get("asset_id"),
        "job_type": row["job_type"],
        "status": row["status"],
        "logs_ref": row.get("logs_ref"),
        "result_skill_id": row.get("result_skill_id"),
        "error": loads_json(row.get("error_json"), None),
        "input": loads_json(row.get("input_json"), {}),
        "output": loads_json(row.get("output_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _semantic_build_event_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "space_id": row.get("space_id"),
        "semantic_pack_id": row.get("semantic_pack_id"),
        "event_type": row["event_type"],
        "sequence": int(row["sequence"]),
        "payload": loads_json(row.get("payload_json"), {}),
        "created_at": row.get("created_at"),
    }


def _question_sql_pair_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row["space_id"],
        "semantic_pack_id": row.get("semantic_pack_id"),
        "question": row["question"],
        "sql": row["sql"],
        "dialect": row.get("dialect") or "ansi",
        "tables": loads_json(row.get("tables_json"), []),
        "notes": row.get("notes") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _instruction_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row["space_id"],
        "semantic_pack_id": row.get("semantic_pack_id"),
        "instruction": row["instruction"],
        "questions": loads_json(row.get("questions_json"), []),
        "is_default": bool(row.get("is_default")),
        "scope": row.get("scope") or "global",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _graph_object_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row.get("space_id"),
        "semantic_pack_id": row["semantic_pack_id"],
        "kind": row["kind"],
        "name": row["name"],
        "normalized_name": row["normalized_name"],
        "description": row.get("description") or "",
        "confidence": float(row.get("confidence") or 0),
        "provenance": loads_json(row.get("provenance_json"), {}),
        "review_status": row.get("review_status") or "suggested",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _graph_relation_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row.get("space_id"),
        "semantic_pack_id": row["semantic_pack_id"],
        "source_object_id": row["source_object_id"],
        "target_object_id": row["target_object_id"],
        "relation_type": row["relation_type"],
        "predicate": row.get("predicate") or "",
        "condition": row.get("condition") or "",
        "confidence": float(row.get("confidence") or 0),
        "evidence": loads_json(row.get("evidence_json"), []),
        "review_status": row.get("review_status") or "suggested",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _alignment_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "space_id": row.get("space_id"),
        "semantic_pack_id": row["semantic_pack_id"],
        "doc_object_id": row["doc_object_id"],
        "mdl_object_ref": row["mdl_object_ref"],
        "alignment_type": row["alignment_type"],
        "confidence": float(row.get("confidence") or 0),
        "evidence": loads_json(row.get("evidence_json"), []),
        "status": row.get("status") or "suggested",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _snapshot_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row.get("source_id"),
        "kind": row.get("kind"),
        "artifact_uri": row.get("artifact_uri"),
        "schema": loads_json(row.get("schema_json"), {}),
        "profile": loads_json(row.get("profile_json"), {}),
        "content_hash": row.get("content_hash"),
        "metadata": _metadata_envelope(row),
        "created_at": row.get("created_at"),
    }


def _metadata_envelope(row: dict[str, Any]) -> KnowledgeAssetMetadataEnvelope:
    return {
        "schema_version": "knowledge_asset.metadata.v1",
        "asset_type": row["asset_type"],
        "asset_id": row["asset_id"],
        "capability_kind": row["capability_kind"],
        "name": row["name"],
        "description": row.get("description"),
        "status": row["status"],
        "publish_state": row["publish_state"],
        "gate": loads_json(row.get("gate_json"), None),
        "version": row.get("version"),
        "consumers": loads_json(row.get("consumers_json"), []),
        "capabilities": loads_json(row.get("capabilities_json"), {}),
        "capability_package": loads_json(row.get("capability_package_json"), {}),
        "query_url": row.get("query_url"),
        "freshness": loads_json(row.get("freshness_json"), {}),
        "provenance": loads_json(row.get("provenance_json"), {}),
        "usage_policy": loads_json(row.get("usage_policy_json"), {}),
        "sample_evidence": loads_json(row.get("sample_evidence_json"), []),
    }


def _normalize_source_status(
    status: str,
    source_type: str,
    *,
    allow_pending: bool = True,
) -> str:
    candidate = (status or "").strip().casefold()
    if candidate == "pending":
        if not allow_pending:
            raise KnowledgeAssetServiceError("数据源状态不能再写入 pending。")
        return _initial_import_status(source_type, "")
    if candidate in _SOURCE_STATUSES:
        return candidate
    raise KnowledgeAssetServiceError("数据源状态无效。")


def _normalize_build_job_status(status: str) -> str:
    candidate = (status or "").strip().casefold()
    if candidate == "success":
        return "succeeded"
    if candidate in {"error", "errored"}:
        return "failed"
    if candidate in _BUILD_JOB_STATUSES:
        return candidate
    raise KnowledgeAssetServiceError("Build job 状态无效。")


def _initial_import_status(source_type: str, target_knowledge_base_id: str) -> str:
    normalized = source_type.strip().casefold()
    if normalized in {"database", "oracle", "mysql", "postgres", "feishu_doc"}:
        return "needs_configuration"
    if normalized == "schema_snapshot":
        return "registered"
    return "importing" if target_knowledge_base_id else "needs_configuration"


def _source_capabilities(source_type: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    normalized = source_type.strip().casefold()
    if normalized in _SCHEMA_SOURCE_TYPES:
        return {
            "can_build_semantic_skill": True,
            "can_create_retrieval_binding": False,
            "schema_fields": len(_normalize_schema_payload(schema)["fields"]),
        }
    return {
        "can_build_semantic_skill": False,
        "can_create_retrieval_binding": normalized not in {"database", "oracle", "mysql", "postgres"},
    }


async def _source_markdown(body: ImportSourceBody) -> tuple[str, str, str]:
    source_type = body.source_type.strip().casefold()
    if source_type in {"file", "pdf", "image"} and body.file:
        file_info = _normalize_file_upload(body.file)
        content = (body.content or "").strip()
        if source_type == "file" and content:
            _assert_no_browser_secrets(content)
            return content, file_info["name"], f"upload://{file_info['name']}"
        return (
            f"Uploaded file: {file_info['name']}",
            file_info["name"],
            f"upload://{file_info['name']}",
        )
    if source_type == "web":
        if not body.uri:
            raise KnowledgeAssetServiceError("在线网页导入需要公开 URL。")
        try:
            from frontend.server.knowledge.web_import import import_web_page

            imported = await import_web_page(body.uri)
        except Exception as error:
            raise KnowledgeAssetServiceError(
                f"网页抓取失败：{_sanitize_text(str(error))}"
            ) from error
        markdown = imported.markdown.strip()
        title = (body.name or imported.title or "网页资料").strip()
        if not markdown:
            raise KnowledgeAssetServiceError("网页没有可导入正文。")
        return markdown, title[:256], imported.final_url
    if source_type in {"local_web", "intranet_web", "file", "pdf", "image"}:
        content = (body.content or "").strip()
        if not content:
            if source_type in {"file", "pdf", "image"}:
                raise KnowledgeAssetServiceError("文件导入需要上传内容或接入文件上传链路。")
            raise KnowledgeAssetServiceError("本地/内网页面导入需要粘贴已清洗内容。")
        _assert_no_browser_secrets(content)
        title = (body.name or "本地资料").strip()
        safe_url = _sanitize_text(body.uri or f"local://{_slug(title)}")
        return content, title[:256], safe_url
    raise KnowledgeAssetServiceError(f"暂不支持导入的数据源类型：{source_type}")


async def _write_knowledge_document(
    knowledge_service: Any,
    *,
    target_knowledge_base_id: str,
    identity: Any,
    region: str,
    source_type: str,
    body: ImportSourceBody,
    title: str,
    safe_url: str,
    markdown: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    file_info = _normalize_file_upload(body.file) if body.file else None
    if source_type in {"file", "pdf", "image"} and file_info is not None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(file_info["name"]).suffix,
            ) as temp:
                temp_path = Path(temp.name)
                temp.write(file_info["bytes"])
            return await asyncio.to_thread(
                knowledge_service.upload_document,
                target_knowledge_base_id,
                identity=identity,
                region=region,
                source=temp_path,
                file_name=file_info["name"],
                mime_type=file_info["mime_type"],
                name=title,
                document_type=file_info["document_type"],
                metadata={
                    **metadata,
                    "_veadk_upload_file_name": file_info["name"],
                    "_veadk_upload_mime_type": file_info["mime_type"],
                },
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    from frontend.server.knowledge.models import CreateDocumentBody

    return await asyncio.to_thread(
        knowledge_service.create_document,
        target_knowledge_base_id,
        CreateDocumentBody(
            source_type="url",
            name=title,
            document_type="html" if source_type == "web" else "txt",
            url=safe_url,
            source_title=title,
            source_markdown=markdown,
            metadata=metadata,
        ),
        identity=identity,
        region=region,
    )


def _normalize_file_upload(value: Mapping[str, Any]) -> dict[str, Any]:
    name = _sanitize_file_name(value.get("name"))
    mime_type = _sanitize_text(str(value.get("mime_type") or value.get("type") or ""))
    data = str(value.get("data") or "")
    if "," in data and data.lstrip().startswith("data:"):
        data = data.split(",", 1)[1]
    if not data:
        raise KnowledgeAssetServiceError("文件上传缺少内容。")
    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise KnowledgeAssetServiceError("文件上传内容不是有效的 base64。") from error
    if not decoded:
        raise KnowledgeAssetServiceError("不能上传空文件。")
    if len(decoded) > 8 * 1024 * 1024:
        raise KnowledgeAssetServiceError("知识资产工作台一次导入文件不能超过 8 MB。")
    suffix = Path(name).suffix.casefold().lstrip(".")
    document_type = _sanitize_text(str(value.get("document_type") or suffix or "txt"))
    return {
        "name": name,
        "mime_type": mime_type or "application/octet-stream",
        "document_type": document_type[:64],
        "bytes": decoded,
    }


def _sanitize_file_name(value: object) -> str:
    candidate = str(value or "").strip()
    if (
        not candidate
        or len(candidate) > 255
        or candidate in {".", ".."}
        or "/" in candidate
        or "\\" in candidate
        or "\x00" in candidate
        or any(ord(char) < 32 for char in candidate)
    ):
        raise KnowledgeAssetServiceError("文件名无效，请重新选择文件。")
    return candidate


def _assert_no_browser_secrets(text: str) -> None:
    patterns = [
        r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+",
        r"(?i)\b(?:set-)?cookie\s*:\s*[^\r\n]+",
        r"(?i)\b(?:access|refresh|session)[_-]?token\s*[:=]\s*[A-Za-z0-9._~+/=-]+",
        r"(?i)\bapi[_-]?key\s*[:=]\s*[A-Za-z0-9._~+/=-]+",
        r"(?i)\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b",
    ]
    if any(re.search(pattern, text) for pattern in patterns):
        raise KnowledgeAssetServiceError(
            "提交内容包含浏览器凭据或登录态信息，请移除 cookie、Authorization header 或 token 后重试。"
        )


def _normalize_schema_payload(value: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    models = _object_list(value.get("models") or value.get("tables"))
    fields = _object_list(value.get("fields") or value.get("columns"))
    relationships = _object_list(value.get("relationships") or value.get("relations"))
    metrics = _object_list(value.get("metrics"))
    normalized_models = [
        {
            "name": _safe_identifier(item.get("name") or item.get("table") or item.get("id")),
            "label": _sanitize_text(str(item.get("label") or item.get("name") or "")),
            "description": _sanitize_text(str(item.get("description") or "")),
        }
        for item in models
        if _safe_identifier(item.get("name") or item.get("table") or item.get("id"))
    ]
    normalized_fields = []
    for item in fields:
        name = _safe_identifier(item.get("name") or item.get("field") or item.get("id"))
        if not name:
            continue
        normalized_fields.append(
            {
                "name": name,
                "model": _safe_identifier(item.get("model") or item.get("table")) or "",
                "type": _sanitize_text(str(item.get("type") or item.get("data_type") or "string")),
                "role": _sanitize_text(str(item.get("role") or "dimension")),
                "description": _sanitize_text(str(item.get("description") or "")),
            }
        )
    return {
        "models": normalized_models,
        "fields": normalized_fields,
        "relationships": [
            {
                "from": _sanitize_text(str(item.get("from") or item.get("left") or "")),
                "to": _sanitize_text(str(item.get("to") or item.get("right") or "")),
                "type": _sanitize_text(str(item.get("type") or "many_to_one")),
            }
            for item in relationships
        ],
        "metrics": [
            {
                "name": _safe_identifier(item.get("name") or item.get("id")),
                "formula": _sanitize_text(str(item.get("formula") or item.get("sql") or "")),
                "description": _sanitize_text(str(item.get("description") or "")),
            }
            for item in metrics
            if _safe_identifier(item.get("name") or item.get("id"))
        ],
    }


def _object_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _safe_identifier(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return ""
    if not re.match(r"^[a-z_]", text):
        text = f"f_{text}"
    return text[:80]


def _slug(value: str | None) -> str:
    text = _safe_identifier(value or "")
    return text.replace("_", "-") or f"asset-{hashlib.sha256(_utc_now().encode()).hexdigest()[:8]}"


def _content_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _asset_row(record_id: str, values: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_sensitive(values)
    return {
        "id": record_id,
        "source_id": values.get("source_id"),
        "space_id": values.get("space_id"),
        "kind": _sanitize_text(values.get("kind") or "knowledge_asset"),
        "artifact_uri": _sanitize_text(values.get("artifact_uri") or "") or None,
        "schema_json": dumps_json(sanitized.get("schema", {})),
        "profile_json": dumps_json(sanitized.get("profile", {})),
        "content_hash": _sanitize_text(values.get("content_hash") or "") or None,
        "type": _sanitize_text(
            values.get("type") or values.get("capability_kind") or "retrieval_binding"
        ),
        "source_ids": dumps_json(sanitized.get("source_ids", [])),
        "snapshot_ids": dumps_json(sanitized.get("snapshot_ids", [])),
        "asset_type": values["asset_type"],
        "asset_id": values["asset_id"],
        "capability_kind": values["capability_kind"],
        "name": _sanitize_text(values["name"].strip()),
        "description": _sanitize_text(values.get("description") or "") or None,
        "status": _sanitize_text(values["status"]),
        "publish_state": _sanitize_text(values["publish_state"]),
        "version": _sanitize_text(values.get("version") or "") or None,
        "gate_json": dumps_json(sanitized.get("gate")) if values.get("gate") else None,
        "consumers_json": dumps_json(sanitized.get("consumers", [])),
        "capabilities_json": dumps_json(sanitized.get("capabilities", {})),
        "capability_package_json": dumps_json(
            sanitized.get("capability_package", {})
        ),
        "query_url": _safe_query_url(values.get("query_url")),
        "freshness_json": dumps_json(sanitized.get("freshness", {})),
        "provenance_json": dumps_json(sanitized.get("provenance", {})),
        "usage_policy_json": dumps_json(sanitized.get("usage_policy", {})),
        "sample_evidence_json": dumps_json(sanitized.get("sample_evidence", [])),
        "metadata_json": dumps_json(sanitized.get("metadata", {})),
    }


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _stable_package_id(asset_type: str, asset_id: str) -> str:
    digest = hashlib.sha256(f"{asset_type}\0{asset_id}".encode()).hexdigest()
    return f"pkg_{digest[:32]}"


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(cursor)
    except ValueError as error:
        raise KnowledgeAssetServiceError("Knowledge asset cursor is invalid.") from error
    if value < 0:
        raise KnowledgeAssetServiceError("Knowledge asset cursor is invalid.")
    return value


def _safe_query_url(value: str | None) -> str | None:
    query_url = (value or "").strip()
    if not query_url:
        return None
    parsed = urlsplit(query_url)
    if parsed.scheme or parsed.netloc:
        raise KnowledgeAssetServiceError(
            "Knowledge asset query URL must be a relative Studio path."
        )
    allowed_prefixes = (
        "/api/external/assets/",
        "/api/knowledge-assets/assets/",
        "/api/knowledge-assets/skill-packages/",
        "/api/knowledge-assets/query/",
        "/api/knowledge-assets/ask-data/",
    )
    if not query_url.startswith(allowed_prefixes):
        raise KnowledgeAssetServiceError(
            "Knowledge asset query URL must target governed AgentKit query paths."
        )
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_key(key) or _sanitize_text(query_value) != query_value:
            raise KnowledgeAssetServiceError(
                "Knowledge asset query URL must not contain credentials."
            )
    return query_url


def _is_sensitive_key(value: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value).casefold())
    return normalized.endswith(_SENSITIVE_SUFFIXES) or normalized in {"ak", "sk", "sig"}


def _sanitize_text(value: str) -> str:
    text = value[:8192]
    text = re.sub(
        r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@[^\s]+",
        lambda match: f"{match.group(1)}{_REDACTED}",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(cookie|authorization|token|password|secret|signature|ak|sk)"
        r"\s*[:=]\s*[^\s,;}&]+",
        lambda match: f"{match.group(1)}={_REDACTED}",
        text,
    )
    return text


__all__ = [
    "KnowledgeAssetCredentialError",
    "KnowledgeAssetServiceError",
    "KnowledgeAssetStore",
    "redact_sensitive",
]
