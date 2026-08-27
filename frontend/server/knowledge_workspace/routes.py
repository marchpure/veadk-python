"""Same-origin FastAPI transport for the Knowledge Workspace V1 slice."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .models import InvocationKind
from .service import Actor, KnowledgeWorkspaceError, KnowledgeWorkspaceService


class CreateDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=8_000)
    connection_ids: list[str] = Field(min_length=1, max_length=64)
    trial_task: str | None = Field(default=None, max_length=20_000)


class UpdateDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str | None = Field(default=None, min_length=1, max_length=8_000)
    connection_ids: list[str] | None = Field(default=None, min_length=1, max_length=64)


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    message: str | None = Field(default=None, max_length=20_000)


class DraftMessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)
    intent: str = Field(pattern=r"^(update|run)$")


class FreezeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: str = Field(min_length=1, max_length=160)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_ids: list[str] = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=20_000)


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_space: str = Field(pattern=r"^(personal|team)$")


class PublicationInvokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)
    connection_ids: list[str] = Field(min_length=1, max_length=64)


def mount_knowledge_workspace_routes(
    app: FastAPI,
    service: KnowledgeWorkspaceService,
    *,
    actor_resolver: Callable[[Request], Actor] | None = None,
    prefix: str = "/api/knowledge/v1",
) -> None:
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
        value = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
        return {"data": value, "meta": {"request_id": request.headers.get("x-request-id", "server-generated")}}

    def request_digest(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

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
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.get(f"{prefix}/invocations/{{invocation_id}}/events")
    async def events(request: Request, invocation_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")) -> StreamingResponse:
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
        return envelope(service.repository.revisions(draft_id, tenant_id=actor(request).tenant_id, workspace_id=actor(request).workspace_id), request)

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
                    idempotency_key=idempotency_key,
                    request_digest=request_digest(body.model_dump(mode="json")),
                )
            ),
            request,
        )

    @app.get(f"{prefix}/artifacts/{{artifact_id}}")
    async def artifact(request: Request, artifact_id: str) -> dict[str, Any]:
        return envelope(service.get_artifact(actor(request), artifact_id), request)

    @app.post(f"{prefix}/skill-revisions/{{revision_id}}/publish", status_code=201)
    async def publish(
        request: Request,
        revision_id: str,
        body: PublishBody,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        return envelope(
            service.publish(
                actor(request),
                revision_id,
                body.target_space,
                idempotency_key=idempotency_key,
                request_digest=request_digest(body.model_dump(mode="json")),
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
