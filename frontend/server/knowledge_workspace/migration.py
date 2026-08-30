"""Legacy payload hydration; the only Knowledge Studio legacy-key boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .source_contracts import KnowledgeSourceRef


def split_knowledge_source_refs(
    refs: object,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    profiles: list[str] = []
    resources: list[str] = []
    if isinstance(refs, (list, tuple)):
        for item in refs:
            if not isinstance(item, Mapping) or item.get("provider") != "openviking":
                continue
            profile = item.get("profile_ref")
            resource = item.get("resource_ref")
            if isinstance(profile, str) and profile and profile not in profiles:
                profiles.append(profile)
            if isinstance(resource, str) and resource and resource not in resources:
                resources.append(resource)
    return tuple(profiles), tuple(resources)


def merge_knowledge_source_refs(
    refs: object | None,
    openviking_profile_ids: object | None = None,
    openviking_resource_refs: object | None = None,
) -> tuple[KnowledgeSourceRef, ...] | None:
    if (
        refs is None
        and openviking_profile_ids is None
        and openviking_resource_refs is None
    ):
        return None

    normalized: list[KnowledgeSourceRef] = []

    def add(item: object) -> None:
        ref = KnowledgeSourceRef.model_validate(item)
        if ref not in normalized:
            normalized.append(ref)

    if isinstance(refs, (list, tuple)):
        for item in refs:
            add(item)
    elif refs is not None:
        add(refs)

    if isinstance(openviking_profile_ids, (list, tuple)):
        for value in openviking_profile_ids:
            if isinstance(value, str) and value:
                add({"provider": "openviking", "profile_ref": value})

    if isinstance(openviking_resource_refs, (list, tuple)):
        for value in openviking_resource_refs:
            if isinstance(value, str) and value:
                add({"provider": "openviking", "resource_ref": value})

    return tuple(normalized)


def hydrate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    refs = merge_knowledge_source_refs(
        result.get("knowledge_source_refs"),
        result.get("openviking_profile_ids"),
        result.get("openviking_resource_refs"),
    )
    if refs is not None:
        result["knowledge_source_refs"] = [
            item.model_dump(mode="json", exclude_none=True) for item in refs
        ]
    result.pop("openviking_profile_ids", None)
    result.pop("openviking_resource_refs", None)
    return result
