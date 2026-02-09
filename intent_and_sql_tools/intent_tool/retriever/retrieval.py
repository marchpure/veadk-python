from __future__ import annotations

import hashlib
import os
import threading
from typing import Any
import re

from pydantic import BaseModel

from intent_and_sql_tools.intent_tool.retriever.slot_catalog import SlotSpec
from intent_and_sql_tools.vikingdb_knowledge_backend import VikingDBKnowledgeBackend


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
    min_score: float = 0.5,
) -> list[DocItem]:
    docs: list[DocItem] = []
    seen: set[str] = set()
    queries = []
    for seed in seeds:
        if seed:
            queries.append(seed)
    for query in _unique_list(queries):
        if slot.slot_name == "time_duration" or _is_time_duration_query(query):
            continue
        kb_name = os.getenv("INTENT_VIKING_KB_NAME", "test_factor_haoxingjun")
        results = search_kb(kb_name, query, per_query_topk)
        for item in results:
            text = _extract_kb_text(item)
            if not text:
                continue
            score = _extract_kb_score(item)
            if score is not None and score < min_score:
                continue
            doc_key = _hash_text(text)
            if doc_key in seen:
                continue
            seen.add(doc_key)
            docs.append(DocItem(text=text, source_query=query, score=score, slot_name=slot.slot_name))
            if len(docs) >= per_slot_topk:
                break
        if len(docs) >= per_slot_topk:
            break
    return docs


_BACKEND_LOCK = threading.Lock()
_BACKENDS: dict[str, VikingDBKnowledgeBackend] = {}


def _get_backend(name: str) -> VikingDBKnowledgeBackend:
    with _BACKEND_LOCK:
        backend = _BACKENDS.get(name)
        if backend is None:
            backend = VikingDBKnowledgeBackend(index=name)
            _BACKENDS[name] = backend
        return backend


def _build_rerank_instruction(time_window: str | None) -> str:
    base = os.getenv("VIKING_RERANK_INSTRUCTION", "").strip() or "Please rerank by relevance."
    if not time_window:
        return base
    return f"{base}; time_window must match: {time_window}"


def search_kb(kb_name: str, query: str, topk: int, time_window: str | None = None) -> list[dict]:
    backend = _get_backend(kb_name)
    response = backend._do_request(
        body={
            "project": backend.volcengine_project,
            "name": backend.index,
            "query": query,
            "limit": int(topk),
            "post_processing": {
                "rerank_switch": True,
                "rerank_instruction": _build_rerank_instruction(time_window),
            },
        },
        path="/api/knowledge/collection/search_knowledge",
        method="POST",
    )
    results = response.get("result_list")
    if results is None:
        results = response.get("data", {}).get("result_list", [])
    return results


def _extract_kb_text(item: Any) -> str | None:
    if isinstance(item, dict):
        text = item.get("content") or item.get("chunk_content") or item.get("text")
        if text:
            return str(text).strip()
    if isinstance(item, str):
        text = item.strip()
        return text or None
    return None


def _extract_kb_score(item: Any) -> float | None:
    if isinstance(item, dict):
        value = item.get("rerank_score")
        if value is None:
            value = item.get("score")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


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


def _is_time_duration_query(query: str) -> bool:
    text = query.strip()
    if not text:
        return True
    return re.fullmatch(r"\d{1,3}日", text) is not None
