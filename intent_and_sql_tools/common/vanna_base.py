import json
import logging
import os
from typing import Any, Callable


class VannaBase:
    def __init__(
        self,
        config: dict,
        llm_stub: Callable[[list[dict]], str] | None = None,
        impl: Any | None = None,
    ):
        self._config = config or {}
        self._impl = impl
        self._llm_stub = llm_stub

    def _ensure_impl(self):
        if self._impl is None:
            try:
                from vanna.chromadb import ChromaDB_VectorStore
            except Exception:
                try:
                    from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore
                except Exception:
                    class ChromaDB_VectorStore:
                        def __init__(self, config=None):
                            pass

                        def get_similar_question_sql(self, question, **kwargs):
                            return []

                        def get_related_documentation(self, question, **kwargs):
                            return []

                        def train(self, **kwargs):
                            pass

                        def add_question_sql(self, question, sql, **kwargs):
                            pass

                        def add_documentation(self, documentation, **kwargs):
                            pass

                        def remove_question_sql(self, question, **kwargs):
                            pass

                        def remove_documentation(self, documentation, **kwargs):
                            pass

            class _Impl(ChromaDB_VectorStore, ArkChat):
                def __init__(self, config: dict):
                    ChromaDB_VectorStore.__init__(self, config=config)
                    ArkChat.__init__(self, config=config)

                def system_message(self, message: str) -> dict:
                    return ArkChat.system_message(self, message)

                def user_message(self, message: str) -> dict:
                    return ArkChat.user_message(self, message)

                def assistant_message(self, message: str) -> dict:
                    return ArkChat.assistant_message(self, message)

                def submit_prompt(self, prompt, **kwargs) -> str:
                    return ArkChat.submit_prompt(self, prompt)

            self._impl = _Impl(self._config)
        return self._impl

    def _submit_prompt(self, messages: list[dict]) -> str:
        if self._llm_stub is not None:
            return self._llm_stub(messages)
        impl = self._ensure_impl()
        return impl.submit_prompt(messages)

    def _get_related_documentation(self, question: str):
        impl = self._ensure_impl()
        return impl.get_related_documentation(question)

    def _get_similar_question_sql(self, question: str):
        impl = self._ensure_impl()
        return impl.get_similar_question_sql(question)

    def train(self, **kwargs):
        impl = self._ensure_impl()
        return impl.train(**kwargs)


class MockVannaImpl:
    def __init__(
        self,
        docs: str = "DOCS",
        examples: str = "EXAMPLES",
        response: str = '{"intent":"query_metric","payload":{"metric":"revenue"}}',
    ):
        self._docs = docs
        self._examples = examples
        self._response = response

    def get_related_documentation(self, question: str):
        return self._docs

    def get_similar_question_sql(self, question: str):
        return self._examples

    def submit_prompt(self, messages: list[dict]):
        return self._response

    def train(self, **kwargs):
        return True


