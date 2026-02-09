import csv
import difflib
import json
import os
from pathlib import Path
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
from loguru import logger

from intent_and_sql_tools.common.registry import ToolRegistry
from intent_and_sql_tools.common.vanna_base import ArkChat, summarize_debug
from intent_and_sql_tools.intent_tool.retriever.slot_catalog import SlotCatalog, load_slot_catalog
from intent_and_sql_tools.intent_tool.retriever.slot_trigger import run_slot_trigger
from intent_and_sql_tools.intent_tool.retriever.retrieval import (
    retrieve_docs_for_slot,
    search_kb,
    _extract_kb_text,
)
from intent_and_sql_tools.intent_tool.retriever.rerank import rerank_docs_by_slot
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.utils.json_repair import parse_json


class IntentVanna:
    def __init__(
        self,
        config: dict,
        llm_stub: Callable[[list[dict]], str] | None = None,
        slot_catalog: SlotCatalog | None = None,
    ):
        self._config = config or {}
        self._slot_catalog = slot_catalog
        self._llm_stub = llm_stub
        self._llm = None

    def _submit_prompt(self, messages: list[dict]) -> str:
        if self._llm_stub is not None:
            return self._llm_stub(messages)
        if self._llm is None:
            self._llm = ArkChat(self._config)
        return self._llm.submit_prompt(messages)

    def _get_related_documentation(self, question: str) -> str:
        kb_name = os.getenv("INTENT_VIKING_KB_NAME", "test_factor_haoxingjun")
        try:
            results = search_kb(kb_name, question, topk=5)
        except Exception as exc:
            logger.warning(f"[intent] viking_docs_error {exc}")
            return ""
        texts = []
        seen = set()
        for item in results or []:
            text = _extract_kb_text(item)
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            texts.append(text)
            if len(texts) >= 5:
                break
        return _reduce_docs_for_prompt("\n".join(texts))

    def _get_similar_question_examples(self, question: str) -> dict[str, Any]:
        rows = _load_select_stocks_qa_rows()
        if not rows:
            return {"examples": [], "term_brief_text": "", "term_briefs": []}
        scored = []
        for row in rows:
            score = _similarity_score(question, row.get("question") or "")
            if score <= 0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_rows = [row for _, row in scored[:3]]
        kb_name = os.getenv(
            "INTENT_VIKING_EXAMPLE_KB_NAME",
            os.getenv("INTENT_VIKING_KB_NAME", "test_factor_haoxingjun"),
        )
        examples: list[str] = []
        term_briefs: list[str] = []
        seen_terms: set[str] = set()
        for row in top_rows:
            q = (row.get("question") or "").strip()
            conditions = row.get("conditions") or []
            factors = _extract_factors_from_conditions(conditions)
            factor_briefs: list[str] = []
            for factor in factors[:12]:
                brief = _get_factor_brief(kb_name, factor)
                if brief:
                    factor_briefs.append(f"{factor}: {brief}")
                    if factor not in seen_terms:
                        seen_terms.add(factor)
                        term_briefs.append(f"{factor}: {brief}")
            example_text = (
                f"Q: {q}\n"
                f"AnswerConditions: {json.dumps(conditions, ensure_ascii=False)}\n"
                f"FactorBriefs: {json.dumps(factor_briefs, ensure_ascii=False)}"
            )
            examples.append(example_text)
        term_brief_text = "\n".join(term_briefs[:20])
        return {
            "examples": examples,
            "term_brief_text": term_brief_text,
            "term_briefs": term_briefs,
        }

    def generate_envelope(self, question: str, system_prompt: str | None = None) -> dict[str, Any]:
        try:
            # 1) 起始输入
            logger.info(f"[intent] step_start {summarize_debug(question)}")

            # 2) Few-shot 示例与术语简述
            examples_payload = self._get_similar_question_examples(question)
            examples = examples_payload.get("examples") or []
            term_brief_text = str(examples_payload.get("term_brief_text") or "").strip()
            debug_context: dict[str, Any] = {
                "examples": summarize_debug(examples),
                "term_brief_text": summarize_debug(term_brief_text),
            }
            logger.info(f"[intent] step_examples {summarize_debug(examples)}")

            # 3) 知识检索与精简（优先使用 slot_catalog 进行分槽检索）
            docs = None
            if self._slot_catalog is not None:
                try:
                    trigger = run_slot_trigger(question, self._slot_catalog, self._submit_prompt)
                    debug_context["slot_trigger"] = trigger.model_dump()
                    logger.info(f"[intent] step_slot_trigger {summarize_debug(trigger.model_dump())}")
                    docs_by_slot: dict[str, list[Any]] = {}
                    slot_pairs: list[tuple[Any, Any]] = []
                    for selected in trigger.selected_slots:
                        slot = self._slot_catalog.get(selected.slot_name)
                        if not slot:
                            continue
                        slot_pairs.append((slot, selected))
                    if slot_pairs:
                        max_workers = min(4, len(slot_pairs))
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            future_map = {
                                executor.submit(
                                    retrieve_docs_for_slot,
                                    self,
                                    slot,
                                    selected.seeds,
                                    question,
                                    per_query_topk=1,
                                ): slot.slot_name
                                for slot, selected in slot_pairs
                            }
                            for future in as_completed(future_map):
                                slot_name = future_map[future]
                                try:
                                    docs_by_slot[slot_name] = future.result()
                                except Exception as exc:
                                    logger.warning(f"[intent] step_slot_docs_error {slot_name} {exc}")
                    blocks = rerank_docs_by_slot(docs_by_slot, self._slot_catalog)
                    if blocks:
                        docs = "\n\n".join(blocks)
                except Exception as exc:
                    debug_context["slot_error"] = str(exc)
                    logger.warning(f"[intent] step_slot_error {exc}")
                    docs = None

            if not docs:
                docs = self._get_related_documentation(question)
            docs = _reduce_docs_for_prompt(docs)
            debug_context["docs"] = summarize_debug(docs)
            logger.info(f"[intent] step_docs {summarize_debug(docs)}")

            # 4) 构造 system_prompt
            system_prompt = system_prompt or (
                "Role: Semantic Parser.\n"
                "Task: Extract an optimized query in markdown format.\n"
                "Return JSON only.\n"
                "Output: JSON with only fields prompt and optimized_query.\n"
                "The `prompt` field must echo the user query in Chinese.\n"
                "The `optimized_query` field is required and must never be empty.\n"
                "The `optimized_query` must be in Markdown (use ## headings and bullet lists), strictly in Chinese.\n"
                "Use the following structure:\n"
                "## 意图分类\n"
                "- ...\n"
                "## 条件拆分\n"
                "- ...\n"
                "## 检索计划\n"
                "- 条件1：...（说明该条件对应的因子/字段，并给出检索建议）\n"
                "- 条件2：...（说明该条件对应的因子/字段，并给出检索建议）\n"
                "- 条件3：...（说明该条件对应的因子/字段，并给出检索建议）\n"
                "## 详细解释\n"
                "- ...\n"
                f"Knowledge:\n---\n{docs}\n---\n"
                f"金融术语列表:\n---\n{term_brief_text}\n---\n"
            )
            logger.info(f"[intent] step_system_prompt {system_prompt}")

            # 5) 调用模型
            raw_resp = self._submit_prompt(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ]
            )
            logger.info(f"[intent] step_raw_response {summarize_debug(raw_resp)}")
            logger.info(f"[intent] step_raw_response_full {raw_resp}")

            # 6) 解析输出
            envelope = parse_json(raw_resp)
            if not isinstance(envelope, dict):
                raise ValueError("IntentEnvelope must be a dict")

            # 7) 提取 optimized_query
            prompt_value = envelope.get("prompt") or envelope.get("query") or question
            optimized_query = envelope.get("optimized_query") or envelope.get("optimizedQuery")
            logger.info(f"[intent] step_optimized_query_from_envelope {summarize_debug(optimized_query)}")
            if not optimized_query and isinstance(envelope.get("payload"), dict):
                payload = envelope.get("payload") or {}
                optimized_query = payload.get("optimized_query") or payload.get("optimizedQuery")
                logger.info(f"[intent] step_optimized_query_from_payload {summarize_debug(optimized_query)}")
            if not optimized_query and isinstance(envelope.get("payload"), dict):
                payload = envelope.get("payload") or {}
                optimized_query = _build_optimized_query_from_payload(payload, "优化查询")
                logger.info(f"[intent] step_optimized_query_from_fallback {summarize_debug(optimized_query)}")
            optimized_query = optimized_query or question
            logger.info(f"[intent] step_optimized_query_after_default {summarize_debug(optimized_query)}")
            if _looks_like_sql(optimized_query):
                optimized_query = question
                logger.info(f"[intent] step_optimized_query_sql_fallback {summarize_debug(optimized_query)}")
            optimized_query = _format_optimized_query_markdown(optimized_query)
            logger.info(f"[intent] step_optimized_query {summarize_debug(optimized_query)}")

            # 8) 返回结果
            return {
                "intent": envelope.get("intent") or "optimized_query",
                "prompt": prompt_value,
                "optimized_query": optimized_query,
                "error": None,
                "debug_context": debug_context,
            }
        except Exception as exc:
            return {
                "intent": "unknown",
                "prompt": question,
                "optimized_query": question,
                "error": str(exc),
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
        return IntentVanna(self._config, llm_stub=self._llm_stub)


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
        default_path = Path(__file__).resolve().parent / "nl2json_pipeline" / "artifacts" / "slot_catalog.json"
        if default_path.exists():
            path_value = str(default_path)
        else:
            logger.info("[intent] slot_catalog_disabled")
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
        logger.warning(f"[intent] slot_catalog_not_found {path}")
        return None
    catalog = load_slot_catalog(str(path))
    logger.info(f"[intent] slot_catalog_loaded {path} slots={len(catalog.slots)}")
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


def _collect_mapped_terms(docs_by_slot: dict[str, list[Any]]) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for docs in docs_by_slot.values():
        for doc in docs:
            term = _extract_factor_name(doc.text)
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return terms


def _extract_factor_name(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("factor:"):
            value = line.split("factor:", 1)[1].strip()
            return value or None
        if line.startswith("因子:"):
            value = line.split("因子:", 1)[1].strip()
            return value or None
    return None


def _reduce_docs_for_prompt(docs: str, max_items: int = 6) -> str:
    if not docs:
        return ""
    blocks = [b.strip() for b in docs.split("\n\n") if b.strip()]
    reduced: list[str] = []
    for block in blocks[:max_items]:
        factor = ""
        desc = ""
        for line in block.splitlines():
            s = line.strip()
            if not factor and s.startswith("factor:"):
                factor = s.split("factor:", 1)[1].strip()
                continue
            if not desc and s.startswith("描述:"):
                desc = s.split("描述:", 1)[1].strip()
                continue
        if factor or desc:
            reduced.append(f"factor: {factor}\n描述: {desc}".strip())
        else:
            reduced.append("\n".join(block.splitlines()[:6]))
    return "\n\n".join(reduced)


def _format_optimized_query_markdown(text: str) -> str:
    if not text:
        return ""
    value = text.strip()
    if "### " in value:
        value = value.replace("### ", "## ")
    return value


def _looks_like_sql(text: str) -> bool:
    if not text:
        return False
    value = text.strip().lower()
    if not value:
        return False
    if value.startswith(("select ", "with ", "insert ", "update ", "delete ", "merge ")):
        return True
    if " from " in value and "select" in value:
        return True
    return False


def _build_retrieval_plan(slot_trigger: Any | None, next_tool: str | None) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    step_id = 1
    steps.append(
        {
            "step": step_id,
            "tool": "intent_tool.retriever.search_kb",
            "target": "knowledge_base",
            "reason": "根据 query 与候选槽位/种子词检索金融术语/因子描述",
        }
    )
    step_id += 1
    if slot_trigger:
        steps.append(
            {
                "step": step_id,
                "tool": "intent_tool.retriever.run_slot_trigger",
                "target": "slot_catalog",
                "reason": "识别 query 中的关键条件片段并映射到槽位",
            }
        )
        step_id += 1
        steps.append(
            {
                "step": step_id,
                "tool": "intent_tool.retriever.rerank_docs_by_slot",
                "target": "retrieved_docs",
                "reason": "对不同槽位检索结果进行去重/截断/重排，形成高质量知识块",
            }
        )
        step_id += 1
    if next_tool:
        steps.append(
            {
                "step": step_id,
                "tool": next_tool,
                "target": "tool_registry",
                "reason": "根据 intent 选择下一步工具，进入结构化检索与筛选执行",
            }
        )
    return steps


def _build_term_impacts(mapped_terms: list[str]) -> list[dict[str, Any]]:
    impacts: list[dict[str, Any]] = []
    for term in mapped_terms[:10]:
        impacts.append(
            {
                "term": term,
                "impact": "用于约束后续检索与筛选条件（例如量能、买盘、趋势、板块/风险过滤）",
                "why": "该术语/因子在知识库命中，可作为因子接入后的字段映射与筛选依据",
            }
        )
    return impacts


_SELECT_STOCKS_QA_ROWS: list[dict[str, Any]] | None = None


def _load_select_stocks_qa_rows() -> list[dict[str, Any]]:
    global _SELECT_STOCKS_QA_ROWS
    if _SELECT_STOCKS_QA_ROWS is not None:
        return _SELECT_STOCKS_QA_ROWS
    path = Path(__file__).resolve().parents[1] / "sample_data" / "dazhihui" / "select_stocks_qa.csv"
    if not path.exists():
        _SELECT_STOCKS_QA_ROWS = []
        return _SELECT_STOCKS_QA_ROWS
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = (row.get("question") or "").strip()
            conditions_raw = row.get("conditions") or ""
            if not q or not conditions_raw:
                continue
            try:
                conditions = json.loads(conditions_raw)
            except Exception:
                continue
            if not isinstance(conditions, list):
                continue
            rows.append({"question": q, "conditions": conditions})
    _SELECT_STOCKS_QA_ROWS = rows
    return rows


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in text.strip().lower() if ch not in {" ", "\t", "\n", "\r"})


def _similarity_score(a: str, b: str) -> float:
    a0 = _normalize_text(a)
    b0 = _normalize_text(b)
    if not a0 or not b0:
        return 0.0
    return difflib.SequenceMatcher(a=a0, b=b0).ratio()


def _extract_factors_from_conditions(conditions: list[Any]) -> list[str]:
    factors: list[str] = []
    seen: set[str] = set()
    for item in conditions:
        if not isinstance(item, dict):
            continue
        factor = str(item.get("factor") or "").strip()
        if not factor:
            continue
        if factor in seen:
            continue
        seen.add(factor)
        factors.append(factor)
    return factors


def _extract_brief_from_text(text: str, max_len: int = 200) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    desc = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("描述:"):
            desc = line.split("描述:", 1)[1].strip()
            break
    if not desc:
        return ""
    if len(desc) <= max_len:
        return desc
    return desc[:max_len].rstrip() + "…"


_FACTOR_BRIEF_CACHE: dict[str, str] = {}


def _get_factor_brief(kb_name: str, factor: str) -> str:
    key = f"{kb_name}::{factor}"
    cached = _FACTOR_BRIEF_CACHE.get(key)
    if cached is not None:
        return cached
    brief = ""
    try:
        results = search_kb(kb_name, factor, topk=1)
        if results:
            text = _extract_kb_text(results[0])
            if text:
                brief = _extract_brief_from_text(text)
    except Exception:
        brief = ""
    _FACTOR_BRIEF_CACHE[key] = brief
    return brief


def _summarize_term_mappings(mappings: list[dict[str, Any]]) -> str:
    uniq: dict[str, dict[str, Any]] = {}
    for m in mappings:
        term = str(m.get("term") or "").strip()
        if not term:
            continue
        if term in uniq:
            continue
        uniq[term] = m
        if len(uniq) >= 20:
            break
    lines: list[str] = []
    for term, m in uniq.items():
        parts = [f"term={term}"]
        for k in ("id", "classid", "subclassid", "back_test_type"):
            v = m.get(k)
            if v is None or v == "":
                continue
            parts.append(f"{k}={v}")
        lines.append(", ".join(parts))
    return " | ".join(lines)


def _build_optimized_query_from_payload(payload: dict[str, Any], intent: str) -> str:
    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        return ""
    lines: list[str] = []
    lines.append(f"### 1. 意图分类：{intent}")
    lines.append("### 2. 条件拆分：")
    detail_lines: list[str] = []
    for idx, cond in enumerate(conditions, start=1):
        if not isinstance(cond, dict):
            continue
        factor = str(cond.get("factor") or "").strip() or "未知因子"
        subclass = str(cond.get("subclass") or "").strip()
        label = factor
        if subclass:
            label = f"{factor}（{subclass}）"
        lines.append(f"{idx}. {label}")
        description = str(cond.get("description") or "").strip()
        if description:
            detail_lines.append(f"- 条件{idx}（{label}）：{description}")
    if detail_lines:
        lines.append("### 3. 详细解释：")
        lines.extend(detail_lines)
    return "\n".join(lines)
