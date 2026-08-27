"""Same-origin FastAPI transport for the Knowledge Workspace V1 slice."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import File, FastAPI, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import Response as FastAPIResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .models import Artifact, Invocation, InvocationKind, Publication, SkillRevision, WorkspaceUpload, new_id
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


def mount_knowledge_workspace_routes(
    app: FastAPI,
    service: KnowledgeWorkspaceService,
    *,
    actor_resolver: Callable[[Request], Actor] | None = None,
    prefix: str = "/api/knowledge/v1",
) -> None:
    app.router.on_startup.append(service.resume_pending)

    def actor(request: Request) -> Actor:
        if actor_resolver:
            return actor_resolver(request)
        # Production composition should replace this with trusted gateway
        # claims; headers are intentionally only a local/test adapter.
        return Actor(
            tenant_id=request.headers.get("x-tenant-id", "local-tenant"),
            workspace_id=request.headers.get("x-workspace-id", "local-workspace"),
            principal_id=request.headers.get("x-principal-id", "local-principal"),
        )

    def invoke(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except KnowledgeWorkspaceError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc

    def envelope(data: Any, request: Request) -> dict[str, Any]:
        if isinstance(data, Invocation):
            data = service.public_invocation(data)
            data["event_url"] = f"{prefix}/invocations/{data['invocation_id']}/events"
        elif isinstance(data, SkillRevision):
            data = service.public_revision(data)
        elif isinstance(data, Artifact):
            data = service.public_artifact(data)
        elif isinstance(data, tuple) and data and isinstance(data[0], Publication):
            data = [item.model_dump(mode="json") for item in data]
        value = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
        return {"data": value, "meta": {"request_id": request.headers.get("x-request-id", "server-generated")}}

    def request_digest(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @app.post(f"{prefix}/uploads", status_code=201)
    async def upload(
        request: Request,
        file: UploadFile = File(...),
        purpose: str = Form("context"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if purpose not in {"context", "skill_input"}:
            raise HTTPException(status_code=422, detail={"code": "INVALID_REQUEST", "message": "invalid upload purpose", "retryable": False})
        filename = (file.filename or "").strip()
        if (
            not filename
            or len(filename) > 255
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or any(ord(char) < 32 for char in filename)
        ):
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": "invalid upload filename", "retryable": False})
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail={"code": "UPLOAD_TOO_LARGE", "message": "upload exceeds 20 MiB", "retryable": False})
        if not content:
            raise HTTPException(status_code=400, detail={"code": "INVALID_REQUEST", "message": "upload is empty", "retryable": False})
        actor_value = actor(request)
        digest = hashlib.sha256(content).hexdigest()
        upload_id = new_id("upload")
        if idempotency_key:
            try:
                upload_id = service.repository.idempotent(
                    f"{actor_value.tenant_id}:{actor_value.workspace_id}:{actor_value.principal_id}:upload",
                    idempotency_key,
                    request_digest({"filename": filename, "purpose": purpose, "sha256": digest}),
                    upload_id,
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_CONFLICT":
                    raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "idempotency key conflict", "retryable": False}) from exc
                raise
            existing = service.repository.get_upload(
                upload_id,
                tenant_id=actor_value.tenant_id,
                workspace_id=actor_value.workspace_id,
            )
            if existing is not None:
                return envelope(existing, request)
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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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

    @app.get(f"{prefix}/skills/drafts/{{draft_id}}")
    async def get_draft(request: Request, response: Response, draft_id: str) -> dict[str, Any]:
        result = invoke(lambda: service.get_draft(actor(request), draft_id))
        response.headers["ETag"] = result.etag
        return envelope(result, request)

    @app.patch(f"{prefix}/skills/drafts/{{draft_id}}")
    async def update_draft(
        request: Request,
        response: Response,
        draft_id: str,
        body: UpdateDraftBody,
        if_match: str | None = Header(default=None, alias="If-Match"),
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
            )
        )
        response.headers["ETag"] = result.etag
        payload = envelope(result, request)
        payload["meta"]["etag"] = result.etag
        return payload

    @app.post(f"{prefix}/skills/drafts/{{draft_id}}/generate", status_code=202)
    async def generate(
        request: Request,
        draft_id: str,
        body: GenerateBody | None = None,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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
                    if_match=request.headers.get("if-match"),
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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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
                    if_match=request.headers.get("if-match"),
                    # Draft-attached uploads are used by default; explicit
                    # IDs are validated by the service before execution.
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.get(f"{prefix}/invocations/{{invocation_id}}/events")
    async def events(request: Request, invocation_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")) -> StreamingResponse:
        invocation = service.repository.get_invocation(
            invocation_id,
            tenant_id=actor(request).tenant_id,
            workspace_id=actor(request).workspace_id,
        )
        if invocation is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "invocation not found", "retryable": False})
        after = 0
        if last_event_id:
            try:
                after = int(last_event_id.rsplit(":", 1)[-1])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "INVALID_CURSOR", "message": "Last-Event-ID must be numeric"}) from exc

        async def stream():
            async for event in service.events(actor(request), invocation_id, after):
                if event.get("heartbeat"):
                    yield ": heartbeat\n\n"
                else:
                    yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    @app.post(f"{prefix}/invocations/{{invocation_id}}/cancel", status_code=202)
    async def cancel(request: Request, invocation_id: str) -> dict[str, Any]:
        return envelope(await invoke_async(lambda: service.cancel(actor(request), invocation_id)), request)

    @app.get(f"{prefix}/skills/drafts/{{draft_id}}/revisions")
    async def revisions(request: Request, draft_id: str) -> dict[str, Any]:
        values = service.repository.revisions(draft_id, tenant_id=actor(request).tenant_id, workspace_id=actor(request).workspace_id)
        return envelope(tuple(service.public_revision(item) for item in values), request)

    @app.post(f"{prefix}/skills/drafts/{{draft_id}}/revisions", status_code=201)
    async def freeze(request: Request, draft_id: str, body: FreezeBody) -> dict[str, Any]:
        return envelope(await invoke_async(lambda: service.freeze(actor(request), draft_id, body.invocation_id)), request)

    @app.post(f"{prefix}/skill-revisions/{{revision_id}}/run", status_code=202)
    async def run(
        request: Request,
        revision_id: str,
        body: RunBody,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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

    @app.get(f"{prefix}/artifacts/{{artifact_id}}")
    async def artifact(request: Request, artifact_id: str) -> dict[str, Any]:
        return envelope(service.get_artifact(actor(request), artifact_id), request)

    @app.get(f"{prefix}/artifacts/{{artifact_id}}/content")
    async def artifact_content(request: Request, artifact_id: str) -> FastAPIResponse:
        try:
            content, media_type, csp = service.artifact_content(actor(request), artifact_id)
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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
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
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc
