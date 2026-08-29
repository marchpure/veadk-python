"""Authorized Connection resource projection for OpenViking imports."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import HTTPException

from frontend.server.knowledge_workspace.service import Actor


class KnowledgeResourceService(Protocol):
    repository: Any

    @staticmethod
    def _public_value(value: object) -> object: ...


class ConnectionResourceGateway(Protocol):
    async def get_adapter_resource(
        self,
        resource_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
        principal_id: str,
    ) -> dict[str, Any]: ...


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sensitive_names = {
            "apikey",
            "authorization",
            "baseurl",
            "credential",
            "credentials",
            "downloadurl",
            "password",
            "privatekey",
            "secret",
            "token",
        }
        return {
            str(key): _safe_metadata(item)
            for key, item in value.items()
            if not any(
                marker
                in "".join(
                    character
                    for character in str(key).casefold()
                    if character.isalnum()
                )
                for marker in sensitive_names
            )
        }
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item) for item in value]
    return value


async def resolve_connection_resource(
    actor: Actor,
    resource_id: str,
    *,
    knowledge_service: KnowledgeResourceService,
    connection_gateway: ConnectionResourceGateway | None,
) -> dict[str, Any]:
    resource = knowledge_service.repository.get_resource(
        resource_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
    )
    if resource is None or not resource.adapter_resource_id:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": "Connection resource not found",
            },
        )
    if connection_gateway is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CONNECTION_SERVICE_UNAVAILABLE",
                "message": "Connection Service is not configured",
            },
        )

    # Re-authorize the adapter projection for the current actor before exposing
    # the BFF-owned, secret-filtered description to OpenViking.
    await connection_gateway.get_adapter_resource(
        resource.adapter_resource_id,
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
        principal_id=actor.principal_id,
    )
    return {
        "kind": str(resource.kind),
        "display_name": resource.display_name,
        "description": _safe_metadata(
            knowledge_service._public_value(resource.metadata)
        ),
    }
