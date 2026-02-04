from __future__ import annotations

import difflib
from typing import Any

from intent_and_sql_tools.intent.slot_catalog import SlotCatalog
from intent_and_sql_tools.intent.retrieval import DocItem


def rerank_docs_by_slot(
    docs_by_slot: dict[str, list[DocItem]],
    slot_catalog: SlotCatalog,
    per_slot_min: int = 3,
    max_total_items: int = 40,
    max_chars: int = 8000,
) -> list[str]:
    blocks: list[str] = []
    total_items = 0
    total_chars = 0
    for slot in slot_catalog.sorted_slots():
        slot_docs = docs_by_slot.get(slot.slot_name, [])
        if not slot_docs:
            continue
        deduped = _dedupe_docs(slot_docs)
        if slot.priority_label() == "high":
            selected = deduped[: max(per_slot_min, 1)]
        else:
            selected = deduped
        if not selected:
            continue
        block_lines = [f"[SLOT: {slot.slot_name} | desc: {slot.slot_desc or ''}]"]
        for doc in selected:
            if total_items >= max_total_items:
                break
            line = f"- {doc.text}"
            if total_chars + len(line) > max_chars:
                break
            block_lines.append(line)
            total_items += 1
            total_chars += len(line)
        if len(block_lines) > 1:
            blocks.append("\n".join(block_lines))
        if total_items >= max_total_items or total_chars >= max_chars:
            break
    return blocks


def _dedupe_docs(docs: list[DocItem], threshold: float = 0.9) -> list[DocItem]:
    result: list[DocItem] = []
    for doc in docs:
        if _is_redundant(doc.text, [d.text for d in result], threshold):
            continue
        result.append(doc)
    return result


def _is_redundant(text: str, existing: list[str], threshold: float) -> bool:
    for other in existing:
        ratio = difflib.SequenceMatcher(a=text, b=other).ratio()
        if ratio >= threshold:
            return True
    return False
