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
                from vanna.legacy.chromadb.chromadb_vector import ChromaDB_VectorStore

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

                def run_sql(self, sql: str):
                    return ArkChat.run_sql(self, sql)

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

    def generate_sql(self, question: str) -> str:
        return "SELECT 1"

    def run_sql(self, sql: str):
        return [{"ok": True}]

    def train(self, **kwargs):
        return True


class ArkChat:
    def __init__(self, config: dict):
        self._config = config or {}
        self._api_key = os.getenv("ARK_API_KEY")
        self._model = os.getenv("ARK_MODEL", "doubao-seed-1-8-251228")
        self._api_base = os.getenv("ARK_API_BASE", "https://ark.cn-beijing.volces.com/api/v3")
        if not self._api_key:
            raise ValueError("ARK_API_KEY is required")
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
        from google.adk.models import LlmRequest
        from google.genai import types
        from veadk.models.ark_llm import ArkLlm

        system_texts = []
        contents = []
        for m in messages:
            role = m.get("role", "user")
            content = str(m.get("content", ""))
            if role == "system":
                system_texts.append(content)
                continue
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=content)])
            )
        model_name = self._model
        if not model_name.startswith("openai/"):
            model_name = f"openai/{model_name}"
        llm_request = LlmRequest(model=model_name, contents=contents)
        if system_texts:
            llm_request.config.system_instruction = "\n\n".join(system_texts)
        llm = ArkLlm(model=model_name, api_key=self._api_key, api_base=self._api_base)

        async def _run():
            async for resp in llm.generate_content_async(llm_request, stream=False):
                return resp
            return None

        llm_response = asyncio.run(_run())
        if not llm_response or not llm_response.content:
            raise ValueError("Empty LLM response")
        response_text = ""
        for part in llm_response.content.parts or []:
            if part.text:
                response_text += part.text
        response_text = response_text.strip()
        if not response_text:
            raise ValueError("Empty LLM response")
        if not _is_sql_prompt(messages):
            json_text = _extract_json(response_text)
            if json_text:
                response_text = json_text
        if _is_sql_prompt(messages) and response_text.lstrip().startswith("{"):
            raise ValueError("Expected SQL but got JSON response")
        return response_text

    def generate_sql(self, question: str) -> str:
        prompt = "Return only SQL for the following question."
        return self.submit_prompt(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ]
        )

    def run_sql(self, sql: str):
        if self._odps_client is None:
            raise ValueError("MaxCompute client is not available. Set maxcompute_ak/maxcompute_sk/MAXCOMPUTE_PROJECT.")
        sql_clean = sql.replace("bigdata_bi.", "")
        run_hints = {"odps.sql.validate.orderby.limit": "false"}
        with self._odps_client.execute_sql(sql_clean, hints=run_hints).open_reader() as reader:
            return reader.to_pandas()


def summarize_debug(value: Any, limit: int = 400):
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit]


def _is_sql_prompt(messages: list[dict]) -> bool:
    for m in messages:
        if m.get("role") == "system":
            content = str(m.get("content", ""))
            if "SQL expert" in content or "ONLY" in content or "SQL" in content:
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
