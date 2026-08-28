"""Same-origin FastAPI transport for the Knowledge Workspace V1 slice."""

from __future__ import annotations

import json
import hashlib
import inspect
from collections.abc import Callable
from typing import Any

from fastapi import (
    File,
    FastAPI,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    JSONResponse,
    Response as FastAPIResponse,
    StreamingResponse,
)
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .connection import ConnectionServiceError, ConnectionServiceGateway
from .models import (
    Artifact,
    Invocation,
    InvocationKind,
    Publication,
    SkillDraft,
    SkillRevision,
    WorkspaceUpload,
    new_id,
)
from .service import Actor, KnowledgeWorkspaceError, KnowledgeWorkspaceService


class CreateDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=8_000)
    connection_ids: list[str] = Field(min_length=1, max_length=64)
    trial_task: str | None = Field(default=None, max_length=20_000)
    upload_ids: list[str] = Field(default_factory=list, max_length=64)


class UpdateDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str | None = Field(default=None, min_length=1, max_length=8_000)
    connection_ids: list[str] | None = Field(default=None, min_length=1, max_length=64)
    trial_task: str | None = Field(default=None, max_length=20_000)
    upload_ids: list[str] | None = Field(default=None, max_length=64)


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    message: str | None = Field(default=None, max_length=20_000)


class DraftMessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)
    intent: str = Field(pattern=r"^(update|run)$")
    upload_ids: list[str] = Field(default_factory=list, max_length=64)


class FreezeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: str = Field(min_length=1, max_length=160)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_ids: list[str] = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=20_000)
    upload_ids: list[str] = Field(default_factory=list, max_length=64)


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_space: str = Field(pattern=r"^(personal|team)$")


class PublicationInvokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)
    connection_ids: list[str] = Field(min_length=1, max_length=64)
    upload_ids: list[str] = Field(default_factory=list, max_length=64)


class CreateConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_key: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=120)
    scope: str = Field(pattern=r"^(personal|team)$")
    config: dict[str, Any] = Field(default_factory=dict)
    credential: dict[str, Any] = Field(default_factory=dict)


class UpdateConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    scope: str | None = Field(default=None, pattern=r"^(personal|team)$")
    config: dict[str, Any] | None = None
    credential: dict[str, Any] | None = None


