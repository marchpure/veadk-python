"""Same-origin BFF routes for AgentKit MCP publications."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from frontend.server.knowledge_workspace.service import Actor

from .client import AgentKitMcpError
from .models import PublicationCreateRequest
from .service import AgentKitMcpPublisher


def mount_agentkit_mcp_routes(
    app: FastAPI,
    publisher: AgentKitMcpPublisher,
    *,
    actor_resolver: Callable[[Request], Actor],
    prefix: str = "/api/data-workshop/v1",
) -> None:
    def actor(request: Request) -> Actor:
        return actor_resolver(request)

    def publication(request: Request, publication_id: str):
        current = publisher.repository.get(
            publication_id,
            tenant_id=actor(request).tenant_id,
            workspace_id=actor(request).workspace_id,
        )
        if current is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "publication not found"})
        return current

    def envelope(data: Any, request: Request) -> dict[str, Any]:
        value = data.model_dump(mode="json", by_alias=True) if hasattr(data, "model_dump") else data
        return {"data": value, "meta": {"request_id": request.headers.get("x-request-id", "server-generated")}}

    def status_for(error: AgentKitMcpError) -> int:
        if error.code in {"PUBLICATION_NOT_FAILED", "IDEMPOTENCY_CONFLICT"}:
            return 409
        if error.code in {"PUBLICATION_DISABLED", "RESOURCE_NOT_OWNED"}:
            return 403
        if error.code in {"TOOLSET_NOT_PROVISIONED", "TOOLSET_NOT_READY"}:
            return 409
        if error.code == "GATEWAY_VERIFIER_UNAVAILABLE":
            return 503
        return 502

    async def invoke(call: Any) -> Any:
        try:
            return await call
        except AgentKitMcpError as error:
            raise HTTPException(
                status_for(error),
                {
                    "code": error.code,
                    "message": str(error),
                    "retryable": error.retryable,
                    "request_id": error.request_id,
                },
            ) from error

    @app.post(f"{prefix}/publications", status_code=202)
    async def create(request: Request, body: dict[str, Any]):
        current_actor = actor(request)
        try:
            publication_request = PublicationCreateRequest.model_validate(body)
        except ValidationError as error:
            raise HTTPException(
                422,
                {
                    "code": "INVALID_ARGUMENT",
                    "message": "Publication request validation failed",
                    "retryable": False,
                    "fields": [
                        ".".join(str(part) for part in item["loc"])
                        for item in error.errors(include_input=False)
                    ],
                },
            ) from error
        value = await invoke(
            publisher.create_or_reuse(
                tenant_id=current_actor.tenant_id,
                workspace_id=current_actor.workspace_id,
                request=publication_request,
            )
        )
        return envelope(value, request)

    @app.get(f"{prefix}/publications/{{publication_id}}")
    async def get(request: Request, publication_id: str):
        return envelope(publication(request, publication_id), request)

    @app.post(f"{prefix}/publications/{{publication_id}}/retry", status_code=202)
    async def retry(request: Request, publication_id: str):
        return envelope(
            await invoke(publisher.retry(publication(request, publication_id))),
            request,
        )

    @app.post(f"{prefix}/publications/{{publication_id}}/disable")
    async def disable(request: Request, publication_id: str):
        value = publication(request, publication_id)
        return envelope(await invoke(publisher.disable(value)), request)

    @app.post(f"{prefix}/publications/{{publication_id}}/verify")
    async def verify(request: Request, publication_id: str):
        result = await invoke(publisher.verify(publication(request, publication_id)))
        return envelope(result, request)
