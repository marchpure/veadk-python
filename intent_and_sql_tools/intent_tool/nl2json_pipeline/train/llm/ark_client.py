'''
Author: haoxingjun
Date: 2026-02-04 09:26:23
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 09:45:06
Description: file information
Company: ByteDance
'''
from __future__ import annotations

import asyncio
import os
from typing import Any

from google.adk.models import LlmRequest
from google.genai import types

from veadk.models.ark_llm import ArkLlm

from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.config import ArkConfig
from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.utils.json_repair import (
    enforce_json_only_messages,
    parse_json,
)


class ArkClient:
    def __init__(self, config: ArkConfig):
        api_key = config.api_key or os.getenv("ARK_API_KEY")
        if not api_key:
            raise ValueError("ARK_API_KEY is required")
        self._api_key = api_key
        self._api_base = config.api_base or os.getenv("ARK_API_BASE") or "https://ark.cn-beijing.volces.com/api/v3"
        model = config.model or os.getenv("ARK_MODEL") or "doubao-seed-1-6-flash-250828"
        self._model = model if model.startswith("openai/") else f"openai/{model}"
        self._timeout = config.timeout
        self._max_retries = config.max_retries
        self._loop = asyncio.new_event_loop()

    def complete(self, messages: list[dict[str, str]]) -> str:
        system_texts: list[str] = []
        contents: list[types.Content] = []
        for m in messages:
            role = m.get("role", "user")
            content = str(m.get("content", ""))
            if role == "system":
                system_texts.append(content)
                continue
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
        llm_request = LlmRequest(model=self._model, contents=contents)
        if system_texts:
            llm_request.config.system_instruction = "\n\n".join(system_texts)
        llm = ArkLlm(model=self._model, api_key=self._api_key, api_base=self._api_base, timeout=self._timeout)

        async def _run():
            agen = llm.generate_content_async(llm_request, stream=False)
            try:
                async for resp in agen:
                    return resp
                return None
            finally:
                await agen.aclose()

        llm_response = self._run(_run())
        if not llm_response or not llm_response.content:
            raise ValueError("Empty LLM response")
        response_text = ""
        for part in llm_response.content.parts or []:
            if part.text:
                response_text += part.text
        response_text = response_text.strip()
        if not response_text:
            raise ValueError("Empty LLM response")
        return response_text

    def _run(self, coro):
        if self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(coro)

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                raw = self.complete(messages if attempt == 0 else enforce_json_only_messages(messages))
                parsed = parse_json(raw)
                if parsed is not None:
                    return parsed
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise ValueError("Failed to obtain JSON response")

    def complete_json_with_raw(self, messages: list[dict[str, str]]) -> tuple[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                raw = self.complete(messages if attempt == 0 else enforce_json_only_messages(messages))
                parsed = parse_json(raw)
                return raw, parsed
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise ValueError("Failed to obtain JSON response")
