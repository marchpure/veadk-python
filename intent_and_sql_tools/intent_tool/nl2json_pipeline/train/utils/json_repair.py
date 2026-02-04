'''
Author: haoxingjun
Date: 2026-02-04 09:25:54
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 09:25:55
Description: file information
Company: ByteDance
'''
from __future__ import annotations

import ast
import json
from typing import Any


def parse_json(text: str) -> Any | None:
    if not text:
        return None
    text = _strip_code_fences(text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        extracted = _extract_json(text)
        if extracted is not None:
            return extracted
        return _parse_python_literal(text)


def _extract_json(text: str) -> Any | None:
    if not text:
        return None
    for token in ("{", "["):
        start = text.find(token)
        if start == -1:
            continue
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(text[start:])
            return obj
        except json.JSONDecodeError:
            continue
    return None


def _parse_python_literal(text: str) -> Any | None:
    if not text:
        return None
    candidate = _extract_literal_slice(text)
    if not candidate:
        return None
    try:
        obj = ast.literal_eval(candidate)
    except (ValueError, SyntaxError):
        return None
    if isinstance(obj, (dict, list)):
        return obj
    return None


def _extract_literal_slice(text: str) -> str | None:
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        return text[brace_start : brace_end + 1]
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
        return text[bracket_start : bracket_end + 1]
    return None


def _strip_code_fences(text: str) -> str:
    if "```" not in text:
        return text
    lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


def enforce_json_only_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "Return JSON only."},
        *messages,
    ]
