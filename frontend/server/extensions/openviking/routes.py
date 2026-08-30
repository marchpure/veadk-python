"""Same-origin OpenViking BFF routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from frontend.server.knowledge_workspace.service import Actor

from .service import OpenVikingError, OpenVikingService


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(min_length=1, max_length=4096)
    workspace_uri: str = Field(default="viking://resources/", max_length=2048)


class OperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict[str, Any] = Field(default_factory=dict)


class ProfileUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    workspace_uri: str | None = Field(default=None, max_length=2048)


class TextImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_ref: str = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=1_048_576)


class ConnectionImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_ref: str = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=160)


def mount_openviking_routes(
    app: FastAPI,
    service: OpenVikingService,
    *,
    actor_resolver: Callable[[Request], Actor],
    connection_resource_resolver: Callable[[Actor, str], Awaitable[dict[str, Any]]]
    | None = None,
    prefix: str = "/api/knowledge/v1/openviking",
) -> None:
    def actor(request: Request) -> Actor:
        return actor_resolver(request)

    def profile(request: Request, profile_id: str):
        principal = actor(request)
        result = service.repository.get(
            profile_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
        )
        if result is None:
            raise HTTPException(
                404, {"code": "NOT_FOUND", "message": "OpenViking profile not found"}
            )
        return result

    def ready_profile(request: Request, profile_id: str):
        result = profile(request, profile_id)
        if result.status != "ready":
            raise HTTPException(
                409,
                {
                    "code": "OPENVIKING_PROFILE_NOT_READY",
                    "message": "OpenViking profile must be validated before use",
                },
            )
        return result

    def envelope(data: Any, request: Request) -> dict[str, Any]:
        return {
            "data": data,
            "meta": {
                "request_id": request.headers.get("x-request-id", "server-generated")
            },
        }

    async def invoke(call):
        try:
            return await call()
        except OpenVikingError as exc:
            raise HTTPException(
                exc.status_code,
                {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.status_code >= 500,
                },
            ) from exc

    @app.get(f"{prefix}/profiles")
    async def list_profiles(request: Request) -> dict[str, Any]:
        principal = actor(request)
        values = service.repository.list(
            tenant_id=principal.tenant_id, workspace_id=principal.workspace_id
        )
        return envelope([service.public_profile(item) for item in values], request)

    @app.post(f"{prefix}/profiles", status_code=201)
    async def create_profile(request: Request, body: ProfileBody) -> dict[str, Any]:
        principal = actor(request)
        try:
            value = service.create_profile(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                principal_id=principal.principal_id,
                **body.model_dump(),
            )
        except OpenVikingError as exc:
            raise HTTPException(
                exc.status_code, {"code": exc.code, "message": str(exc)}
            ) from exc
        return envelope(service.public_profile(value), request)

    @app.get(f"{prefix}/profiles/{{profile_id}}")
    async def get_profile(request: Request, profile_id: str) -> dict[str, Any]:
        return envelope(service.public_profile(profile(request, profile_id)), request)

    @app.post(f"{prefix}/profiles/{{profile_id}}/validate")
    async def validate_profile(request: Request, profile_id: str) -> dict[str, Any]:
        value = profile(request, profile_id)
        await invoke(lambda: service.validate(value))
        refreshed = profile(request, profile_id)
        return envelope(service.public_profile(refreshed), request)

    @app.patch(f"{prefix}/profiles/{{profile_id}}")
    async def update_profile(
        request: Request, profile_id: str, body: ProfileUpdateBody
    ) -> dict[str, Any]:
        try:
            value = service.update_profile(
                profile(request, profile_id),
                **body.model_dump(exclude_none=True),
            )
        except OpenVikingError as exc:
            raise HTTPException(
                exc.status_code, {"code": exc.code, "message": str(exc)}
            ) from exc
        return envelope(service.public_profile(value), request)

    @app.delete(f"{prefix}/profiles/{{profile_id}}", status_code=204)
    async def revoke_profile(request: Request, profile_id: str) -> Response:
        value = profile(request, profile_id)
        service.repository.delete(
            value.profile_id, tenant_id=value.tenant_id, workspace_id=value.workspace_id
        )
        return Response(status_code=204)

    @app.post(f"{prefix}/profiles/{{profile_id}}/operations/{{operation_name}}")
    async def operation(
        request: Request,
        profile_id: str,
        operation_name: str,
        body: OperationBody,
    ) -> dict[str, Any]:
        value = await invoke(
            lambda: service.request_idempotent(
                ready_profile(request, profile_id),
                operation_name,
                payload=body.payload,
                idempotency_key=request.headers.get("idempotency-key"),
            )
        )
        return envelope(value, request)

    @app.post(f"{prefix}/profiles/{{profile_id}}/upload")
    async def upload(
        request: Request,
        profile_id: str,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        content = await file.read(50 * 1_048_576 + 1)
        value = await invoke(
            lambda: service.upload(
                ready_profile(request, profile_id),
                filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                content=content,
            )
        )
        return envelope(value, request)

    @app.post(f"{prefix}/profiles/{{profile_id}}/text")
    async def import_text(
        request: Request, profile_id: str, body: TextImportBody
    ) -> dict[str, Any]:
        value = await invoke(
            lambda: service.write_text(
                ready_profile(request, profile_id), **body.model_dump()
            )
        )
        return envelope(value, request)

    @app.post(f"{prefix}/profiles/{{profile_id}}/connection-resource")
    async def import_connection_resource(
        request: Request, profile_id: str, body: ConnectionImportBody
    ) -> dict[str, Any]:
        openviking_profile = ready_profile(request, profile_id)
        if connection_resource_resolver is None:
            raise HTTPException(
                503,
                {
                    "code": "CONNECTION_SERVICE_UNAVAILABLE",
                    "message": "Connection resources are not configured",
                },
            )
        principal = actor(request)
        document = await connection_resource_resolver(principal, body.resource_id)
        value = await invoke(
            lambda: service.import_connection_resource(
                openviking_profile,
                parent_ref=body.parent_ref,
                filename=body.filename,
                document=document,
            )
        )
        return envelope(value, request)

    @app.post(
        f"{prefix}/profiles/{{profile_id}}/operations/{{operation_name}}/{{item_id}}"
    )
    async def item_operation(
        request: Request,
        profile_id: str,
        operation_name: str,
        item_id: str,
        body: OperationBody,
    ) -> dict[str, Any]:
        value = await invoke(
            lambda: service.request_idempotent(
                ready_profile(request, profile_id),
                operation_name,
                payload=body.payload,
                item_id=item_id,
                idempotency_key=request.headers.get("idempotency-key"),
            )
        )
        return envelope(value, request)
