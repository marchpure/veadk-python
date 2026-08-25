"""Source connector, ingestion, and Golden Data ownership boundary.

The public application is loaded lazily so canonical contract imports can use
the worker-owned models without recursively importing the BFF contract module.
"""

from typing import TYPE_CHECKING

from .models import AccessContext, GoldenContextReference

if TYPE_CHECKING:
    from .application import SourceGoldenApplication, SourcesGoldenError
    from .http_api import mount_source_golden_routes
    from .webhook_ingress import create_webhook_ingress


def __getattr__(name: str):
    if name in {"SourceGoldenApplication", "SourcesGoldenError"}:
        from .application import SourceGoldenApplication, SourcesGoldenError

        return {
            "SourceGoldenApplication": SourceGoldenApplication,
            "SourcesGoldenError": SourcesGoldenError,
        }[name]
    if name == "create_webhook_ingress":
        from .webhook_ingress import create_webhook_ingress

        return create_webhook_ingress
    if name == "mount_source_golden_routes":
        from .http_api import mount_source_golden_routes

        return mount_source_golden_routes
    raise AttributeError(name)


__all__ = [
    "AccessContext",
    "GoldenContextReference",
    "SourceGoldenApplication",
    "SourcesGoldenError",
    "create_webhook_ingress",
    "mount_source_golden_routes",
]
