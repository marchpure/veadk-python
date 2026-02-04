import json
import os
from pathlib import Path
from typing import Any, Callable
import yaml

from intent_and_sql_tools.common.registry import ToolRegistry
from intent_and_sql_tools.common.vanna_base import VannaBase, summarize_debug
from intent_and_sql_tools.intent.slot_catalog import SlotCatalog, load_slot_catalog
from intent_and_sql_tools.intent.slot_trigger import run_slot_trigger
from intent_and_sql_tools.intent.retrieval import retrieve_docs_for_slot
from intent_and_sql_tools.intent.rerank import rerank_docs_by_slot


class IntentVanna(VannaBase):
    def __init__(
        self,
        config: dict,
        llm_stub: Callable[[list[dict]], str] | None = None,
        impl: Any | None = None,
        slot_catalog: SlotCatalog | None = None,
    ):
        super().__init__(config, llm_stub=llm_stub, impl=impl)
        self._slot_catalog = slot_catalog

    def generate_envelope(self, question: str, system_prompt: str | None = None) -> dict[str, Any]:
        try:
            docs = None
            examples = self._get_similar_question_sql(question)
            debug_context: dict[str, Any] = {"examples": summarize_debug(examples)}
            print(f"[intent] step_examples {summarize_debug(examples)}")
            if system_prompt is None and self._slot_catalog:
                try:
                    trigger = run_slot_trigger(question, self._slot_catalog, self._submit_prompt)
                    debug_context["slot_trigger"] = trigger.model_dump()
                    print(f"[intent] step_slot_trigger {summarize_debug(trigger.model_dump())}")
                    docs_by_slot = {}
                    for selected in trigger.selected_slots:
                        slot = self._slot_catalog.get(selected.slot_name)
                        if not slot:
                            continue
                        docs_by_slot[slot.slot_name] = retrieve_docs_for_slot(
                            self,
                            slot,
                            selected.seeds,
                            question,
                            per_query_topk=4,
                        )
                    debug_context["slot_docs"] = _summarize_docs_by_slot(docs_by_slot)
                    print(f"[intent] step_slot_docs {summarize_debug(debug_context['slot_docs'])}")
                    blocks = rerank_docs_by_slot(docs_by_slot, self._slot_catalog)
                    if blocks:
                        docs = "\n\n".join(blocks)
                        print(f"[intent] step_rerank_blocks {summarize_debug(docs)}")
                except Exception as exc:
                    debug_context["slot_error"] = str(exc)
                    print(f"[intent] step_slot_error {exc}")
                    docs = None
            if docs is None:
                docs = self._get_related_documentation(question)
                debug_context["docs"] = summarize_debug(docs)
                print(f"[intent] step_docs {summarize_debug(docs)}")
            system_prompt = system_prompt or (
                "Role: Semantic Parser.\n"
                "Task: Map query to JSON based on Knowledge.\n"
                f"Knowledge: {docs}\n"
                f"Examples: {examples}\n"
                "Output: JSON (IntentEnvelope)\n"
            )
            raw_resp = self._submit_prompt(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ]
            )
            print(f"[intent] step_raw_response {summarize_debug(raw_resp)}")
            envelope = json.loads(raw_resp)
            if not isinstance(envelope, dict):
                raise ValueError("IntentEnvelope must be a dict")
            intent = envelope.get("intent")
            if not intent:
                raise ValueError("Missing intent")
            payload = envelope.get("payload") or {}
            print(f"[intent] step_envelope {summarize_debug(envelope)}")
            if "docs" not in debug_context:
                debug_context["docs"] = summarize_debug(docs)
            tool_name = ToolRegistry.get_tool_name(intent)
            if tool_name == "unknown_tool":
                m = getattr(ToolRegistry, "_intent_map", {})
                if isinstance(m, dict) and intent in m:
                    tool_name = m[intent]
            return {
                "intent": intent,
                "payload": payload,
                "next_tool": tool_name,
                "error": None,
                "confidence": envelope.get("confidence"),
                "debug_context": debug_context,
            }
        except Exception as exc:
            return {
                "intent": "unknown",
                "payload": {},
                "next_tool": "unknown_tool",
                "error": str(exc),
                "confidence": None,
                "debug_context": None,
            }


class IntentVannaFactory:
    def __init__(
        self,
        config: dict,
        llm_stub: Callable[[list[dict]], str] | None = None,
        impl: Any | None = None,
    ):
        self._config = config
        self._llm_stub = llm_stub
        self._impl = impl

    def build(self) -> "IntentVanna":
        return IntentVanna(self._config, llm_stub=self._llm_stub, impl=self._impl)


_brain = None
_config_path = None


def init_engine(config_path: str | None = None):
    global _brain, _config_path
    _config_path = config_path
    _brain = None


def _config_file_path() -> Path:
    if _config_path:
        return Path(_config_path)
    return Path(__file__).resolve().parents[1] / "config" / "config.yaml"


def _load_config() -> dict:
    path = _config_file_path()
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_brain() -> "IntentVanna":
    global _brain
    if _brain is None:
        cfg = _load_config()
        intent_cfg = cfg.get("intent_engine", {})
        slot_catalog = _load_slot_catalog_from_config(intent_cfg)
        _brain = IntentVanna(intent_cfg, slot_catalog=slot_catalog)
    return _brain


def identify_intent(query: str, system_prompt: str | None = None) -> dict:
    brain = get_brain()
    return brain.generate_envelope(query, system_prompt=system_prompt)


def _load_slot_catalog_from_config(intent_cfg: dict) -> SlotCatalog | None:
    env_path = os.getenv("INTENT_SLOT_CATALOG_PATH")
    path_value = env_path or intent_cfg.get("slot_catalog_path")
    if not path_value:
        print("[intent] slot_catalog_disabled")
        return None
    path = Path(path_value)
    if not path.is_absolute():
        base = _config_file_path().parent
        path = base / path
        if not path.exists():
            alt_path = Path.cwd() / path_value
            if alt_path.exists():
                path = alt_path
    if not path.exists():
        print(f"[intent] slot_catalog_not_found {path}")
        return None
    catalog = load_slot_catalog(str(path))
    print(f"[intent] slot_catalog_loaded {path} slots={len(catalog.slots)}")
    return catalog


def _summarize_docs_by_slot(docs_by_slot: dict[str, list[Any]]) -> dict[str, Any]:
    summary = {}
    for slot_name, docs in docs_by_slot.items():
        summary[slot_name] = {
            "docs_count": len(docs),
            "docs_preview": [summarize_debug(doc.text) for doc in docs[:3]],
            "source_queries": list({doc.source_query for doc in docs[:6]}),
        }
    return summary
