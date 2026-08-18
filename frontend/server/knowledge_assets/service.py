# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Business service for Studio knowledge assets and Agent capabilities."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping, Sequence
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
    RecordIndexedDocumentBody,
    RecordSkillPackageBody,
    RecordSnapshotBody,
    SaveCredentialBody,
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
        if body.metadata is not None:
            patch["metadata_json"] = dumps_json(redact_sensitive(body.metadata))
        row = await asyncio.to_thread(self._repository.update_space, space_id, patch)
        return _space_payload(row)

    async def create_source(self, body: CreateSourceBody) -> dict[str, Any]:
        row = {
            "id": _new_id("src"),
            "space_id": body.space_id,
            "source_type": body.source_type.strip(),
            "provider": _sanitize_text(body.provider or "") or None,
            "name": _sanitize_text(body.name.strip()),
            "description": _sanitize_text(body.description or "") or None,
            "uri": _sanitize_text(body.uri or "") or None,
            "status": body.status.strip(),
            "status_reason": None,
            "capabilities_json": dumps_json(redact_sensitive(body.capabilities)),
            "metadata_json": dumps_json(redact_sensitive(body.metadata)),
        }
        return _source_payload(
            await asyncio.to_thread(self._repository.create_source, row)
        )

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
        patch: dict[str, Any] = {
            "status": body.status.strip(),
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
        envelope = self._cipher.encrypt(body.credentials)
        row = {
            "source_id": source_id,
            "envelope_json": dumps_json(envelope),
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
            "document_id": body.document_id,
            "title": body.title,
            "uri": body.uri,
            "content_hash": body.content_hash,
            "status": body.status,
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
        row = _asset_row(_new_id("snap"), body.model_dump())
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

    async def record_skill_package(
        self, body: RecordSkillPackageBody
    ) -> KnowledgeAssetMetadataEnvelope:
        values = body.model_dump()
        package_id = values.pop("package_id") or _stable_package_id(
            values["asset_type"], values["asset_id"]
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
            if not str(item_key).startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item, depth=depth + 1) for item in value]
    return f"<{type(value).__name__}>"


def _space_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
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
        "status": row["status"],
        "status_reason": row.get("status_reason"),
        "capabilities": loads_json(row.get("capabilities_json"), {}),
        "metadata": loads_json(row.get("metadata_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _credential_status_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
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
        "document_id": row.get("document_id"),
        "title": row.get("title"),
        "uri": row.get("uri"),
        "content_hash": row["content_hash"],
        "status": row["status"],
        "metadata": loads_json(row.get("metadata_json"), {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _snapshot_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row.get("source_id"),
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


def _asset_row(record_id: str, values: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_sensitive(values)
    return {
        "id": record_id,
        "source_id": values.get("source_id"),
        "space_id": values.get("space_id"),
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
    if not query_url.startswith(("/api/", "/web/")):
        raise KnowledgeAssetServiceError(
            "Knowledge asset query URL must use an /api/ or /web/ path."
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
