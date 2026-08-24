"""Source connector, ingestion, and Golden Data ownership boundary.

The public application is loaded lazily so canonical contract imports can use
the worker-owned models without recursively importing the BFF contract module.
"""

from .models import AccessContext


def __getattr__(name: str):
    if name in {"SourceGoldenApplication", "SourcesGoldenError"}:
        from .application import SourceGoldenApplication, SourcesGoldenError

        return {
            "SourceGoldenApplication": SourceGoldenApplication,
            "SourcesGoldenError": SourcesGoldenError,
        }[name]
    raise AttributeError(name)

__all__ = [
    "AccessContext",
    "SourceGoldenApplication",
    "SourcesGoldenError",
]
