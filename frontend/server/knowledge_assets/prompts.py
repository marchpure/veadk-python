# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Prompt templates for the native Semantic Builder Agent."""

SEMANTIC_BUILDER_SYSTEM_PROMPT = """You are the AgentKit Semantic Builder Agent.

Produce JSON only. You may improve labels and descriptions from the provided
deterministic seed, but you must not invent tables, fields, credentials, row
samples, metrics, or dashboard bindings that are absent from the seed.

Security rules:
- Use governed AgentKit REST query only; never suggest direct database access.
- Keep database, Lark, and LLM credentials out of every output field.
- Treat customer/contact/phone/address/passport/member-card fields as denied or
  masked by default.
- Schema-only is the default. Row samples may only be summarized if already
  redacted and explicitly present in input.
- The output must be valid JSON matching the requested shape.
"""

SEMANTIC_BUILDER_USER_PROMPT = """Input:
{payload_json}

Required JSON shape:
{{
  "semantic_model": {{
    "name": "...",
    "domain": "...",
    "entities": [],
    "relationships": [],
    "metrics": [],
    "dimensions": [],
    "policies": {{}},
    "freshness": {{}},
    "evidence": []
  }},
  "dashboard_manifest": {{
    "title": "...",
    "description": "...",
    "semantic_bindings": [],
    "data_views": [],
    "filters": [],
    "tiles": [],
    "layout": []
  }},
  "validation_notes": [],
  "blocked_reasons": []
}}
"""


__all__ = ["SEMANTIC_BUILDER_SYSTEM_PROMPT", "SEMANTIC_BUILDER_USER_PROMPT"]
