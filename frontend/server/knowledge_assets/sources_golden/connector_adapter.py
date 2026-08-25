"""Shared connector SPI, typed failures, and lifecycle stage vocabulary."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from pydantic import JsonValue

from .models import (
    CapabilityReason,
    ConnectorDefinition,
    ConnectorOperation,
    DiscoveredResource,
    SourceType,
)

ConnectorStage = Literal[
    "validate",
    "authenticate",
    "authorize",
    "discover",
    "introspect",
    "sample",
    "read",
    "ingest",
    "profile",
    "clean",
    "golden",
    "refresh",
    "checkpoint",
    "close",
]
_T = TypeVar("_T")


class ConnectorAdapterError(RuntimeError):
    """Stable, safe error crossing the adapter/application boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: ConnectorStage,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.retryable = retryable


def call_typed(
    operation: Callable[[], _T],
    *,
    code: str,
    message: str,
    stage: ConnectorStage,
    retryable: bool = False,
) -> _T:
    """Run an adapter boundary and convert ordinary runtime failures."""
    try:
        return operation()
    except ConnectorAdapterError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        raise ConnectorAdapterError(
            code,
            message,
            stage=stage,
            retryable=retryable,
        ) from error


@dataclass(frozen=True)
class ConnectorReadResult:
    source_type: SourceType
    source_locator: str
    raw_content: bytes
    rows: list[dict[str, object]]
    fields: list[tuple[str, str, bool]]
    media_type: str
    adapter_run_id: str
    checkpoint: dict[str, str]


@dataclass
class ConnectorReadCache:
    """Operation-scoped cache that prevents repeated provider reads."""

    result: ConnectorReadResult | None = None

    def load(self, operation: Callable[[], object]) -> ConnectorReadResult:
        if self.result is None:
            result = operation()
            if not isinstance(result, ConnectorReadResult):
                raise ConnectorAdapterError(
                    "CONNECTOR_RESULT_INVALID",
                    "The connector adapter returned an invalid read result.",
                    stage="read",
                )
            self.result = result
        return self.result


@dataclass(frozen=True)
class ConnectorExecutionPolicy:
    """Uniform execution controls supplied to every adapter operation."""

    timeout_seconds: float = 30
    max_pages: int = 10
    max_attempts: int = 1
    freshness_seconds: int = 3_600
    cancelled: Callable[[], bool] = field(
        default=lambda: False,
        compare=False,
        repr=False,
    )
    _deadline: float = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("Connector timeout must be positive.")
        if self.max_pages < 1 or self.max_attempts < 1 or self.freshness_seconds < 1:
            raise ValueError("Connector execution limits must be positive.")
        object.__setattr__(
            self,
            "_deadline",
            time.monotonic() + self.timeout_seconds,
        )

    def ensure_active(self, stage: ConnectorStage) -> None:
        if stage != "close" and self.cancelled():
            raise ConnectorAdapterError(
                "CONNECTOR_CANCELLED",
                "The connector operation was cancelled.",
                stage=stage,
            )
        if stage != "close" and time.monotonic() >= self._deadline:
            raise ConnectorAdapterError(
                "CONNECTOR_TIMEOUT",
                "The connector operation exceeded its total execution timeout.",
                stage=stage,
                retryable=True,
            )

    def run(self, stage: ConnectorStage, operation: Callable[[], _T]) -> _T:
        """Run one stage with cooperative cancellation, deadline, and retry."""
        for attempt in range(1, self.max_attempts + 1):
            self.ensure_active(stage)
            try:
                result = operation()
            except ConnectorAdapterError as error:
                if not error.retryable or attempt >= self.max_attempts:
                    raise
                self.ensure_active(stage)
                continue
            self.ensure_active(stage)
            return result
        raise AssertionError("positive max_attempts must execute at least once")


@dataclass(frozen=True)
class ConnectorRequest:
    connector_key: str
    workspace_id: str
    principal_id: str
    configuration: Mapping[str, JsonValue]
    secret_ref: str | None
    trace_id: str
    connection_id: str | None = None
    resource: DiscoveredResource | None = None
    discovered_resources: tuple[DiscoveredResource, ...] = ()
    arguments: Mapping[str, object] | None = None
    execution: ConnectorExecutionPolicy = field(
        default_factory=ConnectorExecutionPolicy,
        compare=False,
        repr=False,
    )
    read_cache: ConnectorReadCache = field(
        default_factory=ConnectorReadCache,
        compare=False,
        repr=False,
    )


