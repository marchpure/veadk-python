"""Composition-root registration for the OpenViking extension."""

from __future__ import annotations

import os
from functools import partial
from typing import Any

from .connection_resource import resolve_connection_resource
from .routes import mount_openviking_routes
from .service import OpenVikingConfig, OpenVikingProfileRepository, OpenVikingService


def register_openviking(
    app: Any,
    *,
    knowledge_service: Any,
    actor_resolver: Any,
    connection_gateway: Any,
) -> OpenVikingService:
    """Create and mount the extension with one host-facing registration call."""
    service = OpenVikingService(
        OpenVikingProfileRepository(
            os.getenv("OPENVIKING_PROFILE_DATABASE", ".veadk/openviking-profiles.sqlite3")
        ),
        OpenVikingConfig.from_env(),
    )
    knowledge_service.knowledge_context_resolver = lambda actor, profiles, refs: service.creator_context(
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
        profile_ids=tuple(profiles),
        resource_refs=tuple(refs),
    )
    knowledge_service.knowledge_content_resolver = lambda actor, profiles, refs: service.resolved_creator_context(
        tenant_id=actor.tenant_id,
        workspace_id=actor.workspace_id,
        profile_ids=tuple(profiles),
        resource_refs=tuple(refs),
    )
    mount_openviking_routes(
        app,
        service,
        actor_resolver=actor_resolver,
        connection_resource_resolver=partial(
            resolve_connection_resource,
            knowledge_service=knowledge_service,
            connection_gateway=connection_gateway,
        ),
    )
    return service
