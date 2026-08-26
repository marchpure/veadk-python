"""Lifecycle adapter for local stdio and remote MCP transports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping

from .adapters import validate_external_configuration
from .connector_adapter import (
    ConnectorAdapterError,
    ConnectorCertification,
    ConnectorReadResult,
    ConnectorRequest,
    LifecycleConnectorAdapter,
    succeeded_operation,
    validate_configuration,
)
from .mcp_remote import RemoteMcpClient, RemoteMcpError
from .mcp_stdio import McpProcessError, McpProcessStartError, StdioMcpClient
from .models import (
    ConnectorDefinition,
    ConnectorOperation,
    DiscoveredResource,
    McpProcessTrace,
    RemoteMcpConfiguration,
    RemoteMcpTrace,
    StdioMcpConfiguration,
)


class McpConnectorAdapter(LifecycleConnectorAdapter):
    def __init__(
        self,
        *,
        definition: ConnectorDefinition,
        stdio: StdioMcpClient,
        remote: RemoteMcpClient,
        web_resolver: Callable[[str], list[str]] | None,
        allow_private_hosts: set[str],
        save_stdio_trace: Callable[[McpProcessTrace], None],
        save_remote_trace: Callable[[RemoteMcpTrace], None],
    ) -> None:
        self.definition = definition
        self.connector_keys = frozenset({definition.connector_key})
        self._stdio = stdio
        self._remote = remote
        self._web_resolver = web_resolver
        self._allow_private_hosts = allow_private_hosts
        self._save_stdio_trace = save_stdio_trace
        self._save_remote_trace = save_remote_trace

    @property
    def certification(self) -> ConnectorCertification:
        return ConnectorCertification(
            connector_key=self.definition.connector_key,
            implementation=f"{type(self).__module__}.{type(self).__name__}",
            driver="mcp",
            install_command="uv pip install 'mcp==1.26.0'",
            verification_command='python -c "import mcp; print(mcp.__version__)"',
            missing_condition=(
                "A server-owned stdio profile or reachable streamable HTTP/SSE "
                "endpoint is required."
            ),
            required_secret_fields=(),
            provider_scopes=("mcp.tools.list", "mcp.tools.call"),
            checkpoint="tool result content digest plus MCP trace id",
        )

    def validate(self, request: ConnectorRequest) -> ConnectorOperation:
        validate_configuration(self.definition, request.configuration)
        transport = request.configuration.get("transport")
        try:
            if transport == "stdio":
                StdioMcpConfiguration.model_validate(request.configuration)
            else:
                RemoteMcpConfiguration.model_validate(request.configuration)
            validate_external_configuration(
                self.definition,
                dict(request.configuration),
                web_resolver=self._web_resolver,
                allow_private_hosts=self._allow_private_hosts,
            )
        except (TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "MCP_CONFIGURATION_INVALID",
                str(error),
                stage="validate",
            ) from error
        return succeeded_operation(
            "validate",
            request,
            code="MCP_CONFIGURATION_VALIDATED",
            message="MCP transport, limits, and tool allowlist are valid.",
        )

    def discover(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        connection_id = request.connection_id or f"adapter-{request.trace_id}"
        try:
            if request.configuration.get("transport") == "stdio":
                tools, trace = self._stdio.discover(
                    workspace_id=request.workspace_id,
                    principal_id=request.principal_id,
                    connection_id=connection_id,
                    configuration=request.configuration,
                    trace_id=request.trace_id,
                )
                self._save_stdio_trace(trace)
            else:
                tools, trace = self._remote.discover(
                    workspace_id=request.workspace_id,
                    principal_id=request.principal_id,
                    connection_id=connection_id,
                    configuration=request.configuration,
                    secret_ref=request.secret_ref,
                    trace_id=request.trace_id,
                )
                self._save_remote_trace(trace)
        except McpProcessError as error:
            self._save_stdio_trace(error.trace)
            raise ConnectorAdapterError(
                error.code,
                str(error),
                stage="discover",
                retryable=error.code == "MCP_TIMEOUT",
            ) from error
        except McpProcessStartError as error:
            raise ConnectorAdapterError(
                error.code,
                "stdio MCP process could not be started.",
                stage="discover",
            ) from error
        except RemoteMcpError as error:
            self._save_remote_trace(error.trace)
            raise ConnectorAdapterError(
                error.code,
                str(error),
                stage="discover",
                retryable=error.code == "MCP_TIMEOUT",
            ) from error
        except (OSError, TypeError, ValueError) as error:
            raise ConnectorAdapterError(
                "MCP_CONFIGURATION_INVALID",
                "MCP runtime configuration is invalid.",
                stage="discover",
            ) from error
        resources = [
            DiscoveredResource(
                id="mcp-tool-"
                + hashlib.sha256(str(tool["name"]).encode()).hexdigest()[:24],
                name=str(tool["name"]),
                resource_type="tool",
                input_schema=_mapping(tool.get("inputSchema")),
                output_schema=_mapping(tool.get("outputSchema")),
            )
            for tool in tools
            if tool.get("name")
        ]
        return succeeded_operation(
            "discover",
            request,
            code="MCP_TOOLS_DISCOVERED",
            message="MCP initialized and returned the allowlisted tools.",
            resources=resources,
        )

    def authenticate(self, request: ConnectorRequest) -> ConnectorOperation:
        self.validate(request)
        if request.configuration.get("transport") != "stdio":
            try:
                self._remote.validate_credentials(
                    request.secret_ref,
                    workspace_id=request.workspace_id,
                )
            except ValueError as error:
                code = (
                    "INVALID_SECRET_REFERENCE"
                    if "active workspace" in str(error)
                    else "EXTERNAL_CREDENTIAL_UNAVAILABLE"
                )
                raise ConnectorAdapterError(
                    code,
                    str(error),
                    stage="authenticate",
                ) from error
        return succeeded_operation(
            "authenticate",
            request,
            code="MCP_CREDENTIAL_READY",
            message="MCP runtime credentials are available.",
        )

    def read(self, request: ConnectorRequest) -> ConnectorReadResult:
        if request.resource is None or request.resource.resource_type != "tool":
            raise ConnectorAdapterError(
                "MCP_TOOL_REQUIRED",
                "Select one discovered MCP tool.",
                stage="read",
            )
        connection_id = request.connection_id or f"adapter-{request.trace_id}"
        arguments = dict(request.arguments or {})
        try:
            if request.configuration.get("transport") == "stdio":
                call = self._stdio.call(
                    workspace_id=request.workspace_id,
                    principal_id=request.principal_id,
                    connection_id=connection_id,
                    configuration=request.configuration,
                    trace_id=request.trace_id,
                    tool_name=request.resource.name,
                    tool_arguments=arguments,
                )
                self._save_stdio_trace(call.trace)
                run_id = call.structured_result.run_id
            else:
                call = self._remote.call(
                    workspace_id=request.workspace_id,
                    principal_id=request.principal_id,
                    connection_id=connection_id,
                    configuration=request.configuration,
                    secret_ref=request.secret_ref,
                    trace_id=request.trace_id,
                    tool_name=request.resource.name,
                    tool_arguments=arguments,
                )
                self._save_remote_trace(call.trace)
                run_id = call.run_id
        except McpProcessError as error:
            self._save_stdio_trace(error.trace)
            raise ConnectorAdapterError(
                error.code,
                str(error),
                stage="read",
                retryable=error.code == "MCP_TIMEOUT",
            ) from error
        except McpProcessStartError as error:
            raise ConnectorAdapterError(
                error.code,
                "stdio MCP process could not be started.",
                stage="read",
                retryable=True,
            ) from error
        except RemoteMcpError as error:
            self._save_remote_trace(error.trace)
            raise ConnectorAdapterError(
                error.code,
                str(error),
                stage="read",
                retryable=error.code == "MCP_TIMEOUT",
            ) from error
        raw = json.dumps(
            call.rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return ConnectorReadResult(
            source_type="mcp",
            source_locator=f"mcp://tool/{request.resource.name}",
            raw_content=raw,
            rows=call.rows,
            fields=call.schema,
            media_type="application/json",
            adapter_run_id=run_id,
            checkpoint={"contentDigest": hashlib.sha256(raw).hexdigest()},
        )


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(key): item for key, item in value.items()}
