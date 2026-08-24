"""Studio BFF routes for the STEP 1 Knowledge Asset seam."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .application import KnowledgeAssetApplication
from .contracts import (
    CommandRequest,
    CommandResponse,
    ErrorEnvelope,
    OperationAuditResponse,
)
from .repository import KnowledgeAssetRepositoryError


def _error(
    status: int,
    code: str,
    message: str,
    request_id: str,
    *,
    details: dict[str, str] | None = None,
    retryable: bool | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorEnvelope(
            code=code,
            message=message,
            retryable=status >= 500 if retryable is None else retryable,
            request_id=request_id,
            details=details,
        ).model_dump(mode="json", by_alias=True),
        media_type="application/problem+json",
    )


def mount_knowledge_asset_routes(
    app: FastAPI,
    *,
    application: KnowledgeAssetApplication,
    identity_resolver: Callable[[Request], tuple[str, str]],
) -> None:
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        if not request.url.path.startswith("/api/knowledge-assets/v1/"):
            return await request_validation_exception_handler(request, error)
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        messages = []
        for item in error.errors():
            location = ".".join(str(part) for part in item.get("loc", ()))
            message = str(item.get("msg", "请求参数无效。"))
            messages.append(f"{location}: {message}" if location else message)
        return JSONResponse(
            status_code=422,
            content=ErrorEnvelope(
                code="VALIDATION_ERROR",
                message="请求参数不符合已冻结的知识资产命令契约。",
                retryable=False,
                request_id=request_id,
                details={"validation": "; ".join(messages)[:1000]},
            ).model_dump(mode="json"),
            media_type="application/problem+json",
        )

    app.add_exception_handler(RequestValidationError, validation_error)

    @app.get("/api/knowledge-assets/v1/bootstrap")
    async def bootstrap(request: Request) -> Any:
        workspace_id, role = identity_resolver(request)
        return application.bootstrap(workspace_id, role).model_dump(
            mode="json", by_alias=True
        )

    @app.post("/api/knowledge-assets/v1/commands")
    async def command(request: Request, body: CommandRequest) -> CommandResponse:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return _error(400, "IDEMPOTENCY_KEY_REQUIRED", "缺少幂等键。", request_id)
        try:
            if body.command == "skill-draft.create":
                return application.create_skill_draft(
                    body.payload.model_dump(),
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
            if body.command == "skill-draft.save-manifest":
                return application.save_manifest(
                    body.payload.model_dump(),
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
        except KnowledgeAssetRepositoryError as error:
            return _error(
                409 if error.code == "CONFLICT" else 422,
                error.code,
                error.message,
                request_id,
                details=error.details,
                retryable=error.retryable,
            )
        return application.unsupported(body.command, request_id)

    @app.post("/api/knowledge-assets/v1/streams")
    async def streams(request: Request, body: CommandRequest) -> Response:
        del body
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        return _error(
            422,
            "STREAM_COMMAND_REQUIRED",
            "当前 STEP 1 没有开放流式命令。",
            request_id,
        )

    @app.get("/api/knowledge-assets/v1/operations/{operation_id}")
    async def operation(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        value = application.operation(operation_id)
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return value.model_dump(mode="json", by_alias=True)

    @app.get(
        "/api/knowledge-assets/v1/operations/{operation_id}/audit",
        response_model=None,
    )
    async def operation_audit(
        operation_id: str, request: Request
    ) -> OperationAuditResponse | JSONResponse:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        value = application.operation(operation_id)
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return OperationAuditResponse(
            operation_id=operation_id,
            items=value.audit,
        ).model_dump(mode="json", by_alias=True)

    @app.get("/api/knowledge-assets/v1/operations/{operation_id}/events")
    async def operation_events(operation_id: str, request: Request) -> StreamingResponse:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        value = application.operation(operation_id)
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        last_event_id = request.headers.get("Last-Event-ID")
        after = 0
        if last_event_id:
            try:
                after = max(0, int(last_event_id.rsplit(":", 1)[-1]))
            except ValueError:
                return _error(400, "LAST_EVENT_ID_INVALID", "事件游标无效。", request_id)
        events = application.stream_events(operation_id, after)

        async def body():
            for event in events:
                yield (
                    f"id: {event.sequence}\n"
                    f"event: {event.type}\n"
                    f"data: {json.dumps(event.model_dump(mode='json', by_alias=True), ensure_ascii=False)}\n\n"
                ).encode()

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"X-Operation-ID": operation_id},
        )

    @app.post("/api/knowledge-assets/v1/operations/{operation_id}:cancel")
    async def cancel(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        try:
            return application.cancel(operation_id, request_id).model_dump(
                mode="json", by_alias=True
            )
        except KeyError:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
