"""Contracts for the data-workshop AgentKit MCP publication boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    backend_type: Literal["Domain", "ECS"] = Field(
        default="Domain", alias="backendType"
    )
    backend_instance_id: str | None = Field(default=None, alias="backendInstanceId")
    backend_instance_ip: str | None = Field(default=None, alias="backendInstanceIp")
    mcp_service_id: str | None = Field(default=None, alias="mcpServiceId")
    toolset_id: str | None = Field(default=None, alias="toolsetId")
    gateway_endpoint: str | None = Field(default=None, alias="gatewayEndpoint")
    inbound_auth_mode: Literal["CustomJWT"] = Field(alias="inboundAuthMode")
    allowed_client_ref: str = Field(alias="allowedClientRef", min_length=1)
    allowed_client_refs: tuple[str, ...] = Field(
        default_factory=tuple, alias="allowedClientRefs"
    )
    custom_jwt_discovery_url: str = Field(alias="customJwtDiscoveryUrl", min_length=1)
    desired_version: str = Field(alias="desiredVersion", min_length=1)
    observed_version: str | None = Field(default=None, alias="observedVersion")
    status: PublicationStatus
    last_error: str | None = Field(default=None, alias="lastError")
    request_id: str | None = Field(default=None, alias="requestId")
    service_created_by_publisher: bool = Field(
        default=False, alias="serviceCreatedByPublisher"
    )
    toolset_created_by_publisher: bool = Field(
        default=False, alias="toolsetCreatedByPublisher"
    )
    toolset_generation: int = Field(default=0, alias="toolsetGeneration", ge=0)
    created_at: datetime = Field(default_factory=utc_now, alias="createdAt")
    updated_at: datetime = Field(default_factory=utc_now, alias="updatedAt")


class PublicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    access_package_id: str = Field(alias="accessPackageId", min_length=1)
    runtime_token_id: str = Field(alias="runtimeTokenId", min_length=1)
    backend_endpoint_ref: str = Field(alias="backendEndpointRef", min_length=1)
    desired_version: str = Field(alias="desiredVersion", min_length=1)
    allowed_client_ref: str = Field(alias="allowedClientRef", min_length=1)
    allowed_client_refs: tuple[str, ...] = Field(
        default_factory=tuple, alias="allowedClientRefs"
    )
    custom_jwt_discovery_url: str = Field(alias="customJwtDiscoveryUrl", min_length=1)
    inbound_auth_mode: Literal["CustomJWT"] = Field(
        default="CustomJWT", alias="inboundAuthMode"
    )
    backend_type: Literal["Domain", "ECS"] = Field(
        default="Domain", alias="backendType"
    )
    backend_instance_id: str | None = Field(
        default=None, alias="backendInstanceId", min_length=1
    )
    backend_instance_ip: str | None = Field(
        default=None, alias="backendInstanceIp", min_length=1
    )

    @field_validator("runtime_token_id")
    @classmethod
    def validate_runtime_token_reference(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("credential-provider://"):
            raise ValueError(
                "runtimeTokenId must be an Agent Identity Credential Provider reference"
            )
        if not value.removeprefix("credential-provider://"):
            raise ValueError("runtimeTokenId must include a provider name")
        return value

    @field_validator("backend_endpoint_ref")
    @classmethod
    def validate_backend_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("backendEndpointRef must be an HTTP(S) endpoint")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError(
                "backendEndpointRef must not contain credentials or query data"
            )
        path = parsed.path.rstrip("/")
        if path and path != "/mcp":
            raise ValueError("backendEndpointRef path must be /mcp")
        return value.strip()

    @field_validator("custom_jwt_discovery_url")
    @classmethod
    def validate_discovery_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("customJwtDiscoveryUrl must be an HTTPS URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("customJwtDiscoveryUrl must not contain credentials")
        return value.strip()

    @field_validator("backend_instance_ip")
    @classmethod
    def validate_instance_ip(cls, value: str | None) -> str | None:
        if value is not None:
            ip_address(value)
        return value

    @field_validator("backend_instance_id")
    @classmethod
    def normalize_instance_id(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @model_validator(mode="after")
    def validate_backend(self) -> "PublicationCreateRequest":
        if self.backend_type == "ECS" and (
            not self.backend_instance_id or not self.backend_instance_ip
        ):
            raise ValueError(
                "backendInstanceId and backendInstanceIp are required for ECS"
            )
        clients = tuple(
            dict.fromkeys(
                value.strip()
                for value in (self.allowed_client_ref, *self.allowed_client_refs)
                if value.strip()
            )
        )
        if not clients:
            raise ValueError("at least one allowed client is required")
        self.allowed_client_refs = clients
        return self


class ControlPlaneResources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_service_id: str | None = None
    toolset_id: str | None = None
    gateway_endpoint: str | None = None
    observed_version: str | None = None
    request_id: str | None = None
    service_status: str | None = None
    toolset_status: str | None = None
    live_tools_count: int | None = None
    service_created: bool = False
    toolset_created: bool = False

    @classmethod
    def from_service_response(cls, response: dict[str, Any]) -> "ControlPlaneResources":
        result = response.get("Result") or response.get("result") or {}
        service = result.get("MCPService") or result
        return cls(
            mcp_service_id=service.get("MCPServiceId") or service.get("Id"),
            request_id=(response.get("ResponseMetadata") or {}).get("RequestId"),
            service_status=service.get("Status"),
        )

    @classmethod
    def from_toolset_response(cls, response: dict[str, Any]) -> "ControlPlaneResources":
        result = response.get("Result") or response.get("result") or {}
        toolset = result.get("MCPToolset") or result
        networks = toolset.get("NetworkConfigurations") or []
        endpoint = next(
            (
                str(item.get("Endpoint") or "")
                for item in networks
                if item.get("Endpoint")
            ),
            "",
        )
        path = str(toolset.get("Path") or "/mcp")
        gateway_endpoint = (
            f"https://{endpoint.strip('/')}{path}"
            if endpoint and "://" not in endpoint
            else f"{endpoint.rstrip('/')}{path}"
            if endpoint
            else None
        )
        return cls(
            toolset_id=toolset.get("MCPToolsetId") or toolset.get("Id"),
            gateway_endpoint=gateway_endpoint,
            request_id=(response.get("ResponseMetadata") or {}).get("RequestId"),
            toolset_status=toolset.get("Status"),
        )


class GatewayVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initialize_pass: bool
    tools_list_pass: bool
    allowed_call_pass: bool
    denied_call_pass: bool
    unauthorized_client_denied: bool
    live_tools_count: int = Field(ge=0)
    observed_version: str | None = None

    @property
    def live(self) -> bool:
        return all(
            (
                self.initialize_pass,
                self.tools_list_pass,
                self.allowed_call_pass,
                self.denied_call_pass,
                self.unauthorized_client_denied,
            )
        )
