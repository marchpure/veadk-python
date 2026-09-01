"""Idempotent publication orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .client import AgentKitMcpClient, AgentKitMcpError
from .models import AgentKitMcpPublication, PublicationCreateRequest, PublicationStatus
from .repository import AgentKitMcpPublicationRepository


class AgentKitMcpPublisher:
    def __init__(
        self,
        repository: AgentKitMcpPublicationRepository,
        client: AgentKitMcpClient,
    ) -> None:
        self.repository = repository
        self.client = client

    async def create_or_reuse(
        self, *, tenant_id: str, workspace_id: str, request: PublicationCreateRequest,
        idempotency_key: str,
        existing_publication: AgentKitMcpPublication | None = None,
    ) -> AgentKitMcpPublication:
        existing = self.repository.get_by_key(
            idempotency_key, tenant_id=tenant_id, workspace_id=workspace_id
        )
        existing = existing or existing_publication
        if existing and existing.status in {
            PublicationStatus.LIVE, PublicationStatus.CODE_READY,
            PublicationStatus.DISABLED,
        }:
            return existing
        publication = existing or AgentKitMcpPublication(
            publicationId=f"pub_{uuid4().hex}",
            tenantId=tenant_id,
            workspaceId=workspace_id,
            accessPackageId=request.access_package_id,
            runtimeTokenId=request.runtime_token_id,
            backendEndpointRef=request.backend_endpoint_ref,
            inboundAuthMode=request.inbound_auth_mode,
            allowedClientRef=request.allowed_client_ref,
            desiredVersion=request.desired_version,
            status=PublicationStatus.CODE_READY,
        )
        publication.status = PublicationStatus.PROVISIONING
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(publication, idempotency_key=idempotency_key)
        try:
            resources = await self.client.publish(
                workspace_id=workspace_id,
                access_package_id=request.access_package_id,
                backend_endpoint_ref=request.backend_endpoint_ref,
                runtime_token_id=request.runtime_token_id,
                desired_version=request.desired_version,
                inbound_auth_mode=request.inbound_auth_mode,
                allowed_client_ref=request.allowed_client_ref,
                existing_service_id=publication.mcp_service_id,
                existing_toolset_id=publication.toolset_id,
            )
            publication.mcp_service_id = resources.mcp_service_id
            publication.toolset_id = resources.toolset_id
            publication.gateway_endpoint = resources.gateway_endpoint
            publication.observed_version = resources.observed_version
            publication.request_id = resources.request_id
            publication.status = PublicationStatus.LIVE if resources.gateway_endpoint else PublicationStatus.CODE_READY
            publication.last_error = None
        except AgentKitMcpError as error:
            publication.status = PublicationStatus.FAILED
            publication.last_error = str(error)
            publication.request_id = error.request_id
            if error.resources:
                publication.mcp_service_id = error.resources.mcp_service_id
                publication.toolset_id = error.resources.toolset_id
                publication.gateway_endpoint = error.resources.gateway_endpoint
                publication.observed_version = error.resources.observed_version
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(publication, idempotency_key=idempotency_key)
        return publication

    async def retry(self, publication: AgentKitMcpPublication, *, idempotency_key: str):
        request = PublicationCreateRequest(
            accessPackageId=publication.access_package_id,
            runtimeTokenId=publication.runtime_token_id,
            backendEndpointRef=publication.backend_endpoint_ref,
            desiredVersion=publication.desired_version,
            allowedClientRef=publication.allowed_client_ref,
            inboundAuthMode=publication.inbound_auth_mode,
        )
        return await self.create_or_reuse(
            tenant_id=publication.tenant_id,
            workspace_id=publication.workspace_id,
            request=request,
            idempotency_key=idempotency_key,
            existing_publication=publication,
        )

    async def disable(self, publication: AgentKitMcpPublication, *, idempotency_key: str):
        await self.client.disable(publication)
        publication.status = PublicationStatus.DISABLED
        publication.updated_at = datetime.now(timezone.utc)
        self.repository.save(publication, idempotency_key=idempotency_key)
        return publication

    async def verify(self, publication: AgentKitMcpPublication):
        return await self.client.verify(publication)
