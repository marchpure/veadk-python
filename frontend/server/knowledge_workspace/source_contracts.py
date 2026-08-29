"""Vendor-neutral seam between Knowledge Studio and source extensions."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSourceRef(BaseModel):
    """Opaque, provider-neutral reference persisted by Knowledge Studio."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str = Field(min_length=1, max_length=80)
    profile_ref: str | None = Field(default=None, max_length=512)
    resource_ref: str | None = Field(default=None, max_length=2_048)
    version: str | None = Field(default=None, max_length=256)
    etag: str | None = Field(default=None, max_length=256)
    metadata: dict[str, str] | None = None


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
