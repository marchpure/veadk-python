"""Server-owned registry of the 37 executable connector adapters."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType

from .adapters import LocalSourceAdapter, validate_external_configuration
from .catalog import BUILTIN_CONNECTORS
from .connector_adapter import (
    ConnectorAdapter,
    ConnectorAdapterError,
    ConnectorCertification,
    ConnectorReadResult,
    ConnectorRequest,
    LifecycleConnectorAdapter,
    succeeded_operation,
    validate_configuration,
)
from .database_adapter import SqlDatabaseAdapter
from .http_adapters import HttpSourceAdapter
from .http_transport import SecureHttpTransport
from .lifecycle import LocalLifecycle, MaterializedSource
from .mcp_connector import McpConnectorAdapter
from .mcp_remote import RemoteMcpClient
from .mcp_stdio import StdioMcpClient
from .models import (
    ConnectionInstance,
    ConnectorDefinition,
    ConnectorOperation,
    McpProcessTrace,
    RemoteMcpTrace,
)
from .openapi_adapter import OpenApiAdapter
from .provider_adapters import (
    ExternalDatabaseAdapter,
    KafkaConnectorAdapter,
    LarkOfficeConnectorAdapter,
    ObjectStorageAdapter,
    lark_provider_spec,
    provider_specifications,
)
from .webhook_adapter import WebhookAdapter

_LOCAL_KEYS = frozenset(
    {"csv", "excel", "json", "parquet", "doc_txt", "local_file", "sqlite"}
)
_HTTP_KEYS = HttpSourceAdapter.CONNECTORS
_LARK_KEYS = frozenset(
    {
        "lark_doc",
        "lark_wiki",
        "lark_drive",
        "lark_meeting",
        "lark_minutes",
        "lark_group",
        "lark_chat",
        "lark_sheet",
        "lark_base",
        "lark_mail",
    }
)
_EXTERNAL_DATABASE_KEYS = frozenset(
    {
        "oracle",
        "sqlserver",
        "clickhouse",
        "doris",
        "starrocks",
        "snowflake",
        "bigquery",
        "hive",
    }
)
EXTERNAL_PROVIDER_KEYS = frozenset(
    {*_EXTERNAL_DATABASE_KEYS, "s3", "oss", "kafka", *_LARK_KEYS}
)


class LocalFileConnectorAdapter(LifecycleConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        adapter: LocalSourceAdapter,
        lifecycle: LocalLifecycle,
    ) -> None:
        self.definition = definition
        self.connector_keys = frozenset({definition.connector_key})
        self._adapter = adapter
        self._lifecycle = lifecycle

    @property
    def certification(self) -> ConnectorCertification:
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver="python-standard-library/server-parser",
            install_command="uv sync --all-extras",
            verification_command=(
                "python -m pytest -q tests/frontend -k step3b_connector"
            ),
            missing_condition="none",
            required_secret_fields=(),
            provider_scopes=(),
            checkpoint="content SHA-256 plus schema digest",
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        validate_configuration(self.definition, request.configuration)
        try:
            _path, operation = self._adapter.validate(
                connector_key=request.connector_key,
                configuration=dict(request.configuration),
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "SOURCE_VALIDATION_FAILED",
                str(error),
                stage="validate",
            ) from error
        return operation

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        try:
            path, _operation = self._adapter.validate(
                connector_key=request.connector_key,
                configuration=dict(request.configuration),
                trace_id=request.trace_id,
            )
            return self._adapter.discover(
                connector_key=request.connector_key,
                path=path,
                trace_id=request.trace_id,
                configuration=dict(request.configuration),
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "SOURCE_DISCOVERY_FAILED",
                str(error),
                stage="discover",
            ) from error

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        resource = request.resource
        if resource is None:
            resources = self.discover(request).resources
            if len(resources) != 1:
                raise ConnectorAdapterError(
                    "RESOURCE_REQUIRED",
                    "Select one discovered source resource.",
                    stage="read",
                )
            resource = resources[0]
        connection = ConnectionInstance(
            id=request.connection_id or f"adapter-{request.connector_key}",
            workspace_id=request.workspace_id,
            connector_key=request.connector_key,
            display_name=self.definition.name,
            scope="personal",
            owner_id=request.principal_id,
            status="ready",
            configuration=dict(request.configuration),
            secret_ref=request.secret_ref,
            sync_mode=self.definition.sync_modes[0],
            created_at="1970-01-01T00:00:00+00:00",
            updated_at="1970-01-01T00:00:00+00:00",
            discovered_resources=[resource],
        )
        try:
            materialized = self._lifecycle.materialize(connection, resource.id)
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "SOURCE_READ_FAILED",
                str(error),
                stage="read",
            ) from error
        return _connector_read_result(materialized, request.connector_key)


class SqlConnectorAdapter(LifecycleConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        adapter: SqlDatabaseAdapter,
    ) -> None:
        self.definition = definition
        self.connector_keys = frozenset({definition.connector_key})
        self._adapter = adapter

    @property
    def certification(self) -> ConnectorCertification:
        driver = (
            "psycopg2" if self.definition.connector_key == "postgresql" else "pymysql"
        )
        package = (
            "psycopg2-binary"
            if self.definition.connector_key == "postgresql"
            else "pymysql"
        )
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver=driver,
            install_command=f"uv pip install {package}",
            verification_command=f'python -c "import {driver}; print({driver}.__version__)"',
            missing_condition=(
                f"A reachable {self.definition.name} endpoint and read-only "
                "username/password secret are required."
            ),
            required_secret_fields=("username", "password"),
            provider_scopes=("schema.metadata.read", "table.data.read"),
            checkpoint="content digest plus selected table identity",
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        validate_configuration(self.definition, request.configuration)
        try:
            validate_external_configuration(
                self.definition,
                dict(request.configuration),
                web_resolver=None,
            )
        except (TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "DATABASE_CONFIGURATION_INVALID",
                str(error),
                stage="validate",
            ) from error
        return succeeded_operation(
            "validate",
            request,
            code="DATABASE_CONFIGURATION_VALIDATED",
            message="Database configuration passed read-only validation.",
        )

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        try:
            self._adapter.options(
                request.connector_key,
                request.configuration,
                request.secret_ref,
                workspace_id=request.workspace_id,
            )
        except ConnectorAdapterError:
            raise
        except PermissionError as error:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_UNAVAILABLE",
                str(error),
                stage="authenticate",
            ) from error
        except (TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "EXTERNAL_CREDENTIAL_INVALID",
                str(error),
                stage="authenticate",
            ) from error
        return succeeded_operation(
            "authenticate",
            request,
            code="DATABASE_CREDENTIAL_READY",
            message="Database credentials are available for a read-only session.",
        )

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.authenticate(request)
        try:
            return self._adapter.discover(
                connector_key=request.connector_key,
                configuration=request.configuration,
                secret_ref=request.secret_ref,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, PermissionError, TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "DATABASE_DISCOVERY_FAILED",
                str(error),
                stage="discover",
                retryable=isinstance(error, OSError),
            ) from error

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        if request.resource is None:
            raise ConnectorAdapterError(
                "DATABASE_RESOURCE_REQUIRED",
                "Select one discovered database table.",
                stage="read",
            )
        self.authenticate(request)
        try:
            result = self._adapter.read(
                connector_key=request.connector_key,
                configuration=request.configuration,
                secret_ref=request.secret_ref,
                resource=request.resource,
                parameters=request.arguments,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, PermissionError, TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "DATABASE_READ_FAILED",
                str(error),
                stage="read",
                retryable=isinstance(error, OSError),
            ) from error
        return ConnectorReadResult(source_type="database", **result.__dict__)


class HttpConnectorAdapter(LifecycleConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        adapter: HttpSourceAdapter,
        secret_resolver: Callable[[str], str | None],
        web_resolver: Callable[[str], list[str]] | None,
        allow_private_hosts: set[str],
    ) -> None:
        self.definition = definition
        self.connector_keys = frozenset({definition.connector_key})
        self._adapter = adapter
        self._secret_resolver = secret_resolver
        self._web_resolver = web_resolver
        self._allow_private_hosts = allow_private_hosts

    @property
    def certification(self) -> ConnectorCertification:
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver="httpx",
            install_command="uv pip install httpx",
            verification_command='python -c "import httpx; print(httpx.__version__)"',
            missing_condition="A reachable allowlisted HTTP endpoint is required.",
            required_secret_fields=(),
            provider_scopes=tuple(self.definition.permissions.provider_scopes),
            checkpoint="ETag and Last-Modified, with response digest lineage",
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        if request.connector_key == "custom_http" and request.configuration.get(
            "method"
        ) not in {None, "GET", "HEAD"}:
            raise ConnectorAdapterError(
                "HTTP_CONFIGURATION_INVALID",
                "Custom HTTP connector accepts read-only GET or HEAD requests.",
                stage="validate",
            )
        validate_configuration(self.definition, request.configuration)
        try:
            validate_external_configuration(
                self.definition,
                dict(request.configuration),
                web_resolver=self._web_resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
        except (TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "HTTP_CONFIGURATION_INVALID",
                str(error),
                stage="validate",
            ) from error
        return succeeded_operation(
            "validate",
            request,
            code="HTTP_CONFIGURATION_VALIDATED",
            message="HTTP configuration passed bounded network validation.",
        )

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        try:
            operation, _result = self._adapter.discover(
                connector_key=request.connector_key,
                configuration=request.configuration,
                secret_ref=request.secret_ref,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "HTTP_DISCOVERY_FAILED",
                str(error),
                stage="discover",
                retryable=isinstance(error, (OSError, TimeoutError)),
            ) from error
        return operation

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        if request.secret_ref:
            if not request.secret_ref.startswith(f"secret://{request.workspace_id}/"):
                raise ConnectorAdapterError(
                    "INVALID_SECRET_REFERENCE",
                    "secretRef must belong to the active workspace.",
                    stage="authenticate",
                )
            if self._secret_resolver(request.secret_ref) is None:
                raise ConnectorAdapterError(
                    "EXTERNAL_CREDENTIAL_UNAVAILABLE",
                    "HTTP authorization secretRef could not be resolved.",
                    stage="authenticate",
                )
        return succeeded_operation(
            "authenticate",
            request,
            code=(
                "HTTP_CREDENTIAL_READY"
                if request.secret_ref
                else "AUTHENTICATION_NOT_REQUIRED"
            ),
            message="HTTP authentication requirements are satisfied.",
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        try:
            result = self._adapter.read(
                connector_key=request.connector_key,
                configuration=request.configuration,
                secret_ref=request.secret_ref,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "HTTP_READ_FAILED",
                str(error),
                stage="read",
                retryable=isinstance(error, (OSError, TimeoutError)),
            ) from error
        return ConnectorReadResult(source_type="http", **result.__dict__)


class OpenApiConnectorAdapter(LifecycleConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        adapter: OpenApiAdapter,
    ) -> None:
        self.definition = definition
        self.connector_keys = frozenset({definition.connector_key})
        self._adapter = adapter

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        try:
            self._adapter.validate_credentials(
                request.secret_ref,
                workspace_id=request.workspace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            code = (
                "INVALID_SECRET_REFERENCE"
                if "active workspace" in str(error)
                else "EXTERNAL_CREDENTIAL_UNAVAILABLE"
                if "could not be resolved" in str(error)
                else "EXTERNAL_CREDENTIAL_INVALID"
            )
            raise ConnectorAdapterError(
                code,
                str(error),
                stage="authenticate",
            ) from error
        return succeeded_operation(
            "authenticate",
            request,
            code=(
                "OPENAPI_CREDENTIAL_READY"
                if request.secret_ref
                else "AUTHENTICATION_NOT_REQUIRED"
            ),
            message="OpenAPI authentication requirements are satisfied.",
        )

    @property
    def certification(self) -> ConnectorCertification:
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver="PyYAML/httpx",
            install_command="uv sync --all-extras",
            verification_command='python -c "import yaml, httpx; print(yaml.__version__)"',
            missing_condition="A readable OpenAPI file and reachable allowlisted server are required.",
            required_secret_fields=(),
            provider_scopes=(),
            checkpoint="ETag and Last-Modified, with response digest lineage",
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        validate_configuration(self.definition, request.configuration)
        try:
            self._adapter.discover(
                configuration=request.configuration,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "OPENAPI_CONFIGURATION_INVALID",
                str(error),
                stage="validate",
            ) from error
        return succeeded_operation(
            "validate",
            request,
            code="OPENAPI_SPEC_VALIDATED",
            message="OpenAPI definition and read-only operation allowlist are valid.",
        )

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        try:
            return self._adapter.discover(
                configuration=request.configuration,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "OPENAPI_DISCOVERY_FAILED",
                str(error),
                stage="discover",
            ) from error

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        if request.resource is None:
            raise ConnectorAdapterError(
                "OPENAPI_RESOURCE_REQUIRED",
                "Select one discovered OpenAPI operation.",
                stage="read",
            )
        try:
            result = self._adapter.read(
                configuration=request.configuration,
                secret_ref=request.secret_ref,
                resource_id=request.resource.id,
                trace_id=request.trace_id,
            )
        except ConnectorAdapterError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise ConnectorAdapterError(
                "OPENAPI_READ_FAILED",
                str(error),
                stage="read",
            ) from error
        return ConnectorReadResult(source_type="http", **result.__dict__)


class WebhookConnectorAdapter(LifecycleConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        adapter: WebhookAdapter,
    ) -> None:
        self.definition = definition
        self.connector_keys = frozenset({definition.connector_key})
        self._adapter = adapter

    @property
    def certification(self) -> ConnectorCertification:
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver="ASGI inbound HTTP/HMAC-SHA256",
            install_command="uv sync --all-extras",
            verification_command=(
                "python -m pytest -q tests/frontend -k 'step3b_connector and webhook'"
            ),
            missing_condition="A workspace HMAC secretRef is required.",
            required_secret_fields=("hmacSecret",),
            provider_scopes=("webhook.deliver",),
            checkpoint="last durable event sequence plus content digest",
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        validate_configuration(self.definition, request.configuration)
        self._adapter.validate_configuration(request.configuration)
        return succeeded_operation(
            "validate",
            request,
            code="WEBHOOK_CONFIGURATION_VALIDATED",
            message="Webhook listener and JSON Schema are valid.",
        )

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        self._adapter.authenticate(
            request.secret_ref, workspace_id=request.workspace_id
        )
        return succeeded_operation(
            "authenticate",
            request,
            code="WEBHOOK_CREDENTIAL_READY",
            message="Webhook HMAC secret is available.",
        )

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        return self._adapter.discover(
            configuration=request.configuration,
            secret_ref=request.secret_ref,
            trace_id=request.trace_id,
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        arguments = request.arguments or {}
        raw_events = arguments.get("events", [])
        if not isinstance(raw_events, Sequence):
            raise ConnectorAdapterError(
                "WEBHOOK_EVENT_INVALID",
                "Webhook read events must be a sequence.",
                stage="read",
            )
        events: list[tuple[int, object]] = []
        for event in raw_events:
            if (
                not isinstance(event, Sequence)
                or isinstance(event, (str, bytes))
                or len(event) != 2
                or isinstance(event[0], bool)
                or not isinstance(event[0], int)
            ):
                raise ConnectorAdapterError(
                    "WEBHOOK_EVENT_INVALID",
                    "Webhook read events must contain sequence/payload pairs.",
                    stage="read",
                )
            events.append((event[0], event[1]))
        result = self._adapter.read(
            configuration=request.configuration,
            events=events,
            trace_id=request.trace_id,
        )
        return ConnectorReadResult(source_type="http", **result.__dict__)


def build_connector_registry(
    *,
    local_adapter: LocalSourceAdapter,
    lifecycle: LocalLifecycle,
    database_adapter: SqlDatabaseAdapter,
    http_adapter: HttpSourceAdapter,
    openapi_adapter: OpenApiAdapter,
    webhook_adapter: WebhookAdapter,
    stdio_mcp_client: StdioMcpClient,
    remote_mcp_client: RemoteMcpClient,
    secret_resolver: Callable[[str], str | None],
    http_transport: SecureHttpTransport,
    web_resolver: Callable[[str], list[str]] | None,
    allow_private_hosts: set[str],
    save_stdio_trace: Callable[[McpProcessTrace], None],
    save_remote_trace: Callable[[RemoteMcpTrace], None],
) -> Mapping[str, ConnectorAdapter]:
    definitions = {item.connector_key: item for item in BUILTIN_CONNECTORS}
    specs = provider_specifications()
    adapters: dict[str, ConnectorAdapter] = {}
    for key in _LOCAL_KEYS:
        adapters[key] = LocalFileConnectorAdapter(
            definition=definitions[key],
            adapter=local_adapter,
            lifecycle=lifecycle,
        )
    for key in SqlDatabaseAdapter.CONNECTORS:
        adapters[key] = SqlConnectorAdapter(
            definition=definitions[key],
            adapter=database_adapter,
        )
    for key in _HTTP_KEYS:
        adapters[key] = HttpConnectorAdapter(
            definition=definitions[key],
            adapter=http_adapter,
            secret_resolver=secret_resolver,
            web_resolver=web_resolver,
            allow_private_hosts=allow_private_hosts,
        )
    adapters["openapi_spec"] = OpenApiConnectorAdapter(
        definition=definitions["openapi_spec"],
        adapter=openapi_adapter,
    )
    adapters["webhook"] = WebhookConnectorAdapter(
        definition=definitions["webhook"],
        adapter=webhook_adapter,
    )
    adapters["mcp_custom"] = McpConnectorAdapter(
        definition=definitions["mcp_custom"],
        stdio=stdio_mcp_client,
        remote=remote_mcp_client,
        web_resolver=web_resolver,
        allow_private_hosts=allow_private_hosts,
        save_stdio_trace=save_stdio_trace,
        save_remote_trace=save_remote_trace,
    )
    for key in _EXTERNAL_DATABASE_KEYS:
        adapters[key] = ExternalDatabaseAdapter(
            definition=definitions[key],
            spec=specs[key],
            secret_resolver=secret_resolver,
            resolver=web_resolver,
            allow_private_hosts=allow_private_hosts,
        )
    for key in ("s3", "oss"):
        adapters[key] = ObjectStorageAdapter(
            definition=definitions[key],
            spec=specs[key],
            secret_resolver=secret_resolver,
            resolver=web_resolver,
            allow_private_hosts=allow_private_hosts,
        )
    adapters["kafka"] = KafkaConnectorAdapter(
        definition=definitions["kafka"],
        spec=specs["kafka"],
        secret_resolver=secret_resolver,
        resolver=web_resolver,
        allow_private_hosts=allow_private_hosts,
    )
    for key in _LARK_KEYS:
        adapters[key] = LarkOfficeConnectorAdapter(
            definition=definitions[key],
            spec=lark_provider_spec(key),
            secret_resolver=secret_resolver,
            transport=http_transport,
        )
    expected = set(definitions)
    if set(adapters) != expected:
        missing = sorted(expected - set(adapters))
        extra = sorted(set(adapters) - expected)
        raise RuntimeError(
            f"connector registry mismatch; missing={missing}, extra={extra}"
        )
    return MappingProxyType(adapters)


def _connector_read_result(
    materialized: MaterializedSource, connector_key: str
) -> ConnectorReadResult:
    digest = hashlib.sha256(materialized.raw_content).hexdigest()
    return ConnectorReadResult(
        source_type=materialized.source_type,
        source_locator=materialized.source_locator,
        raw_content=materialized.raw_content,
        rows=materialized.rows,
        fields=materialized.fields,
        media_type=materialized.media_type,
        adapter_run_id=materialized.adapter_run_id
        or f"{connector_key}-run-{digest[:24]}",
        checkpoint=materialized.checkpoint or {"contentDigest": digest},
    )
