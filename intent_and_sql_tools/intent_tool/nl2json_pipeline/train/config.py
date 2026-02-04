'''
Author: haoxingjun
Date: 2026-02-04 09:24:15
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 11:09:51
Description: file information
Company: ByteDance
'''
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TermFieldMapping(BaseModel):
    term_id: str = "term_id"
    name: str = "name"
    aliases: str = "aliases"
    desc: str = "desc"


class TermSourceConfig(BaseModel):
    path: str
    format: str | None = None
    field_mapping: TermFieldMapping = Field(default_factory=TermFieldMapping)
    csv_delimiter: str = ","
    alias_delimiter: str = ","


class FewShotConfig(BaseModel):
    path: str | None = None
    format: str | None = None


class ArkConfig(BaseModel):
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None
    timeout: float = 60.0
    max_retries: int = 3


class SchemaInductionPhaseAConfig(BaseModel):
    batch_size: int = 200
    min_slots: int = 8
    max_slots: int = 9999
    output_path: str | None = None
    max_batches: int | None = None


class PipelineConfig(BaseModel):
    term_source: TermSourceConfig
    fewshot: FewShotConfig | None = None
    llm: ArkConfig = Field(default_factory=ArkConfig)
    schema_induction_phase_a: SchemaInductionPhaseAConfig = Field(
        default_factory=SchemaInductionPhaseAConfig
    )


def load_config(path: str) -> PipelineConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    content = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() in {".json"}:
        data = json.loads(content)
    else:
        data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValueError("Config must be an object")
    return PipelineConfig.model_validate(data)


def merge_phase_a_overrides(
    config: PipelineConfig,
    output_path: str | None = None,
    batch_size: int | None = None,
    max_batches: int | None = None,
) -> PipelineConfig:
    data: dict[str, Any] = config.model_dump()
    phase_a = data.get("schema_induction_phase_a", {})
    if output_path:
        phase_a["output_path"] = output_path
    if batch_size:
        phase_a["batch_size"] = batch_size
    if max_batches:
        phase_a["max_batches"] = max_batches
    data["schema_induction_phase_a"] = phase_a
    return PipelineConfig.model_validate(data)
