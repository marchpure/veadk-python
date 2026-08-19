# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""FastAPI routes for the Studio knowledge asset store."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from .agents import (
    AskTableDashboardAgent,
    InternalAgentRunner,
    SemanticBuilderAgent,
)
from .builders.dashboard import (
    AskDataQueryBody,
    DashboardSkillBuildBody,
    GovernedSemanticQueryService,
    SemanticAssetQueryBody,
)
from .builders.dashboard.dashboard_query_service import (
    DashboardQueryBody,
    DashboardQueryService,
)
from .builders.semantic.service import (
    SemanticBuildBlocked,
    SemanticSkillBuildRequest,
)
from .contract import KnowledgeAssetType, KnowledgeCapabilityKind
from .crypto import CredentialCryptoError
from .evaluation.routes import mount_knowledge_asset_evaluation_routes
from .evaluation.service import KnowledgeAssetEvaluatorService
from .models import (
    BuildSemanticSkillBody,
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
    UpdateSemanticReviewStatusBody,
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
    *,
    knowledge_service: Any = None,
    identity_resolver: Callable[[Request], Any] | None = None,
    region_resolver: Callable[[str | None], str] | None = None,
    internal_agent_runner: InternalAgentRunner | None = None,
) -> None:
    store = service or KnowledgeAssetStore()
    semantic_agent = SemanticBuilderAgent(store, runner=internal_agent_runner)
    ask_dashboard_agent = AskTableDashboardAgent(store, runner=internal_agent_runner)
    dashboard_query = DashboardQueryService(store)
    semantic_query = GovernedSemanticQueryService(store)
    evaluation = KnowledgeAssetEvaluatorService(store)
    mount_knowledge_asset_evaluation_routes(app, evaluation)

    async def invoke(call: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await call()
        except Exception as error:
            raise _convert_error(error) from error

    @app.get("/api/knowledge-assets/health")
    async def health() -> dict[str, Any]:
        semantic_status = semantic_agent.health()
        ask_dashboard_status = ask_dashboard_agent.health()
        return {
            "configured": True,
            "mock": False,
            "store": "sqlite",
            "agents": {
                "semantic_builder": semantic_status,
                "asktable_dashboard": ask_dashboard_status,
            },
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
        except Exception:  # noqa: BLE001 - datastudio is optional; health must fail closed.
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

    @app.post(
        "/api/knowledge-assets/sources/import",
        status_code=status.HTTP_201_CREATED,
    )
    async def import_source(
        body: ImportSourceBody,
        request: Request,
    ) -> dict[str, Any]:
        identity = identity_resolver(request) if identity_resolver else None
        resolved_region = (
            region_resolver(body.region) if region_resolver else (body.region or "")
        )
        return await invoke(
            lambda: store.import_source(
                body,
                knowledge_service=knowledge_service,
                identity=identity,
                region=resolved_region,
            )
        )

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

    @app.post(
        "/api/knowledge-assets/build/semantic-skill",
        status_code=status.HTTP_201_CREATED,
    )
    async def build_semantic_skill(
        body: BuildSemanticSkillBody,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        request = SemanticSkillBuildRequest(
            space_id=body.space_id,
            source_ids=body.source_ids,
            snapshot_ids=body.snapshot_ids,
            name=body.name,
            description=body.description,
            intent=body.intent,
            target_domain=body.target_domain,
            publish=body.publish,
        )
        job = await invoke(lambda: semantic_agent.enqueue(request))
        background_tasks.add_task(
            _run_semantic_skill_build,
            semantic_agent,
            job["id"],
            request,
        )
        return job

    @app.post("/api/knowledge-assets/semantic-build/stream")
    async def stream_semantic_build(body: BuildSemanticSkillBody) -> StreamingResponse:
        request = SemanticSkillBuildRequest(
            space_id=body.space_id,
            source_ids=body.source_ids,
            snapshot_ids=body.snapshot_ids,
            name=body.name,
            description=body.description,
            intent=body.intent,
            target_domain=body.target_domain,
            publish=body.publish,
        )
        job = await invoke(lambda: semantic_agent.enqueue(request))

        async def stream_events():
            yield _sse("job_status", {"status": "queued", "job": job, "job_id": job["id"]})
            async for event in semantic_agent.stream(job["id"], request):
                yield _sse(event["event_type"], event)

        return StreamingResponse(
            stream_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/knowledge-assets/semantic-build/{job_id}/events")
    async def list_semantic_build_events(
        job_id: str,
        after_sequence: Annotated[int | None, Query(ge=0)] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_build_events(job_id, after_sequence=after_sequence)
        )
        return {"items": items, "total": len(items), "mock": False}

    async def _run_semantic_skill_build(
        builder: SemanticBuilderAgent,
        job_id: str,
        request: SemanticSkillBuildRequest,
    ) -> None:
        try:
            await builder.run_job(job_id, request)
        except Exception as error:  # noqa: BLE001 - background job boundary records terminal failure.
            await store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status="failed",
                    error={
                        "code": "SEMANTIC_BUILD_FAILED",
                        "message": redact_sensitive(str(error)),
                    },
                ),
            )

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

    @app.get("/api/knowledge-assets/semantic/question-sql-pairs")
    async def list_question_sql_pairs(
        space_id: Annotated[str, Query(min_length=1, max_length=128)],
        semantic_pack_id: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_question_sql_pairs(
                space_id=space_id,
                semantic_pack_id=semantic_pack_id,
            )
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.post(
        "/api/knowledge-assets/semantic/question-sql-pairs",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_question_sql_pair(
        body: SemanticQuestionSqlPairBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.create_question_sql_pair(body))

    @app.patch("/api/knowledge-assets/semantic/question-sql-pairs/{pair_id}")
    async def update_question_sql_pair(
        pair_id: str,
        body: UpdateSemanticQuestionSqlPairBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.update_question_sql_pair(pair_id, body))

    @app.delete(
        "/api/knowledge-assets/semantic/question-sql-pairs/{pair_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_question_sql_pair(pair_id: str) -> None:
        await invoke(lambda: store.delete_question_sql_pair(pair_id))

    @app.get("/api/knowledge-assets/semantic/instructions")
    async def list_instructions(
        space_id: Annotated[str, Query(min_length=1, max_length=128)],
        semantic_pack_id: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_instructions(
                space_id=space_id,
                semantic_pack_id=semantic_pack_id,
            )
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.post(
        "/api/knowledge-assets/semantic/instructions",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_instruction(body: SemanticInstructionBody) -> dict[str, Any]:
        return await invoke(lambda: store.create_instruction(body))

    @app.patch("/api/knowledge-assets/semantic/instructions/{instruction_id}")
    async def update_instruction(
        instruction_id: str,
        body: UpdateSemanticInstructionBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.update_instruction(instruction_id, body))

    @app.delete(
        "/api/knowledge-assets/semantic/instructions/{instruction_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_instruction(instruction_id: str) -> None:
        await invoke(lambda: store.delete_instruction(instruction_id))

    @app.get("/api/knowledge-assets/semantic/graph-objects")
    async def list_graph_objects(
        space_id: Annotated[str | None, Query(max_length=128)] = None,
        semantic_pack_id: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_graph_objects(
                space_id=space_id,
                semantic_pack_id=semantic_pack_id,
            )
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.patch("/api/knowledge-assets/semantic/graph-objects/{object_id}")
    async def update_graph_object(
        object_id: str,
        body: UpdateSemanticReviewStatusBody,
    ) -> dict[str, Any]:
        return await invoke(
            lambda: store.update_graph_object_status(
                object_id,
                body.review_status or body.status or "suggested",
            )
        )

    @app.get("/api/knowledge-assets/semantic/graph-relations")
    async def list_graph_relations(
        space_id: Annotated[str | None, Query(max_length=128)] = None,
        semantic_pack_id: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_graph_relations(
                space_id=space_id,
                semantic_pack_id=semantic_pack_id,
            )
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.patch("/api/knowledge-assets/semantic/graph-relations/{relation_id}")
    async def update_graph_relation(
        relation_id: str,
        body: UpdateSemanticReviewStatusBody,
    ) -> dict[str, Any]:
        return await invoke(
            lambda: store.update_graph_relation_status(
                relation_id,
                body.review_status or body.status or "suggested",
            )
        )

    @app.get("/api/knowledge-assets/semantic/alignments")
    async def list_alignments(
        space_id: Annotated[str | None, Query(max_length=128)] = None,
        semantic_pack_id: Annotated[str | None, Query(max_length=256)] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: store.list_alignments(
                space_id=space_id,
                semantic_pack_id=semantic_pack_id,
            )
        )
        return {"items": items, "total": len(items), "mock": False}

    @app.patch("/api/knowledge-assets/semantic/alignments/{alignment_id}")
    async def update_alignment(
        alignment_id: str,
        body: UpdateSemanticReviewStatusBody,
    ) -> dict[str, Any]:
        return await invoke(
            lambda: store.update_alignment_status(
                alignment_id,
                body.status or body.review_status or "suggested",
            )
        )

    @app.get("/api/knowledge-assets/semantic-packs/{asset_id}/detail")
    async def semantic_pack_detail(asset_id: str) -> dict[str, Any]:
        return await invoke(lambda: store.semantic_pack_detail(asset_id))

    @app.get("/api/knowledge-assets/workbench/overview")
    async def workbench_overview(
        space_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
    ) -> dict[str, Any]:
        return await invoke(lambda: store.overview(space_id=space_id))

    @app.post("/api/knowledge-assets/askdata/query")
    async def askdata_query(body: AskDataQueryBody) -> dict[str, Any]:
        return await invoke(lambda: ask_dashboard_agent.query(body))

    @app.post(
        "/api/knowledge-assets/build/dashboard-skill",
        status_code=status.HTTP_201_CREATED,
    )
    async def build_dashboard_skill(body: DashboardSkillBuildBody) -> dict[str, Any]:
        return await invoke(lambda: ask_dashboard_agent.build_dashboard(body))

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

    @app.post("/api/knowledge-assets/assets/dashboard/{asset_id}/query")
    async def query_dashboard_asset(
        asset_id: str,
        body: DashboardQueryBody,
    ) -> dict[str, Any]:
        return await invoke(lambda: dashboard_query.query(asset_id, body))

    @app.post("/api/knowledge-assets/assets/{asset_type}/{asset_id}/query")
    async def query_knowledge_asset(
        asset_type: KnowledgeAssetType,
        asset_id: str,
        body: SemanticAssetQueryBody,
    ) -> dict[str, Any]:
        if asset_type == "dashboard":
            return await invoke(
                lambda: dashboard_query.query(
                    asset_id,
                    DashboardQueryBody(
                        filters=body.filters,
                        data_view_ids=body.data_view_ids,
                        mode=body.mode,
                    ),
                )
            )
        if asset_type != "semantic_model":
            raise _api_error(
                400,
                "KNOWLEDGE_ASSET_INVALID_REQUEST",
                "Only semantic_model and dashboard assets are queryable.",
            )
        return await invoke(lambda: semantic_query.query_asset(asset_id, body))

    @app.post("/api/external/assets/{asset_type}/{asset_id}/query")
    async def query_external_asset_route(
        asset_type: KnowledgeAssetType,
        asset_id: str,
        body: SemanticAssetQueryBody,
    ) -> dict[str, Any]:
        return await query_knowledge_asset(asset_type, asset_id, body)

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
    if isinstance(error, SemanticBuildBlocked):
        return _api_error(409, "SEMANTIC_BUILD_BLOCKED", str(error))
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


def _sse(event: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(redact_sensitive(payload), ensure_ascii=False)}\n\n"
    )


__all__ = ["mount_knowledge_asset_routes"]
