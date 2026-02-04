from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, Field

from intent_and_sql_tools.intent.slot_catalog import SlotCatalog, SlotSpec
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.utils.json_repair import parse_json


class SlotTriggerSlot(BaseModel):
    slot_name: str
    seeds: list[str] = Field(default_factory=list)
    reason: str | None = None


class SlotTriggerResult(BaseModel):
    selected_slots: list[SlotTriggerSlot]
    global_spans: list[str] = Field(default_factory=list)
    confidence: float | None = None


def run_slot_trigger(
    question: str,
    slot_catalog: SlotCatalog,
    llm_call: Callable[[list[dict[str, str]]], str],
    top_k: int = 5,
) -> SlotTriggerResult:
    slot_summary = _summarize_slots(slot_catalog)
    system_prompt = (
        "You are a slot trigger engine. "
        "Given a user query and slot catalog summary, select the most relevant slots. "
        "Return JSON only with fields: selected_slots, global_spans, confidence. "
        "selected_slots is a list of {slot_name, seeds, reason}. "
        "Split query into spans and assign spans to slots as seeds."
    )
    user_payload = {
        "query": question,
        "slots": slot_summary,
        "top_k": top_k,
        "rules": [
            "selected_slots must be size 3-6",
            "include high priority slots if strongly related",
        ],
    }
    raw = llm_call(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
    )
    print(f"[slot_trigger] raw {raw}")
    parsed = parse_json(raw)
    print(f"[slot_trigger] parsed_type {type(parsed).__name__}")
    if isinstance(parsed, list):
        parsed = {"selected_slots": parsed}
    elif isinstance(parsed, dict) and "selected_slots" not in parsed and "slot_name" in parsed:
        parsed = {"selected_slots": [parsed]}
    if not isinstance(parsed, dict):
        print("[slot_trigger] fallback_reason invalid_json")
        return _fallback_result(question, slot_catalog)
    result = _normalize_result(parsed, slot_catalog, question)
    return result


def _normalize_result(
    parsed: dict[str, Any],
    slot_catalog: SlotCatalog,
    question: str,
) -> SlotTriggerResult:
    selected = parsed.get("selected_slots")
    if not isinstance(selected, list):
        print("[slot_trigger] fallback_reason missing_selected_slots")
        return _fallback_result(question, slot_catalog)
    slots: list[SlotTriggerSlot] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        slot_name = str(item.get("slot_name") or "").strip()
        if not slot_name:
            continue
        seeds = [str(s).strip() for s in item.get("seeds", []) if str(s).strip()]
        reason = str(item.get("reason") or "").strip() or None
        slots.append(SlotTriggerSlot(slot_name=slot_name, seeds=seeds, reason=reason))
    slots = _ensure_high_priority(slots, slot_catalog, question)
    slots = _ensure_seeds(slots, question)
    if len(slots) > 6:
        slots = slots[:6]
    if len(slots) < 3:
        print("[slot_trigger] fallback_reason too_few_slots")
        slots = _fallback_result(question, slot_catalog).selected_slots
    global_spans = [
        str(s).strip()
        for s in parsed.get("global_spans", [])
        if isinstance(s, (str, int, float)) and str(s).strip()
    ]
    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None
    return SlotTriggerResult(selected_slots=slots, global_spans=global_spans, confidence=confidence)


def _summarize_slots(slot_catalog: SlotCatalog) -> list[dict[str, Any]]:
    summary = []
    for slot in slot_catalog.slots:
        summary.append(
            {
                "slot_name": slot.slot_name,
                "slot_desc": slot.slot_desc,
                "priority": slot.priority_label(),
                "keywords": slot.keywords[:8],
                "examples": slot.examples[:5],
            }
        )
    return summary


def _fallback_result(question: str, slot_catalog: SlotCatalog) -> SlotTriggerResult:
    slots = [
        SlotTriggerSlot(slot_name=slot.slot_name, seeds=[question], reason="fallback")
        for slot in slot_catalog.high_priority_slots()
    ]
    if not slots:
        slots = [SlotTriggerSlot(slot_name=slot.slot_name, seeds=[question]) for slot in slot_catalog.slots[:3]]
    return SlotTriggerResult(selected_slots=slots, global_spans=[question], confidence=None)


def _ensure_seeds(slots: list[SlotTriggerSlot], question: str) -> list[SlotTriggerSlot]:
    for slot in slots:
        if not slot.seeds:
            slot.seeds = [question]
    return slots


def _ensure_high_priority(
    slots: list[SlotTriggerSlot],
    slot_catalog: SlotCatalog,
    question: str,
) -> list[SlotTriggerSlot]:
    selected_names = {slot.slot_name for slot in slots}
    for high_slot in slot_catalog.high_priority_slots():
        if high_slot.slot_name in selected_names:
            continue
        if _matches_slot(high_slot, question):
            slots.append(SlotTriggerSlot(slot_name=high_slot.slot_name, seeds=[question], reason="priority_match"))
            selected_names.add(high_slot.slot_name)
    return slots


def _matches_slot(slot: SlotSpec, question: str) -> bool:
    q = question.lower()
    for kw in slot.keywords + slot.examples:
        if kw and str(kw).lower() in q:
            return True
    return False
