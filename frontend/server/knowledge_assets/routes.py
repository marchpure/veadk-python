# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""FastAPI routes for the Studio knowledge asset store."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, status

from .contract import KnowledgeAssetType, KnowledgeCapabilityKind
from .crypto import CredentialCryptoError
from .models import (
    CreateSourceBody,
    CreateSpaceBody,
    RecordBuildJobBody,
    RecordIndexedDocumentBody,
    RecordSkillPackageBody,
    RecordSnapshotBody,
    SaveCredentialBody,
    UpdateBuildJobBody,
    UpdateSourceStatusBody,
    UpdateSpaceBody,
)
from .repository import (
    KnowledgeAssetConflict,
    KnowledgeAssetNotFound,
    KnowledgeAssetRepositoryError,
)
from .service import (
    KnowledgeAssetCredentialError,
    KnowledgeAssetServiceError,
    KnowledgeAssetStore,
    redact_sensitive,
)


def mount_knowledge_asset_routes(
    app: FastAPI,
    service: KnowledgeAssetStore | None = None,
) -> None:
    store = service or KnowledgeAssetStore()

    async def invoke(call: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await call()
        except Exception as error:
            raise _convert_error(error) from error

    @app.get("/api/knowledge-assets/health")
    async def health() -> dict[str, Any]:
        return {
            "configured": True,
            "mock": False,
            "store": "sqlite",
            "capabilities": [
                "spaces",
                "sources",
                "retrieval_binding",
                "semantic_skill",
                "dashboard_skill",
            ],
        }

    @app.get("/api/knowledge-assets/sidecars")
    async def sidecars() -> dict[str, Any]:
        try:
            from frontend.server.datastudio.service import (
                config_payload,
                configured_origin,
            )

            config = config_payload()
            datastudio = {
                **config.model_dump(mode="json"),
                "origin": configured_origin(config),
            }
        except Exception:
            datastudio = {
                "configured": False,
                "baseUrl": "",
                "embedUrl": "",
                "origin": "",
                "mock": False,
            }
        return {
            "items": [
                {
                    "id": "byaan-datastudio",
                    "label": "BYAAN Data Studio sidecar",
                    "role": "governed_query_and_dashboard_builder",
                    "configured": bool(datastudio.get("configured")),
                    "status": "available"
                    if datastudio.get("configured")
                    else "not_configured",
                    "debug_url": datastudio.get("embedUrl") or "",
                    "mock": bool(datastudio.get("mock")),
                }
            ],
            "mock": False,
        }

    @app.post("/api/knowledge-assets/spaces", status_code=status.HTTP_201_CREATED)
    async def create_space(body: CreateSpaceBody) -> dict[str, Any]:
        return await invoke(lambda: store.create_space(body))

    @app.get("/api/knowledge-assets/spaces")
    async def list_spaces() -> dict[str, Any]:
        items = await invoke(store.list_spaces)
        return {"items": items, "total": len(items), "mock": False}

    @app.get("/api/knowledge-assets/spaces/{space_id}")
    async def get_space(space_id: str) -> dict[str, Any]:
        return await invoke(lambda: store.get_space(space_id))

    @app.patch("/api/knowledge-assets/spaces/{space_id}")
    async def update_space(space_id: str, body: UpdateSpaceBody) -> dict[str, Any]:
        return await invoke(lambda: store.update_space(space_id, body))

    @app.post("/api/knowledge-assets/sources", status_code=status.HTTP_201_CREATED)
    async def create_source(body: CreateSourceBody) -> dict[str, Any]:
        return await invoke(lambda: store.create_source(body))

    @app.get("/api/knowledge-assets/sources")
    async def list_sources(
        space_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
    ) -> dict[str, Any]:
        items = await invoke(lambda: store.list_sources(space_id=space_id))
        return {"items": items, "total": len(items), "mock": False}

    @app.get("/api/knowledge-assets/sources/{source_id}")
    async def get_source(source_id: str) -> dict[str, Any]:
        return await invoke(lambda: store.get_source(source_id))

    @app.patch("/api/knowledge-assets/sources/{source_id}/status")
    async def update_source_status(
        source_id: str,
        body: UpdateSourceStatusBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.update_source_status(source_id, body))

    @app.put("/api/knowledge-assets/sources/{source_id}/credential")
    async def save_credential(
        source_id: str,
        body: SaveCredentialBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.save_credential(source_id, body))

    @app.get("/api/knowledge-assets/sources/{source_id}/credential")
    async def credential_status(source_id: str) -> dict[str, Any]:
        return await invoke(lambda: store.credential_status(source_id))

    @app.delete(
        "/api/knowledge-assets/sources/{source_id}/credential",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_credential(source_id: str) -> None:
        await invoke(lambda: store.delete_credential(source_id))

    @app.post(
        "/api/knowledge-assets/indexed-documents",
        status_code=status.HTTP_201_CREATED,
    )
    async def record_indexed_document(
        body: RecordIndexedDocumentBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.record_indexed_document(body))

    @app.get("/api/knowledge-assets/indexed-documents")
    async def list_indexed_documents(
        source_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
    ) -> dict[str, Any]:
        items = await invoke(lambda: store.list_indexed_documents(source_id=source_id))
        return {"items": items, "total": len(items), "mock": False}

    @app.post("/api/knowledge-assets/build-jobs", status_code=status.HTTP_201_CREATED)
    async def record_build_job(body: RecordBuildJobBody) -> dict[str, Any]:
        return await invoke(lambda: store.record_build_job(body))

    @app.get("/api/knowledge-assets/build-jobs")
    async def list_build_jobs(
        space_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
        source_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
        asset_id: Annotated[
            str | None, Query(min_length=1, max_length=256)
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_build_jobs(
                space_id=space_id,
                source_id=source_id,
                asset_id=asset_id,
                limit=limit,
            )
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.get("/api/knowledge-assets/build-jobs/{job_id}")
    async def get_build_job(job_id: str) -> dict[str, Any]:
        return await invoke(lambda: store.get_build_job(job_id))

    @app.patch("/api/knowledge-assets/build-jobs/{job_id}")
    async def update_build_job(
        job_id: str,
        body: UpdateBuildJobBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.update_build_job(job_id, body))

    @app.post("/api/knowledge-assets/snapshots", status_code=status.HTTP_201_CREATED)
    async def record_snapshot(body: RecordSnapshotBody) -> dict[str, Any]:
        return await invoke(lambda: store.record_snapshot(body))

    @app.get("/api/knowledge-assets/snapshots")
    async def list_snapshots(
        asset_id: Annotated[
            str | None, Query(min_length=1, max_length=256)
        ] = None,
        source_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_snapshots(asset_id=asset_id, source_id=source_id)
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.post(
        "/api/knowledge-assets/skill-packages",
        status_code=status.HTTP_201_CREATED,
    )
    async def record_skill_package(body: RecordSkillPackageBody) -> dict[str, Any]:
        return await invoke(lambda: store.record_skill_package(body))

    @app.get("/api/knowledge-assets/skill-packages")
    async def list_skill_packages(
        space_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
        q: Annotated[str, Query(max_length=200)] = "",
        asset_type: Annotated[list[KnowledgeAssetType] | None, Query()] = None,
        capability_kind: Annotated[
            list[KnowledgeCapabilityKind] | None, Query()
        ] = None,
        cursor: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> dict[str, Any]:
        return await invoke(
            lambda: store.list_skill_packages(
                space_id=space_id,
                asset_types=asset_type or (),
                capability_kinds=capability_kind or (),
                query=q,
                cursor=cursor,
                limit=limit,
            )
        )

    @app.get("/api/knowledge-assets/skill-packages/{package_id}")
    async def get_skill_package(package_id: str) -> dict[str, Any]:
        return await invoke(lambda: store.get_skill_package(package_id))

    @app.get("/api/knowledge-assets/assets")
    async def list_assets(
        q: Annotated[str, Query(max_length=200)] = "",
        asset_type: Annotated[list[KnowledgeAssetType] | None, Query()] = None,
        capability_kind: Annotated[
            list[KnowledgeCapabilityKind] | None, Query()
        ] = None,
        cursor: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        return await invoke(
            lambda: store.list_assets(
                query=q,
                asset_types=asset_type or (),
                capability_kinds=capability_kind or (),
                cursor=cursor,
                limit=limit,
            )
        )

    @app.get("/api/knowledge-assets/assets/{asset_type}/{asset_id}")
    async def get_asset(asset_type: KnowledgeAssetType, asset_id: str) -> dict[str, Any]:
        return await invoke(
            lambda: store.get_asset(asset_type=asset_type, asset_id=asset_id)
        )


def _convert_error(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, KnowledgeAssetNotFound):
        return _api_error(404, error.code, str(error))
    if isinstance(error, KnowledgeAssetConflict):
        return _api_error(409, error.code, str(error))
    if isinstance(error, (KnowledgeAssetServiceError, ValueError)):
        return _api_error(400, "KNOWLEDGE_ASSET_INVALID_REQUEST", str(error))
    if isinstance(error, (KnowledgeAssetCredentialError, CredentialCryptoError)):
        return _api_error(500, "KNOWLEDGE_ASSET_CREDENTIAL_ERROR", str(error))
    if isinstance(error, KnowledgeAssetRepositoryError):
        return _api_error(error.status_code, error.code, str(error))
    return _api_error(
        500,
        "KNOWLEDGE_ASSET_STORE_ERROR",
        "Knowledge asset store is temporarily unavailable.",
    )


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": redact_sensitive(message),
            "retryable": status_code >= 500,
        },
    )


__all__ = ["mount_knowledge_asset_routes"]