class ConnectorAdapter(ABC):
    """Uniform runtime boundary implemented by every catalog connector.

    Provider-specific adapters may stop at authentication when credentials or
    an official driver are unavailable, but every lifecycle method remains a
    real callable contract and must fail with :class:`ConnectorAdapterError`.
    """

    connector_keys: frozenset[str]

    @property
    @abstractmethod
    def certification(self) -> ConnectorCertification:
        raise NotImplementedError

    @abstractmethod
    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def authorize(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def introspect(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def sample(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        raise NotImplementedError

    @abstractmethod
    def ingest(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def profile(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def clean(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def golden(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError

    @abstractmethod
    def refresh(self, request: ConnectorRequest) -> ConnectorReadResult:
        raise NotImplementedError

    @abstractmethod
    def checkpoint(self, request: ConnectorRequest) -> Mapping[str, str]:
        raise NotImplementedError

    @abstractmethod
    def close(self, request: ConnectorRequest) -> ConnectorOperation:
        raise NotImplementedError


class LifecycleConnectorAdapter(ConnectorAdapter):
    """Deep default lifecycle for adapters whose core operations are read-only.

    Concrete adapters implement validation, discovery, and bounded reads.  The
    remaining stages deliberately execute through those primitives so every
    catalog connector has one callable lifecycle rather than a metadata-only
    placeholder.
    """

    definition: ConnectorDefinition

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        return succeeded_operation(
            "authenticate",
            request,
            code="AUTHENTICATION_NOT_REQUIRED",
            message=f"{self.definition.name} does not require provider authentication.",
        )

    def authorize(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        return succeeded_operation(
            "authorize",
            request,
            code="SOURCE_READ_AUTHORIZED",
            message=f"{self.definition.name} read access is authorized.",
        )

    def introspect(self, request: ConnectorRequest) -> ConnectorOperation:
        if not request.discovered_resources:
            return self.discover(request).model_copy(update={"operation": "introspect"})
        return succeeded_operation(
            "introspect",
            request,
            code="SOURCE_SCHEMA_INTROSPECTED",
            message=f"{self.definition.name} resource metadata was introspected.",
            resources=list(request.discovered_resources),
        )

    def sample(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._read_stage("sample", request)

    def ingest(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._read_stage("ingest", request)

    def profile(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._read_stage("profile", request)

    def clean(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._read_stage("clean", request)

    def golden(self, request: ConnectorRequest) -> ConnectorOperation:
        request.read_cache.load(lambda: self.read(request))
        return self._read_stage("golden", request)

    def refresh(self, request: ConnectorRequest) -> ConnectorReadResult:
        return request.read_cache.load(lambda: self.read(request))

    def checkpoint(self, request: ConnectorRequest) -> Mapping[str, str]:
        result = request.read_cache.load(lambda: self.read(request))
        checkpoint = getattr(result, "checkpoint", None)
        if not isinstance(checkpoint, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in checkpoint.items()
        ):
            raise ConnectorAdapterError(
                "CHECKPOINT_UNAVAILABLE",
                f"{self.definition.name} did not return a valid checkpoint.",
                stage="checkpoint",
            )
        return dict(checkpoint)

    def close(self, request: ConnectorRequest) -> ConnectorOperation:
        return succeeded_operation(
            "close",
            request,
            code="CONNECTOR_CLOSED",
            message=f"{self.definition.name} released its operation resources.",
        )

    def _read_stage(
        self, stage: ConnectorStage, request: ConnectorRequest
    ) -> ConnectorOperation:
        return succeeded_operation(
            stage,
            request,
            code="CONNECTOR_STAGE_SUCCEEDED",
            message=f"{self.definition.name} completed the {stage} stage.",
            resources=[request.resource] if request.resource else [],
        )


@dataclass(frozen=True)
class ConnectorCertification:
    connector_key: str
    implementation: str
    driver: str
    install_command: str
    verification_command: str
    missing_condition: str
    required_secret_fields: tuple[str, ...]
    provider_scopes: tuple[str, ...]
    checkpoint: str
    supports_live_execution: bool = True


def succeeded_operation(
    stage: ConnectorStage,
    request: ConnectorRequest,
    *,
    code: str,
    message: str,
    resources: list[DiscoveredResource] | None = None,
) -> ConnectorOperation:
    request.execution.ensure_active(stage)
    return ConnectorOperation(
        operation=stage,
        status="succeeded",
        trace_id=request.trace_id,
        reason=CapabilityReason(code=code, message=message),
        resources=resources or [],
    )


def validate_configuration(
    definition: ConnectorDefinition,
    configuration: Mapping[str, object],
) -> None:
    properties = definition.input_schema.properties
    unknown = set(configuration) - set(properties)
    if unknown:
        raise ConnectorAdapterError(
            "INVALID_CONFIGURATION",
            f"Fields are not valid for {definition.connector_key}: {sorted(unknown)}",
            stage="validate",
        )
    missing = [
        key
        for key in definition.input_schema.required
        if configuration.get(key) in (None, "", [])
    ]
    if missing:
        raise ConnectorAdapterError(
            "INVALID_CONFIGURATION",
            f"Required fields are missing: {missing}",
            stage="validate",
        )
    max_attempts = configuration.get("maxAttempts", 1)
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 5
    ):
        raise ConnectorAdapterError(
            "INVALID_CONFIGURATION",
            "maxAttempts must be an integer between 1 and 5.",
            stage="validate",
        )
    for key, value in configuration.items():
        field = properties[key]
        valid = (
            field.type in {"string", "file", "url"}
            and isinstance(value, str)
            or field.type == "integer"
            and isinstance(value, int)
            and not isinstance(value, bool)
            or field.type == "number"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            or field.type == "boolean"
            and isinstance(value, bool)
            or field.type == "select"
            and isinstance(value, str)
            and (not field.options or value in field.options)
            or field.type == "string_array"
            and isinstance(value, list)
            and all(isinstance(item, str) and item for item in value)
            or field.type == "object"
            and isinstance(value, dict)
        )
        if not valid:
            raise ConnectorAdapterError(
                "INVALID_CONFIGURATION",
                f"Field {key} has an invalid {field.type} value.",
                stage="validate",
            )
