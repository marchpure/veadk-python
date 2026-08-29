"""One-way compatibility conversion for legacy Knowledge Studio payloads."""

from __future__ import annotations

from collections.abc import Mapping

from .contracts import KnowledgeSourceRef


def knowledge_source_refs(payload: Mapping[str, object]) -> tuple[KnowledgeSourceRef, ...]:
    """Read legacy OpenViking arrays while emitting one stable opaque ref list."""
    refs: list[KnowledgeSourceRef] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    profiles = payload.get("openviking_profile_ids", ())
    resources = payload.get("openviking_resource_refs", ())
    if isinstance(profiles, (list, tuple)):
        for profile in profiles:
            if isinstance(profile, str) and profile:
                key = ("openviking", profile, None)
                if key not in seen:
                    seen.add(key)
                    refs.append(KnowledgeSourceRef(provider="openviking", profile_ref=profile))
    if isinstance(resources, (list, tuple)):
        for resource in resources:
            if isinstance(resource, str) and resource:
                key = ("openviking", None, resource)
                if key not in seen:
                    seen.add(key)
                    refs.append(KnowledgeSourceRef(provider="openviking", resource_ref=resource))
    return tuple(refs)
