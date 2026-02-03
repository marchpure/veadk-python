import json
from pathlib import Path
from typing import Any, Callable
import yaml

from intent_and_sql_tools.common.registry import ToolRegistry
from intent_and_sql_tools.common.vanna_base import VannaBase, summarize_debug


class IntentVanna(VannaBase):
    def generate_envelope(self, question: str, system_prompt: str | None = None) -> dict[str, Any]:
        try:
            docs = self._get_related_documentation(question)
            examples = self._get_similar_question_sql(question)
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
            envelope = json.loads(raw_resp)
            if not isinstance(envelope, dict):
                raise ValueError("IntentEnvelope must be a dict")
            intent = envelope.get("intent")
            if not intent:
                raise ValueError("Missing intent")
            payload = envelope.get("payload") or {}
            debug_context = {
                "docs": summarize_debug(docs),
                "examples": summarize_debug(examples),
            }
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


def _load_config() -> dict:
    if _config_path:
        path = Path(_config_path)
    else:
        path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_brain() -> "IntentVanna":
    global _brain
    if _brain is None:
        cfg = _load_config()
        _brain = IntentVanna(cfg["intent_engine"])
    return _brain


def identify_intent(query: str, system_prompt: str | None = None) -> dict:
    brain = get_brain()
    return brain.generate_envelope(query, system_prompt=system_prompt)
