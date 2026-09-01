"""Same-origin BFF routes for AgentKit MCP publications."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request

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

    @app.post(f"{prefix}/publications", status_code=202)
    async def create(request: Request, body: PublicationCreateRequest):
        current_actor = actor(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            raise HTTPException(400, {"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "idempotency-key is required"})
        value = await publisher.create_or_reuse(
            tenant_id=current_actor.tenant_id, workspace_id=current_actor.workspace_id,
            request=body, idempotency_key=key,
        )
        return envelope(value, request)

    @app.get(f"{prefix}/publications/{{publication_id}}")
    async def get(request: Request, publication_id: str):
        return envelope(publication(request, publication_id), request)

    @app.post(f"{prefix}/publications/{{publication_id}}/retry", status_code=202)
    async def retry(request: Request, publication_id: str):
        key = request.headers.get("idempotency-key", "").strip() or f"retry:{publication_id}"
        return envelope(await publisher.retry(publication(request, publication_id), idempotency_key=key), request)

    @app.post(f"{prefix}/publications/{{publication_id}}/disable")
    async def disable(request: Request, publication_id: str):
        value = publication(request, publication_id)
        return envelope(await publisher.disable(value, idempotency_key=f"disable:{publication_id}"), request)

    @app.post(f"{prefix}/publications/{{publication_id}}/verify")
    async def verify(request: Request, publication_id: str):
        try:
            result = await publisher.verify(publication(request, publication_id))
        except AgentKitMcpError as error:
            raise HTTPException(502, {"code": "GATEWAY_VERIFY_FAILED", "message": str(error)}) from error
        return envelope(result, request)
