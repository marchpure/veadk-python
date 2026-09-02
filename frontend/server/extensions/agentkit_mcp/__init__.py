"""BFF adapter for publishing a data-workshop MCP toolset to AgentKit."""

from .client import AgentKitMcpClient, AgentKitMcpError
from .models import (
    AgentKitMcpPublication,
    GatewayVerification,
    PublicationCreateRequest,
    PublicationStatus,
)
from .repository import AgentKitMcpPublicationRepository
from .routes import mount_agentkit_mcp_routes, mount_managed_mcp_routes
from .credential import IdentityApiKeyCredentialProvider
from .domain_repository import ManagedPublicationRepository
from .managed_service import ManagedPublicationService
from .service import AgentKitMcpPublisher
from .verifier import IdentityM2MGatewayVerifier

__all__ = [
    "AgentKitMcpClient",
    "AgentKitMcpError",
    "AgentKitMcpPublication",
    "AgentKitMcpPublicationRepository",
    "AgentKitMcpPublisher",
    "GatewayVerification",
    "IdentityM2MGatewayVerifier",
    "IdentityApiKeyCredentialProvider",
    "ManagedPublicationRepository",
    "ManagedPublicationService",
    "PublicationCreateRequest",
    "PublicationStatus",
    "mount_agentkit_mcp_routes",
    "mount_managed_mcp_routes",
]
