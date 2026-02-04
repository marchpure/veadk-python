from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SlotSignatureHint(BaseModel):
    top_terms: list[str] = Field(default_factory=list)
    summary: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class SlotDefinition(BaseModel):
    slot_id: str
    slot_name: str
    slot_desc: str
    value_type: Literal["single", "multi", "struct"]
    priority: Literal["high", "medium", "low"]
    keywords: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    slot_signature_hint: SlotSignatureHint | None = None


class SlotCatalog(BaseModel):
    slots: list[SlotDefinition]
