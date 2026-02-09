from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class SlotSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    slot_name: str
    slot_desc: str | None = None
    priority: str | int | None = None
    keywords: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)

    def priority_label(self) -> str:
        value = self.priority
        if value is None:
            return "medium"
        if isinstance(value, int):
            if value <= 1:
                return "high"
            if value == 2:
                return "medium"
            return "low"
        text = str(value).strip().lower()
        mapping = {
            "high": "high",
            "medium": "medium",
            "low": "low",
            "p0": "high",
            "p1": "medium",
            "p2": "low",
        }
        return mapping.get(text, "medium")


class SlotCatalog(BaseModel):
    slots: list[SlotSpec]

    def get(self, slot_name: str) -> SlotSpec | None:
        for slot in self.slots:
            if slot.slot_name == slot_name:
                return slot
        return None

    def high_priority_slots(self) -> list[SlotSpec]:
        return [slot for slot in self.slots if slot.priority_label() == "high"]

    def keywords_text(self, slot_name: str) -> str:
        slot = self.get(slot_name)
        if not slot:
            return ""
        return ", ".join(slot.keywords)

    def sorted_slots(self) -> list[SlotSpec]:
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(self.slots, key=lambda s: order.get(s.priority_label(), 1))


def load_slot_catalog(path: str) -> SlotCatalog:
    content = Path(path).read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, dict) and "slots" in data:
        slots = data["slots"]
    else:
        slots = data
    if not isinstance(slots, list):
        raise ValueError("slot_catalog must contain slots list")
    parsed = [SlotSpec.model_validate(item) for item in slots if isinstance(item, dict)]
    return SlotCatalog(slots=parsed)
