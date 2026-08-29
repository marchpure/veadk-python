"""Small host-facing contracts for the OpenViking extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class KnowledgeSourceRef:
    provider: str
    profile_ref: str | None = None
    resource_ref: str | None = None
    version: str | None = None
    etag: str | None = None


class KnowledgeContextResolver(Protocol):
    def __call__(
        self, actor: Any, refs: Sequence[KnowledgeSourceRef]
    ) -> Mapping[str, object]: ...
