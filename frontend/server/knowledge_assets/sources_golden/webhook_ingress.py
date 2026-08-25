"""Independently mountable ASGI ingress for signed connector webhooks."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .application import SourceGoldenApplication, SourcesGoldenError
from .models import AccessContext

WebhookContextResolver = Callable[[str, str], AccessContext]
_MAX_INGRESS_BYTES = 10_000_000


def create_webhook_ingress(
    application: SourceGoldenApplication,
    *,
    context_resolver: WebhookContextResolver,
) -> FastAPI:
    """Create an isolated receiver that can be mounted by the host runtime."""
    app = FastAPI(
        title="Knowledge Connector Webhook Ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.post(
        "/workspaces/{workspace_id}/connections/{connection_id}/{listen_path:path}",
        status_code=202,
    )
    async def receive(
        workspace_id: str,
        connection_id: str,
        listen_path: str,
        request: Request,
    ) -> JSONResponse:
        context = context_resolver(workspace_id, connection_id)
        if context.workspace_id != workspace_id:
            return _error_response("PERMISSION_DENIED", 403)
        try:
            body = await _bounded_body(request)
            event = application.receive_webhook(
                context,
                connection_id=connection_id,
                path=f"/{listen_path}",
                headers=dict(request.headers),
                body=body,
                trace_id=(
                    request.headers.get("x-trace-id") or f"webhook-{uuid.uuid4().hex}"
                ),
            )
        except SourcesGoldenError as error:
            return _error_response(error.code, _status_code(error.code), error.message)
        return JSONResponse(
            status_code=202,
            content=event.model_dump(mode="json", by_alias=True),
        )

    return app


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > _MAX_INGRESS_BYTES:
                raise SourcesGoldenError(
                    "WEBHOOK_PAYLOAD_LIMIT",
                    "Webhook payload exceeds the ingress byte limit.",
                )
        except ValueError as error:
            raise SourcesGoldenError(
                "WEBHOOK_CONTENT_LENGTH_INVALID",
                "Webhook Content-Length is invalid.",
            ) from error
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_INGRESS_BYTES:
            raise SourcesGoldenError(
                "WEBHOOK_PAYLOAD_LIMIT",
                "Webhook payload exceeds the ingress byte limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _error_response(
    code: str,
    status_code: int,
    message: str | None = None,
) -> JSONResponse:
    headers = {"Retry-After": "60"} if status_code == 429 else None
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message or "Webhook request was rejected."},
        headers=headers,
    )


def _status_code(code: str) -> int:
    if code in {
        "WEBHOOK_AUTHENTICATION_FAILED",
        "WEBHOOK_CREDENTIAL_REQUIRED",
        "WEBHOOK_CREDENTIAL_INVALID",
    }:
        return 401
    if code in {"CONNECTION_NOT_FOUND", "WEBHOOK_PATH_MISMATCH"}:
        return 404
    if code in {"PERMISSION_DENIED", "INVALID_SECRET_REFERENCE"}:
        return 403
    if code in {"WEBHOOK_REPLAY", "WEBHOOK_NOT_READY"}:
        return 409
    if code == "WEBHOOK_PAYLOAD_LIMIT":
        return 413
    if code == "WEBHOOK_CONTENT_TYPE_INVALID":
        return 415
    if code == "WEBHOOK_RATE_LIMIT":
        return 429
    if code == "WEBHOOK_CREDENTIAL_UNAVAILABLE":
        return 503
    return 422
