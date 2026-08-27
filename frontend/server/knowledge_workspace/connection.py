"""Connection invocation-context port owned by the BFF boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field


class EphemeralConnectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: str = Field(min_length=1, max_length=256)
    connection_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    allowed_actions: tuple[str, ...] = Field(min_length=1, max_length=128)
    expires_at: datetime
    runtime_ref: str = Field(min_length=1, max_length=2_048)


class ConnectionInvocationContextPort(Protocol):
    async def issue(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
        invocation_id: str,
        connection_ids: Sequence[str],
        allowed_actions: Sequence[str],
        ttl_seconds: int,
    ) -> EphemeralConnectionContext:
        """Issue a short-lived, invocation-bound least-privilege context."""

    async def revoke(self, lease_id: str) -> None:
        """Revoke the context at invocation termination."""

