"""Contracts for the data-workshop AgentKit MCP publication boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublicationStatus(StrEnum):
    CODE_READY = "CODE_READY"
    PROVISIONING = "PROVISIONING"
    LIVE = "LIVE"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


class AgentKitMcpPublication(BaseModel):
    """Only non-secret publication metadata is persisted."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    publication_id: str = Field(alias="publicationId", min_length=1)
    tenant_id: str = Field(alias="tenantId", min_length=1)
    workspace_id: str = Field(alias="workspaceId", min_length=1)
    access_package_id: str = Field(alias="accessPackageId", min_length=1)
    runtime_token_id: str = Field(alias="runtimeTokenId", min_length=1)
    backend_endpoint_ref: str = Field(alias="backendEndpointRef", min_length=1)
    mcp_service_id: str | None = Field(default=None, alias="mcpServiceId")
    toolset_id: str | None = Field(default=None, alias="toolsetId")
    gateway_endpoint: str | None = Field(default=None, alias="gatewayEndpoint")
    inbound_auth_mode: str = Field(alias="inboundAuthMode", min_length=1)
    allowed_client_ref: str | None = Field(default=None, alias="allowedClientRef")
    desired_version: str = Field(alias="desiredVersion", min_length=1)
    observed_version: str | None = Field(default=None, alias="observedVersion")
    status: PublicationStatus
    last_error: str | None = Field(default=None, alias="lastError")
    request_id: str | None = Field(default=None, alias="requestId")
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")


class PublicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    access_package_id: str = Field(alias="accessPackageId", min_length=1)
    runtime_token_id: str = Field(alias="runtimeTokenId", min_length=1)
    backend_endpoint_ref: str = Field(alias="backendEndpointRef", min_length=1)
    desired_version: str = Field(alias="desiredVersion", min_length=1)
    allowed_client_ref: str | None = Field(default=None, alias="allowedClientRef")
    inbound_auth_mode: str = Field(default="CustomJWT", alias="inboundAuthMode")

    @field_validator("runtime_token_id")
    @classmethod
    def validate_runtime_token_reference(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("credential-provider://", "secret-ref://")):
            raise ValueError("runtimeTokenId must be a server-side credential reference")
        return value


class ControlPlaneResources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_service_id: str | None = None
    toolset_id: str | None = None
    gateway_endpoint: str | None = None
    observed_version: str | None = None
    request_id: str | None = None
    live_tools_count: int | None = None

    @classmethod
    def from_response(cls, response: dict[str, Any]) -> "ControlPlaneResources":
        result = response.get("Result") or response.get("result") or response
        return cls(
            mcp_service_id=result.get("MCPServiceId") or result.get("mcpServiceId"),
            toolset_id=result.get("MCPToolsetId")
            or result.get("toolsetId")
            or result.get("ToolsetId"),
            gateway_endpoint=result.get("GatewayEndpoint")
            or result.get("gatewayEndpoint"),
            observed_version=result.get("Version") or result.get("version"),
            request_id=(response.get("ResponseMetadata") or {}).get("RequestId"),
            live_tools_count=result.get("LiveToolsCount")
            or result.get("liveToolsCount"),
        )
