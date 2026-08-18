"""AskData query loop for published Semantic Skills."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from ...models import ApiModel
from ...service import KnowledgeAssetStore
from .common import redacted
from .semantic_query_adapter import (
    GovernedSemanticQueryService,
    SemanticQueryRequest,
)


class AskDataQueryBody(ApiModel):
    semantic_asset_id: str = Field(min_length=1, max_length=256)
    metric: str | None = Field(default=None, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_range: dict[str, Any] = Field(default_factory=dict)
    question: str | None = Field(default=None, max_length=1000)
    limit: int = Field(default=100, ge=1, le=500)
    mode: str = Field(default="summary", max_length=80)

    @field_validator("dimensions")
    @classmethod
    def _trim_dimensions(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class AskDataQueryService:
    def __init__(self, store: KnowledgeAssetStore) -> None:
        self._store = store
        self._semantic_query = GovernedSemanticQueryService(store)

    async def query(self, body: AskDataQueryBody) -> dict[str, Any]:
        asset = await self._store.get_asset(
            asset_type="semantic_model",
            asset_id=body.semantic_asset_id,
        )
        semantic_result = await self._semantic_query.query_loaded_asset(
            asset,
            SemanticQueryRequest.from_body(body),
        )
        data = semantic_result.get("data") if isinstance(semantic_result, dict) else {}
        policy_decision = data.get("policyDecision") if isinstance(data, dict) else {}
        decision = str(
            policy_decision.get("decision", "")
            if isinstance(policy_decision, dict)
            else ""
        ).casefold()
        return redacted(
            {
                "schema": "agentkit.askdata.result.v1",
                "status": "blocked" if decision == "deny" else "completed",
                "asset": {
                    "type": "semantic_model",
                    "id": asset["asset_id"],
                    "name": asset["name"],
                    "version": asset.get("version") or "v1",
                },
                "query": body.model_dump(mode="json"),
                "data": data,
                "mock": False,
            }
        )
