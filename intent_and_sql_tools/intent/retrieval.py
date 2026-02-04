from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel

from intent_and_sql_tools.intent.slot_catalog import SlotSpec


class DocItem(BaseModel):
    text: str
    source_query: str
    score: float | None
    slot_name: str


def retrieve_docs_for_slot(
    brain,
    slot: SlotSpec,
    seeds: list[str],
    question: str,
    per_query_topk: int = 4,
    per_slot_topk: int = 10,
) -> list[DocItem]:
    docs: list[DocItem] = []
    seen: set[str] = set()
    keywords_text = ", ".join(slot.keywords)
    queries = []
    for seed in seeds:
        if seed:
            queries.append(seed)
            queries.append(f"{slot.slot_name} {keywords_text} {seed}".strip())
    queries.append(question)
    for query in _unique_list(queries):
        result = brain._get_related_documentation(query)
        for text in _normalize_docs(result)[:per_query_topk]:
            doc_key = _hash_text(text)
            if doc_key in seen:
                continue
            seen.add(doc_key)
            docs.append(
                DocItem(text=text, source_query=query, score=None, slot_name=slot.slot_name)
            )
            if len(docs) >= per_slot_topk:
                break
        if len(docs) >= per_slot_topk:
            break
    return docs


def _normalize_docs(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, list):
        return [str(item).strip() for item in result if str(item).strip()]
    if isinstance(result, dict):
        values = []
        for value in result.values():
            if isinstance(value, list):
                values.extend([str(item).strip() for item in value if str(item).strip()])
        if values:
            return values
        return [str(result)]
    text = str(result).strip()
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines or [text]


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _unique_list(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
