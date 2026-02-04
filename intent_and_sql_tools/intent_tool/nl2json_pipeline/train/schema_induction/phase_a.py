from __future__ import annotations

import concurrent.futures
import json
import re
from pathlib import Path
from typing import Any

from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.config import (
    PipelineConfig,
)
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.io.term_loader import (
    TermEntry,
    iter_batches,
    load_terms,
)
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.llm.ark_client import ArkClient
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.schema.slot_catalog import (
    SlotCatalog,
    SlotDefinition,
    SlotSignatureHint,
)


def run_schema_induction_phase_a(
    config: PipelineConfig,
    llm_client: ArkClient | None = None,
) -> SlotCatalog:
    terms = load_terms(config.term_source)
    if not terms:
        raise ValueError("Term source is empty")
    print(f"[schema_phase_a] loaded_terms={len(terms)} batch_size={config.schema_induction_phase_a.batch_size}")
    llm_client = llm_client or ArkClient(config.llm)
    batch_summaries = _summarize_batches(terms, config, llm_client)
    print(f"[schema_phase_a] batch_summaries={len(batch_summaries)}")
    catalog = _build_final_catalog(batch_summaries, config, llm_client)
    output_path = config.schema_induction_phase_a.output_path or _default_output_path()
    _write_catalog(Path(output_path), catalog)
    print(f"[schema_phase_a] output={output_path} slots={len(catalog.slots)}")
    return catalog


def _summarize_batches(
    terms: list[TermEntry],
    config: PipelineConfig,
    llm_client: ArkClient,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    batches = list(iter_batches(terms, config.schema_induction_phase_a.batch_size))
    max_batches = config.schema_induction_phase_a.max_batches
    if max_batches is not None:
        batches = batches[:max_batches]
    total = len(batches)
    print(f"[schema_phase_a] batch_count={total}")
    for index, batch in enumerate(batches, start=1):
        print(f"[schema_phase_a] batch_start {index}/{total} size={len(batch)}")

    if llm_client is not None and not isinstance(llm_client, ArkClient):
        for index, batch in enumerate(batches, start=1):
            summary = _summarize_single_batch(index, total, batch, llm_client, config)
            if summary is None:
                print(f"[schema_phase_a] batch_skip {index}/{total} error=stub_failed")
                continue
            print(f"[schema_phase_a] batch_done {index}/{total} candidates={len(summary)}")
            summaries.append({"batch_size": len(batch), "candidates": summary})
        return summaries

    def _process_batch(batch_index: int, batch_terms: list[TermEntry]) -> tuple[int, list[dict[str, Any]] | None, str | None]:
        client = ArkClient(config.llm)
        summary = _summarize_single_batch(batch_index, total, batch_terms, client, config)
        if summary is None:
            return batch_index, None, "Batch summary failed"
        return batch_index, summary, None

    max_workers = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_batch, index, batch)
            for index, batch in enumerate(batches, start=1)
        ]
        for future in concurrent.futures.as_completed(futures):
            batch_index, summary, error = future.result()
            if summary is None:
                print(f"[schema_phase_a] batch_skip {batch_index}/{total} error={error}")
                continue
            print(f"[schema_phase_a] batch_done {batch_index}/{total} candidates={len(summary)}")
            summaries.append({"batch_size": len(batches[batch_index - 1]), "candidates": summary})
    return summaries


def _summarize_single_batch(
    batch_index: int,
    total: int,
    batch_terms: list[TermEntry],
    llm_client: Any,
    config: PipelineConfig,
) -> list[dict[str, Any]] | None:
    messages = _build_batch_prompt(batch_terms)
    last_error: Exception | None = None
    for attempt in range(1, config.llm.max_retries + 1):
        raw = None
        try:
            if hasattr(llm_client, "complete_json_with_raw"):
                raw_text, raw = llm_client.complete_json_with_raw(messages)
                print(f"[schema_phase_a] batch_raw {batch_index}/{total} attempt={attempt} {raw_text}")
            else:
                raw = llm_client.complete_json(messages)
            if raw is None:
                raise ValueError("Batch summary parse failed")
            summary = _normalize_candidates(raw)
            return summary
        except Exception as exc:
            last_error = exc
            raw_info = _describe_json(raw) if "raw" in locals() else "raw=unavailable"
            print(
                f"[schema_phase_a] batch_retry {batch_index}/{total} attempt={attempt} error={exc} {raw_info}"
            )
    return None


def _build_final_catalog(
    batch_summaries: list[dict[str, Any]],
    config: PipelineConfig,
    llm_client: ArkClient,
) -> SlotCatalog:
    min_slots = config.schema_induction_phase_a.min_slots
    max_slots = config.schema_induction_phase_a.max_slots
    last_error: Exception | None = None
    for attempt in range(1, config.llm.max_retries + 1):
        print(f"[schema_phase_a] final_catalog_attempt {attempt}")
        messages = _build_final_prompt(batch_summaries, min_slots, max_slots)
        if hasattr(llm_client, "complete_json_with_raw"):
            raw_text, result = llm_client.complete_json_with_raw(messages)
        else:
            raw_text = ""
            result = llm_client.complete_json(messages)
        if result is None:
            if raw_text:
                print(f"[schema_phase_a] final_catalog_raw attempt={attempt} {raw_text}")
            last_error = ValueError("Final catalog parse failed")
            continue
        try:
            catalog = _normalize_catalog(result)
        except Exception as exc:
            last_error = exc
            print(f"[schema_phase_a] final_catalog_invalid attempt={attempt} error={exc}")
            continue
        if min_slots <= len(catalog.slots) <= max_slots:
            return catalog
        print(f"[schema_phase_a] final_catalog_out_of_range attempt={attempt} slots={len(catalog.slots)}")
        last_error = ValueError("Slot count out of range")
    if last_error:
        raise last_error
    raise ValueError("Failed to build slot catalog")


