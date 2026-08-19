"""FastAPI routes for Knowledge Asset evaluation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, status

from ..repository import KnowledgeAssetNotFound, KnowledgeAssetRepositoryError
from ..service import KnowledgeAssetServiceError, redact_sensitive
from .models import (
    CreateKnowledgeAssetEvalCaseBody,
    CreateKnowledgeAssetEvalSuiteBody,
    ImportKnowledgeAssetEvalCasesBody,
    KnowledgeAssetEvalTargetKind,
    RunKnowledgeAssetEvalBody,
)
from .service import KnowledgeAssetEvaluatorService


def mount_knowledge_asset_evaluation_routes(
    app: FastAPI,
    service: KnowledgeAssetEvaluatorService,
) -> None:
    async def invoke(call: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await call()
        except Exception as error:
            raise _convert_error(error) from error

    @app.get("/api/knowledge-assets/evaluation/suites")
    async def list_suites(
        space_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
        target_kind: Annotated[
            KnowledgeAssetEvalTargetKind | None, Query()
        ] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: service.list_suites(space_id=space_id, target_kind=target_kind)
        )
        return {
            "items": [item.model_dump(mode="json", by_alias=True) for item in items],
            "total": len(items),
            "mock": False,
        }

    @app.post(
        "/api/knowledge-assets/evaluation/suites",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_suite(body: CreateKnowledgeAssetEvalSuiteBody) -> dict[str, Any]:
        suite = await invoke(lambda: service.create_suite(body))
        return {**suite.model_dump(mode="json", by_alias=True), "mock": False}

    @app.get("/api/knowledge-assets/evaluation/suites/{suite_id}/cases")
    async def list_cases(suite_id: str) -> dict[str, Any]:
        items = await invoke(lambda: service.list_cases(suite_id))
        return {
            "items": [item.model_dump(mode="json", by_alias=True) for item in items],
            "total": len(items),
            "mock": False,
        }

    @app.post(
        "/api/knowledge-assets/evaluation/suites/{suite_id}/cases",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_case(
        suite_id: str,
        body: CreateKnowledgeAssetEvalCaseBody,
    ) -> dict[str, Any]:
        item = await invoke(lambda: service.create_case(suite_id, body))
        return {**item.model_dump(mode="json", by_alias=True), "mock": False}

    @app.post(
        "/api/knowledge-assets/evaluation/suites/{suite_id}/cases/import",
        status_code=status.HTTP_201_CREATED,
    )
    async def import_cases(
        suite_id: str,
        body: ImportKnowledgeAssetEvalCasesBody,
    ) -> dict[str, Any]:
        result = await invoke(lambda: service.import_cases(suite_id, body))
        return result.model_dump(mode="json", by_alias=True)

    @app.post("/api/knowledge-assets/evaluation/runs")
    async def run_evaluation(body: RunKnowledgeAssetEvalBody) -> dict[str, Any]:
        detail = await invoke(lambda: service.run(body))
        return detail.model_dump(mode="json", by_alias=True)

    @app.get("/api/knowledge-assets/evaluation/runs")
    async def list_runs(
        suite_id: Annotated[
            str | None, Query(min_length=1, max_length=128)
        ] = None,
        target_kind: Annotated[
            KnowledgeAssetEvalTargetKind | None, Query()
        ] = None,
        target_asset_id: Annotated[
            str | None, Query(min_length=1, max_length=256)
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: service.list_runs(
                suite_id=suite_id,
                target_kind=target_kind,
                target_asset_id=target_asset_id,
                limit=limit,
            )
        )
        return {
            "items": [item.model_dump(mode="json", by_alias=True) for item in items],
            "total": len(items),
            "mock": False,
        }

    @app.get("/api/knowledge-assets/evaluation/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        detail = await invoke(lambda: service.get_run_detail(run_id))
        return detail.model_dump(mode="json", by_alias=True)

    @app.get("/api/knowledge-assets/evaluation/optimizations")
    async def list_optimizations(
        target_kind: Annotated[
            KnowledgeAssetEvalTargetKind | None, Query()
        ] = None,
        target_asset_id: Annotated[
            str | None, Query(min_length=1, max_length=256)
        ] = None,
    ) -> dict[str, Any]:
        items = await invoke(
            lambda: service.list_optimizations(
                target_kind=target_kind,
                target_asset_id=target_asset_id,
            )
        )
        return {
            "items": [item.model_dump(mode="json", by_alias=True) for item in items],
            "total": len(items),
            "mock": False,
        }


def _convert_error(error: Exception) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(error, KnowledgeAssetNotFound):
        return _api_error(404, error.code, str(error))
    if isinstance(error, (KnowledgeAssetServiceError, ValueError)):
        return _api_error(400, "KNOWLEDGE_ASSET_INVALID_REQUEST", str(error))
    if isinstance(error, KnowledgeAssetRepositoryError):
        return _api_error(error.status_code, error.code, str(error))
    return _api_error(
        500,
        "KNOWLEDGE_ASSET_EVALUATION_ERROR",
        "Knowledge asset evaluation is temporarily unavailable.",
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


__all__ = ["mount_knowledge_asset_evaluation_routes"]
