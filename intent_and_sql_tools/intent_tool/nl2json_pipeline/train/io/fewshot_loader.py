'''
Author: haoxingjun
Date: 2026-02-04 09:25:41
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 09:35:29
Description: file information
Company: ByteDance
'''
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from intent_and_sql_tools.intent_tool.nl2json_pipeline.train.config import FewShotConfig


class FewShotExample(BaseModel):
    query: str
    ground_truth_json: dict[str, Any]


def load_fewshot(config: FewShotConfig | None) -> list[FewShotExample]:
    if not config or not config.path:
        return []
    path = Path(config.path)
    if not path.exists():
        raise FileNotFoundError(f"Few-shot file not found: {path}")
    fmt = (config.format or path.suffix.lstrip(".")).lower()
    if fmt == "jsonl":
        records = _read_jsonl(path)
    else:
        records = _read_json(path)
    examples: list[FewShotExample] = []
    for record in records:
        if isinstance(record, dict):
            if "query" in record and "ground_truth_json" in record:
                examples.append(FewShotExample.model_validate(record))
    return examples


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if isinstance(data, dict):
            records.append(data)
    return records


def _read_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []
