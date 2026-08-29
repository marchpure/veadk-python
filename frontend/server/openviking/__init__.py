"""Server-owned OpenViking profile and operation boundary."""

from .routes import mount_openviking_routes
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
]
