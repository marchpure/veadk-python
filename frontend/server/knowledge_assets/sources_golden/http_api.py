"""Independently mountable HTTP API for Source/Golden connector operations."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ..contract_base import ContractModel
from .application import SourceGoldenApplication, SourcesGoldenError
from .models import AccessContext, CleaningOperation, GoldenContextReference

SourceGoldenIdentityResolver = Callable[[Request], AccessContext]
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_CONTENT_ADDRESSED_NAME = re.compile(r"^[0-9a-f]{64}\.[a-z0-9]+$")
_UPLOAD_SUFFIXES = frozenset(
    {
        ".csv",
        ".db",
        ".htm",
        ".html",
        ".json",
        ".jsonl",
        ".markdown",
        ".md",
        ".ndjson",
        ".parquet",
        ".pdf",
        ".sqlite",
        ".sqlite3",
        ".txt",
        ".xlsx",
        ".yaml",
        ".yml",
    }
)


class ConnectionCreateBody(ContractModel):
    connector_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    scope: Literal["personal", "team"] = "personal"
    configuration: dict[str, object] = Field(default_factory=dict)
    secret_ref: str | None = None
    mcp_profile_id: str | None = Field(default=None, max_length=256)
    tool_allowlist: list[str] = Field(default_factory=list, max_length=100)


class IngestBody(ContractModel):
    resource_id: str | None = Field(default=None, max_length=256)
    recipe_operations: list[CleaningOperation] = Field(default_factory=lambda: ["trim"])
    tool_arguments: dict[str, object] = Field(default_factory=dict)


class RefreshBody(ContractModel):
    retry_of: str | None = Field(default=None, max_length=256)


class RevokeBody(ContractModel):
    reason: str = Field(min_length=1, max_length=256)


class ContextResolveBody(ContractModel):
    reference: GoldenContextReference


def mount_source_golden_routes(
    app: FastAPI,
    *,
    application: SourceGoldenApplication,
    identity_resolver: SourceGoldenIdentityResolver,
    prefix: str = "/api/source-golden/v1",
    context_max_age_seconds: int = 3_600,
) -> None:
    """Mount the complete W1 HTTP surface without modifying the shared BFF."""
    if context_max_age_seconds < 0:
        raise ValueError("Context maximum age must be non-negative.")

    @app.get(f"{prefix}/catalog")
    async def catalog(request: Request) -> object:
        return application.connector_catalog(identity_resolver(request)).model_dump(
            mode="json", by_alias=True
        )

    @app.get(f"{prefix}/overview")
    async def overview(request: Request) -> object:
        return application.data_overview(identity_resolver(request)).model_dump(
            mode="json", by_alias=True
        )

    @app.get(f"{prefix}/connections/{{connection_id}}")
    async def connection_detail(connection_id: str, request: Request) -> Response:
        try:
            result = application.connection_detail(
                identity_resolver(request),
                connection_id,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.get(f"{prefix}/connections/{{connection_id}}/operations")
    async def connection_operations(connection_id: str, request: Request) -> Response:
        try:
            result = application.connector_operations(
                identity_resolver(request),
                connection_id,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(
            [item.model_dump(mode="json", by_alias=True) for item in result]
        )

    @app.get(f"{prefix}/connections/{{connection_id}}/traces/{{trace_id}}")
    async def connection_trace(
        connection_id: str,
        trace_id: str,
        request: Request,
    ) -> Response:
        try:
            result = application.connector_trace(
                identity_resolver(request),
                connection_id,
                trace_id,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.post(f"{prefix}/uploads")
    async def upload_source(
        request: Request,
        upload: Annotated[UploadFile, File()],
    ) -> Response:
        try:
            context = identity_resolver(request)
            result = await _store_upload(
                application.source_root,
                context.workspace_id,
                upload,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result, status_code=201)

    @app.post(f"{prefix}/connections")
    async def create_connection(
        request: Request, body: ConnectionCreateBody
    ) -> Response:
        try:
            context = identity_resolver(request)
            idempotency_key = _idempotency_key(request)
            _validate_uploaded_source_ownership(context, body)
            configuration, secret_ref = _connection_configuration(application, body)
            result = application.create_connection(
                context,
                connector_key=body.connector_key,
                display_name=body.display_name,
                scope=body.scope,
                configuration=configuration,
                secret_ref=secret_ref,
                idempotency_key=idempotency_key,
                trace_id=_trace_id(request),
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(
            result.model_dump(mode="json", by_alias=True),
            status_code=201,
        )

    @app.post(f"{prefix}/connections/{{connection_id}}/ingestions")
    async def ingest(
        connection_id: str,
        request: Request,
        body: IngestBody,
    ) -> Response:
        try:
            result = application.ingest(
                identity_resolver(request),
                connection_id=connection_id,
                resource_id=body.resource_id,
                recipe_operations=body.recipe_operations,
                tool_arguments=body.tool_arguments,
                idempotency_key=_idempotency_key(request),
                trace_id=_trace_id(request),
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.get(f"{prefix}/golden-revisions/{{revision_id}}")
    async def golden_data(revision_id: str, request: Request) -> Response:
        try:
            result = application.golden_data(identity_resolver(request), revision_id)
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.get(f"{prefix}/golden-assets/{{asset_id}}")
    async def golden_asset_detail(asset_id: str, request: Request) -> Response:
        try:
            result = application.golden_asset_detail(
                identity_resolver(request),
                asset_id,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.get(f"{prefix}/golden-revisions/{{revision_id}}/content")
    async def golden_content(revision_id: str, request: Request) -> Response:
        try:
            content = application.golden_asset_content(
                identity_resolver(request), revision_id
            )
        except SourcesGoldenError as error:
            return _error(error)
        return Response(
            content,
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post(f"{prefix}/context/resolve")
    async def resolve_context(request: Request, body: ContextResolveBody) -> Response:
        try:
            result = application.resolve_context_reference(
                identity_resolver(request),
                body.reference,
                max_age_seconds=context_max_age_seconds,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.post(f"{prefix}/golden-assets/{{asset_id}}/refresh")
    async def refresh(asset_id: str, request: Request, body: RefreshBody) -> Response:
        try:
            result = application.refresh(
                identity_resolver(request),
                asset_id=asset_id,
                idempotency_key=_idempotency_key(request),
                trace_id=_trace_id(request),
                retry_of=body.retry_of,
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.post(f"{prefix}/refresh-runs/{{run_id}}/retry")
    async def retry_refresh(run_id: str, request: Request) -> Response:
        try:
            result = application.retry_refresh(
                identity_resolver(request),
                failed_run_id=run_id,
                idempotency_key=_idempotency_key(request),
                trace_id=_trace_id(request),
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.post(f"{prefix}/golden-assets/{{asset_id}}/refresh-cancel")
    async def cancel_refresh(asset_id: str, request: Request) -> Response:
        try:
            result = application.cancel_refresh(
                identity_resolver(request),
                asset_id=asset_id,
                idempotency_key=_idempotency_key(request),
                trace_id=_trace_id(request),
            )
        except SourcesGoldenError as error:
            return _error(error)
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    @app.delete(f"{prefix}/connections/{{connection_id}}")
    async def revoke_connection(
        connection_id: str,
        request: Request,
        body: RevokeBody,
    ) -> Response:
        try:
            application.revoke_connection(
                identity_resolver(request),
                connection_id,
                reason=body.reason,
                trace_id=_trace_id(request),
            )
        except SourcesGoldenError as error:
            return _error(error)
        return Response(status_code=204)


async def _store_upload(
    source_root: Path, workspace_id: str, upload: UploadFile
) -> dict[str, object]:
    suffix = Path(upload.filename or "").suffix.casefold()
    if suffix not in _UPLOAD_SUFFIXES:
        raise SourcesGoldenError(
            "UPLOAD_TYPE_UNSUPPORTED",
            "The uploaded source extension is not supported.",
        )
    source_root.mkdir(parents=True, exist_ok=True)
    workspace_segment = hashlib.sha256(workspace_id.encode()).hexdigest()[:24]
    workspace_root = source_root / f"workspace-{workspace_segment}"
    if workspace_root.is_symlink():
        raise SourcesGoldenError(
            "UPLOAD_PATH_UNSAFE",
            "The workspace upload directory is unsafe.",
        )
    workspace_root.mkdir(mode=0o700, exist_ok=True)
    temporary = workspace_root / f".upload-{uuid.uuid4().hex}.tmp"
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("xb") as handle:
            while chunk := await upload.read(64 * 1024):
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    raise SourcesGoldenError(
                        "UPLOAD_SIZE_LIMIT",
                        "The uploaded source exceeds the 10 MiB limit.",
                    )
                digest.update(chunk)
                handle.write(chunk)
        sha256 = digest.hexdigest()
        filename = f"{sha256}{suffix}"
        source_ref = f"{workspace_root.name}/{filename}"
        target = workspace_root / filename
        if target.is_symlink():
            raise SourcesGoldenError(
                "UPLOAD_PATH_UNSAFE",
                "The content-addressed upload target is unsafe.",
            )
        if target.exists():
            temporary.unlink()
        else:
            os.replace(temporary, target)
    finally:
        await upload.close()
        if temporary.exists():
            temporary.unlink()
    return {
        "sourceRef": source_ref,
        "mediaType": upload.content_type or "application/octet-stream",
        "bytes": size,
        "sha256": sha256,
    }


def _idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key")
    if not value or len(value) > 256:
        raise SourcesGoldenError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "A bounded Idempotency-Key header is required.",
        )
    return value


def _trace_id(request: Request) -> str:
    value = request.headers.get("X-Request-ID")
    return value[:256] if value else f"source-golden-{uuid.uuid4().hex}"


def _validate_uploaded_source_ownership(
    context: AccessContext, body: ConnectionCreateBody
) -> None:
    if body.connector_key not in {
        "csv",
        "excel",
        "json",
        "parquet",
        "doc_txt",
        "local_file",
        "sqlite",
        "openapi_spec",
        "webhook",
    }:
        return
    key = "specRef" if body.connector_key == "openapi_spec" else "sourceRef"
    if body.connector_key == "webhook":
        key = "schemaRef"
    source_ref = body.configuration.get(key)
    expected = (
        "workspace-" + hashlib.sha256(context.workspace_id.encode()).hexdigest()[:24]
    )
    parts = Path(source_ref).parts if isinstance(source_ref, str) else ()
    if (
        len(parts) != 2
        or parts[0] != expected
        or not _CONTENT_ADDRESSED_NAME.fullmatch(parts[1])
        or Path(parts[1]).suffix.casefold() not in _UPLOAD_SUFFIXES
    ):
        raise SourcesGoldenError(
            "UPLOAD_WORKSPACE_MISMATCH",
            "The uploaded source does not belong to the authenticated workspace.",
        )


def _connection_configuration(
    application: SourceGoldenApplication,
    body: ConnectionCreateBody,
) -> tuple[dict[str, object], str | None]:
    """Resolve browser-safe MCP references into server-owned configuration."""
    if body.connector_key != "mcp_custom":
        if body.mcp_profile_id is not None or body.tool_allowlist:
            raise SourcesGoldenError(
                "INVALID_CONNECTION",
                "MCP profile fields are only valid for the MCP connector.",
            )
        return body.configuration, body.secret_ref

    if body.secret_ref is not None:
        raise SourcesGoldenError(
            "MCP_BROWSER_CONFIGURATION_FORBIDDEN",
            "MCP credentials must be resolved by the selected server profile.",
        )
    if set(body.configuration) - {"profileId"}:
        raise SourcesGoldenError(
            "MCP_BROWSER_CONFIGURATION_FORBIDDEN",
            "MCP execution settings cannot be supplied by the browser.",
        )
    profile_from_configuration = body.configuration.get("profileId")
    profile_id = body.mcp_profile_id or (
        profile_from_configuration
        if isinstance(profile_from_configuration, str)
        else None
    )
    if not profile_id:
        raise SourcesGoldenError(
            "MCP_PROFILE_NOT_CONFIGURED",
            "A server-owned MCP profileId is required.",
        )
    return application.mcp_profile_configuration(profile_id, body.tool_allowlist), None


def _error(error: SourcesGoldenError) -> JSONResponse:
    if error.code in {
        "CONNECTION_NOT_FOUND",
        "GOLDEN_ASSET_NOT_FOUND",
        "GOLDEN_REVISION_NOT_FOUND",
        "SOURCE_REVISION_NOT_FOUND",
    }:
        status = 404
    elif error.code == "PERMISSION_DENIED":
        status = 403
    elif error.code in {"UPLOAD_SIZE_LIMIT"}:
        status = 413
    elif error.code.endswith("_NOT_READY"):
        status = 409
    else:
        status = 422
    return JSONResponse(
        {"code": error.code, "message": error.message},
        status_code=status,
        media_type="application/problem+json",
    )
