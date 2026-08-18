"""Prompt and JSON contracts for optional Semantic Builder model assistance."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SemanticBuilderAgentOutput(BaseModel):
    """Validated model output. The deterministic path can run without it."""

    model_config = ConfigDict(extra="forbid")

    semantic_model: dict[str, Any] = Field(default_factory=dict)
    validation_notes: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)


def semantic_builder_prompt_contract() -> dict[str, Any]:
    return {
        "schema": "agentkit.semantic_builder.prompt_contract.v1",
        "input_policy": {
            "allowed_inputs": ["schema_snapshot", "profile_snapshot", "deterministic_seed", "doc_context_summary"],
            "forbidden_inputs": ["credentials", "connection_string", "tokens", "raw_pii_samples"],
        },
        "output_schema": SemanticBuilderAgentOutput.model_json_schema(),
        "safety_rules": [
            "Do not invent tables, columns, or credentials.",
            "Only enhance labels, descriptions, and ambiguity notes for fields present in the deterministic seed.",
            "Customer/contact/phone/address/passport/member-card fields must remain masked or denied.",
            "Query execution must be governed REST only.",
        ],
    }

