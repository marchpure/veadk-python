"""Legacy payload hydration; the only Knowledge Studio legacy-key boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

def hydrate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    if not result.get("knowledge_source_refs"):
        refs = []
        seen = set()
        for key, field in (("profile_ref", "openviking_profile_ids"), ("resource_ref", "openviking_resource_refs")):
            values = payload.get(field, ())
            if isinstance(values, (list, tuple)):
                for value in values:
                    if isinstance(value, str) and value and (key, value) not in seen:
                        seen.add((key, value))
                        refs.append({"provider": "openviking", key: value})
        result["knowledge_source_refs"] = refs
    result.pop("openviking_profile_ids", None)
    result.pop("openviking_resource_refs", None)
    return result
