"""Server-owned OpenViking profile and operation boundary."""

from .connection_resource import resolve_connection_resource
from .routes import mount_openviking_routes
from .register import register_openviking
from .service import (
    OpenVikingConfig,
    OpenVikingProfileRepository,
    OpenVikingService,
)

__all__ = [
    "OpenVikingConfig",
    "OpenVikingProfileRepository",
    "OpenVikingService",
    "mount_openviking_routes",
    "resolve_connection_resource",
    "register_openviking",
]