class ArkChat:
    def __init__(self, config: dict):
        self._config = config or {}
        self._api_key = os.getenv("ARK_API_KEY") or os.getenv("MODEL_AGENT_API_KEY")
        self._model = os.getenv("ARK_MODEL") or os.getenv("MODEL_AGENT_NAME") or "doubao-seed-1-6-flash-250828"
        self._api_base = (
            os.getenv("ARK_API_BASE")
            or os.getenv("MODEL_AGENT_API_BASE")
            or "https://ark.cn-beijing.volces.com/api/v3"
        )
        if not self._api_key:
            raise ValueError("ARK_API_KEY or MODEL_AGENT_API_KEY is required")
        self._odps_client = None
        self._connect_to_maxcompute()
        self.run_sql_is_set = True

    def _connect_to_maxcompute(self):
        try:
            from odps import ODPS
        except Exception:
            logging.warning("ODPS package not found. MaxCompute connection unavailable.")
            return
        access_id = os.environ.get("maxcompute_ak")
        access_key = os.environ.get("maxcompute_sk")
        project = os.environ.get("MAXCOMPUTE_PROJECT") or "douyu_te"
        endpoint = os.environ.get("MAXCOMPUTE_ENDPOINT") or "http://service.cn-beijing.maxcompute.aliyun.com/api"
        if not access_id or not access_key:
            logging.warning("MaxCompute credentials (maxcompute_ak, maxcompute_sk) not found.")
            return
        try:
            self._odps_client = ODPS(access_id, access_key, project, endpoint=endpoint)
            list(self._odps_client.list_projects())[:1]
            logging.info("Successfully connected to MaxCompute.")
        except Exception as exc:
            logging.error(f"Failed to connect to MaxCompute: {exc}")
            self._odps_client = None

    def system_message(self, message: str) -> dict:
        return {"role": "system", "content": message}

    def user_message(self, message: str) -> dict:
        return {"role": "user", "content": message}

    def assistant_message(self, message: str) -> dict:
        return {"role": "assistant", "content": message}

    def submit_prompt(self, messages: list[dict]) -> str:
        import asyncio
        # from google.adk.models import LlmRequest
        # from google.genai import types

        # Mock types needed
        class Types:
            class Part:
                @staticmethod
                def from_text(text):
                    return text
            
            class Content:
                def __init__(self, role, parts):
                    self.role = role
                    self.parts = parts

        system_texts = []
        contents = []
        for m in messages:
            role = m.get("role", "user")
            content = str(m.get("content", ""))
            if role == "system":
                system_texts.append(content)
                continue
            contents.append(
                {"role": role, "content": content}
            )
        
        # Use litellm directly if google.adk is not available
        try:
            from litellm import completion
            
            model_name = self._model
            # Adjust model name for litellm if needed
            if "/" not in model_name:
                provider = os.getenv("MODEL_AGENT_PROVIDER", "openai")
                model_name = f"{provider}/{model_name}"
            
            # Prepare messages for litellm
            litellm_messages = []
            if system_texts:
                litellm_messages.append({"role": "system", "content": "\n\n".join(system_texts)})
            
            for m in messages:
                if m.get("role") != "system":
                    litellm_messages.append(m)

            extra_params: dict[str, Any] = {}
            raw_params = os.getenv("MODEL_AGENT_LLM_PARAMS") or os.getenv("ARK_LLM_PARAMS")
            if raw_params:
                try:
                    parsed = json.loads(raw_params)
                    if isinstance(parsed, dict):
                        extra_params.update(parsed)
                except Exception:
                    logging.warning("MODEL_AGENT_LLM_PARAMS/ARK_LLM_PARAMS must be valid JSON")
            disable_thinking = os.getenv("MODEL_AGENT_DISABLE_THINKING") or os.getenv("ARK_DISABLE_THINKING")
            if str(disable_thinking).lower() in {"1", "true", "yes"}:
                extra_params.setdefault("thinking", "off")
                extra_params.setdefault("reasoning", {"effort": "low"})
            response = completion(
                model=model_name,
                messages=litellm_messages,
                api_key=self._api_key,
                base_url=self._api_base,
                **extra_params,
            )
            
            response_text = response.choices[0].message.content
            
            if not response_text:
                raise ValueError("Empty LLM response")
                
            if not _is_sql_prompt(messages):
                json_text = _extract_json(response_text)
                if json_text:
                    response_text = json_text
            if _is_sql_prompt(messages) and response_text.lstrip().startswith("{"):
                raise ValueError("Expected SQL but got JSON response")
            return response_text

        except Exception as e:
            # Fallback to original implementation only if litellm fails AND google.adk is present
            # But since user wants to remove google.adk dependency, we should stick to litellm or standard openai client
            logging.error(f"LiteLLM completion failed: {e}")
            raise e




def summarize_debug(value: Any, limit: int = 400):
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit]




def _is_sql_prompt(messages: list[dict]) -> bool:
    for m in messages:
        if m.get("role") == "system":
            content = str(m.get("content", ""))
            normalized = content.lower()
            if "sql expert" in normalized:
                return True
            if "only sql" in normalized:
                return True
            if "return only sql" in normalized:
                return True
    return False


def _extract_json(text: str) -> str | None:
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return json.dumps(obj, ensure_ascii=False)
