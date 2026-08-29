"""Vendor-neutral seam between Knowledge Studio and source extensions."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from typing import Any, Protocol


class KnowledgeContextResolver(Protocol):
    def __call__(
        self,
        actor: Any,
        profile_refs: Sequence[str],
        resource_refs: Sequence[str],
    ) -> Mapping[str, object]: ...


class AsyncKnowledgeContextResolver(Protocol):
    def __call__(
        self,
        actor: Any,
        profile_refs: Sequence[str],
        resource_refs: Sequence[str],
    ) -> Awaitable[Mapping[str, object]]: ...
