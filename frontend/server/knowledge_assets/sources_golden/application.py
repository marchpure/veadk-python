"""Public façade for the Worker 1 source and Golden Data domain."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue

from .adapters import LocalSourceAdapter, adapter_contract
from .catalog import (
    BUILTIN_CONNECTORS,
    bootstrap_connector_catalog,
    connector_catalog,
)
from .connector_adapter import (
    ConnectorAdapter,
    ConnectorAdapterError,
    ConnectorExecutionPolicy,
    ConnectorReadResult,
    ConnectorRequest,
    succeeded_operation,
)
from .connector_registry import build_connector_registry
from .database_adapter import DatabaseReadResult, SqlDatabaseAdapter
from .http_adapters import HttpReadResult, HttpSourceAdapter
from .http_transport import SecureHttpTransport
from .lifecycle import ContentAddressedArtifactStore, LocalLifecycle, MaterializedSource
from .mcp_remote import RemoteMcpClient, RemoteMcpError
from .mcp_stdio import (
    McpCallResult,
    McpProcessError,
    McpProcessStartError,
    StdioMcpClient,
)
from .models import (
    AccessContext,
    AdapterContract,
    AddDataView,
    CapabilityReason,
    CleaningOperation,
    ConnectionDetailView,
    ConnectionInstance,
    ConnectionStatus,
    ConnectionViewModel,
    ConnectorCapabilityEvidence,
    ConnectorCapabilityMatrix,
    ConnectorCapabilityRow,
    ConnectorCatalogView,
    ConnectorCategory,
    ConnectorCertificationView,
    ConnectorEventRecord,
    ConnectorOperation,
    ConnectorOperationName,
    CreateConnectionResult,
    DataOverviewView,
    GoldenAssetDetailView,
    GoldenAssetSummary,
    GoldenContextReference,
    GoldenDataView,
    GoldenOverview,
    GoldenResourceBinding,
    IngestLifecycleResult,
    OperationStatus,
    RefreshResult,
    RefreshRunRecord,
    RemoteMcpConfiguration,
    StdioMcpConfiguration,
)
from .openapi_adapter import OpenApiAdapter
from .repository import SourcesGoldenRepository
from .webhook_adapter import WebhookAdapter, WebhookReadResult


class SourcesGoldenError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _object_mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _positive_int(value: object, default: int) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else default
    )


def _positive_float(value: object, default: float) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        else default
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceGoldenApplication:
    """Small public surface; persistence and adapters stay behind this façade."""

    def __init__(
        self,
        *,
        database_path: str | Path,
        artifact_root: str | Path,
        source_root: str | Path,
        web_resolver=None,
        secret_resolver=None,
        mcp_profiles: dict[str, dict[str, object]] | None = None,
        network_allow_private_hosts: set[str] | None = None,
        http_transport=None,
    ) -> None:
        self.database_path = Path(database_path)
        self.artifact_root = Path(artifact_root)
        self.source_root = Path(source_root).resolve()
        self.repository = SourcesGoldenRepository(database_path)
        self._local_adapter = LocalSourceAdapter(root=self.source_root)
        self._artifact_store = ContentAddressedArtifactStore(self.artifact_root)
        self._lifecycle = LocalLifecycle(
            source_root=self.source_root,
            artifact_store=self._artifact_store,
        )
        self._web_resolver = web_resolver
        self._network_allow_private_hosts = set(network_allow_private_hosts or ())
        self._provider_execution_enabled = secret_resolver is not None
        self._secret_resolver = secret_resolver or (lambda _ref: None)
        self._http_transport = SecureHttpTransport(
            resolver=web_resolver,
            allow_private_hosts=network_allow_private_hosts,
            transport=http_transport,
        )
        self._openapi_adapter = OpenApiAdapter(
            source_root=self.source_root,
            http_transport=self._http_transport,
            secret_resolver=self._secret_resolver,
        )
        self._http_adapter = HttpSourceAdapter(
            transport=self._http_transport,
            secret_resolver=self._secret_resolver,
        )
        self._database_adapter = SqlDatabaseAdapter(
            secret_resolver=self._secret_resolver,
            resolver=web_resolver,
            allow_private_hosts=self._network_allow_private_hosts,
        )
        self._webhook_adapter = WebhookAdapter(
            source_root=self.source_root,
            secret_resolver=self._secret_resolver,
        )
        self._mcp_client = StdioMcpClient(secret_resolver=secret_resolver)
        self._remote_mcp_client = RemoteMcpClient(
            secret_resolver=self._secret_resolver,
            resolver=web_resolver,
            allow_private_hosts=self._network_allow_private_hosts,
            transport=http_transport,
        )
        self._connector_registry = build_connector_registry(
            local_adapter=self._local_adapter,
            lifecycle=self._lifecycle,
            database_adapter=self._database_adapter,
            http_adapter=self._http_adapter,
            openapi_adapter=self._openapi_adapter,
            webhook_adapter=self._webhook_adapter,
            stdio_mcp_client=self._mcp_client,
            remote_mcp_client=self._remote_mcp_client,
            secret_resolver=self._secret_resolver,
            http_transport=self._http_transport,
            web_resolver=self._web_resolver,
            allow_private_hosts=self._network_allow_private_hosts,
            save_stdio_trace=self.repository.save_mcp_trace,
            save_remote_trace=self.repository.save_connector_trace,
        )
        self._mcp_profiles = {
            str(key): dict(value) for key, value in (mcp_profiles or {}).items()
        }

    def mcp_profile_configuration(
        self, profile_id: str, requested_tools: list[str]
    ) -> dict[str, object]:
        profile = self._mcp_profiles.get(profile_id)
        if profile is None:
            raise SourcesGoldenError(
                "MCP_PROFILE_NOT_CONFIGURED",
                "指定的 MCP server profile 未由服务端配置。",
            )
        raw_tools = profile.get("toolAllowlist", [])
        if not isinstance(raw_tools, list):
            raise SourcesGoldenError(
                "MCP_PROFILE_INVALID",
                "MCP server profile toolAllowlist must be a list.",
            )
        configured_tools = [str(item) for item in raw_tools]
        if requested_tools and not set(requested_tools).issubset(set(configured_tools)):
            raise SourcesGoldenError(
                "MCP_TOOL_NOT_ALLOWED",
                "请求的 MCP tool 不在服务端 profile allowlist 中。",
            )
        configuration = {
            key: value
            for key, value in profile.items()
            if key not in {"profileId", "label"}
        }
        configuration["toolAllowlist"] = requested_tools or configured_tools
        try:
            if configuration.get("transport") == "stdio":
                StdioMcpConfiguration.model_validate(configuration)
            elif configuration.get("transport") in {"streamable_http", "sse"}:
                RemoteMcpConfiguration.model_validate(configuration)
            else:
                raise ValueError("MCP server profile transport is unsupported.")
        except (TypeError, ValueError) as error:
            raise SourcesGoldenError(
                "MCP_PROFILE_INVALID",
                "MCP server profile is incomplete or invalid for its transport.",
            ) from error
        return configuration

    def mcp_profile_catalog(self) -> list[dict[str, object]]:
        """Expose selectable MCP metadata without exposing execution fields."""
        profiles: list[dict[str, object]] = []
        for profile_id, profile in sorted(self._mcp_profiles.items()):
            raw_tools = profile.get("toolAllowlist", [])
            if not isinstance(raw_tools, list):
                raw_tools = []
            profiles.append(
                {
                    "profileId": profile_id,
                    "label": str(profile.get("label") or profile_id),
                    "transport": str(profile.get("transport") or "stdio"),
                    "toolAllowlist": [str(item) for item in raw_tools],
                }
            )
        return profiles

    def mcp_tool_configurations(
        self,
        context: AccessContext,
        revision_ids: list[str],
    ) -> list[dict[str, object]]:
        """Return server-owned stdio configurations for authorized Golden refs.

        This is a read-only composition seam for MAIN's Agent/Runner adapter.
        The browser cannot provide any of these execution fields; they originate
        from a registered profile and are checked against the persisted,
        authorized Golden revision.
        """
        configurations: list[dict[str, object]] = []
        seen: set[str] = set()
        for revision_id in revision_ids:
            revision = self.golden_revision(context, revision_id)
            connection = self._connection_for_context(
                context, revision.lineage.connection_id
            )
            if connection.connector_key != "mcp_custom":
                continue
            if connection.status != "ready":
                raise SourcesGoldenError(
                    "MCP_CONNECTION_NOT_READY",
                    "The pinned MCP connection is not ready.",
                )
            if connection.id in seen:
                continue
            configuration = dict(connection.configuration)
            required = {"command", "args", "cwd"}
            if not required.issubset(configuration):
                raise SourcesGoldenError(
                    "MCP_PROFILE_INVALID",
                    "The persisted MCP connection lacks server-owned stdio fields.",
                )
            if not isinstance(configuration["command"], str) or not isinstance(
                configuration["args"], list
            ):
                raise SourcesGoldenError(
                    "MCP_PROFILE_INVALID",
                    "The persisted MCP stdio configuration has invalid types.",
                )
            configurations.append(
                {str(key): value for key, value in configuration.items()}
            )
            seen.add(connection.id)
        return configurations

    def golden_asset_content(
        self,
        context: AccessContext,
        revision_id: str,
    ) -> bytes:
        """Read an authorized Golden revision through the owned artifact store."""
        revision = self.golden_revision(context, revision_id)
        try:
            return self._artifact_store.read(
                type(revision.storage_ref).model_validate(
                    revision.storage_ref.model_dump(mode="json")
                )
            )
        except (OSError, ValueError) as error:
            raise SourcesGoldenError(
                "GOLDEN_CONTENT_UNAVAILABLE",
                "The authorized Golden revision content is unavailable.",
            ) from error

    def connector_catalog(
        self,
        context: AccessContext,
        *,
        category: ConnectorCategory | None = None,
        query: str | None = None,
    ) -> ConnectorCatalogView:
        del context
        return connector_catalog(category=category, query=query)

    def connector_adapters(self) -> Mapping[str, ConnectorAdapter]:
        """Return the immutable server registry used for all 37 catalog keys."""
        return self._connector_registry

    def connector_capability_matrix(self) -> ConnectorCapabilityMatrix:
        """Return one auditable row for each registered catalog connector."""
        locally_verified = {
            "csv",
            "excel",
            "json",
            "parquet",
            "doc_txt",
            "local_file",
            "sqlite",
            "postgresql",
            "mysql",
            "rest_api",
            "graphql",
            "web_discovery",
            "webhook",
            "mcp_custom",
            "custom_http",
            "openapi_spec",
        }
        evidence_by_connector = _connector_evidence_index()
        rows = []
        for definition in BUILTIN_CONNECTORS:
            certification = self._connector_registry[
                definition.connector_key
            ].certification
            external_blocked = definition.connector_key not in locally_verified
            rows.append(
                ConnectorCapabilityRow(
                    connector_key=definition.connector_key,
                    category=definition.category,
                    capability_state=definition.capability_state,
                    permissions=definition.permissions,
                    certification=ConnectorCertificationView(
                        implementation=certification.implementation,
                        driver=certification.driver,
                        install_command=certification.install_command,
                        verification_command=certification.verification_command,
                        missing_condition=certification.missing_condition,
                        required_secret_fields=list(
                            certification.required_secret_fields
                        ),
                        provider_scopes=list(certification.provider_scopes),
                        checkpoint=certification.checkpoint,
                    ),
                    capability=ConnectorCapabilityEvidence(
                        adapter=certification.implementation,
                        checkpoint=certification.checkpoint,
                        live_e2e=("external_blocked" if external_blocked else "passed"),
                        credential_state=(
                            "external_blocked"
                            if external_blocked
                            else "available"
                            if definition.connector_key
                            in {"postgresql", "mysql", "webhook"}
                            else "not_required"
                        ),
                        blocker=(
                            (
                                "No live credential or official provider sandbox "
                                f"was supplied for {definition.connector_key}."
                            )
                            if external_blocked
                            else None
                        ),
                        evidence=evidence_by_connector[definition.connector_key],
                    ),
                )
            )
        return ConnectorCapabilityMatrix(connectors=rows)

    def add_data(
        self, context: AccessContext, *, connector_key: str | None = None
    ) -> AddDataView:
        catalog = self.connector_catalog(context)
        selected = (
            self._definition(connector_key) if connector_key is not None else None
        )
        return AddDataView(
            catalog=catalog,
            selected_connector=selected,
            steps=["configure", "authorize", "discover", "save"],
            can_create=context.role in {"editor", "admin"},
            blocked_reason=(
                selected.reason
                if selected
                and selected.capability_state in {"credential_blocked", "unsupported"}
                else None
            ),
        )

    def bootstrap_projection(self, context: AccessContext) -> dict[str, object]:
        overview = self.data_overview(context)
        return {
            "routes": ["data_overview", "add_data", "connector_catalog"],
            "connections": [
                connection.model_dump(mode="json", by_alias=True)
                for connection in overview.connections
            ],
            "resources": [
                asset.model_dump(mode="json", by_alias=True)
                for asset in overview.golden_assets
            ],
            "workspaceData": {
                "connectorCatalog": bootstrap_connector_catalog(),
                "mcpProfileCatalog": self.mcp_profile_catalog(),
            },
        }

    def create_connection(
        self,
        context: AccessContext,
        *,
        connector_key: str,
        display_name: str,
        scope: Literal["personal", "team"],
        configuration: dict[str, object],
        secret_ref: str | None,
        idempotency_key: str,
        trace_id: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> CreateConnectionResult:
        self._require_write(context)
        if scope not in {"personal", "team"} or not display_name.strip():
            raise SourcesGoldenError(
                "INVALID_CONNECTION",
                "Connection name and scope must be valid.",
            )
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        existing = self.repository.connection_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if existing is not None:
            operation = self._operation_for_existing(existing, trace_id)
            return CreateConnectionResult(
                connection=self._connection_view(existing),
                validation=operation,
                discovery=operation.model_copy(update={"operation": "discover"}),
                replayed=True,
            )
        definition = self._definition(connector_key)
        self._validate_form(
            definition,
            configuration,
            secret_ref,
            workspace_id=context.workspace_id,
        )
        timestamp = _now()
        public_configuration = self._public_configuration(configuration)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "workspace": context.workspace_id,
                    "principal": context.principal_id,
                    "connector": connector_key,
                    "idempotency": idempotency_key,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        connection_id = f"connection-{digest[:24]}"
        (
            validation,
            discovery,
            last_error,
            create_operations,
        ) = self._create_adapter_operations(
            adapter=self._connector_registry[connector_key],
            context=context,
            connection_id=connection_id,
            connector_key=connector_key,
            configuration=public_configuration,
            secret_ref=secret_ref,
            trace_id=trace_id,
            cancelled=cancelled,
        )
        status = "credential_blocked" if last_error is not None else "ready"
        last_success_at = None if last_error is not None else timestamp
        connection = ConnectionInstance(
            id=connection_id,
            workspace_id=context.workspace_id,
            connector_key=connector_key,
            display_name=display_name.strip(),
            scope=scope,
            owner_id=context.principal_id,
            status=status,
            configuration=public_configuration,
            secret_ref=secret_ref,
            sync_mode=definition.sync_modes[0],
            created_at=timestamp,
            updated_at=timestamp,
            last_success_at=last_success_at,
            last_error=last_error,
            discovered_resources=discovery.resources,
        )
        self.repository.save_connection(
            connection, idempotency_key=scoped_idempotency_key
        )
        for operation in create_operations:
            self.repository.record_operation(
                workspace_id=context.workspace_id,
                connection_id=connection.id,
                trace_id=trace_id,
                operation=operation.operation,
                status=operation.status,
                payload=operation.model_dump(mode="json", by_alias=True),
                created_at=timestamp,
            )
        return CreateConnectionResult(
            connection=self._connection_view(connection),
            validation=validation,
            discovery=discovery,
        )

    def _create_adapter_operations(
        self,
        *,
        adapter: ConnectorAdapter,
        context: AccessContext,
        connection_id: str,
        connector_key: str,
        configuration: dict[str, JsonValue],
        secret_ref: str | None,
        trace_id: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[
        ConnectorOperation,
        ConnectorOperation,
        CapabilityReason | None,
        tuple[ConnectorOperation, ...],
    ]:
        request = self._adapter_request(
            adapter=adapter,
            context=context,
            connection_id=connection_id,
            connector_key=connector_key,
            configuration=configuration,
            secret_ref=secret_ref,
            trace_id=trace_id,
            cancelled=cancelled,
        )
        completed: list[ConnectorOperation] = []
        try:
            validation = request.execution.run(
                "validate", lambda: adapter.validate(request)
            )
            completed.append(validation)
            completed.append(
                request.execution.run(
                    "authenticate", lambda: adapter.authenticate(request)
                )
            )
            completed.append(
                request.execution.run("authorize", lambda: adapter.authorize(request))
            )
            discovery = request.execution.run(
                "discover", lambda: adapter.discover(request)
            )
            completed.append(discovery)
            introspection_request = ConnectorRequest(
                connector_key=request.connector_key,
                workspace_id=request.workspace_id,
                principal_id=request.principal_id,
                configuration=request.configuration,
                secret_ref=request.secret_ref,
                trace_id=request.trace_id,
                connection_id=request.connection_id,
                discovered_resources=tuple(discovery.resources),
                execution=request.execution,
            )
            completed.append(
                request.execution.run(
                    "introspect", lambda: adapter.introspect(introspection_request)
                )
            )
        except ConnectorAdapterError as error:
            if error.code not in {
                "EXTERNAL_CREDENTIAL_REQUIRED",
                "EXTERNAL_CREDENTIAL_UNAVAILABLE",
                "EXTERNAL_DRIVER_UNAVAILABLE",
                "WEBHOOK_CREDENTIAL_REQUIRED",
                "WEBHOOK_CREDENTIAL_UNAVAILABLE",
            }:
                try:
                    request.execution.run("close", lambda: adapter.close(request))
                except ConnectorAdapterError:
                    pass
                raise SourcesGoldenError(error.code, error.message) from error
            reason = CapabilityReason(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            )
            completed_names = {operation.operation for operation in completed}
            blocked = tuple(
                ConnectorOperation(
                    operation=operation,
                    status="credential_blocked",
                    trace_id=trace_id,
                    reason=reason,
                )
                for operation in (
                    "authenticate",
                    "authorize",
                    "discover",
                    "introspect",
                    "sample",
                )
                if operation not in completed_names
            )
            closed = request.execution.run("close", lambda: adapter.close(request))
            operations = (*completed, *blocked, closed)
            validation = next(
                operation
                for operation in operations
                if operation.operation == "validate"
            )
            discovery = next(
                operation
                for operation in operations
                if operation.operation == "discover"
            )
            return (
                validation,
                discovery,
                reason,
                operations,
            )
        closed = request.execution.run("close", lambda: adapter.close(request))
        completed.append(closed)
        return (
            validation,
            discovery,
            None,
            tuple(completed),
        )

    @staticmethod
    def _adapter_request(
        *,
        adapter: ConnectorAdapter,
        context: AccessContext,
        connection_id: str | None,
        connector_key: str,
        configuration: Mapping[str, JsonValue],
        secret_ref: str | None,
        trace_id: str,
        resource=None,
        arguments: Mapping[str, object] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ConnectorRequest:
        if connector_key not in adapter.connector_keys:
            raise SourcesGoldenError(
                "CONNECTOR_ADAPTER_MISMATCH",
                "The registered adapter does not own this connector.",
            )
        return ConnectorRequest(
            connector_key=connector_key,
            workspace_id=context.workspace_id,
            principal_id=context.principal_id,
            connection_id=connection_id,
            configuration=configuration,
            secret_ref=secret_ref,
            trace_id=trace_id,
            resource=resource,
            arguments=arguments,
            execution=ConnectorExecutionPolicy(
                timeout_seconds=_positive_float(
                    configuration.get("timeoutSeconds", 30),
                    30,
                ),
                max_pages=_positive_int(configuration.get("maxPages", 10), 10),
                max_attempts=_positive_int(
                    configuration.get("maxAttempts", 1),
                    1,
                ),
                freshness_seconds=_positive_int(
                    configuration.get("refreshSeconds", 3_600),
                    3_600,
                ),
                cancelled=cancelled or (lambda: False),
            ),
        )

    def _create_stdio_mcp_operations(
        self,
        *,
        context: AccessContext,
        connection_id: str,
        configuration: dict[str, object],
        trace_id: str,
    ):
        from .models import ConnectorOperation, DiscoveredResource

        try:
            tools, trace = self._mcp_client.discover(
                workspace_id=context.workspace_id,
                principal_id=context.principal_id,
                connection_id=connection_id,
                configuration=configuration,
                trace_id=trace_id,
            )
            self.repository.save_mcp_trace(trace)
        except ValueError as error:
            raise SourcesGoldenError(
                "MCP_CONFIGURATION_INVALID",
                "stdio MCP configuration is invalid.",
            ) from error
        except McpProcessStartError as error:
            raise SourcesGoldenError(error.code, str(error)) from error
        except McpProcessError as error:
            self.repository.save_mcp_trace(error.trace)
            raise SourcesGoldenError(error.code, str(error)) from error
        resources = []
        for tool in tools:
            if not tool.get("name"):
                continue
            resources.append(
                DiscoveredResource(
                    id="mcp-tool-"
                    + hashlib.sha256(str(tool["name"]).encode()).hexdigest()[:24],
                    name=str(tool["name"]),
                    resource_type="tool",
                    input_schema=_object_mapping(tool.get("inputSchema")),
                    output_schema=_object_mapping(tool.get("outputSchema")),
                )
            )
        reason = CapabilityReason(
            code="MCP_STDIO_READY",
            message="Independent MCP subprocess initialized and tools were discovered.",
        )
        return (
            ConnectorOperation(
                operation="validate",
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
            ),
            ConnectorOperation(
                operation="discover",
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
                resources=resources,
            ),
        )

    def _create_remote_mcp_operations(
        self,
        *,
        context: AccessContext,
        connection_id: str,
        configuration: dict[str, object],
        secret_ref: str | None,
        trace_id: str,
    ):
        from .models import DiscoveredResource

        try:
            tools, trace = self._remote_mcp_client.discover(
                workspace_id=context.workspace_id,
                principal_id=context.principal_id,
                connection_id=connection_id,
                configuration=configuration,
                secret_ref=secret_ref,
                trace_id=trace_id,
            )
            self.repository.save_connector_trace(trace)
        except ValueError as error:
            raise SourcesGoldenError(
                "MCP_CONFIGURATION_INVALID",
                "Remote MCP configuration is invalid.",
            ) from error
        except RemoteMcpError as error:
            self.repository.save_connector_trace(error.trace)
            raise SourcesGoldenError(error.code, str(error)) from error
        resources = [
            DiscoveredResource(
                id="mcp-tool-"
                + hashlib.sha256(str(tool["name"]).encode()).hexdigest()[:24],
                name=str(tool["name"]),
                resource_type="tool",
                input_schema=_object_mapping(tool.get("inputSchema")),
                output_schema=_object_mapping(tool.get("outputSchema")),
            )
            for tool in tools
            if tool.get("name")
        ]
        reason = CapabilityReason(
            code="MCP_REMOTE_READY",
            message="Remote MCP initialized and allowlisted tools were discovered.",
        )
        return (
            ConnectorOperation(
                operation="validate",
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
            ),
            ConnectorOperation(
                operation="discover",
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
                resources=resources,
            ),
        )

    def data_overview(self, context: AccessContext) -> DataOverviewView:
        connections = [
            connection
            for connection in self.repository.connections(context.workspace_id)
            if self._can_access_connection(context, connection)
        ]
        by_id = {connection.id: connection for connection in connections}
        golden_assets = [
            GoldenAssetSummary(
                asset_id=revision.asset_id,
                golden_revision_id=revision.id,
                revision=revision.revision,
                display_name=(
                    next(
                        (
                            resource.name
                            for resource in by_id[
                                revision.lineage.connection_id
                            ].discovered_resources
                            if resource.id == revision.lineage.resource_id
                        ),
                        by_id[revision.lineage.connection_id].display_name,
                    )
                ),
                asset_kind=revision.asset_kind,
                connector_key=by_id[revision.lineage.connection_id].connector_key,
                quality_score=revision.quality_score,
                freshness_at=revision.freshness_at,
                owner=revision.owner,
                permissions=revision.permissions,
                trace_id=revision.trace_id,
            )
            for revision in self.repository.latest_golden_assets(context.workspace_id)
            if revision.lineage.connection_id in by_id
        ]
        revisions_by_connection: dict[str, list[str]] = {}
        for revision in self.repository.latest_golden_assets(context.workspace_id):
            if revision.lineage.connection_id in by_id:
                revisions_by_connection.setdefault(
                    revision.lineage.connection_id, []
                ).append(revision.id)
        connections = [
            connection.model_copy(
                update={
                    "golden_revision_ids": revisions_by_connection.get(
                        connection.id, []
                    )
                }
            )
            for connection in connections
        ]
        return DataOverviewView(
            workspace_id=context.workspace_id,
            connections=[
                self._connection_view(connection) for connection in connections
            ],
            golden_assets=golden_assets,
            can_create=context.role in {"editor", "admin"},
            empty_state=None if connections else "no_connections",
        )

    def connection_detail(
        self, context: AccessContext, connection_id: str
    ) -> ConnectionDetailView:
        connection = self._connection_for_context(context, connection_id)
        actions = ["read"]
        if context.role in {"editor", "admin"}:
            actions.extend(["refresh", "delete", "revoke"])
        return ConnectionDetailView(
            connection=self._connection_view(connection),
            connector=self._definition(connection.connector_key),
            actions=actions,
        )

    def adapter_contract(self, connector_key: str) -> AdapterContract:
        return adapter_contract(self._definition(connector_key))

    def ingest(
        self,
        context: AccessContext,
        *,
        connection_id: str,
        resource_id: str | None,
        recipe_operations: list[CleaningOperation],
        tool_arguments: dict[str, object] | None = None,
        idempotency_key: str,
        trace_id: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> IngestLifecycleResult:
        self._require_write(context)
        connection = self._connection_for_context(context, connection_id)
        self._validate_tool_arguments(tool_arguments or {})
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        replay = self.repository.ingest_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if replay is not None:
            return IngestLifecycleResult(
                status="succeeded",
                source_revision=replay[0],
                profile_run=replay[1],
                cleaning_recipe=replay[2],
                clean_run=replay[3],
                golden_asset_revision=replay[4],
                replayed=True,
            )
        if connection.status != "ready":
            raise SourcesGoldenError(
                "CONNECTION_NOT_READY",
                "A blocked connection cannot produce source revisions.",
            )
        if resource_id is None and len(connection.discovered_resources) == 1:
            resource_id = connection.discovered_resources[0].id
        if not resource_id:
            raise SourcesGoldenError(
                "RESOURCE_REQUIRED",
                "Select one discovered source resource.",
            )
        asset_id = (
            "golden-"
            + hashlib.sha256(f"{connection.id}:{resource_id}".encode()).hexdigest()[:24]
        )
        timestamp = _now()
        adapter = self._connector_registry[connection.connector_key]
        resource = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == resource_id
            ),
            None,
        )
        if resource is None:
            raise SourcesGoldenError(
                "RESOURCE_NOT_FOUND",
                "The selected resource was not discovered by this connection.",
            )
        arguments: Mapping[str, object] | None = tool_arguments
        if connection.connector_key == "webhook":
            events = self.repository.events(
                context.workspace_id,
                connection.id,
                event_type="webhook.delivery.accepted",
            )
            arguments = {
                "events": [(event.sequence, event.payload) for event in events]
            }
        elif connection.connector_key in SqlDatabaseAdapter.CONNECTORS:
            configured_parameters = connection.configuration.get("queryParameters")
            arguments = (
                configured_parameters
                if isinstance(configured_parameters, Mapping)
                else None
            )
        request = self._adapter_request(
            adapter=adapter,
            context=context,
            connection_id=connection.id,
            connector_key=connection.connector_key,
            configuration=connection.configuration,
            secret_ref=connection.secret_ref,
            trace_id=trace_id,
            resource=resource,
            arguments=arguments,
            cancelled=cancelled,
        )
        adapter_operations: list[ConnectorOperation] = []
        try:
            adapter_operations.append(
                request.execution.run(
                    "authenticate", lambda: adapter.authenticate(request)
                )
            )
            adapter_operations.append(
                request.execution.run("authorize", lambda: adapter.authorize(request))
            )
            adapter_operations.append(
                request.execution.run("sample", lambda: adapter.sample(request))
            )
            read = request.read_cache.load(
                lambda: request.execution.run("read", lambda: adapter.read(request))
            )
            adapter_operations.append(
                succeeded_operation(
                    "read",
                    request,
                    code="CONNECTOR_READ_SUCCEEDED",
                    message="The connector returned a bounded source revision.",
                    resources=[resource],
                )
            )
            adapter_operations.append(
                request.execution.run("ingest", lambda: adapter.ingest(request))
            )
            materialized = self._materialized_connector_result(read)
            records = self._lifecycle.build(
                connection=connection,
                resource_id=resource_id,
                operations=recipe_operations,
                recipe_version=self.repository.next_recipe_version(asset_id),
                golden_revision=self.repository.next_golden_revision(
                    context.workspace_id, asset_id
                ),
                principal_id=context.principal_id,
                trace_id=trace_id,
                timestamp=timestamp,
                materialized=materialized,
                tool_arguments=tool_arguments,
            )
            adapter_operations.extend(
                [
                    request.execution.run("profile", lambda: adapter.profile(request)),
                    request.execution.run("clean", lambda: adapter.clean(request)),
                    request.execution.run("golden", lambda: adapter.golden(request)),
                ]
            )
            checkpoint = dict(
                request.execution.run("checkpoint", lambda: adapter.checkpoint(request))
            )
            adapter_operations.append(
                succeeded_operation(
                    "checkpoint",
                    request,
                    code="CONNECTOR_CHECKPOINT_PERSISTED",
                    message="The connector checkpoint is ready to persist.",
                )
            )
            adapter_operations.append(
                request.execution.run("close", lambda: adapter.close(request))
            )
        except (
            ConnectorAdapterError,
            RemoteMcpError,
            McpProcessError,
            McpProcessStartError,
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            self._record_adapter_failure(
                connection=connection,
                adapter=adapter,
                request=request,
                completed=adapter_operations,
                error=error,
                timestamp=timestamp,
            )
            raise SourcesGoldenError(
                getattr(error, "code", "SOURCE_INGEST_FAILED"), str(error)
            ) from error
        self.repository.save_ingest(
            source=records.source,
            profile=records.profile,
            recipe=records.recipe,
            clean=records.clean,
            golden=records.golden,
            idempotency_key=scoped_idempotency_key,
        )
        self._record_adapter_operations(
            connection=connection,
            operations=adapter_operations,
            timestamp=timestamp,
            checkpoint=checkpoint,
        )
        return IngestLifecycleResult(
            status="succeeded",
            source_revision=records.source,
            profile_run=records.profile,
            cleaning_recipe=records.recipe,
            clean_run=records.clean,
            golden_asset_revision=records.golden,
        )

    def golden_data(self, context: AccessContext, revision_id: str) -> GoldenDataView:
        revision = self.golden_revision(context, revision_id)
        rows = [
            json.loads(line)
            for line in self._artifact_store.read(revision.storage_ref)
            .decode("utf-8")
            .splitlines()
            if line.strip()
        ]
        return GoldenDataView(
            binding=self.golden_resource_binding(context, revision_id),
            rows=rows,
        )

    def golden_resource_binding(
        self, context: AccessContext, revision_id: str
    ) -> GoldenResourceBinding:
        revision = self.golden_revision(context, revision_id)
        source = self.source_revision(context, revision.lineage.source_revision_id)
        profile = self.repository.profile_run(revision.lineage.profile_run_id)
        connection = self._connection_for_context(
            context, revision.lineage.connection_id
        )
        if profile is None:
            raise SourcesGoldenError(
                "LIFECYCLE_NOT_FOUND",
                "Golden Asset profile is unavailable.",
            )
        resource = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == revision.lineage.resource_id
            ),
            None,
        )
        return GoldenResourceBinding(
            object_id=revision.asset_id,
            revision=revision.id,
            provider_revision=source.id,
            display_name=(resource.name if resource else connection.display_name),
            scope=connection.scope,
            schema_digest=revision.schema_digest,
            content_digest=revision.lineage.content_digest,
            semantic_fields=[field.name for field in profile.fields],
            capabilities=[
                "source.read",
                "golden_data.read",
                "lineage.read",
                "freshness.read",
            ],
            freshness_at=revision.freshness_at,
            data_as_of=revision.data_as_of,
            lineage=revision.lineage,
            permissions=revision.permissions,
            authorized=True,
        )

    def resolve_context_reference(
        self,
        context: AccessContext,
        reference: GoldenContextReference,
        *,
        max_age_seconds: int | None = None,
        as_of: datetime | None = None,
    ) -> GoldenResourceBinding:
        """Re-authorize an immutable browser reference before Agent use."""
        if reference.revision.casefold() in {"latest", "current", "head", "draft"}:
            raise SourcesGoldenError(
                "MUTABLE_CONTEXT_REFERENCE",
                "Agent context must pin an immutable Golden revision.",
            )
        binding = self.golden_resource_binding(context, reference.revision)
        if binding.object_id != reference.object_id:
            raise SourcesGoldenError(
                "CONTEXT_OBJECT_MISMATCH",
                "Golden context object and revision do not match.",
            )
        if binding.provider_revision != reference.provider_revision:
            raise SourcesGoldenError(
                "CONTEXT_PROVIDER_REVISION_MISMATCH",
                "Golden context provider revision does not match.",
            )
        if max_age_seconds is not None:
            if isinstance(max_age_seconds, bool) or max_age_seconds < 0:
                raise SourcesGoldenError(
                    "CONTEXT_FRESHNESS_INVALID",
                    "Context max age must be a non-negative integer.",
                )
            resolved_as_of = as_of or datetime.now(timezone.utc)
            if resolved_as_of.tzinfo is None:
                resolved_as_of = resolved_as_of.replace(tzinfo=timezone.utc)
            freshness_at = datetime.fromisoformat(binding.freshness_at)
            if freshness_at.tzinfo is None:
                freshness_at = freshness_at.replace(tzinfo=timezone.utc)
            if freshness_at + timedelta(seconds=max_age_seconds) < resolved_as_of:
                raise SourcesGoldenError(
                    "CONTEXT_REVISION_EXPIRED",
                    "The pinned Golden revision is older than the allowed context age.",
                )
        return binding

    def golden_asset_detail(
        self, context: AccessContext, asset_id: str
    ) -> GoldenAssetDetailView:
        asset = self.repository.latest_golden(context.workspace_id, asset_id)
        if asset is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, asset.lineage.connection_id)
        profile = self.repository.profile_run(asset.lineage.profile_run_id)
        clean = self.repository.clean_run(asset.lineage.clean_run_id)
        if profile is None or clean is None:
            raise SourcesGoldenError(
                "LIFECYCLE_NOT_FOUND",
                "Golden Asset profile or clean run is unavailable.",
            )
        quality_report = json.loads(self._artifact_store.read(clean.quality_report_ref))
        preview: list[dict[str, object]] = []
        for line in (
            self._artifact_store.read(asset.storage_ref).decode("utf-8").splitlines()
        ):
            if not line.strip():
                continue
            value: object = json.loads(line)
            if isinstance(value, dict):
                preview.append({str(key): item for key, item in value.items()})
            if len(preview) == 100:
                break
        safe_preview: list[dict[str, object]] = [
            {
                key: (
                    "[REDACTED]"
                    if key in profile.sensitive_fields and value not in (None, "")
                    else value
                )
                for key, value in row.items()
            }
            for row in preview
        ]
        return GoldenAssetDetailView(
            asset=asset,
            overview=GoldenOverview(
                row_count=int(quality_report["outputRows"]),
                field_count=len(profile.fields),
                storage_bytes=asset.storage_ref.bytes,
                quality_score=asset.quality_score,
                freshness_at=asset.freshness_at,
            ),
            preview=safe_preview,
            fields=profile.fields,
            profile=profile,
            lineage=asset.lineage,
            owner=asset.owner,
            permissions=asset.permissions,
            tabs=[
                "overview",
                "preview",
                "fields",
                "lineage",
                "quality",
                "usage",
            ],
        )

    def golden_revision(self, context: AccessContext, revision_id: str):
        revision = self.repository.golden_revision(context.workspace_id, revision_id)
        if revision is None:
            raise SourcesGoldenError(
                "GOLDEN_REVISION_NOT_FOUND",
                "Golden revision does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, revision.lineage.connection_id)
        return revision

    def source_revision(self, context: AccessContext, revision_id: str):
        revision = self.repository.source_revision(context.workspace_id, revision_id)
        if revision is None:
            raise SourcesGoldenError(
                "SOURCE_REVISION_NOT_FOUND",
                "Source revision does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, revision.connection_id)
        return revision

    def refresh(
        self,
        context: AccessContext,
        *,
        asset_id: str,
        idempotency_key: str,
        trace_id: str,
        retry_of: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> RefreshResult:
        self._require_write(context)
        previous = self.repository.latest_golden(context.workspace_id, asset_id)
        if previous is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        connection = self._connection_for_context(
            context, previous.lineage.connection_id
        )
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        replay = self.repository.refresh_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if replay is not None:
            promoted = (
                self.repository.golden_revision_including_revoked(
                    context.workspace_id, replay.promoted_revision_id
                )
                if replay.promoted_revision_id
                else None
            )
            return RefreshResult(
                run=replay,
                golden_asset_revision=promoted,
                last_good_revision=self.repository.latest_golden(
                    context.workspace_id, asset_id
                ),
            )
        timestamp = _now()
        run_id = (
            "refresh-"
            + hashlib.sha256(
                (
                    f"{context.workspace_id}:{context.principal_id}:{idempotency_key}"
                ).encode()
            ).hexdigest()[:24]
        )
        prior_recipe = self.repository.cleaning_recipe(
            previous.lineage.recipe_id, previous.lineage.recipe_version
        )
        operations: list[CleaningOperation] = (
            list(prior_recipe.operations) if prior_recipe else ["trim"]
        )
        candidate = None
        resource = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == previous.lineage.resource_id
            ),
            None,
        )
        if resource is None:
            raise SourcesGoldenError(
                "RESOURCE_NOT_FOUND",
                "The Golden revision's source is no longer discoverable.",
            )
        adapter = self._connector_registry[connection.connector_key]
        arguments: Mapping[str, object] | None = previous.lineage.tool_arguments
        if connection.connector_key == "webhook":
            events = self.repository.events(
                context.workspace_id,
                connection.id,
                event_type="webhook.delivery.accepted",
            )
            arguments = {
                "events": [(event.sequence, event.payload) for event in events]
            }
        elif connection.connector_key in SqlDatabaseAdapter.CONNECTORS:
            configured_parameters = connection.configuration.get("queryParameters")
            arguments = (
                configured_parameters
                if isinstance(configured_parameters, Mapping)
                else None
            )
        request = self._adapter_request(
            adapter=adapter,
            context=context,
            connection_id=connection.id,
            connector_key=connection.connector_key,
            configuration=connection.configuration,
            secret_ref=connection.secret_ref,
            trace_id=trace_id,
            resource=resource,
            arguments=arguments,
            cancelled=cancelled,
        )
        adapter_operations: list[ConnectorOperation] = []
        try:
            adapter_operations.append(
                request.execution.run(
                    "authenticate", lambda: adapter.authenticate(request)
                )
            )
            adapter_operations.append(
                request.execution.run("authorize", lambda: adapter.authorize(request))
            )
            refreshed = request.execution.run(
                "refresh", lambda: adapter.refresh(request)
            )
            if not isinstance(refreshed, ConnectorReadResult):
                raise ConnectorAdapterError(
                    "CONNECTOR_RESULT_INVALID",
                    "The connector adapter returned an invalid refresh result.",
                    stage="refresh",
                )
            request.read_cache.result = refreshed
            adapter_operations.append(
                succeeded_operation(
                    "refresh",
                    request,
                    code="CONNECTOR_REFRESH_SUCCEEDED",
                    message="The connector returned a refreshed source revision.",
                    resources=[resource],
                )
            )
            adapter_operations.append(
                succeeded_operation(
                    "read",
                    request,
                    code="CONNECTOR_READ_SUCCEEDED",
                    message="The refreshed connector result is ready to materialize.",
                    resources=[resource],
                )
            )
            candidate = self._lifecycle.build(
                connection=connection,
                resource_id=previous.lineage.resource_id,
                operations=operations,
                recipe_version=self.repository.next_recipe_version(asset_id),
                golden_revision=previous.revision + 1,
                principal_id=context.principal_id,
                trace_id=trace_id,
                timestamp=timestamp,
                materialized=self._materialized_connector_result(refreshed),
                tool_arguments=previous.lineage.tool_arguments,
            )
            adapter_operations.extend(
                [
                    request.execution.run("profile", lambda: adapter.profile(request)),
                    request.execution.run("clean", lambda: adapter.clean(request)),
                    request.execution.run("golden", lambda: adapter.golden(request)),
                ]
            )
            checkpoint = dict(
                request.execution.run("checkpoint", lambda: adapter.checkpoint(request))
            )
            adapter_operations.append(
                succeeded_operation(
                    "checkpoint",
                    request,
                    code="CONNECTOR_CHECKPOINT_PERSISTED",
                    message="The refreshed connector checkpoint is ready to persist.",
                )
            )
            adapter_operations.append(
                request.execution.run("close", lambda: adapter.close(request))
            )
            if candidate.golden.schema_digest != previous.schema_digest:
                run = RefreshRunRecord(
                    id=run_id,
                    workspace_id=context.workspace_id,
                    asset_id=asset_id,
                    status="schema_drift",
                    previous_revision_id=previous.id,
                    staging_ref=candidate.golden.storage_ref,
                    reason=CapabilityReason(
                        code="SCHEMA_DRIFT",
                        message="Schema changed; staging output was not promoted.",
                    ),
                    retry_of=retry_of,
                    trace_id=trace_id,
                    started_at=timestamp,
                    finished_at=_now(),
                )
                self.repository.save_refresh(
                    run, idempotency_key=scoped_idempotency_key
                )
                self._record_adapter_operations(
                    connection=connection,
                    operations=adapter_operations,
                    timestamp=timestamp,
                    checkpoint=checkpoint,
                )
                return RefreshResult(run=run, last_good_revision=previous)
            self.repository.save_ingest(
                source=candidate.source,
                profile=candidate.profile,
                recipe=candidate.recipe,
                clean=candidate.clean,
                golden=candidate.golden,
                idempotency_key=(f"refresh-ingest:{scoped_idempotency_key}"),
            )
            run = RefreshRunRecord(
                id=run_id,
                workspace_id=context.workspace_id,
                asset_id=asset_id,
                status="succeeded",
                previous_revision_id=previous.id,
                promoted_revision_id=candidate.golden.id,
                staging_ref=candidate.golden.storage_ref,
                reason=CapabilityReason(
                    code="PROMOTED",
                    message="Staging passed schema, quality, and permission gates.",
                ),
                retry_of=retry_of,
                trace_id=trace_id,
                started_at=timestamp,
                finished_at=_now(),
            )
            self.repository.save_refresh(run, idempotency_key=scoped_idempotency_key)
            self._record_adapter_operations(
                connection=connection,
                operations=adapter_operations,
                timestamp=timestamp,
                checkpoint=checkpoint,
            )
            return RefreshResult(
                run=run,
                golden_asset_revision=candidate.golden,
                last_good_revision=candidate.golden,
            )
        except (
            ConnectorAdapterError,
            McpProcessError,
            McpProcessStartError,
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            self._record_adapter_failure(
                connection=connection,
                adapter=adapter,
                request=request,
                completed=adapter_operations,
                error=error,
                timestamp=timestamp,
            )
            code = (
                "PERMISSION_REVOKED"
                if isinstance(error, PermissionError)
                else getattr(error, "code", "SOURCE_READ_FAILED")
            )
            status = "permission_denied" if code == "PERMISSION_REVOKED" else "failed"
            run = RefreshRunRecord(
                id=run_id,
                workspace_id=context.workspace_id,
                asset_id=asset_id,
                status=status,
                previous_revision_id=previous.id,
                staging_ref=candidate.golden.storage_ref if candidate else None,
                reason=CapabilityReason(
                    code=code,
                    message=str(error),
                    retryable=code
                    in {
                        "SOURCE_READ_FAILED",
                        "MCP_PROCESS_START_FAILED",
                        "MCP_PROCESS_EXITED",
                        "MCP_TIMEOUT",
                    },
                ),
                retry_of=retry_of,
                trace_id=trace_id,
                started_at=timestamp,
                finished_at=_now(),
            )
            self.repository.save_refresh(run, idempotency_key=scoped_idempotency_key)
            return RefreshResult(run=run, last_good_revision=previous)

    def retry_refresh(
        self,
        context: AccessContext,
        *,
        failed_run_id: str,
        idempotency_key: str,
        trace_id: str,
    ) -> RefreshResult:
        self._require_write(context)
        previous_run = self.repository.refresh_run(context.workspace_id, failed_run_id)
        if previous_run is None:
            raise SourcesGoldenError(
                "REFRESH_NOT_RETRYABLE",
                "The requested refresh run is not retryable.",
            )
        previous = self.repository.latest_golden(
            context.workspace_id, previous_run.asset_id
        )
        if previous is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, previous.lineage.connection_id)
        if previous_run.status not in {
            "failed",
            "schema_drift",
            "permission_denied",
        }:
            raise SourcesGoldenError(
                "REFRESH_NOT_RETRYABLE",
                "The requested refresh run is not retryable.",
            )
        return self.refresh(
            context,
            asset_id=previous_run.asset_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            retry_of=failed_run_id,
        )

    def cancel_refresh(
        self,
        context: AccessContext,
        *,
        asset_id: str,
        idempotency_key: str,
        trace_id: str,
    ) -> RefreshRunRecord:
        self._require_write(context)
        previous = self.repository.latest_golden(context.workspace_id, asset_id)
        if previous is None:
            raise SourcesGoldenError(
                "GOLDEN_ASSET_NOT_FOUND",
                "Golden Asset does not exist in the authenticated workspace.",
            )
        self._connection_for_context(context, previous.lineage.connection_id)
        scoped_idempotency_key = self._scoped_idempotency(context, idempotency_key)
        replay = self.repository.refresh_for_idempotency(
            context.workspace_id, scoped_idempotency_key
        )
        if replay is not None:
            return replay
        timestamp = _now()
        run = RefreshRunRecord(
            id="refresh-"
            + hashlib.sha256(
                (
                    f"{context.workspace_id}:{context.principal_id}:{idempotency_key}"
                ).encode()
            ).hexdigest()[:24],
            workspace_id=context.workspace_id,
            asset_id=asset_id,
            status="cancelled",
            previous_revision_id=previous.id,
            reason=CapabilityReason(
                code="CANCELLED",
                message="Refresh was cancelled before source processing.",
            ),
            trace_id=trace_id,
            started_at=timestamp,
            finished_at=timestamp,
        )
        self.repository.save_refresh(run, idempotency_key=scoped_idempotency_key)
        return run

    def revoke_connection(
        self,
        context: AccessContext,
        connection_id: str,
        *,
        reason: str,
        trace_id: str,
    ) -> None:
        self._require_write(context)
        connection = self._connection_for_context(context, connection_id)
        timestamp = _now()
        revoked = connection.model_copy(
            update={
                "status": "revoked",
                "updated_at": timestamp,
                "last_error": CapabilityReason(
                    code="PERMISSION_REVOKED", message=reason
                ),
            }
        )
        self.repository.revoke_connection(
            workspace_id=context.workspace_id,
            connection_id=connection_id,
            revoked_at=timestamp,
            replacement=revoked,
        )
        self.repository.record_operation(
            workspace_id=context.workspace_id,
            connection_id=connection_id,
            trace_id=trace_id,
            operation="revoke",
            status="succeeded",
            payload={
                "reason": {
                    "code": "PERMISSION_REVOKED",
                    "message": reason,
                }
            },
            created_at=timestamp,
        )

    def delete_connection(
        self,
        context: AccessContext,
        connection_id: str,
        *,
        trace_id: str,
    ) -> None:
        self.revoke_connection(
            context,
            connection_id,
            reason="Connection deleted by an authorized user.",
            trace_id=trace_id,
        )

    def mcp_process_traces(self, context: AccessContext, connection_id: str):
        self._connection_for_context(context, connection_id, include_revoked=True)
        return self.repository.mcp_traces(context.workspace_id, connection_id)

    def mcp_process_traces_for_workspace(self, context: AccessContext):
        accessible = {
            connection.id
            for connection in self.repository.connections(context.workspace_id)
            if self._can_access_connection(context, connection)
        }
        return [
            trace
            for trace in self.repository.mcp_traces_for_workspace(context.workspace_id)
            if trace.connection_id in accessible
            or trace.principal_id == context.principal_id
        ]

    def connector_traces(self, context: AccessContext, connection_id: str):
        self._connection_for_context(context, connection_id, include_revoked=True)
        return self.repository.connector_traces(context.workspace_id, connection_id)

    def connector_events(self, context: AccessContext, connection_id: str):
        self._connection_for_context(context, connection_id, include_revoked=True)
        return self.repository.events(context.workspace_id, connection_id)

    def connector_operations(self, context: AccessContext, connection_id: str):
        self._connection_for_context(context, connection_id, include_revoked=True)
        return self.repository.operations(context.workspace_id, connection_id)

    def connector_trace(
        self,
        context: AccessContext,
        connection_id: str,
        trace_id: str,
    ):
        self._connection_for_context(context, connection_id, include_revoked=True)
        return self.repository.trace(context.workspace_id, connection_id, trace_id)

    def receive_webhook(
        self,
        context: AccessContext,
        *,
        connection_id: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        trace_id: str,
    ) -> ConnectorEventRecord:
        connection = self._connection_for_context(context, connection_id)
        if connection.connector_key != "webhook" or connection.status != "ready":
            raise SourcesGoldenError(
                "WEBHOOK_NOT_READY",
                "The requested connection is not an active webhook.",
            )
        rate_limit = connection.configuration.get("rateLimitPerMinute", 60)
        if (
            isinstance(rate_limit, bool)
            or not isinstance(rate_limit, int)
            or rate_limit < 1
        ):
            raise SourcesGoldenError(
                "WEBHOOK_LIMIT_INVALID",
                "Webhook rateLimitPerMinute must be a positive integer.",
            )
        if (
            self.repository.recent_event_count(context.workspace_id, connection.id)
            >= rate_limit
        ):
            raise SourcesGoldenError(
                "WEBHOOK_RATE_LIMIT",
                "Webhook delivery rate exceeds the configured limit.",
            )
        timestamp = _now()
        try:
            delivery_id, rows = self._webhook_adapter.receive(
                configuration=connection.configuration,
                secret_ref=connection.secret_ref,
                path=path,
                headers=headers,
                body=body,
            )
            event_id = (
                "webhook-event-"
                + hashlib.sha256(f"{connection.id}:{delivery_id}".encode()).hexdigest()[
                    :32
                ]
            )
            if self.repository.event_exists(event_id):
                raise ConnectorAdapterError(
                    "WEBHOOK_REPLAY",
                    "Webhook delivery ID has already been accepted.",
                    stage="authorize",
                )
            payload = cast(JsonValue, rows[0] if len(rows) == 1 else rows)
            event = ConnectorEventRecord(
                id=event_id,
                workspace_id=context.workspace_id,
                connection_id=connection.id,
                sequence=self.repository.next_event_sequence(
                    context.workspace_id, connection.id
                ),
                event_type="webhook.delivery.accepted",
                trace_id=trace_id,
                payload_digest=hashlib.sha256(body).hexdigest(),
                payload=payload,
                created_at=timestamp,
            )
            self.repository.save_event(event)
            self._record_operation(
                connection=connection,
                operation="authorize",
                status="succeeded",
                trace_id=trace_id,
                reason=CapabilityReason(
                    code="WEBHOOK_DELIVERY_ACCEPTED",
                    message="Webhook signature and payload schema were accepted.",
                ),
                timestamp=timestamp,
            )
            return event
        except ConnectorAdapterError as error:
            self._record_operation(
                connection=connection,
                operation=error.stage,
                status="failed",
                trace_id=trace_id,
                reason=CapabilityReason(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                ),
                timestamp=timestamp,
            )
            raise SourcesGoldenError(error.code, error.message) from error

    def _call_mcp(
        self,
        *,
        context: AccessContext,
        connection,
        trace_id: str,
        tool_name: str,
        tool_arguments: dict[str, object],
    ):
        if connection.configuration.get("transport") == "stdio":
            try:
                call = self._mcp_client.call(
                    workspace_id=context.workspace_id,
                    principal_id=context.principal_id,
                    connection_id=connection.id,
                    configuration=connection.configuration,
                    trace_id=trace_id,
                    tool_name=tool_name,
                    tool_arguments=tool_arguments,
                )
                self.repository.save_mcp_trace(call.trace)
                return call
            except McpProcessError as error:
                self.repository.save_mcp_trace(error.trace)
                raise
        try:
            call = self._remote_mcp_client.call(
                workspace_id=context.workspace_id,
                principal_id=context.principal_id,
                connection_id=connection.id,
                configuration=connection.configuration,
                secret_ref=connection.secret_ref,
                trace_id=trace_id,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
            )
            self.repository.save_connector_trace(call.trace)
            return call
        except RemoteMcpError as error:
            self.repository.save_connector_trace(error.trace)
            raise

    def _mcp_materialized(
        self,
        *,
        context: AccessContext,
        connection,
        resource_id: str,
        tool_arguments: dict[str, object],
        trace_id: str,
    ):
        selected = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == resource_id and item.resource_type == "tool"
            ),
            None,
        )
        if selected is None:
            raise ValueError("MCP tool was not discovered by this connection")
        call = self._call_mcp(
            context=context,
            connection=connection,
            trace_id=trace_id,
            tool_name=selected.name,
            tool_arguments=tool_arguments,
        )
        return self._lifecycle.materialized_mcp(
            tool_name=call.tool_name,
            rows=call.rows,
            fields=call.schema,
            adapter_run_id=(
                call.structured_result.run_id
                if isinstance(call, McpCallResult)
                else call.run_id
            ),
        )

    def _openapi_materialized(self, *, connection, resource_id: str, trace_id: str):
        from .lifecycle import MaterializedSource

        read = self._openapi_adapter.read(
            configuration=connection.configuration,
            secret_ref=connection.secret_ref,
            resource_id=resource_id,
            trace_id=trace_id,
        )
        return MaterializedSource(
            source_type="http",
            source_locator=read.source_locator,
            raw_content=read.raw_content,
            rows=read.rows,
            fields=read.fields,
            media_type=read.media_type,
            adapter_run_id=read.adapter_run_id,
            checkpoint=read.checkpoint,
        )

    def _http_materialized(self, *, connection, trace_id: str):
        read = self._http_adapter.read(
            connector_key=connection.connector_key,
            configuration=connection.configuration,
            secret_ref=connection.secret_ref,
            trace_id=trace_id,
        )
        return self._materialized_http(read)

    def _database_materialized(
        self,
        *,
        connection,
        resource_id: str,
        trace_id: str,
    ):
        resource = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == resource_id and item.resource_type == "table"
            ),
            None,
        )
        if resource is None:
            raise ValueError("database table was not discovered by this connection")
        parameters = connection.configuration.get("queryParameters")
        if parameters is not None and not isinstance(parameters, dict):
            raise ValueError("database queryParameters must be an object")
        read = self._database_adapter.read(
            connector_key=connection.connector_key,
            configuration=connection.configuration,
            secret_ref=connection.secret_ref,
            resource=resource,
            parameters=parameters,
            trace_id=trace_id,
        )
        return self._materialized_database(read)

    def _webhook_materialized(self, *, connection, trace_id: str):
        events = self.repository.events(
            connection.workspace_id,
            connection.id,
            event_type="webhook.delivery.accepted",
        )
        read = self._webhook_adapter.read(
            configuration=connection.configuration,
            events=[(event.sequence, event.payload) for event in events],
            trace_id=trace_id,
        )
        return self._materialized_webhook(read)

    def _provider_materialized(
        self,
        *,
        context: AccessContext,
        connection: ConnectionInstance,
        resource_id: str,
        trace_id: str,
        arguments: Mapping[str, object] | None,
    ):
        resource = next(
            (
                item
                for item in connection.discovered_resources
                if item.id == resource_id
            ),
            None,
        )
        if resource is None:
            raise ConnectorAdapterError(
                "PROVIDER_RESOURCE_NOT_FOUND",
                "The selected provider resource was not discovered by this connection.",
                stage="read",
            )
        adapter = self._connector_registry[connection.connector_key]
        request = self._adapter_request(
            adapter=adapter,
            context=context,
            connection_id=connection.id,
            connector_key=connection.connector_key,
            configuration=connection.configuration,
            secret_ref=connection.secret_ref,
            trace_id=trace_id,
            resource=resource,
            arguments=arguments,
        )
        read = request.execution.run("read", lambda: adapter.read(request))
        if not isinstance(read, ConnectorReadResult):
            raise ConnectorAdapterError(
                "CONNECTOR_RESULT_INVALID",
                "The provider adapter returned an invalid read result.",
                stage="read",
            )
        from .lifecycle import MaterializedSource

        return MaterializedSource(
            source_type=read.source_type,
            source_locator=read.source_locator,
            raw_content=read.raw_content,
            rows=read.rows,
            fields=read.fields,
            media_type=read.media_type,
            adapter_run_id=read.adapter_run_id,
            checkpoint=read.checkpoint,
        )

    @staticmethod
    def _materialized_connector_result(
        read: ConnectorReadResult,
    ) -> MaterializedSource:
        return MaterializedSource(
            source_type=read.source_type,
            source_locator=read.source_locator,
            raw_content=read.raw_content,
            rows=read.rows,
            fields=read.fields,
            media_type=read.media_type,
            adapter_run_id=read.adapter_run_id,
            checkpoint=read.checkpoint,
        )

    @staticmethod
    def _materialized_http(read: HttpReadResult):
        from .lifecycle import MaterializedSource

        return MaterializedSource(
            source_type="http",
            source_locator=read.source_locator,
            raw_content=read.raw_content,
            rows=read.rows,
            fields=read.fields,
            media_type=read.media_type,
            adapter_run_id=read.adapter_run_id,
            checkpoint=read.checkpoint,
        )

    @staticmethod
    def _materialized_database(read: DatabaseReadResult):
        from .lifecycle import MaterializedSource

        return MaterializedSource(
            source_type="database",
            source_locator=read.source_locator,
            raw_content=read.raw_content,
            rows=read.rows,
            fields=read.fields,
            media_type=read.media_type,
            adapter_run_id=read.adapter_run_id,
            checkpoint=read.checkpoint,
        )

    @staticmethod
    def _materialized_webhook(read: WebhookReadResult):
        from .lifecycle import MaterializedSource

        return MaterializedSource(
            source_type="http",
            source_locator=read.source_locator,
            raw_content=read.raw_content,
            rows=read.rows,
            fields=read.fields,
            media_type=read.media_type,
            adapter_run_id=read.adapter_run_id,
            checkpoint=read.checkpoint,
        )

    def _record_operation(
        self,
        *,
        connection,
        operation: str,
        status: str,
        trace_id: str,
        reason: CapabilityReason,
        timestamp: str,
        checkpoint: dict[str, str] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "reason": reason.model_dump(mode="json", by_alias=True)
        }
        if checkpoint:
            payload["checkpoint"] = checkpoint
        self.repository.record_operation(
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            trace_id=trace_id,
            operation=operation,
            status=status,
            payload=payload,
            created_at=timestamp,
        )

    def _record_lifecycle_operations(
        self,
        *,
        connection,
        records,
        trace_id: str,
        timestamp: str,
        refresh: bool,
    ) -> None:
        reason = CapabilityReason(
            code="LIFECYCLE_STAGE_SUCCEEDED",
            message="The connector lifecycle stage completed successfully.",
        )
        stages = ["read"]
        if not refresh:
            stages.append("ingest")
        stages.extend(["profile", "clean", "golden", "checkpoint"])
        if refresh:
            stages.append("refresh")
        stages.append("close")
        for stage in stages:
            self._record_operation(
                connection=connection,
                operation=stage,
                status="succeeded",
                trace_id=trace_id,
                reason=reason,
                timestamp=timestamp,
                checkpoint=(
                    records.source.checkpoint if stage == "checkpoint" else None
                ),
            )

    def _record_adapter_operations(
        self,
        *,
        connection: ConnectionInstance,
        operations: list[ConnectorOperation],
        timestamp: str,
        checkpoint: Mapping[str, str] | None = None,
    ) -> None:
        for operation in operations:
            payload: dict[str, object] = {
                "reason": operation.reason.model_dump(mode="json", by_alias=True),
                "resources": [
                    resource.model_dump(mode="json", by_alias=True)
                    for resource in operation.resources
                ],
            }
            if operation.operation == "checkpoint" and checkpoint:
                payload["checkpoint"] = dict(checkpoint)
            self.repository.record_operation(
                workspace_id=connection.workspace_id,
                connection_id=connection.id,
                trace_id=operation.trace_id,
                operation=operation.operation,
                status=operation.status,
                payload=payload,
                created_at=timestamp,
            )

    def _record_adapter_failure(
        self,
        *,
        connection: ConnectionInstance,
        adapter: ConnectorAdapter,
        request: ConnectorRequest,
        completed: list[ConnectorOperation],
        error: Exception,
        timestamp: str,
    ) -> None:
        stage: ConnectorOperationName
        if isinstance(error, ConnectorAdapterError):
            stage = cast(ConnectorOperationName, error.stage)
        else:
            stage = "read"
        reason = CapabilityReason(
            code=getattr(error, "code", "SOURCE_INGEST_FAILED"),
            message=str(error),
            retryable=getattr(error, "retryable", False),
        )
        operations = [
            *completed,
            ConnectorOperation(
                operation=stage,
                status="failed",
                trace_id=request.trace_id,
                reason=reason,
            ),
        ]
        if stage != "close":
            try:
                operations.append(
                    request.execution.run("close", lambda: adapter.close(request))
                )
            except ConnectorAdapterError as close_error:
                operations.append(
                    ConnectorOperation(
                        operation="close",
                        status="failed",
                        trace_id=request.trace_id,
                        reason=CapabilityReason(
                            code=close_error.code,
                            message=close_error.message,
                            retryable=close_error.retryable,
                        ),
                    )
                )
        self._record_adapter_operations(
            connection=connection,
            operations=operations,
            timestamp=timestamp,
        )

    def _record_refresh_operation(
        self,
        *,
        connection,
        run: RefreshRunRecord,
        timestamp: str,
    ) -> None:
        self._record_operation(
            connection=connection,
            operation="refresh",
            status="failed" if run.status != "succeeded" else "succeeded",
            trace_id=run.trace_id,
            reason=run.reason,
            timestamp=timestamp,
        )

    @staticmethod
    def _require_write(context: AccessContext) -> None:
        if context.role not in {"editor", "admin"}:
            raise SourcesGoldenError(
                "PERMISSION_DENIED", "source.write permission is required."
            )

    @staticmethod
    def _can_access_connection(
        context: AccessContext, connection: ConnectionInstance
    ) -> bool:
        return connection.scope == "team" or connection.owner_id == context.principal_id

    def _connection_for_context(
        self,
        context: AccessContext,
        connection_id: str,
        *,
        include_revoked: bool = False,
    ) -> ConnectionInstance:
        loader = (
            self.repository.connection_including_revoked
            if include_revoked
            else self.repository.connection
        )
        connection = loader(context.workspace_id, connection_id)
        if connection is None:
            raise SourcesGoldenError(
                "CONNECTION_NOT_FOUND",
                "Connection does not exist in the authenticated workspace.",
            )
        if not self._can_access_connection(context, connection):
            raise SourcesGoldenError(
                "PERMISSION_DENIED",
                "Connection is not available to the authenticated principal.",
            )
        return connection

    @staticmethod
    def _scoped_idempotency(context: AccessContext, idempotency_key: str) -> str:
        return f"{context.principal_id}:{idempotency_key}"

    @staticmethod
    def _definition(connector_key: str):
        definition = next(
            (
                item
                for item in BUILTIN_CONNECTORS
                if item.connector_key == connector_key
            ),
            None,
        )
        if definition is None:
            raise SourcesGoldenError(
                "CONNECTOR_NOT_FOUND", "Unknown connector definition."
            )
        return definition

    @staticmethod
    def _validate_form(
        definition,
        configuration: dict[str, object],
        secret_ref: str | None,
        *,
        workspace_id: str,
    ) -> None:
        properties = definition.input_schema.properties
        secret_names = {
            key
            for key in configuration
            if key in {"password", "token", "apiKey", "api_key", "secret", "credential"}
            or "password" in key.casefold()
            or "tokenvalue" in key.casefold()
        }
        if secret_names:
            raise SourcesGoldenError(
                "INLINE_SECRET_REJECTED",
                "Credentials must be supplied only as a secretRef.",
            )
        unknown = set(configuration) - set(properties)
        if unknown:
            raise SourcesGoldenError(
                "INVALID_CONFIGURATION",
                f"Fields are not valid for {definition.connector_key}: {sorted(unknown)}",
            )
        if secret_ref is not None and not secret_ref.startswith(
            f"secret://{workspace_id}/"
        ):
            raise SourcesGoldenError(
                "INVALID_SECRET_REFERENCE",
                "secretRef must identify the active workspace's server-side secret store.",
            )
        missing = [
            key
            for key in definition.input_schema.required
            if configuration.get(key) in (None, "", [])
        ]
        if missing:
            raise SourcesGoldenError(
                "INVALID_CONFIGURATION", f"Required fields are missing: {missing}"
            )

    @staticmethod
    def _validate_tool_arguments(arguments: dict[str, object]) -> None:
        def contains_sensitive_value(value: object) -> bool:
            if isinstance(value, dict):
                return any(
                    any(
                        marker in str(key).casefold().replace("-", "").replace("_", "")
                        for marker in (
                            "password",
                            "token",
                            "secret",
                            "credential",
                            "apikey",
                            "privatekey",
                        )
                    )
                    or contains_sensitive_value(item)
                    for key, item in value.items()
                )
            if isinstance(value, list):
                return any(contains_sensitive_value(item) for item in value)
            return isinstance(value, str) and value.startswith("secret://")

        if contains_sensitive_value(arguments):
            raise SourcesGoldenError(
                "INLINE_SECRET_REJECTED",
                "MCP tool credentials must use runtime secretRef environment injection.",
            )

    @staticmethod
    def _public_configuration(
        configuration: dict[str, object],
    ) -> dict[str, JsonValue]:
        def json_value(value: object) -> JsonValue:
            if value is None or isinstance(value, (str, bool, int)):
                return value
            if isinstance(value, float):
                if not math.isfinite(value):
                    raise SourcesGoldenError(
                        "INVALID_CONFIGURATION",
                        "Connection configuration must contain finite JSON values.",
                    )
                return value
            if isinstance(value, list):
                return [json_value(item) for item in value]
            if isinstance(value, dict) and all(isinstance(key, str) for key in value):
                return {cast(str, key): json_value(item) for key, item in value.items()}
            raise SourcesGoldenError(
                "INVALID_CONFIGURATION",
                "Connection configuration must contain JSON-compatible values.",
            )

        return {key: json_value(value) for key, value in configuration.items()}

    @staticmethod
    def _connection_view(connection: ConnectionInstance) -> ConnectionViewModel:
        return ConnectionViewModel.model_validate(
            connection.model_dump(exclude={"configuration", "secret_ref"})
        )

    @staticmethod
    def _operation_for_existing(connection: ConnectionInstance, trace_id: str):
        from .models import ConnectorOperation

        status_by_connection: dict[ConnectionStatus, OperationStatus] = {
            "ready": "succeeded",
            "config_required": "config_required",
            "credential_blocked": "credential_blocked",
            "unsupported": "unsupported",
            "revoked": "failed",
        }
        status = status_by_connection[connection.status]
        return ConnectorOperation(
            operation="validate",
            status=status,
            trace_id=trace_id,
            reason=connection.last_error
            or CapabilityReason(
                code="IDEMPOTENT_REPLAY",
                message="The persisted connection result was replayed.",
            ),
            resources=connection.discovered_resources,
        )


def _connector_evidence_index() -> dict[str, list[str]]:
    """Map every capability row to executable, connector-specific evidence."""
    adapter_contract = (
        "tests/frontend/knowledge_workspace_v21141/"
        "test_step3b_connector_adapters.py::"
        "test_all_37_catalog_entries_have_a_formal_callable_adapter"
    )
    typed_validation = (
        "tests/frontend/knowledge_workspace_v21141/"
        "test_step3b_connector_adapters.py::"
        "test_all_37_adapters_reject_invalid_configuration_with_typed_errors"
    )
    context_authorization = (
        "tests/frontend/knowledge_workspace_v21141/"
        "test_step3b_connector_adapters.py::"
        "test_context_reference_is_pinned_reauthorized_and_freshness_bounded"
    )
    execution_policy = (
        "tests/frontend/knowledge_workspace_v21141/"
        "test_step3b_connector_adapters.py::"
        "test_uniform_execution_policy_enforces_retry_timeout_and_cancellation"
    )
    bounded_retry_configuration = (
        "tests/frontend/knowledge_workspace_v21141/"
        "test_step3b_connector_adapters.py::"
        "test_all_adapters_validate_bounded_retry_policy"
    )
    catalog_keys = {definition.connector_key for definition in BUILTIN_CONNECTORS}
    evidence: dict[str, list[str]] = {
        key: [
            adapter_contract,
            typed_validation,
            context_authorization,
            execution_policy,
            bounded_retry_configuration,
        ]
        for key in catalog_keys
    }
    groups = {
        ("csv", "sqlite", "local_file"): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3_sources_golden.py::"
            "test_markdown_csv_and_sqlite_build_persisted_golden_revisions"
        ),
        ("excel",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3_sources_golden.py::"
            "test_excel_builds_persisted_profile_clean_and_golden_revision"
        ),
        ("json",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_json_runs_the_real_lifecycle_and_survives_restart"
        ),
        ("parquet",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_parquet_discovers_schema_and_builds_a_golden_revision"
        ),
        ("doc_txt",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3_sources_golden.py::"
            "test_pdf_builds_persisted_profile_clean_and_golden_revision"
        ),
        ("postgresql", "mysql"): (
            "tests/frontend/knowledge_workspace_v21141/test_step3b_database_live.py"
        ),
        ("rest_api",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_rest_http_runs_paginated_lifecycle_with_durable_checkpoint_and_secret_safety"
        ),
        ("graphql", "web_discovery", "custom_http"): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_graphql_web_and_custom_http_use_real_read_only_endpoints"
        ),
        ("openapi_spec",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_openapi_allowlisted_operation_reads_real_http_and_detects_schema_drift"
        ),
        ("webhook",): (
            "tests/frontend/knowledge_workspace_v21141/test_step3b_webhook_ingress.py"
        ),
        ("mcp_custom",): (
            "tests/frontend/knowledge_workspace_v21141/test_step3b_remote_mcp_live.py"
        ),
        (
            "oracle",
            "sqlserver",
            "clickhouse",
            "doris",
            "starrocks",
            "snowflake",
            "bigquery",
            "hive",
        ): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_provider_adapters.py::"
            "test_warehouse_named_parameters_use_the_driver_parameter_style"
        ),
        ("s3", "oss"): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_provider_adapters.py::"
            "test_object_storage_maps_dns_failure_to_typed_validation_error"
        ),
        ("kafka",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_provider_adapters.py::"
            "test_kafka_rejects_private_broker_resolution_without_explicit_allowlist"
        ),
        (
            "lark_doc",
            "lark_wiki",
            "lark_drive",
            "lark_meeting",
            "lark_minutes",
            "lark_group",
            "lark_chat",
            "lark_base",
            "lark_mail",
        ): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_provider_adapters.py::"
            "test_lark_reads_apply_source_specific_selection_parameters"
        ),
        ("lark_sheet",): (
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_lark_adapters.py::"
            "test_lark_sheet_discovers_selected_sheet_and_reads_bounded_cells"
        ),
    }
    for connector_keys, test_reference in groups.items():
        for connector_key in connector_keys:
            evidence[connector_key].append(test_reference)
    for connector_key in ("postgresql", "mysql"):
        evidence[connector_key].append(
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_database_adapters_reject_private_endpoint_without_allowlist"
        )
        evidence[connector_key].append(
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_connector_adapters.py::"
            "test_database_adapters_reject_dns_rebinding_during_discovery"
        )
    for connector_key in (
        "oracle",
        "sqlserver",
        "clickhouse",
        "doris",
        "starrocks",
        "hive",
    ):
        evidence[connector_key].append(
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_provider_adapters.py::"
            "test_external_databases_reject_private_endpoint_without_allowlist"
        )
        evidence[connector_key].append(
            "tests/frontend/knowledge_workspace_v21141/"
            "test_step3b_provider_adapters.py::"
            "test_external_databases_reject_dns_rebinding_during_discovery"
        )
    if set(evidence) != catalog_keys:
        raise RuntimeError("connector evidence index is out of sync with the catalog")
    return evidence
