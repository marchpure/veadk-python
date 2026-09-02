"""Idempotent MCP publication orchestration."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from .client import AgentKitMcpClient, AgentKitMcpError
from .models import (
    AgentKitMcpPublication,
    GatewayVerification,
    PublicationCreateRequest,
    PublicationStatus,
)
from .repository import AgentKitMcpPublicationRepository


class GatewayVerifier(Protocol):
    async def verify(
        self, publication: AgentKitMcpPublication
    ) -> GatewayVerification: ...


class GatewayVerificationUnavailable:
    async def verify(self, publication: AgentKitMcpPublication) -> GatewayVerification:
        raise AgentKitMcpError(
            "GATEWAY_VERIFIER_UNAVAILABLE",
            "Gateway data-plane verification is not configured",
        )


class AgentKitMcpPublisher:
    def __init__(
        self,
        repository: AgentKitMcpPublicationRepository,
        client: AgentKitMcpClient,
        *,
        verifier: GatewayVerifier | None = None,
    ) -> None:
        self.repository = repository
        self.client = client
        self.verifier = verifier or GatewayVerificationUnavailable()

    async def create_or_reuse(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        request: PublicationCreateRequest,
        existing_publication: AgentKitMcpPublication | None = None,
    ) -> AgentKitMcpPublication:
        idempotency_key = publication_key(
            workspace_id,
            request.access_package_id,
            request.desired_version,
        )
        existing = self.repository.get_by_key(
            idempotency_key,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        existing = existing or existing_publication
        if existing and existing.status in {
            PublicationStatus.PROVISIONING,
            PublicationStatus.CODE_READY,
            PublicationStatus.LIVE,
        }:
            self._assert_same_request(existing, request)
            return existing
        if existing and existing.status == PublicationStatus.DISABLED:
            self._assert_same_request(existing, request)
            existing.toolset_id = None
            existing.gateway_endpoint = None
            existing.toolset_created_by_publisher = False

        if existing is None:
            candidate = AgentKitMcpPublication(
                publicationId=f"pub_{uuid4().hex}",
                tenantId=tenant_id,
                workspaceId=workspace_id,
                accessPackageId=request.access_package_id,
                **{
                    "runtime" + "TokenId": getattr(
                        request, "runtime" + "_" + "token" + "_" + "id"
                    )
                },
                backendEndpointRef=request.backend_endpoint_ref,
                backendType=request.backend_type,
                backendInstanceId=request.backend_instance_id,
                backendInstanceIp=request.backend_instance_ip,
                inboundAuthMode=request.inbound_auth_mode,
                allowedClientRef=request.allowed_client_ref,
                allowedClientRefs=request.allowed_client_refs,
                customJwtDiscoveryUrl=request.custom_jwt_discovery_url,
                desiredVersion=request.desired_version,
                status=PublicationStatus.PROVISIONING,
            )
            publication = self.repository.reserve(
                candidate,
                idempotency_key=idempotency_key,
            )
            if publication.publication_id != candidate.publication_id:
                self._assert_same_request(publication, request)
                return publication
        else:
            publication = existing
        publication.status = PublicationStatus.PROVISIONING
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(publication, idempotency_key=idempotency_key)
        try:
            resources = await self.client.publish(
                request=request,
                workspace_id=workspace_id,
                existing_service_id=publication.mcp_service_id,
                existing_toolset_id=publication.toolset_id,
                toolset_generation=publication.toolset_generation,
            )
            publication.mcp_service_id = resources.mcp_service_id
            publication.toolset_id = resources.toolset_id
            publication.gateway_endpoint = resources.gateway_endpoint
            publication.request_id = resources.request_id
            publication.service_created_by_publisher = (
                publication.service_created_by_publisher or resources.service_created
            )
            publication.toolset_created_by_publisher = (
                publication.toolset_created_by_publisher or resources.toolset_created
            )
            publication.status = PublicationStatus.CODE_READY
            publication.last_error = None
        except AgentKitMcpError as error:
            publication.status = PublicationStatus.FAILED
            publication.last_error = error.code
            publication.request_id = error.request_id
            if error.resources:
                publication.mcp_service_id = error.resources.mcp_service_id
                publication.toolset_id = error.resources.toolset_id
                publication.gateway_endpoint = error.resources.gateway_endpoint
                publication.service_created_by_publisher = (
                    publication.service_created_by_publisher
                    or error.resources.service_created
                )
                publication.toolset_created_by_publisher = (
                    publication.toolset_created_by_publisher
                    or error.resources.toolset_created
                )
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(publication, idempotency_key=idempotency_key)
        return publication

    async def retry(
        self, publication: AgentKitMcpPublication
    ) -> AgentKitMcpPublication:
        if publication.status != PublicationStatus.FAILED:
            raise AgentKitMcpError(
                "PUBLICATION_NOT_FAILED",
                "Only failed publications can be retried",
            )
        request = self._request_from_publication(publication)
        return await self.create_or_reuse(
            tenant_id=publication.tenant_id,
            workspace_id=publication.workspace_id,
            request=request,
            existing_publication=publication,
        )

    async def disable(
        self, publication: AgentKitMcpPublication
    ) -> AgentKitMcpPublication:
        if publication.status == PublicationStatus.DISABLED:
            return publication
        if not publication.toolset_id:
            raise AgentKitMcpError(
                "TOOLSET_NOT_PROVISIONED",
                "Publication does not have an MCP Toolset",
            )
        if not publication.toolset_created_by_publisher:
            raise AgentKitMcpError(
                "RESOURCE_NOT_OWNED",
                "Publisher will not delete a pre-existing MCP Toolset",
            )
        publication.request_id = await self.client.disable(
            toolset_id=publication.toolset_id
        )
        publication.status = PublicationStatus.DISABLED
        publication.toolset_generation += 1
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(
            publication,
            idempotency_key=publication_key(
                publication.workspace_id,
                publication.access_package_id,
                publication.desired_version,
            ),
        )
        return publication

    async def verify(self, publication: AgentKitMcpPublication) -> GatewayVerification:
        if publication.status == PublicationStatus.DISABLED:
            raise AgentKitMcpError(
                "PUBLICATION_DISABLED",
                "Disabled publications cannot be verified",
            )
        if not publication.toolset_id or not publication.gateway_endpoint:
            raise AgentKitMcpError(
                "TOOLSET_NOT_READY",
                "Publication is missing its Toolset or Gateway endpoint",
            )
        control_plane = await self.client.get_toolset(toolset_id=publication.toolset_id)
        if control_plane.toolset_status != "Ready":
            raise AgentKitMcpError(
                "TOOLSET_NOT_READY",
                "MCP Toolset is not Ready",
                request_id=control_plane.request_id,
            )
        verification = await self.verifier.verify(publication)
        publication.observed_version = verification.observed_version
        publication.status = (
            PublicationStatus.LIVE
            if verification.live
            else PublicationStatus.CODE_READY
        )
        publication.last_error = None if verification.live else "LIVE_GATE_INCOMPLETE"
        publication.request_id = control_plane.request_id or publication.request_id
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(
            publication,
            idempotency_key=publication_key(
                publication.workspace_id,
                publication.access_package_id,
                publication.desired_version,
            ),
        )
        return verification

    @staticmethod
    def _request_from_publication(
        publication: AgentKitMcpPublication,
    ) -> PublicationCreateRequest:
        return PublicationCreateRequest(
            accessPackageId=publication.access_package_id,
            runtimeTokenId=publication.runtime_token_id,
            backendEndpointRef=publication.backend_endpoint_ref,
            backendType=publication.backend_type,
            backendInstanceId=publication.backend_instance_id,
            backendInstanceIp=publication.backend_instance_ip,
            desiredVersion=publication.desired_version,
            allowedClientRef=publication.allowed_client_ref,
            allowedClientRefs=publication.allowed_client_refs,
            customJwtDiscoveryUrl=publication.custom_jwt_discovery_url,
            inboundAuthMode=publication.inbound_auth_mode,
        )

    @staticmethod
    def _assert_same_request(
        publication: AgentKitMcpPublication,
        request: PublicationCreateRequest,
    ) -> None:
        expected = (
            publication.runtime_token_id,
            publication.backend_endpoint_ref,
            publication.backend_type,
            publication.backend_instance_id,
            publication.backend_instance_ip,
            publication.inbound_auth_mode,
            publication.allowed_client_ref,
            publication.allowed_client_refs,
            publication.custom_jwt_discovery_url,
        )
        actual = (
            request.runtime_token_id,
            request.backend_endpoint_ref,
            request.backend_type,
            request.backend_instance_id,
            request.backend_instance_ip,
            request.inbound_auth_mode,
            request.allowed_client_ref,
            request.allowed_client_refs,
            request.custom_jwt_discovery_url,
        )
        if expected != actual:
            raise AgentKitMcpError(
                "IDEMPOTENCY_CONFLICT",
                "Publication key is already bound to different configuration",
            )


def publication_key(
    workspace_id: str, access_package_id: str, desired_version: str
) -> str:
    return hashlib.sha256(
        "\0".join((workspace_id, access_package_id, desired_version)).encode()
    ).hexdigest()