def mount_knowledge_workspace_routes(
    app: FastAPI,
    service: KnowledgeWorkspaceService,
    *,
    actor_resolver: Callable[[Request], Actor] | None = None,
    connection_gateway: ConnectionServiceGateway | None = None,
    allow_insecure_test_headers: bool = False,
    prefix: str = "/api/knowledge/v1",
) -> None:
    if actor_resolver is None and not allow_insecure_test_headers:
        raise ValueError(
            "a trusted server-side actor_resolver is required; "
            "allow_insecure_test_headers is test-only"
        )
    app.router.on_startup.append(service.resume_pending)
    prior_http_handler = app.exception_handlers.get(StarletteHTTPException)
    prior_validation_handler = app.exception_handlers.get(RequestValidationError)

    async def call_handler(
        handler: Callable[[Request, Exception], Any],
        request: Request,
        exc: Exception,
    ) -> Response:
        result = handler(request, exc)
        return await result if inspect.isawaitable(result) else result

    def request_id(request: Request) -> str:
        return request.headers.get("x-request-id", "server-generated")

    @app.exception_handler(StarletteHTTPException)
    async def knowledge_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        if not request.url.path.startswith(prefix):
            return await call_handler(
                prior_http_handler or http_exception_handler, request, exc
            )
        detail = exc.detail
        if isinstance(detail, dict):
            error = {
                "code": str(detail.get("code") or "HTTP_ERROR"),
                "message": str(detail.get("message") or "Request failed"),
                "retryable": bool(detail.get("retryable", exc.status_code >= 500)),
            }
            if isinstance(detail.get("details"), dict):
                error["details"] = detail["details"]
        else:
            error = {
                "code": "HTTP_ERROR",
                "message": str(detail),
                "retryable": exc.status_code >= 500,
            }
        return JSONResponse(
            {"error": error, "meta": {"request_id": request_id(request)}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def knowledge_validation_error(
        request: Request, exc: RequestValidationError
    ) -> Response:
        if not request.url.path.startswith(prefix):
            return await call_handler(
                prior_validation_handler or request_validation_exception_handler,
                request,
                exc,
            )
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "Request validation failed",
                    "retryable": False,
                    "details": {"errors": exc.errors()},
                },
                "meta": {"request_id": request_id(request)},
            },
            status_code=422,
        )

    def actor(request: Request) -> Actor:
        if actor_resolver:
            return actor_resolver(request)
        # This branch is deliberately opt-in and exists only for local tests.
        return Actor(
            tenant_id=request.headers.get("x-tenant-id", "local-tenant"),
            workspace_id=request.headers.get("x-workspace-id", "local-workspace"),
            principal_id=request.headers.get("x-principal-id", "local-principal"),
        )

    def invoke(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except KnowledgeWorkspaceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc), "retryable": False},
            ) from exc

    def envelope(data: Any, request: Request) -> dict[str, Any]:
        if isinstance(data, Invocation):
            data = service.public_invocation(data)
            data["event_url"] = f"{prefix}/invocations/{data['invocation_id']}/events"
        elif isinstance(data, WorkspaceUpload):
            data = service.public_upload(data)
        elif isinstance(data, SkillDraft):
            data = service.public_draft(data)
        elif isinstance(data, SkillRevision):
            data = service.public_revision(data)
        elif isinstance(data, Artifact):
            data = service.public_artifact(data)
        elif isinstance(data, tuple):
            if data and isinstance(data[0], Publication):
                data = [service.public_publication(item) for item in data]
            elif data and isinstance(data[0], SkillDraft):
                data = [service.public_draft(item) for item in data]
            else:
                data = list(data)
        elif isinstance(data, Publication):
            data = service.public_publication(data)
        value = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
        return {"data": value, "meta": {"request_id": request_id(request)}}

    def request_digest(value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def connection_idempotency(
        request: Request,
        operation: str,
        key: str,
        digest: str,
        value: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        principal = actor(request)
        scope = (
            f"{principal.tenant_id}:{principal.workspace_id}:"
            f"{principal.principal_id}:connection:{operation}"
        )
        try:
            if value is None:
                saved = service.repository.idempotency_value(scope, key, digest)
                return json.loads(saved) if saved else None
            saved = service.repository.idempotent(
                scope,
                key,
                digest,
                json.dumps(value, ensure_ascii=False, sort_keys=True),
            )
            return json.loads(saved)
        except ValueError as exc:
            if str(exc) == "IDEMPOTENCY_CONFLICT":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "idempotency key was reused with different input",
                        "retryable": False,
                    },
                ) from exc
            raise

    def connection_actor(request: Request) -> dict[str, str]:
        value = actor(request)
        return {
            "tenant_id": value.tenant_id,
            "workspace_id": value.workspace_id,
            "principal_id": value.principal_id,
        }

    def require_connections() -> ConnectionServiceGateway:
        if connection_gateway is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CONNECTION_SERVICE_UNAVAILABLE",
                    "message": "Connection Service is not configured",
                    "retryable": True,
                },
            )
        return connection_gateway

    async def connection_call(call: Callable[[], Any]) -> Any:
        try:
            return await call()
        except ConnectionServiceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.status_code >= 500,
                },
            ) from exc

    @app.get(f"{prefix}/connector-definitions")
    async def connector_definitions(request: Request) -> dict[str, Any]:
        result = await connection_call(
            lambda: require_connections().catalog(**connection_actor(request))
        )
        return envelope(result, request)

    @app.get(f"{prefix}/connections")
    async def connections(request: Request) -> dict[str, Any]:
        result = await connection_call(
            lambda: require_connections().list_connections(**connection_actor(request))
        )
        return envelope(result, request)

    @app.get(f"{prefix}/connections/{{connection_id}}")
    async def get_connection(
        request: Request,
        response: Response,
        connection_id: str,
    ) -> dict[str, Any]:
        result = await connection_call(
            lambda: require_connections().get_connection(
                connection_id, **connection_actor(request)
            )
        )
        response.headers["ETag"] = str(result.pop("_revision"))
        return envelope(result, request)

    @app.post(f"{prefix}/connections", status_code=201)
    async def create_connection(
        request: Request,
        response: Response,
        body: CreateConnectionBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        body_value = body.model_dump(mode="json")
        digest = request_digest(body_value)
        result = connection_idempotency(request, "create", idempotency_key, digest)
        if result is None:
            result = await connection_call(
                lambda: require_connections().create_connection(
                    body_value, **connection_actor(request)
                )
            )
            result = connection_idempotency(
                request, "create", idempotency_key, digest, result
            )
        assert result is not None
        response.headers["ETag"] = str(result.pop("_revision"))
        return envelope(result, request)

    @app.patch(f"{prefix}/connections/{{connection_id}}")
    async def update_connection(
        request: Request,
        response: Response,
        connection_id: str,
        body: UpdateConnectionBody,
        if_match: str = Header(..., alias="If-Match", min_length=1),
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        body_value = body.model_dump(mode="json", exclude_none=True)
        digest = request_digest(
            {"connection_id": connection_id, "if_match": if_match, "body": body_value}
        )
        replay = connection_idempotency(
            request, f"update:{connection_id}", idempotency_key, digest
        )
        if replay is not None:
            response.headers["ETag"] = str(replay.pop("_revision"))
            return envelope(replay, request)
        current = await connection_call(
            lambda: require_connections().get_connection(
                connection_id, **connection_actor(request)
            )
        )
        if if_match.strip('"') != str(current["_revision"]):
            raise HTTPException(
                status_code=412,
                detail={
                    "code": "PRECONDITION_FAILED",
                    "message": "connection was modified by another request",
                    "retryable": False,
                },
            )
        result = await connection_call(
            lambda: require_connections().update_connection(
                connection_id,
                body_value,
                **connection_actor(request),
            )
        )
        result = connection_idempotency(
            request, f"update:{connection_id}", idempotency_key, digest, result
        )
        assert result is not None
        response.headers["ETag"] = str(result.pop("_revision"))
        return envelope(result, request)

    @app.delete(f"{prefix}/connections/{{connection_id}}", status_code=204)
    async def delete_connection(
        request: Request,
        connection_id: str,
        if_match: str = Header(..., alias="If-Match", min_length=1),
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> Response:
        digest = request_digest({"connection_id": connection_id, "if_match": if_match})
        if (
            connection_idempotency(
                request, f"delete:{connection_id}", idempotency_key, digest
            )
            is not None
        ):
            return Response(status_code=204)
        current = await connection_call(
            lambda: require_connections().get_connection(
                connection_id, **connection_actor(request)
            )
        )
        if if_match.strip('"') != str(current["_revision"]):
            raise HTTPException(status_code=412, detail="connection version changed")
        await connection_call(
            lambda: require_connections().delete_connection(
                connection_id, **connection_actor(request)
            )
        )
        connection_idempotency(
            request,
            f"delete:{connection_id}",
            idempotency_key,
            digest,
            {"deleted": True},
        )
        return Response(status_code=204)

    @app.post(f"{prefix}/connections/{{connection_id}}/validate", status_code=202)
    async def validate_connection(
        request: Request,
        connection_id: str,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        digest = request_digest({"connection_id": connection_id, "kind": "validate"})
        result = connection_idempotency(
            request, f"validate:{connection_id}", idempotency_key, digest
        )
        if result is None:
            result = await connection_call(
                lambda: require_connections().start_job(
                    connection_id, "validate", **connection_actor(request)
                )
            )
            result = connection_idempotency(
                request,
                f"validate:{connection_id}",
                idempotency_key,
                digest,
                result,
            )
        return envelope(result, request)

    @app.post(f"{prefix}/connections/{{connection_id}}/discover", status_code=202)
    async def discover_connection(
        request: Request,
        connection_id: str,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        digest = request_digest({"connection_id": connection_id, "kind": "discover"})
        result = connection_idempotency(
            request, f"discover:{connection_id}", idempotency_key, digest
        )
        if result is None:
            result = await connection_call(
                lambda: require_connections().start_job(
                    connection_id, "discover", **connection_actor(request)
                )
            )
            result = connection_idempotency(
                request,
                f"discover:{connection_id}",
                idempotency_key,
                digest,
                result,
            )
        return envelope(result, request)

    @app.get(f"{prefix}/connection-jobs/{{job_id}}")
    async def connection_job(request: Request, job_id: str) -> dict[str, Any]:
        result = await connection_call(
            lambda: require_connections().get_job(job_id, **connection_actor(request))
        )
        return envelope(result, request)

    @app.post(f"{prefix}/uploads", status_code=201)
    async def upload(
        request: Request,
        file: UploadFile = File(...),
        purpose: str = Form("context"),
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        if purpose not in {"context", "skill_input"}:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "invalid upload purpose",
                    "retryable": False,
                },
            )
        filename = (file.filename or "").strip()
        if (
            not filename
            or len(filename) > 255
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or any(ord(char) < 32 for char in filename)
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "invalid upload filename",
                    "retryable": False,
                },
            )
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "UPLOAD_TOO_LARGE",
                    "message": "upload exceeds 20 MiB",
                    "retryable": False,
                },
            )
        if not content:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "upload is empty",
                    "retryable": False,
                },
            )
        actor_value = actor(request)
        digest = hashlib.sha256(content).hexdigest()
        upload_id = new_id("upload")
        if idempotency_key:
            try:
                upload_id = service.repository.idempotent(
                    f"{actor_value.tenant_id}:{actor_value.workspace_id}:{actor_value.principal_id}:upload",
                    idempotency_key,
                    request_digest(
                        {"filename": filename, "purpose": purpose, "sha256": digest}
                    ),
                    upload_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": "idempotency key conflict",
                            "retryable": False,
                        },
                    ) from exc
                raise
            existing = service.repository.get_upload(
                upload_id,
                tenant_id=actor_value.tenant_id,
                workspace_id=actor_value.workspace_id,
            )
            if existing is not None:
                return envelope(existing, request)
        connection_file_id = None
        if connection_gateway is not None:
            connection_file_id = await connection_call(
                lambda: connection_gateway.upload_file(
                    filename=filename,
                    content=content,
                    media_type=file.content_type or "application/octet-stream",
                    **connection_actor(request),
                )
            )
        uri = service.repository.put_object(digest, content, suffix=".upload")
        value = WorkspaceUpload(
            tenant_id=actor_value.tenant_id,
            workspace_id=actor_value.workspace_id,
            upload_id=upload_id,
            filename=filename,
            sha256=digest,
            size_bytes=len(content),
            media_type=file.content_type or "application/octet-stream",
            purpose=purpose,
            uri=uri,
            connection_file_id=connection_file_id,
        )
        return envelope(service.repository.save_upload(value), request)

    @app.get(f"{prefix}/skills/drafts")
    async def list_drafts(request: Request) -> dict[str, Any]:
        return envelope(service.list_drafts(actor(request)), request)

    @app.post(f"{prefix}/skills/drafts", status_code=201)
    async def create_draft(
        request: Request,
        response: Response,
        body: CreateDraftBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        result = invoke(
            lambda: service.create_draft(
                actor(request),
                body.goal,
                body.connection_ids,
                trial_task=body.trial_task,
                upload_ids=body.upload_ids,
                idempotency_key=idempotency_key,
                request_digest=request_digest(body.model_dump(mode="json")),
            )
        )
        response.headers["ETag"] = result.etag
        return envelope(
            result,
            request,
        )

    @app.get(f"{prefix}/skills/drafts/{{draft_id}}", response_model=None)
    async def get_draft(
        request: Request,
        response: Response,
        draft_id: str,
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    ) -> dict[str, Any] | Response:
        result = invoke(lambda: service.get_draft(actor(request), draft_id))
        response.headers["ETag"] = result.etag
        if if_none_match and if_none_match.strip('"') == result.etag:
            return Response(status_code=304, headers={"ETag": result.etag})
        return envelope(result, request)

    @app.patch(f"{prefix}/skills/drafts/{{draft_id}}")
    async def update_draft(
        request: Request,
        response: Response,
        draft_id: str,
        body: UpdateDraftBody,
        if_match: str = Header(..., alias="If-Match", min_length=1),
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        result = invoke(
            lambda: service.update_draft(
                actor(request),
                draft_id,
                goal=body.goal,
                connection_ids=body.connection_ids,
                if_match=if_match,
                trial_task=body.trial_task,
                upload_ids=body.upload_ids,
                idempotency_key=idempotency_key,
                request_digest=request_digest(body.model_dump(mode="json")),
            )
        )
        response.headers["ETag"] = result.etag
        payload = envelope(result, request)
        payload["meta"]["etag"] = result.etag
        return payload

    @app.get(f"{prefix}/skills/drafts/{{draft_id}}/conversation")
    async def conversation(request: Request, draft_id: str) -> dict[str, Any]:
        values = invoke(lambda: service.conversation(actor(request), draft_id))
        for item in values:
            invocation = item["invocation"]
            invocation["event_url"] = (
                f"{prefix}/invocations/{invocation['invocation_id']}/events"
            )
        return envelope(values, request)

    @app.post(f"{prefix}/skills/drafts/{{draft_id}}/generate", status_code=202)
    async def generate(
        request: Request,
        draft_id: str,
        body: GenerateBody | None = None,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
        if_match: str = Header(..., alias="If-Match", min_length=1),
    ) -> dict[str, Any]:
        body = body or GenerateBody()
        return envelope(
            invoke(
                lambda: service.start(
                    actor(request),
                    draft_id,
                    InvocationKind.GENERATE,
                    message=body.message or "",
                    model=body.model,
                    if_match=if_match,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.post(f"{prefix}/skills/drafts/{{draft_id}}/messages", status_code=202)
    async def message(
        request: Request,
        draft_id: str,
        body: DraftMessageBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
        if_match: str = Header(..., alias="If-Match", min_length=1),
    ) -> dict[str, Any]:
        kind = InvocationKind.UPDATE if body.intent == "update" else InvocationKind.RUN
        return envelope(
            invoke(
                lambda: service.start(
                    actor(request),
                    draft_id,
                    kind,
                    message=body.message,
                    connection_ids=(),
                    upload_ids=body.upload_ids,
                    if_match=if_match,
                    # Draft-attached uploads are used by default; explicit
                    # IDs are validated by the service before execution.
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.get(f"{prefix}/invocations/{{invocation_id}}/events")
    async def events(
        request: Request,
        invocation_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        invocation = service.repository.get_invocation(
            invocation_id,
            tenant_id=actor(request).tenant_id,
            workspace_id=actor(request).workspace_id,
        )
        if invocation is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "NOT_FOUND",
                    "message": "invocation not found",
                    "retryable": False,
                },
            )
        after = 0
        if last_event_id:
            try:
                after = int(last_event_id.rsplit(":", 1)[-1])
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "INVALID_CURSOR",
                        "message": "Last-Event-ID must be numeric",
                    },
                ) from exc

        async def stream():
            async for event in service.events(actor(request), invocation_id, after):
                if event.get("heartbeat"):
                    yield ": heartbeat\n\n"
                else:
                    yield f"id: {event['cursor']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.post(f"{prefix}/invocations/{{invocation_id}}/cancel", status_code=202)
    async def cancel(
        request: Request,
        invocation_id: str,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        return envelope(
            await invoke_async(
                lambda: service.cancel(
                    actor(request),
                    invocation_id,
                    idempotency_key=idempotency_key,
                    request_digest=invocation_id,
                )
            ),
            request,
        )

    @app.get(f"{prefix}/skills/drafts/{{draft_id}}/revisions")
    async def revisions(request: Request, draft_id: str) -> dict[str, Any]:
        values = service.repository.revisions(
            draft_id,
            tenant_id=actor(request).tenant_id,
            workspace_id=actor(request).workspace_id,
        )
        return envelope(
            tuple(service.public_revision(item) for item in values), request
        )

    @app.post(f"{prefix}/skills/drafts/{{draft_id}}/revisions", status_code=201)
    async def freeze(
        request: Request,
        draft_id: str,
        body: FreezeBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
        if_match: str = Header(..., alias="If-Match"),
    ) -> dict[str, Any]:
        return envelope(
            await invoke_async(
                lambda: service.freeze(
                    actor(request),
                    draft_id,
                    body.invocation_id,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                    if_match=if_match,
                )
            ),
            request,
        )

    @app.post(f"{prefix}/skill-revisions/{{revision_id}}/run", status_code=202)
    async def run(
        request: Request,
        revision_id: str,
        body: RunBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        return envelope(
            await invoke_async(
                lambda: service.run_revision(
                    actor(request),
                    revision_id,
                    body.message,
                    body.connection_ids,
                    upload_ids=body.upload_ids,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.get(f"{prefix}/artifacts/{{artifact_id}}", response_model=None)
    async def artifact(
        request: Request,
        artifact_id: str,
        response: Response,
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    ) -> dict[str, Any] | Response:
        result = service.get_artifact(actor(request), artifact_id)
        response.headers["ETag"] = result.sha256
        if if_none_match and if_none_match.strip('"') == result.sha256:
            return Response(status_code=304, headers={"ETag": result.sha256})
        return envelope(result, request)

    @app.get(f"{prefix}/artifacts/{{artifact_id}}/content")
    async def artifact_content(request: Request, artifact_id: str) -> FastAPIResponse:
        try:
            content, media_type, csp = service.artifact_content(
                actor(request), artifact_id
            )
        except KnowledgeWorkspaceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc), "retryable": False},
            ) from exc
        return FastAPIResponse(
            content=content,
            media_type=media_type,
            headers={
                "Content-Security-Policy": csp,
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get(f"{prefix}/publications")
    async def publications(request: Request) -> dict[str, Any]:
        return envelope(service.list_publications(actor(request)), request)

    @app.post(f"{prefix}/skill-revisions/{{revision_id}}/publish", status_code=201)
    async def publish(
        request: Request,
        revision_id: str,
        body: PublishBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        return envelope(
            invoke(
                lambda: service.publish(
                    actor(request),
                    revision_id,
                    body.target_space,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.post(f"{prefix}/publications/{{publication_id}}/invoke", status_code=202)
    async def invoke_publication(
        request: Request,
        publication_id: str,
        body: PublicationInvokeBody,
        idempotency_key: str = Header(
            ..., alias="Idempotency-Key", min_length=16, max_length=256
        ),
    ) -> dict[str, Any]:
        return envelope(
            await invoke_async(
                lambda: service.invoke_publication(
                    actor(request),
                    publication_id,
                    body.message,
                    body.connection_ids,
                    upload_ids=body.upload_ids,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )


async def invoke_async(call: Callable[[], Any]) -> Any:
    try:
        return await call()
    except KnowledgeWorkspaceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc), "retryable": False},
        ) from exc
