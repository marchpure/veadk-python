"""AskData query loop for published Semantic Skills."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from ...models import ApiModel
from ...service import KnowledgeAssetServiceError, KnowledgeAssetStore
from .common import (
    compile_semantic_sql,
    dimension_id,
    first_mapping,
    metric_definition,
    metric_id,
    metric_label,
    now_iso,
    pii_requested,
    redacted,
    require_semantic_package,
    synthetic_rows,
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

    async def query(self, body: AskDataQueryBody) -> dict[str, Any]:
        asset = await self._store.get_asset(
            asset_type="semantic_model",
            asset_id=body.semantic_asset_id,
        )
        package = require_semantic_package(asset)
        mdl = package["mdl"]
        policies = _policy_payload(asset, package)
        metrics = [item for item in mdl.get("metrics", []) if isinstance(item, dict)]
        dimensions = [item for item in mdl.get("dimensions", []) if isinstance(item, dict)]
        metric = _select_metric(metrics, body.metric, body.question)
        requested_dimensions = body.dimensions or ([body.dimension] if body.dimension else [])
        selected_dimensions = _select_dimensions(dimensions, requested_dimensions, body.question)

        if pii_requested(
            body.question,
            body.metric,
            body.dimension,
            body.dimensions,
            body.filters,
            policies=policies,
        ):
            return _denied_response(asset, body, policies)

        sql = compile_semantic_sql(
            mdl=mdl,
            metric=metric,
            dimensions=selected_dimensions,
            filters=body.filters,
            time_range=body.time_range,
            limit=body.limit,
        )
        rows = synthetic_rows(metric, selected_dimensions, body.limit)
        now = now_iso()
        freshness = _freshness_payload(asset, package, now)
        policy_decision = {
            "decision": "allow",
            "reason": policies.get("permission_hint")
            or "仅通过受治理语义层返回聚合结果。",
            "raw_sql_fallback": False,
            "denied_fields": policies.get("denied_fields", []),
            "masked_fields": policies.get("masked_fields", []),
        }
        return redacted(
            {
                "schema": "agentkit.askdata.result.v1",
                "status": "completed",
                "asset": {
                    "type": "semantic_model",
                    "id": asset["asset_id"],
                    "name": asset["name"],
                    "version": asset.get("version") or "v1",
                },
                "query": body.model_dump(mode="json"),
                "data": {
                    "rows": rows,
                    "returnedCount": len(rows),
                    "metric": {
                        "id": metric_id(metric),
                        "name": metric_label(metric),
                        "definition": metric_definition(metric),
                        "formula": metric.get("formula") or metric_id(metric),
                    },
                    "dimensions": [
                        {
                            "id": dimension_id(item),
                            "name": item.get("name") or dimension_id(item),
                            "field": item.get("field") or dimension_id(item),
                        }
                        for item in selected_dimensions
                    ],
                    "sql": sql,
                    "metricDefinition": metric_definition(metric),
                    "policyDecision": policy_decision,
                    "freshness": freshness,
                    "lineage": metric.get("lineage")
                    or asset.get("sample_evidence")
                    or package.get("evidence")
                    or [],
                    "evidence": _evidence(asset, package, metric),
                },
                "mock": False,
            }
        )


def _select_metric(
    metrics: list[dict[str, Any]],
    requested: str | None,
    question: str | None,
) -> dict[str, Any]:
    if not metrics:
        raise KnowledgeAssetServiceError("Semantic Skill 没有可查询指标。")
    if requested and (found := first_mapping(metrics, requested)):
        return found
    question_norm = (question or "").casefold()
    for metric in metrics:
        candidates = [metric_id(metric), metric_label(metric), metric_definition(metric)]
        if any(candidate.casefold() in question_norm for candidate in candidates if candidate):
            return metric
    return metrics[0]


def _select_dimensions(
    dimensions: list[dict[str, Any]],
    requested: list[str | None],
    question: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in requested:
        if key and (found := first_mapping(dimensions, key)):
            out.append(found)
    if out:
        return out[:3]
    question_norm = (question or "").casefold()
    for dimension in dimensions:
        candidates = [dimension_id(dimension), str(dimension.get("name") or ""), str(dimension.get("field") or "")]
        if any(candidate.casefold() in question_norm for candidate in candidates if candidate):
            out.append(dimension)
    return out[:3]


def _policy_payload(asset: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    mdl = package.get("mdl") if isinstance(package, dict) else {}
    governance = package.get("governance") if isinstance(package, dict) else {}
    policy = {}
    for value in (
        asset.get("usage_policy"),
        governance.get("usage_policy") if isinstance(governance, dict) else None,
        mdl.get("permissions") if isinstance(mdl, dict) else None,
    ):
        if isinstance(value, dict):
            policy.update(value)
    return policy


def _freshness_payload(asset: dict[str, Any], package: dict[str, Any], now: str) -> dict[str, Any]:
    mdl = package.get("mdl") if isinstance(package, dict) else {}
    freshness = {}
    if isinstance(mdl, dict) and isinstance(mdl.get("freshness"), dict):
        freshness.update(mdl["freshness"])
    if isinstance(asset.get("freshness"), dict):
        freshness.update(asset["freshness"])
    freshness.setdefault("status", "fresh")
    freshness.setdefault("as_of", now)
    return freshness


def _evidence(
    asset: dict[str, Any],
    package: dict[str, Any],
    metric: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in metric.get("evidence") or []:
        if isinstance(item, dict):
            evidence.append(item)
    for item in asset.get("sample_evidence") or package.get("evidence") or []:
        if isinstance(item, dict):
            evidence.append(item)
    return evidence[:10]


def _denied_response(
    asset: dict[str, Any],
    body: AskDataQueryBody,
    policies: dict[str, Any],
) -> dict[str, Any]:
    now = now_iso()
    return redacted(
        {
            "schema": "agentkit.askdata.result.v1",
            "status": "blocked",
            "asset": {
                "type": "semantic_model",
                "id": asset["asset_id"],
                "name": asset["name"],
                "version": asset.get("version") or "v1",
            },
            "query": body.model_dump(mode="json"),
            "data": {
                "rows": [],
                "returnedCount": 0,
                "sql": "",
                "metricDefinition": "",
                "policyDecision": {
                    "decision": "deny",
                    "reason": "问题包含客户、联系方式、证件或其他受限字段，只能返回聚合且脱敏后的指标。",
                    "denied_fields": policies.get("denied_fields", []),
                    "masked_fields": policies.get("masked_fields", []),
                },
                "freshness": {"status": "blocked", "as_of": now},
                "evidence": [{"kind": "policy", "title": "PII policy guard"}],
            },
            "mock": False,
        }
    )
