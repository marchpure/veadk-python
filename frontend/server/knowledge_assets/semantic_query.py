"""Governed REST query adapter for generated Semantic Skills.

This adapter intentionally does not open source credentials or execute raw SQL.
It resolves a published Semantic Skill, validates metric/dimension policy, and
returns aggregate evidence already captured in sanitized snapshot metadata.
"""

from __future__ import annotations

import re
from typing import Any

from .contract import KnowledgeAssetType
from .models import QueryExternalAssetBody
from .service import KnowledgeAssetServiceError, KnowledgeAssetStore, redact_sensitive

_PII_RE = re.compile(
    r"(customer|cust|buyer|contact|phone|mobile|tel|address|addr|passport|member[_ -]?card|"
    r"vip[_ -]?card|id[_ -]?card|email|mail|person|姓名|客户|电话|手机|地址|护照|会员卡)",
    re.IGNORECASE,
)


async def query_external_asset(
    store: KnowledgeAssetStore,
    *,
    asset_type: KnowledgeAssetType,
    asset_id: str,
    body: QueryExternalAssetBody,
) -> dict[str, Any]:
    if asset_type != "semantic_model":
        raise KnowledgeAssetServiceError("Only semantic_model governed query is supported here.")
    asset = await store.get_asset(asset_type=asset_type, asset_id=asset_id)
    if asset.get("capability_kind") != "semantic_skill":
        raise KnowledgeAssetServiceError("Only published Semantic Skill assets can be queried.")
    package = asset.get("capability_package")
    if not isinstance(package, dict):
        raise KnowledgeAssetServiceError("Semantic Skill package is missing.")
    mdl = package.get("mdl") if isinstance(package.get("mdl"), dict) else {}
    governance = package.get("governance") if isinstance(package.get("governance"), dict) else {}
    metrics = _items(mdl.get("metrics"))
    dimensions = _items(mdl.get("dimensions"))
    metric_id = body.metric.strip()
    if not metric_id:
        raise KnowledgeAssetServiceError("metric is required for governed semantic query.")
    metric = _find_by_id_or_name(metrics, metric_id)
    if metric is None:
        raise KnowledgeAssetServiceError(f"Metric is not declared in this Semantic Skill: {metric_id}")
    dimension_id = (body.dimension or "").strip()
    dimension = _find_by_id_or_name(dimensions, dimension_id) if dimension_id else None
    if dimension_id and dimension is None:
        raise KnowledgeAssetServiceError(f"Dimension is not declared in this Semantic Skill: {dimension_id}")

    policy = asset.get("usage_policy") if isinstance(asset.get("usage_policy"), dict) else {}
    denied = _policy_denial(policy, body)
    if denied:
        return _response(
            asset=asset,
            metric=metric,
            dimension=dimension,
            rows=[],
            sql="",
            decision="deny",
            reason=denied,
        )
    if str(metric.get("certification") or "").lower() == "blocked":
        return _response(
            asset=asset,
            metric=metric,
            dimension=dimension,
            rows=[],
            sql=_planned_sql(mdl, metric, dimension, body.limit),
            decision="blocked",
            reason="Metric certification is blocked pending business review.",
        )

    allowed_metrics = [str(item) for item in _items(governance.get("allowed_metrics"))]
    allowed_dimensions = [str(item) for item in _items(governance.get("allowed_dimensions"))]
    if allowed_metrics and str(metric.get("id")) not in allowed_metrics:
        raise KnowledgeAssetServiceError("Metric is outside the Semantic Skill governance allowlist.")
    if dimension and allowed_dimensions and str(dimension.get("id")) not in allowed_dimensions:
        raise KnowledgeAssetServiceError("Dimension is outside the Semantic Skill governance allowlist.")

    rows = _snapshot_rows(mdl.get("snapshot_results"), metric, dimension, body.limit)
    sql = _planned_sql(mdl, metric, dimension, body.limit)
    return _response(
        asset=asset,
        metric=metric,
        dimension=dimension,
        rows=rows,
        sql=sql,
        decision="allow",
        reason="Governed aggregate metric query; raw SQL fallback is disabled.",
    )


