"""Local OpenAPI definition adapter with allowlisted, server-side HTTP reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import yaml

from .adapters import _infer_mapping_fields
from .http_transport import (
    SecureHttpTransport,
    decode_json_rows,
    response_run_id,
)
from .models import (
    CapabilityReason,
    ConnectorOperation,
    DiscoveredResource,
)


@dataclass(frozen=True)
class OpenApiReadResult:
    source_locator: str
    raw_content: bytes
    rows: list[dict[str, object]]
    fields: list[tuple[str, str, bool]]
    media_type: str
    adapter_run_id: str
    checkpoint: dict[str, str]


class OpenApiAdapter:
    def __init__(
        self,
        *,
        source_root: Path,
        http_transport: SecureHttpTransport,
        secret_resolver: Callable[[str], str | None] | None = None,
        max_spec_bytes: int = 2 * 1024 * 1024,
        max_spec_depth: int = 64,
        max_spec_nodes: int = 100_000,
    ) -> None:
        self._source_root = source_root.resolve()
        self._http = http_transport
        self._secret_resolver = secret_resolver or (lambda _ref: None)
        self._max_spec_bytes = max_spec_bytes
        self._max_spec_depth = max_spec_depth
        self._max_spec_nodes = max_spec_nodes

    def discover(
        self,
        *,
        configuration: Mapping[str, object],
        trace_id: str,
    ) -> ConnectorOperation:
        document = self._document(configuration)
        operations = self._operations(document, configuration)
        resources = [
            DiscoveredResource(
                id=self._resource_id(operation_id),
                name=operation_id,
                resource_type="operation",
                input_schema=input_schema,
                output_schema=output_schema,
            )
            for operation_id, _method, _url, input_schema, output_schema in operations
        ]
        return ConnectorOperation(
            operation="discover",
            status="succeeded",
            trace_id=trace_id,
            reason=CapabilityReason(
                code="OPENAPI_OPERATIONS_DISCOVERED",
                message="Allowlisted read-only OpenAPI operations were discovered.",
            ),
            resources=resources,
        )

    def read(
        self,
        *,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        resource_id: str,
        trace_id: str,
    ) -> OpenApiReadResult:
        document = self._document(configuration)
        operations = self._operations(document, configuration)
        selected = next(
            (
                operation
                for operation in operations
                if self._resource_id(operation[0]) == resource_id
            ),
            None,
        )
        if selected is None:
            raise ValueError("OpenAPI operation was not discovered by this connection")
        operation_id, method, url, _input_schema, _output_schema = selected
        payload = self._http.request(
            method=method,
            url=url,
            trace_id=trace_id,
            timeout_seconds=float(_integer(configuration, "timeoutSeconds", 30)),
            max_response_bytes=_integer(
                configuration, "maxResponseBytes", 5 * 1024 * 1024
            ),
            rate_limit_per_minute=_integer(configuration, "rateLimitPerMinute", 60),
            accepted_media_types={
                "application/json",
                "application/problem+json",
                "*+json",
            },
            headers=self._authorization_headers(secret_ref),
        )
        rows = decode_json_rows(
            payload,
            max_rows=_integer(configuration, "maxRows", 10_000),
        )
        return OpenApiReadResult(
            source_locator=f"openapi://operation/{operation_id}",
            raw_content=payload.content,
            rows=rows,
            fields=_infer_mapping_fields(rows),
            media_type=payload.media_type,
            adapter_run_id=response_run_id(payload),
            checkpoint={
                key: value
                for key, value in payload.headers.items()
                if key in {"etag", "last-modified"}
            },
        )

    def _spec_path(self, configuration: Mapping[str, object]) -> Path:
        source_ref = configuration.get("specRef")
        if not isinstance(source_ref, str) or not source_ref:
            raise ValueError("OpenAPI specRef is required")
        unresolved = self._source_root / source_ref
        if unresolved.is_symlink():
            raise ValueError("OpenAPI spec symlinks are not allowed")
        path = unresolved.resolve()
        if path != self._source_root and self._source_root not in path.parents:
            raise ValueError("OpenAPI spec escapes the configured workspace root")
        if path.suffix.casefold() not in {".json", ".yaml", ".yml"}:
            raise ValueError("OpenAPI spec must be JSON or YAML")
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size > self._max_spec_bytes:
            raise ValueError("OpenAPI spec exceeds the configured byte limit")
        return path

    def _document(self, configuration: Mapping[str, object]) -> dict[str, object]:
        path = self._spec_path(configuration)
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as error:
            raise ValueError("OpenAPI spec is invalid") from error
        _validate_document_complexity(
            value,
            max_depth=self._max_spec_depth,
            max_nodes=self._max_spec_nodes,
        )
        if not isinstance(value, dict):
            raise TypeError("OpenAPI spec root must be an object")
        version = value.get("openapi") or value.get("swagger")
        if not isinstance(version, str) or not (
            version.startswith("3.") or version == "2.0"
        ):
            raise ValueError("OpenAPI spec version is not supported")
        if not isinstance(value.get("paths"), dict):
            raise TypeError("OpenAPI spec paths must be an object")
        return {str(key): item for key, item in value.items()}

    def _operations(
        self,
        document: Mapping[str, object],
        configuration: Mapping[str, object],
    ) -> list[tuple[str, str, str, dict[str, object] | None, dict[str, object] | None]]:
        raw_allowlist = configuration.get("operationAllowlist")
        if (
            not isinstance(raw_allowlist, list)
            or not raw_allowlist
            or not all(isinstance(item, str) and item for item in raw_allowlist)
        ):
            raise ValueError("OpenAPI operation allowlist must not be empty")
        allowlist = set(raw_allowlist)
        base_url = configuration.get("serverUrl")
        if not isinstance(base_url, str) or not base_url:
            servers = document.get("servers")
            first_server = (
                servers[0]
                if isinstance(servers, list)
                and servers
                and isinstance(servers[0], dict)
                else None
            )
            base_url = (
                first_server.get("url") if isinstance(first_server, dict) else None
            )
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("OpenAPI spec requires an absolute server URL")
        paths = document["paths"]
        assert isinstance(paths, dict)
        found: dict[
            str,
            tuple[str, str, str, dict[str, object] | None, dict[str, object] | None],
        ] = {}
        mutating: set[str] = set()
        for raw_path, path_item in paths.items():
            if (
                not isinstance(raw_path, str)
                or not raw_path.startswith("/")
                or "://" in raw_path
                or not isinstance(path_item, dict)
            ):
                raise ValueError("OpenAPI path is invalid")
            for raw_method, operation in path_item.items():
                method = str(raw_method).upper()
                if method not in {
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                    "TRACE",
                } or not isinstance(operation, dict):
                    continue
                operation_id = operation.get("operationId")
                if not isinstance(operation_id, str) or not operation_id:
                    continue
                if operation_id not in allowlist:
                    continue
                if method not in {"GET", "HEAD"}:
                    mutating.add(operation_id)
                    continue
                responses = operation.get("responses")
                output_schema = _response_schema(responses)
                input_schema = _parameter_schema(operation.get("parameters"))
                found[operation_id] = (
                    operation_id,
                    method,
                    urljoin(base_url.rstrip("/") + "/", raw_path.lstrip("/")),
                    input_schema,
                    output_schema,
                )
        if mutating:
            raise ValueError(
                f"OpenAPI connector is read-only; mutating operations are forbidden: {sorted(mutating)}"
            )
        missing = allowlist - set(found)
        if missing:
            raise ValueError(
                f"OpenAPI operation allowlist contains unknown operations: {sorted(missing)}"
            )
        return [found[operation_id] for operation_id in raw_allowlist]

    @staticmethod
    def _resource_id(operation_id: str) -> str:
        return (
            "openapi-operation-"
            + hashlib.sha256(operation_id.encode()).hexdigest()[:24]
        )

    def _authorization_headers(self, secret_ref: str | None) -> dict[str, str]:
        if secret_ref is None:
            return {}
        value = self._secret_resolver(secret_ref)
        if value is None:
            raise PermissionError("OpenAPI secretRef could not be resolved")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"Authorization": f"Bearer {value}"}
        if not isinstance(decoded, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in decoded.items()
        ):
            raise ValueError("OpenAPI secret must contain a string header map")
        return {str(key): str(item) for key, item in decoded.items()}

    def validate_credentials(
        self, secret_ref: str | None, *, workspace_id: str
    ) -> None:
        if secret_ref is None:
            return
        if not secret_ref.startswith(f"secret://{workspace_id}/"):
            raise ValueError("OpenAPI secretRef must belong to the active workspace")
        self._authorization_headers(secret_ref)


def _integer(configuration: Mapping[str, object], key: str, default: int) -> int:
    value = configuration.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"OpenAPI {key} must be a positive integer")
    return value


def _validate_document_complexity(
    value: object, *, max_depth: int, max_nodes: int
) -> None:
    pending = [(value, 1)]
    seen_containers: set[int] = set()
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > max_nodes:
            raise ValueError("OpenAPI spec exceeds the configured node limit")
        if depth > max_depth:
            raise ValueError("OpenAPI spec exceeds the configured nesting depth")
        if not isinstance(current, (dict, list)):
            continue
        identity = id(current)
        if identity in seen_containers:
            raise ValueError("OpenAPI spec aliases or cycles are not allowed")
        seen_containers.add(identity)
        children = current.values() if isinstance(current, dict) else current
        pending.extend((child, depth + 1) for child in children)


def _parameter_schema(value: object) -> dict[str, object] | None:
    if not isinstance(value, list):
        return None
    properties: dict[str, object] = {}
    required: list[str] = []
    for parameter in value:
        if not isinstance(parameter, dict) or not isinstance(
            parameter.get("name"), str
        ):
            continue
        properties[str(parameter["name"])] = parameter.get("schema", {})
        if parameter.get("required") is True:
            required.append(str(parameter["name"]))
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _response_schema(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    response = value.get("200") or value.get("2XX") or value.get("default")
    if not isinstance(response, dict):
        return None
    content = response.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    schema = media.get("schema")
    return (
        {str(key): item for key, item in schema.items()}
        if isinstance(schema, dict)
        else None
    )