def _normalize_catalog(result: Any) -> SlotCatalog:
    if isinstance(result, dict) and "slots" in result:
        slots = result.get("slots")
    else:
        slots = result
    if not isinstance(slots, list):
        raise ValueError("Slot catalog must contain a slots array")
    normalized: list[SlotDefinition] = []
    for raw in slots:
        if not isinstance(raw, dict):
            continue
        slot_name = _to_snake_case(str(raw.get("slot_name") or raw.get("name") or "").strip())
        if not slot_name:
            continue
        slot_desc = str(raw.get("slot_desc") or raw.get("desc") or slot_name).strip()
        value_type = _normalize_value_type(raw.get("value_type"))
        priority = _normalize_priority(raw.get("priority"))
        keywords = _listify(raw.get("keywords"))
        examples = _listify(raw.get("examples"))
        signature = raw.get("slot_signature_hint") or {}
        signature_hint = SlotSignatureHint(
            top_terms=_listify(signature.get("top_terms")) if isinstance(signature, dict) else keywords[:5],
            summary=str(signature.get("summary")) if isinstance(signature, dict) and signature.get("summary") else None,
            extras=signature if isinstance(signature, dict) else {},
        )
        slot_id = _normalize_slot_id(raw.get("slot_id"), slot_name)
        normalized.append(
            SlotDefinition(
                slot_id=slot_id,
                slot_name=slot_name,
                slot_desc=slot_desc,
                value_type=value_type,
                priority=priority,
                keywords=keywords,
                examples=examples,
                slot_signature_hint=signature_hint,
            )
        )
    catalog = SlotCatalog(slots=normalized)
    return catalog


def _normalize_candidates(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        if _looks_like_candidate(result):
            return [result]
        list_candidates = _extract_list_candidates(result)
        if list_candidates is not None:
            return list_candidates
        candidates = result.get("candidates")
        if isinstance(candidates, list):
            return [item for item in candidates if isinstance(item, dict)]
        slots = result.get("slots")
        if isinstance(slots, list):
            return [item for item in slots if isinstance(item, dict)]
        items = result.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        output = result.get("output")
        if isinstance(output, list):
            return [item for item in output if isinstance(item, dict)]
        data = result.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        result_list = result.get("result")
        if isinstance(result_list, list):
            return [item for item in result_list if isinstance(item, dict)]
        categories = result.get("categories")
        if isinstance(categories, list):
            return [item for item in categories if isinstance(item, dict)]
    raise ValueError("Batch summary must be a JSON array")


def _build_batch_prompt(batch: list[TermEntry]) -> list[dict[str, str]]:
    term_payload = [
        {
            "term_id": term.term_id,
            "name": term.name,
            "aliases": term.aliases,
            "desc": term.desc,
        }
        for term in batch
    ]
    system_prompt = (
        "You are a schema induction engine. "
        "Given terms, derive candidate slot categories. "
        "Return JSON only, no markdown. "
        "Each item fields: slot_name, slot_desc, value_type, priority, keywords, examples."
    )
    user_prompt = json.dumps(
        {"phase": "batch_summary", "terms": term_payload},
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def _build_final_prompt(
    batch_summaries: list[dict[str, Any]],
    min_slots: int,
    max_slots: int,
) -> list[dict[str, str]]:
    system_prompt = (
        "You are a schema induction engine. "
        f"Merge batch summaries into {min_slots}-{max_slots} stable slots. "
        "Return JSON object with field slots. "
        "Each slot fields: slot_id, slot_name, slot_desc, value_type, priority, keywords, examples, slot_signature_hint."
    )
    user_prompt = json.dumps(
        {"phase": "final_catalog", "batch_summaries": batch_summaries},
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def _describe_json(value: Any) -> str:
    if isinstance(value, list):
        return f"type=list len={len(value)}"
    if isinstance(value, dict):
        keys = list(value.keys())
        return f"type=dict keys={keys[:6]}"
    return f"type={type(value).__name__}"


def _looks_like_candidate(value: dict[str, Any]) -> bool:
    required = {"slot_name", "slot_desc", "value_type"}
    return required.issubset(set(value.keys()))


def _extract_list_candidates(value: dict[str, Any]) -> list[dict[str, Any]] | None:
    list_values = []
    for item in value.values():
        if isinstance(item, list) and item and all(isinstance(v, dict) for v in item):
            list_values.append(item)
    if len(list_values) == 1:
        return list_values[0]
    return None


def _normalize_slot_id(value: Any, slot_name: str) -> str:
    if value is None or value == "":
        return _stable_slot_id(slot_name)
    return str(value).strip()


def _normalize_value_type(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else "single"
    mapping = {
        "single": "single",
        "multi": "multi",
        "list": "multi",
        "array": "multi",
        "struct": "struct",
        "object": "struct",
    }
    return mapping.get(text, "single")


def _normalize_priority(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else "medium"
    mapping = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "p0": "high",
        "p1": "medium",
        "p2": "low",
    }
    return mapping.get(text, "medium")


def _write_catalog(path: Path, catalog: SlotCatalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = catalog.model_dump()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_output_path() -> str:
    base = Path(__file__).resolve().parents[3]
    return str(base / "artifacts" / "slot_catalog.json")


def _stable_slot_id(slot_name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]", "_", slot_name.lower()).strip("_")
    return f"slot_{slug}"


def _to_snake_case(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
    return cleaned.lower()


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(value).strip()]