def _response(
    *,
    asset: dict[str, Any],
    metric: dict[str, Any],
    dimension: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    sql: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    payload = {
        "schema": "agentkit.semantic_query.result.v1",
        "asset": {
            "asset_type": asset.get("asset_type"),
            "asset_id": asset.get("asset_id"),
            "capability_kind": asset.get("capability_kind"),
        },
        "rows": rows,
        "row_count": len(rows),
        "execution_mode": "snapshot_evidence_plan",
        "sql": sql,
        "metricDefinition": {
            "id": metric.get("id"),
            "name": metric.get("name"),
            "definition": metric.get("definition"),
            "formula": metric.get("formula"),
            "unit": metric.get("unit"),
            "certification": metric.get("certification"),
            "lineage": metric.get("lineage") or [],
        },
        "dimension": dimension or None,
        "policyDecision": {
            "decision": decision,
            "reason": reason,
            "raw_sql_fallback": False,
            "permission_hint": (asset.get("usage_policy") or {}).get("permission_hint")
            if isinstance(asset.get("usage_policy"), dict)
            else "",
        },
        "freshness": asset.get("freshness") or {},
        "evidence": {
            "sample": (asset.get("sample_evidence") or [])[:8],
            "snapshot_results": ((asset.get("capability_package") or {}).get("mdl") or {}).get("snapshot_results", {}),
        },
    }
    return {"data": redact_sensitive(payload), **{key: payload[key] for key in ("schema", "asset")}}


def _policy_denial(policy: dict[str, Any], body: QueryExternalAssetBody) -> str:
    haystack = " ".join(
        [
            body.metric,
            body.dimension or "",
            body.grain or "",
            str(body.filters or {}),
            str(body.time_range or {}),
            body.question or "",
        ]
    )
    denied_fields = []
    for item in _items(policy.get("denied_fields")):
        if isinstance(item, dict):
            field = str(item.get("field") or item.get("column") or item.get("name") or "")
        else:
            field = str(item)
        if field:
            denied_fields.append(field)
    for field in denied_fields:
        if field and field.lower() in haystack.lower():
            return f"Denied by Semantic Skill policy for field: {field}"
    if _PII_RE.search(haystack):
        return "Denied by Semantic Skill policy for customer/contact identity fields."
    return ""


def _snapshot_rows(
    snapshot_results: Any,
    metric: dict[str, Any],
    dimension: dict[str, Any] | None,
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(snapshot_results, dict):
        return []
    golden = snapshot_results.get("golden_results")
    if not isinstance(golden, dict):
        golden = {}
    metric_id = str(metric.get("id") or "")
    dimension_id = str((dimension or {}).get("id") or "")
    if metric_id == "ticket_count" and dimension_id == "store":
        rows = golden.get("top_3_stores_by_ticket_count")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)][:limit]
    if metric_id == "ticket_count":
        value = golden.get("ticket_count_last_30_snapshot_days")
        if isinstance(value, (int, float)):
            return [{"metric": metric_id, "value": value}]
    for key, value in golden.items():
        key_text = str(key).lower()
        if metric_id.lower() in key_text and isinstance(value, list):
            return [row for row in value if isinstance(row, dict)][:limit]
        if metric_id.lower() in key_text and isinstance(value, (int, float, str)):
            return [{"metric": metric_id, "value": value}]
    return []


def _planned_sql(
    mdl: dict[str, Any],
    metric: dict[str, Any],
    dimension: dict[str, Any] | None,
    limit: int,
) -> str:
    entity_id = str(metric.get("entity") or "")
    entity = next(
        (item for item in _items(mdl.get("entities")) if str(item.get("id") or item.get("name") or "") == entity_id),
        {},
    )
    table = _sql_identifier(str(entity.get("table") or entity_id or "semantic_model"))
    formula = _formula_sql(str(metric.get("formula") or ""))
    if not formula:
        formula = "COUNT(*)"
    if dimension:
        field = _sql_identifier(str(dimension.get("field") or dimension.get("id") or "dimension"))
        return (
            f"SELECT {field} AS dimension, {formula} AS value "
            f"FROM {table} GROUP BY {field} ORDER BY value DESC LIMIT {max(1, min(limit, 1000))}"
        )
    return f"SELECT {formula} AS value FROM {table} LIMIT 1"


def _formula_sql(value: str) -> str:
    cleaned = value.replace(";", " ").replace("--", " ").replace("/*", " ").replace("*/", " ")
    cleaned = re.sub(r"\bcount_distinct\s*\(([^)]+)\)", r"COUNT(DISTINCT \1)", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsum\s*\(", "SUM(", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bcount\s*\(", "COUNT(", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _sql_identifier(value: str) -> str:
    parts = [part for part in value.replace('"', "").split(".") if part.strip()]
    if not parts:
        return '"semantic_model"'
    return ".".join(f'"{part.strip()}"' for part in parts)


def _find_by_id_or_name(items: list[dict[str, Any]], value: str) -> dict[str, Any] | None:
    needle = value.casefold()
    for item in items:
        if str(item.get("id") or "").casefold() == needle or str(item.get("name") or "").casefold() == needle:
            return item
    return None


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
