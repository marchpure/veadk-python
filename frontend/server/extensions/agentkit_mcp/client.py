"""Small, injectable AgentKit MCP control-plane client.

The control-plane schema is deliberately isolated here. The caller supplies the
already-approved credential/signing transport; this module never accepts or
persists a Runtime Token value.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .models import ControlPlaneResources


class AgentKitMcpError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        resources: ControlPlaneResources | None = None,
    ) -> None:
        super().__init__(message)
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
    ) -> None:
        self._transport = transport
        self._region = region
        self._attempts = max(1, attempts)
        self._timeout = timeout_seconds

    async def _post(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._attempts):
            try:
                if hasattr(self._transport, "post"):
                    call = self._transport.post(
                        region=self._region, action=action, payload=payload
                    )
                else:
                    call = self._transport(
                        region=self._region, action=action, payload=payload
                    )
                return await asyncio.wait_for(call, timeout=self._timeout)
            except Exception as error:
                if attempt + 1 == self._attempts:
                    raise AgentKitMcpError(f"{action} failed: {type(error).__name__}") from error
        raise AssertionError("unreachable")

    async def publish(
        self,
        *,
        workspace_id: str,
        access_package_id: str,
        backend_endpoint_ref: str,
        runtime_token_id: str,
        desired_version: str,
        inbound_auth_mode: str,
        allowed_client_ref: str | None,
        existing_service_id: str | None = None,
        existing_toolset_id: str | None = None,
    ) -> ControlPlaneResources:
        # Runtime Token is represented only by its provider reference. The
        # Gateway must resolve and inject it server-side.
        service = (
            {"Result": {"MCPServiceId": existing_service_id}}
            if existing_service_id
            else await self._post(
                "CreateMCPService",
                {
                    "Name": f"data-workshop-{workspace_id}-{desired_version}",
                    "BackendType": "ECS",
                    "BackendEndpoint": backend_endpoint_ref.rstrip("/") + "/mcp",
                    "OutboundCredentialRef": runtime_token_id,
                    "WorkspaceId": workspace_id,
                    "AccessPackageId": access_package_id,
                },
            )
        )
        first = ControlPlaneResources.from_response(service)
        try:
            toolset = (
                {"Result": {"MCPToolsetId": existing_toolset_id}}
                if existing_toolset_id
                else await self._post(
                    "CreateMCPToolset",
                    {
                        "Name": f"data-workshop-{workspace_id}-{desired_version}",
                        "MCPServiceId": first.mcp_service_id,
                        "InboundAuthMode": inbound_auth_mode,
                        "AllowedClientRef": allowed_client_ref,
                        "DesiredVersion": desired_version,
                    },
                )
            )
        except AgentKitMcpError as error:
            raise AgentKitMcpError(
                str(error),
                request_id=error.request_id or first.request_id,
                resources=first,
            ) from error
        second = ControlPlaneResources.from_response(toolset)
        return ControlPlaneResources(
            mcp_service_id=second.mcp_service_id or first.mcp_service_id,
            toolset_id=second.toolset_id,
            gateway_endpoint=second.gateway_endpoint,
            observed_version=second.observed_version or desired_version,
            request_id=second.request_id or first.request_id,
            live_tools_count=second.live_tools_count,
        )

    async def disable(self, publication: Any) -> None:
        if publication.toolset_id:
            await self._post("DisableMCPToolset", {"MCPToolsetId": publication.toolset_id})

    async def verify(self, publication: Any) -> dict[str, Any]:
        if not publication.gateway_endpoint:
            raise AgentKitMcpError("gateway endpoint is not provisioned")
        return await self._post(
            "VerifyMCPToolset",
            {"MCPToolsetId": publication.toolset_id, "GatewayEndpoint": publication.gateway_endpoint},
        )
