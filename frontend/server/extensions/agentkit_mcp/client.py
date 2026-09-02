"""AgentKit MCP control-plane client using the official 2025-10-30 schema."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from .models import ControlPlaneResources, PublicationCreateRequest

_TERMINAL = {"Ready", "Error"}


class AgentKitMcpError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        request_id: str | None = None,
        resources: ControlPlaneResources | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id
        self.resources = resources


class AgentKitControlPlaneTransport(Protocol):
    async def post(
        self, *, region: str, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


class AgentKitMcpClient:
    API_VERSION = "2025-10-30"

    def __init__(
        self,
        transport: AgentKitControlPlaneTransport
        | Callable[..., Awaitable[dict[str, Any]]],
        *,
        region: str = "cn-beijing",
        attempts: int = 2,
        timeout_seconds: float = 30,
        poll_attempts: int = 10,
        poll_interval_seconds: float = 1,
    ) -> None:
        self._transport = transport
        self._region = region
        self._attempts = max(1, attempts)
        self._timeout = timeout_seconds
        self._poll_attempts = max(1, poll_attempts)
        self._poll_interval = max(0, poll_interval_seconds)

    async def _post(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._attempts):
            try:
                if hasattr(self._transport, "post"):
                    transport = cast(AgentKitControlPlaneTransport, self._transport)
                    call = transport.post(
                        region=self._region, action=action, payload=payload
                    )
                else:
                    transport_call = cast(
                        Callable[..., Awaitable[dict[str, Any]]], self._transport
                    )
                    call = transport_call(
                        region=self._region, action=action, payload=payload
                    )
                response = await asyncio.wait_for(call, timeout=self._timeout)
                if not isinstance(response, dict):
                    raise TypeError("control plane returned a non-object response")
                return response
            except AgentKitMcpError:
                raise
            except Exception as error:
                if attempt + 1 == self._attempts:
                    code = str(getattr(error, "code", "") or type(error).__name__)
                    raise AgentKitMcpError(
                        code,
                        f"{action} failed",
                        retryable=True,
                        request_id=_request_id_from_error(error),
                    ) from error
        raise AssertionError("unreachable")

    async def publish(
        self,
        *,
        request: PublicationCreateRequest,
        workspace_id: str,
        existing_service_id: str | None = None,
        existing_toolset_id: str | None = None,
        toolset_generation: int = 0,
    ) -> ControlPlaneResources:
        service = ControlPlaneResources(mcp_service_id=existing_service_id)
        if not existing_service_id:
            response = await self._post(
                "CreateMCPService",
                self._service_payload(request, workspace_id),
            )
            service = ControlPlaneResources.from_service_response(response)
            service.service_created = True
            if not service.mcp_service_id:
                raise AgentKitMcpError(
                    "INVALID_RESPONSE",
                    "CreateMCPService did not return MCPServiceId",
                    request_id=service.request_id,
                )

        toolset = ControlPlaneResources(toolset_id=existing_toolset_id)
        try:
            service_detail = await self._poll(
                action="GetMCPService",
                payload={"MCPServiceId": service.mcp_service_id},
                parser=ControlPlaneResources.from_service_response,
                status_attr="service_status",
            )
            service.service_status = service_detail.service_status
            service.request_id = service_detail.request_id or service.request_id
            if service.service_status == "Error":
                raise AgentKitMcpError(
                    "MCP_SERVICE_ERROR",
                    "MCP Service entered Error state",
                    request_id=service.request_id,
                    resources=service,
                )
            service_id = service.mcp_service_id
            if not service_id:
                raise AgentKitMcpError(
                    "INVALID_RESPONSE",
                    "GetMCPService did not return MCPServiceId",
                    request_id=service.request_id,
                    resources=service,
                )

            if not existing_toolset_id:
                response = await self._post(
                    "CreateMCPToolset",
                    self._toolset_payload(
                        request,
                        workspace_id,
                        service_id,
                        toolset_generation,
                    ),
                )
                toolset = ControlPlaneResources.from_toolset_response(response)
                toolset.toolset_created = True
                if not toolset.toolset_id:
                    raise AgentKitMcpError(
                        "INVALID_RESPONSE",
                        "CreateMCPToolset did not return MCPToolsetId",
                        request_id=toolset.request_id,
                        resources=service,
                    )

            toolset_detail = await self._poll(
                action="GetMCPToolset",
                payload={"MCPToolsetId": toolset.toolset_id},
                parser=ControlPlaneResources.from_toolset_response,
                status_attr="toolset_status",
            )
            if toolset_detail.toolset_status == "Error":
                partial = ControlPlaneResources(
                    mcp_service_id=service_id,
                    toolset_id=toolset.toolset_id,
                    service_created=service.service_created,
                    toolset_created=toolset.toolset_created,
                )
                raise AgentKitMcpError(
                    "MCP_TOOLSET_ERROR",
                    "MCP Toolset entered Error state",
                    request_id=toolset_detail.request_id,
                    resources=partial,
                )
            return ControlPlaneResources(
                mcp_service_id=service_id,
                toolset_id=toolset.toolset_id,
                gateway_endpoint=toolset_detail.gateway_endpoint,
                request_id=toolset_detail.request_id
                or toolset.request_id
                or service.request_id,
                service_status=service.service_status,
                toolset_status=toolset_detail.toolset_status,
                service_created=service.service_created,
                toolset_created=toolset.toolset_created,
            )
        except AgentKitMcpError as error:
            partial = error.resources or ControlPlaneResources()
            partial.mcp_service_id = partial.mcp_service_id or service.mcp_service_id
            partial.toolset_id = partial.toolset_id or toolset.toolset_id
            partial.service_created = partial.service_created or service.service_created
            partial.toolset_created = partial.toolset_created or toolset.toolset_created
            raise AgentKitMcpError(
                error.code,
                str(error),
                retryable=error.retryable,
                request_id=error.request_id or service.request_id,
                resources=partial,
            ) from error

    async def disable(self, *, toolset_id: str) -> str | None:
        response = await self._post("DeleteMCPToolset", {"MCPToolsetId": toolset_id})
        return (response.get("ResponseMetadata") or {}).get("RequestId")

    async def get_toolset(self, *, toolset_id: str) -> ControlPlaneResources:
        response = await self._post("GetMCPToolset", {"MCPToolsetId": toolset_id})
        return ControlPlaneResources.from_toolset_response(response)

    async def _poll(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        parser: Callable[[dict[str, Any]], ControlPlaneResources],
        status_attr: str,
    ) -> ControlPlaneResources:
        last = ControlPlaneResources()
        for index in range(self._poll_attempts):
            last = parser(await self._post(action, payload))
            status = getattr(last, status_attr)
            if status in _TERMINAL:
                return last
            if index + 1 < self._poll_attempts and self._poll_interval:
                await asyncio.sleep(self._poll_interval)
        raise AgentKitMcpError(
            "CONTROL_PLANE_TIMEOUT",
            f"{action} did not reach a terminal state",
            retryable=True,
            request_id=last.request_id,
            resources=last,
        )

    @staticmethod
    def _service_payload(
        request: PublicationCreateRequest, workspace_id: str
    ) -> dict[str, Any]:
        endpoint = urlsplit(request.backend_endpoint_ref)
        port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
        backend_configuration: dict[str, Any]
        if request.backend_type == "ECS":
            backend_configuration = {
                "EcsConfiguration": {
                    "Instances": [
                        {
                            "InstanceId": request.backend_instance_id,
                            "Ip": request.backend_instance_ip,
                            "Port": port,
                        }
                    ]
                }
            }
        else:
            backend_configuration = {
                "CustomConfiguration": {
                    "Domain": endpoint.hostname,
                    "Port": port,
                    "ProtocolType": endpoint.scheme.upper(),
                    "TlsSettings": {
                        "TlsMode": "SIMPLE" if endpoint.scheme == "https" else "DISABLE"
                    },
                }
            }
        return {
            "Name": _resource_name("dw-mcp", workspace_id, request.desired_version),
            "ClientToken": _client_token(
                "service",
                workspace_id,
                request.access_package_id,
                request.desired_version,
            ),
            "Path": "/mcp",
            "ProtocolType": "MCP",
            "BackendType": request.backend_type,
            "BackendConfiguration": backend_configuration,
            "NetworkConfigurations": [{"NetworkType": "Public"}],
            "InboundAuthorizerConfiguration": {
                "AuthorizerType": "ApiKey",
                "Authorizer": {
                    "KeyAuth": {
                        "ApiKeys": [{"Name": "gateway-internal"}],
                        "ApiKeyLocation": "HEADER",
                        "Parameter": "Authorization",
                    }
                },
            },
            "OutboundAuthorizerConfiguration": {
                "AuthorizerType": "Identity",
                "Authorizer": {
                    "IdentityAuthorizer": {
                        "CredentialProviderName": request.runtime_token_id.removeprefix(
                            "credential-provider://"
                        ),
                        "ProviderType": "ApiKey",
                    }
                },
            },
            "ProjectName": "default",
        }

    @staticmethod
    def _toolset_payload(
        request: PublicationCreateRequest,
        workspace_id: str,
        service_id: str,
        toolset_generation: int,
    ) -> dict[str, Any]:
        return {
            "Name": _resource_name("dw-toolset", workspace_id, request.desired_version),
            "ClientToken": _client_token(
                "toolset",
                workspace_id,
                request.access_package_id,
                request.desired_version,
                str(toolset_generation),
            ),
            "Path": "/mcp",
            "MCPServiceIds": [service_id],
            "MCPServices": [{"MCPServiceId": service_id, "IsAllTools": True}],
            "Mode": "AllTools",
            "NetworkConfigurations": [{"NetworkType": "Public"}],
            "AuthorizerConfiguration": {
                "AuthorizerType": "CustomJWT",
                "Authorizer": {
                    "CustomJwtAuthorizer": {
                        "DiscoveryUrl": request.custom_jwt_discovery_url,
                        "AllowedClients": list(request.allowed_client_refs),
                    }
                },
            },
            "ProjectName": "default",
        }


def _resource_name(prefix: str, workspace_id: str, version: str) -> str:
    raw = f"{prefix}-{workspace_id}-{version}"
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-_")
    if len(value) < 4:
        value = f"{prefix}-resource"
    if len(value) <= 64:
        return value
    digest = hashlib.sha256(raw.encode()).hexdigest()[:10]
    return f"{value[:53]}-{digest}"


def _client_token(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _request_id_from_error(error: Exception) -> str | None:
    explicit = getattr(error, "request_id", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    match = re.search(r"\brequest_id=([A-Za-z0-9_-]{1,128})\b", str(error))
    return match.group(1) if match else None
