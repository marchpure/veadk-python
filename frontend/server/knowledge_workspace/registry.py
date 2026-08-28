"""Cross-Agent publication registry boundary.

STEP 2C only defines this port.  The registry implementation and its Agent
ACLs remain owned by the surrounding Studio/Agent platform.
"""

from __future__ import annotations

from typing import Mapping, Protocol, Any


class PublicationRegistryPort(Protocol):
    def register_publication(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        publication_id: str,
        revision_id: str,
        skill_name: str,
        revision_sha256: str,
        artifact_sha256: tuple[str, ...],
        target_space: str,
        published_by: str,
        policy_snapshot: Mapping[str, Any],
    ) -> None:
        """Register a fixed revision for cross-Agent discovery.

        Implementations must enforce their own Agent grants and idempotency.
        Consumers still reauthorize Connection access at invocation time.
        """
