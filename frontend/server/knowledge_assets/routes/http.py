"""Studio BFF routes for the STEP 1 Knowledge Asset seam."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import ExceptionHandler

from ..application import KnowledgeAssetApplication
from ..contracts import (
    CommandRequest,
    ErrorEnvelope,
    OperationAuditResponse,
)
from ..repository import KnowledgeAssetRepositoryError
from ..sources_golden import SourcesGoldenError
from frontend.server.skill_authoring.models import SkillAuthoringError
from frontend.server.skill_authoring.streaming import (
    AuthoringEventFeed,
    parse_last_event_id,
)


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

    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_error),
    )

    @app.get("/api/knowledge-assets/v1/bootstrap")
    async def bootstrap(request: Request) -> Any:
        workspace_id, role = identity_resolver(request)
        return application.bootstrap(workspace_id, role).model_dump(
            mode="json", by_alias=True
        )

    @app.post("/api/knowledge-assets/v1/commands")
    async def command(request: Request, body: CommandRequest) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return _error(400, "IDEMPOTENCY_KEY_REQUIRED", "缺少幂等键。", request_id)
        workspace_id, _role = identity_resolver(request)
        if body.command == "skill-authoring.answer":
            return await application.answer_skill_authoring(
                body.payload.model_dump(mode="python"),
                caller_id=workspace_id,
                workspace_id=workspace_id,
                request_id=request_id,
            )
        if body.command == "skill-authoring.start":
            return await application.start_skill_authoring(
                body.payload.model_dump(mode="python"),
                caller_id=workspace_id,
                workspace_id=workspace_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
        if body.command == "skill-authoring.patch":
            return await application.patch_skill_authoring(
                body.payload.model_dump(mode="python"),
                caller_id=workspace_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
        if body.command == "skill-authoring.execute":
            return await application.execute_skill_authoring(
                body.payload.model_dump(mode="python"),
                caller_id=workspace_id,
                request_id=request_id,
            )
        if body.command == "source-golden.connection.create":
            try:
                if (
                    body.payload.connector_key == "mcp_custom"
                    and body.payload.configuration
                ):
                    return _error(
                        422,
                        "MCP_CLIENT_EXECUTION_FIELDS_FORBIDDEN",
                        "浏览器不得提交 MCP command、args、cwd 或 env。",
                        request_id,
                    )
                return application.source_golden_connection(
                    body.payload,
                    workspace_id=workspace_id,
                    principal_id=workspace_id,
                    role=_role,
                    idempotency_key=idempotency_key,
                    trace_id=request_id,
                )
            except SourcesGoldenError as error:
                return _error(422, error.code, error.message, request_id)
        if body.command == "source-golden.ingest":
            try:
                return application.source_golden_ingest(
                    body.payload,
                    workspace_id=workspace_id,
                    principal_id=workspace_id,
                    role=_role,
                    idempotency_key=idempotency_key,
                    trace_id=request_id,
                )
            except SourcesGoldenError as error:
                return _error(422, error.code, error.message, request_id)
        async_mode = body.command in {
            "skill-draft.run",
            "skill-draft.retry",
        } and "respond-async" in request.headers.get("Prefer", "")
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
        try:
            return application.unsupported(
                body.command,
                request_id,
                body.payload.model_dump(mode="python"),
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
                async_mode=async_mode,
            )
        except KnowledgeAssetRepositoryError as error:
            status_code = 404 if error.code.endswith("_NOT_FOUND") else 422
            return _error(
                status_code,
                error.code,
                error.message,
                request_id,
                details=error.details,
                retryable=error.retryable,
            )

    @app.get(
        "/api/knowledge-assets/v1/workspaces/{workspace_id}"
        "/skill-view-revisions/{view_revision_id}/artifacts/{sha256}"
    )
    async def immutable_html_artifact(
        workspace_id: str,
        view_revision_id: str,
        sha256: str,
        request: Request,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        authenticated_workspace, _role = identity_resolver(request)
        if authenticated_workspace != workspace_id:
            return _error(
                404, "ARTIFACT_NOT_FOUND", "HTML revision does not exist.", request_id
            )
        try:
            content = application.immutable_html_artifact(
                workspace_id=workspace_id,
                view_revision_id=view_revision_id,
                sha256=sha256,
            )
        except KnowledgeAssetRepositoryError as error:
            status = (
                500
                if error.code == "ARTIFACT_INTEGRITY_FAILED"
                else (422 if error.code == "ARTIFACT_REF_MISMATCH" else 404)
            )
            return _error(
                status,
                error.code,
                error.message,
                request_id,
                details=error.details,
                retryable=error.retryable,
            )
        return Response(
            content=content,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Length": str(len(content)),
                "ETag": f'"sha256:{sha256}"',
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                    "font-src data:; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'"
                ),
            },
        )

    @app.post("/api/knowledge-assets/v1/streams")
    async def streams(request: Request, body: CommandRequest) -> Response:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return _error(
                400,
                "IDEMPOTENCY_KEY_REQUIRED",
                "缺少幂等键。",
                request_id,
            )
        if body.command != "skill-authoring.start":
            return _error(
                422,
                "STREAM_COMMAND_REQUIRED",
                "流式入口仅接受 skill-authoring.start。",
                request_id,
            )
        authoring = getattr(application, "_authoring", None)
        if authoring is None:
            return _error(
                503,
                "AUTHORING_NOT_CONFIGURED",
                "生产 authoring repository 尚未配置。",
                request_id,
                retryable=False,
            )
        workspace_id, _role = identity_resolver(request)
        payload = body.payload.model_dump(mode="python")
        envelope = application._authoring_envelope(
            payload,
            caller_id=workspace_id,
            workspace_id=workspace_id,
            request_id=request_id,
        )
        from frontend.server.skill_authoring.models import (
            Scope as AuthoringScope,
            SkillKind as AuthoringSkillKind,
        )

        try:
            kind = payload.get("requested_kind")
            accepted = await authoring.start_turn(
                envelope,
                requested_kind=AuthoringSkillKind(kind) if kind else None,
                scope=AuthoringScope(str(payload.get("scope", "personal"))),
                display_name=payload.get("display_name"),
                idempotency_key=idempotency_key,
            )
            operation_id = accepted.operation_id
        except SkillAuthoringError as error:
            return _error(
                403 if error.code.value == "permission_denied" else 422,
                error.code.value.upper(),
                error.message,
                request_id,
                retryable=False,
            )
        try:
            after = parse_last_event_id(
                request.headers.get("Last-Event-ID"),
                operation_id=operation_id,
            )
        except ValueError:
            return _error(400, "LAST_EVENT_ID_INVALID", "事件游标无效。", request_id)
        feed = AuthoringEventFeed(authoring.repository)

        async def stream_body():
            async for frame in feed.iter_frames(operation_id, after_sequence=after):
                if await request.is_disconnected():
                    break
                if frame.kind == "heartbeat":
                    yield b": heartbeat\n\n"
                    continue
                event = frame.event
                if event is None:
                    continue
                payload = event.model_dump(mode="json", by_alias=True)
                yield (
                    f"id: {operation_id}:{event.sequence}\n"
                    f"event: {event.type}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                ).encode()

        return StreamingResponse(
            stream_body(),
            media_type="text/event-stream",
            headers={
                "X-Operation-ID": operation_id,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/knowledge-assets/v1/operations/{operation_id}")
    async def operation(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        value = application.operation(operation_id)
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return value.model_dump(mode="json", by_alias=True)

    @app.get("/api/knowledge-assets/v1/authoring/operations/{operation_id}")
    async def authoring_operation(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        value = await application.authoring_operation(operation_id)
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        workspace_id, _role = identity_resolver(request)
        if value.operation.workspace_id != workspace_id:
            # Keep durable operation reads aligned with the event feed and
            # mutation routes: operation IDs are not bearer capabilities.
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return value.model_dump(mode="json", by_alias=True)

    def authoring_service():
        # The application composes this domain service; routes intentionally
        # keep authoring transport concerns out of the shared application API.
        return getattr(application, "_authoring", None)

    @app.get("/api/knowledge-assets/v1/authoring/operations/{operation_id}/events")
    async def authoring_operation_events(
        operation_id: str, request: Request
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        read = await application.authoring_operation(operation_id)
        authoring = authoring_service()
        if read is None or authoring is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        workspace_id, _role = identity_resolver(request)
        if read.operation.workspace_id != workspace_id:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        try:
            after = parse_last_event_id(
                request.headers.get("Last-Event-ID"),
                operation_id=operation_id,
            )
        except ValueError:
            return _error(400, "LAST_EVENT_ID_INVALID", "事件游标无效。", request_id)
        feed = AuthoringEventFeed(authoring.repository)

        async def body():
            async for frame in feed.iter_frames(operation_id, after_sequence=after):
                if await request.is_disconnected():
                    break
                if frame.kind == "heartbeat":
                    yield b": heartbeat\n\n"
                    continue
                event = frame.event
                if event is None:
                    continue
                payload = event.model_dump(mode="json", by_alias=True)
                yield (
                    f"id: {operation_id}:{event.sequence}\n"
                    f"event: {event.type}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                ).encode()

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={
                "X-Operation-ID": operation_id,
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/knowledge-assets/v1/authoring/operations/{operation_id}:cancel")
    async def cancel_authoring(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        workspace_id, _role = identity_resolver(request)
        authoring = authoring_service()
        if authoring is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        try:
            value = await authoring.cancel(operation_id, caller_id=workspace_id)
        except SkillAuthoringError as error:
            return _error(
                403 if error.code.value == "permission_denied" else 422,
                error.code.value.upper(),
                error.message,
                request_id,
            )
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return value.model_dump(mode="json", by_alias=True)

    @app.post("/api/knowledge-assets/v1/authoring/operations/{operation_id}:retry")
    async def retry_authoring(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        workspace_id, _role = identity_resolver(request)
        authoring = authoring_service()
        if authoring is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        try:
            value = await authoring.retry(operation_id, caller_id=workspace_id)
        except SkillAuthoringError as error:
            return _error(
                403 if error.code.value == "permission_denied" else 422,
                error.code.value.upper(),
                error.message,
                request_id,
            )
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return value.model_dump(mode="json", by_alias=True)

    @app.get(
        "/api/knowledge-assets/v1/operations/{operation_id}/audit",
        response_model=None,
    )
    async def operation_audit(operation_id: str, request: Request) -> Any:
        request_id = request.headers.get("X-Request-ID", "missing-request-id")
        value = application.operation(operation_id)
        if value is None:
            return _error(404, "OPERATION_NOT_FOUND", "操作不存在。", request_id)
        return OperationAuditResponse(
            operation_id=operation_id,
            items=value.audit,
        ).model_dump(mode="json", by_alias=True)

    @app.get("/api/knowledge-assets/v1/operations/{operation_id}/events")
    async def operation_events(operation_id: str, request: Request) -> Response:
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
                return _error(
                    400, "LAST_EVENT_ID_INVALID", "事件游标无效。", request_id
                )
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
