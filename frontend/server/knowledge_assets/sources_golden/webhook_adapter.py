"""Authenticated, schema-validated inbound Webhook connector."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from .adapters import _infer_mapping_fields
from .connector_adapter import ConnectorAdapterError
from .models import (
    CapabilityReason,
    ConnectorOperation,
    DiscoveredField,
    DiscoveredResource,
)

_LISTEN_PATH = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9/_-]{0,255}$")


@dataclass(frozen=True)
class WebhookReadResult:
    source_locator: str
    raw_content: bytes
    rows: list[dict[str, object]]
    fields: list[tuple[str, str, bool]]
    media_type: str
    adapter_run_id: str
    checkpoint: dict[str, str]


class WebhookAdapter:
    def __init__(
        self,
        *,
        source_root: Path,
        secret_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._root = source_root.resolve()
        self._secret_resolver = secret_resolver or (lambda _ref: None)

    def validate_configuration(self, configuration: Mapping[str, object]) -> None:
        self._listen_path(configuration)
        self._schema(configuration)
        _positive_integer(configuration, "maxEventBytes", 1_000_000, maximum=10_000_000)
        _positive_integer(configuration, "maxEvents", 10_000, maximum=1_000_000)
        _positive_integer(configuration, "rateLimitPerMinute", 60, maximum=10_000)

    def authenticate(self, secret_ref: str | None, *, workspace_id: str) -> None:
        if not secret_ref:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_REQUIRED",
                "Webhook HMAC secretRef is required.",
                stage="authenticate",
            )
        if not secret_ref.startswith(f"secret://{workspace_id}/"):
            raise ConnectorAdapterError(
                "INVALID_SECRET_REFERENCE",
                "secretRef must belong to the active workspace.",
                stage="authenticate",
            )
        self._secret(secret_ref)

    def discover(
        self,
        *,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        trace_id: str,
    ) -> ConnectorOperation:
        schema = self._schema(configuration)
        self._secret(secret_ref)
        properties = schema.get("properties")
        raw_required = schema.get("required")
        required = (
            {str(item) for item in raw_required}
            if isinstance(raw_required, list)
            else set()
        )
        fields = [
            DiscoveredField(
                name=str(name),
                data_type=str(value.get("type", "mixed"))
                if isinstance(value, dict)
                else "mixed",
                nullable=str(name) not in required,
            )
            for name, value in (
                properties.items() if isinstance(properties, dict) else ()
            )
        ]
        listen_path = self._listen_path(configuration)
        resource = DiscoveredResource(
            id=self.resource_id(listen_path),
            name=listen_path,
            resource_type="operation",
            row_count=0,
            fields=fields,
        )
        return ConnectorOperation(
            operation="discover",
            status="succeeded",
            trace_id=trace_id,
            reason=CapabilityReason(
                code="WEBHOOK_RECEIVER_READY",
                message="The signed webhook receiver is ready for schema-valid events.",
            ),
            resources=[resource],
        )

    def receive(
        self,
        *,
        configuration: Mapping[str, object],
        secret_ref: str | None,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[str, list[dict[str, object]]]:
        listen_path = self._listen_path(configuration)
        if path != listen_path:
            raise ConnectorAdapterError(
                "WEBHOOK_PATH_MISMATCH",
                "Webhook request path does not match the configured listener.",
                stage="authorize",
            )
        max_bytes = _positive_integer(
            configuration, "maxEventBytes", 1_000_000, maximum=10_000_000
        )
        if not body or len(body) > max_bytes:
            raise ConnectorAdapterError(
                "WEBHOOK_PAYLOAD_LIMIT",
                "Webhook payload is empty or exceeds the configured byte limit.",
                stage="read",
            )
        normalized_headers = {
            str(key).casefold(): str(value) for key, value in headers.items()
        }
        content_type = normalized_headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().casefold() != "application/json":
            raise ConnectorAdapterError(
                "WEBHOOK_CONTENT_TYPE_INVALID",
                "Webhook payload must use application/json.",
                stage="validate",
            )
        secret = self._secret(secret_ref)
        supplied = normalized_headers.get("x-webhook-signature", "")
        expected = (
            "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(supplied, expected):
            raise ConnectorAdapterError(
                "WEBHOOK_AUTHENTICATION_FAILED",
                "Webhook signature verification failed.",
                stage="authenticate",
            )
        delivery_id = normalized_headers.get("x-webhook-id", "").strip()
        if not delivery_id or len(delivery_id) > 256:
            raise ConnectorAdapterError(
                "WEBHOOK_DELIVERY_ID_REQUIRED",
                "Webhook requests require a bounded X-Webhook-Id.",
                stage="validate",
            )
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConnectorAdapterError(
                "WEBHOOK_JSON_INVALID",
                "Webhook payload is not valid UTF-8 JSON.",
                stage="validate",
            ) from error
        values = value if isinstance(value, list) else [value]
        max_events = _positive_integer(
            configuration, "maxEvents", 10_000, maximum=1_000_000
        )
        if len(values) > max_events or not all(
            isinstance(item, dict) for item in values
        ):
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_INVALID",
                "Webhook payload must be an object or bounded array of objects.",
                stage="validate",
            )
        schema = self._schema(configuration)
        validator = Draft202012Validator(schema)
        for item in values:
            errors = sorted(
                validator.iter_errors(item), key=lambda error: list(error.path)
            )
            if errors:
                raise ConnectorAdapterError(
                    "WEBHOOK_SCHEMA_INVALID",
                    f"Webhook payload does not match schema: {errors[0].message}",
                    stage="validate",
                )
        return delivery_id, [
            {str(key): item for key, item in row.items()} for row in values
        ]

    def read(
        self,
        *,
        configuration: Mapping[str, object],
        events: Sequence[tuple[int, object]],
        trace_id: str,
    ) -> WebhookReadResult:
        rows: list[dict[str, object]] = []
        last_sequence = 0
        for sequence, payload in events:
            last_sequence = max(last_sequence, sequence)
            values = payload if isinstance(payload, list) else [payload]
            if not all(isinstance(row, dict) for row in values):
                raise ConnectorAdapterError(
                    "WEBHOOK_EVENT_CORRUPT",
                    "Persisted webhook event is not a row object.",
                    stage="read",
                )
            for row in values:
                if not isinstance(row, dict):
                    raise ConnectorAdapterError(
                        "WEBHOOK_EVENT_CORRUPT",
                        "Persisted webhook event is not a row object.",
                        stage="read",
                    )
                rows.append({str(key): item for key, item in row.items()})
        if not rows:
            raise ConnectorAdapterError(
                "WEBHOOK_EVENT_REQUIRED",
                "No authenticated webhook event has been received.",
                stage="read",
                retryable=True,
            )
        max_events = _positive_integer(
            configuration, "maxEvents", 10_000, maximum=1_000_000
        )
        if len(rows) > max_events:
            raise ConnectorAdapterError(
                "WEBHOOK_EVENT_LIMIT",
                "Persisted webhook stream exceeds the configured event limit.",
                stage="read",
            )
        raw = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = hashlib.sha256(raw).hexdigest()
        return WebhookReadResult(
            source_locator=f"webhook://{self._listen_path(configuration)}",
            raw_content=raw,
            rows=rows,
            fields=_infer_mapping_fields(rows),
            media_type="application/json",
            adapter_run_id=f"webhook-run-{trace_id}-{digest[:12]}",
            checkpoint={
                "lastSequence": str(last_sequence),
                "contentDigest": digest,
            },
        )

    @staticmethod
    def resource_id(listen_path: str) -> str:
        return "webhook-stream-" + hashlib.sha256(listen_path.encode()).hexdigest()[:24]

    def _schema(self, configuration: Mapping[str, object]) -> dict[str, object]:
        schema_ref = configuration.get("schemaRef")
        if not isinstance(schema_ref, str) or not schema_ref:
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_REQUIRED",
                "Webhook schemaRef is required.",
                stage="validate",
            )
        unresolved = self._root / schema_ref
        if unresolved.is_symlink():
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_UNSAFE",
                "Webhook schemaRef must not be a symlink.",
                stage="validate",
            )
        path = unresolved.resolve()
        if path != self._root and self._root not in path.parents:
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_UNSAFE",
                "Webhook schemaRef escapes the configured source root.",
                stage="validate",
            )
        if not path.is_file() or path.suffix.casefold() != ".json":
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_REQUIRED",
                "Webhook schemaRef must identify a local JSON Schema file.",
                stage="validate",
            )
        if path.stat().st_size > 1_000_000:
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_LIMIT",
                "Webhook schema exceeds the configured byte limit.",
                stage="validate",
            )
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(schema, dict):
                raise TypeError
            Draft202012Validator.check_schema(schema)
        except Exception as error:
            raise ConnectorAdapterError(
                "WEBHOOK_SCHEMA_INVALID",
                "Webhook schemaRef does not contain a valid JSON Schema.",
                stage="validate",
            ) from error
        return {str(key): value for key, value in schema.items()}

    @staticmethod
    def _listen_path(configuration: Mapping[str, object]) -> str:
        value = configuration.get("listenPath")
        if (
            not isinstance(value, str)
            or not _LISTEN_PATH.fullmatch(value)
            or ".." in value
        ):
            raise ConnectorAdapterError(
                "WEBHOOK_PATH_INVALID",
                "Webhook listenPath must be a bounded absolute path.",
                stage="validate",
            )
        return value

    def _secret(self, secret_ref: str | None) -> str:
        if not secret_ref:
            raise ConnectorAdapterError(
                "WEBHOOK_CREDENTIAL_REQUIRED",
                "Webhook HMAC secretRef is required.",
                stage="authenticate",
            )
        value = self._secret_resolver(secret_ref)
        if value is None:
            raise ConnectorAdapterError(
                "WEBHOOK_CREDENTIAL_UNAVAILABLE",
                "Webhook HMAC secretRef could not be resolved.",
                stage="authenticate",
            )
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = value
        if isinstance(decoded, dict):
            decoded = decoded.get("hmacSecret")
        if not isinstance(decoded, str) or len(decoded) < 16:
            raise ConnectorAdapterError(
                "WEBHOOK_CREDENTIAL_INVALID",
                "Webhook secret must contain at least 16 characters.",
                stage="authenticate",
            )
        return decoded


def _positive_integer(
    configuration: Mapping[str, object],
    key: str,
    default: int,
    *,
    maximum: int,
) -> int:
    value = configuration.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise ConnectorAdapterError(
            "WEBHOOK_LIMIT_INVALID",
            f"Webhook {key} must be between 1 and {maximum}.",
            stage="validate",
        )
    return value
