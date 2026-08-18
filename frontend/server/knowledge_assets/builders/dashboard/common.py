"""Shared helpers for native AskData and Dashboard Skill builders."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from ...service import KnowledgeAssetServiceError, redact_sensitive

_IDENTIFIER_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_PII_RE = re.compile(
    r"(customer|cust|contact|phone|tel|mobile|email|address|addr|passport|"
    r"idcard|identity|member[_-]?card|buyer|recipient|consignee)",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_slug(value: str, fallback: str = "asset") -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().casefold())
    slug = re.sub(r"-{2,}", "-", slug).strip("-._")
    return slug[:96] or f"{fallback}-{hashlib.sha256(value.encode()).hexdigest()[:8]}"


def safe_identifier(value: Any, *, fallback: str = "field") -> str:
    text = _IDENTIFIER_RE.sub("_", str(value or "").strip()).strip("._-")
    return text[:128] or fallback


def first_mapping(items: Any, key: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    normalized = key.casefold()
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get("id"),
            item.get("slug"),
            item.get("name"),
            item.get("field"),
            item.get("businessName"),
            item.get("business_name"),
        ]
        if any(str(candidate or "").casefold() == normalized for candidate in candidates):
            return item
    return None


def metric_id(metric: dict[str, Any]) -> str:
    return safe_identifier(
        metric.get("id")
        or metric.get("slug")
        or metric.get("name")
        or metric.get("businessName")
        or metric.get("business_name"),
        fallback="metric",
    )


def metric_label(metric: dict[str, Any]) -> str:
    return str(
        metric.get("businessName")
        or metric.get("business_name")
        or metric.get("name")
        or metric_id(metric)
    )


def metric_definition(metric: dict[str, Any]) -> str:
    return str(
        metric.get("definition")
        or metric.get("description")
        or metric.get("formula")
        or metric_label(metric)
    )


def metric_formula(metric: dict[str, Any]) -> str:
    return str(metric.get("formula") or metric.get("expr") or metric_id(metric))


def dimension_id(dimension: dict[str, Any]) -> str:
    return safe_identifier(
        dimension.get("id")
        or dimension.get("slug")
        or dimension.get("field")
        or dimension.get("name"),
        fallback="dimension",
    )


def dimension_label(dimension: dict[str, Any]) -> str:
    return str(dimension.get("name") or dimension.get("field") or dimension_id(dimension))


def dimension_field(dimension: dict[str, Any]) -> str:
    return safe_identifier(dimension.get("field") or dimension_id(dimension), fallback="dimension")


def pii_requested(*values: Any, policies: dict[str, Any] | None = None) -> bool:
    text = " ".join(str(value or "") for value in values)
    if _PII_RE.search(text):
        return True
    policy = policies or {}
    for key in ("denied_fields", "masked_fields", "deny_patterns"):
        raw = policy.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                raw_item = " ".join(str(value) for value in item.values())
            else:
                raw_item = str(item)
            if raw_item and raw_item.casefold() in text.casefold():
                return True
    return False


def require_semantic_package(asset: dict[str, Any]) -> dict[str, Any]:
    if asset.get("asset_type") != "semantic_model":
        raise KnowledgeAssetServiceError("AskData 需要选择已发布的 Semantic Skill。")
    package = asset.get("capability_package")
    if not isinstance(package, dict):
        raise KnowledgeAssetServiceError("Semantic Skill 缺少能力包。")
    mdl = package.get("mdl")
    if not isinstance(mdl, dict):
        raise KnowledgeAssetServiceError("Semantic Skill 缺少 mdl 定义。")
    return package


def sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''")[:512] + "'"


def compile_semantic_sql(
    *,
    mdl: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    filters: dict[str, Any],
    time_range: dict[str, Any],
    limit: int,
) -> str:
    metric_expr = metric_formula(metric)
    metric_alias = metric_id(metric)
    select_parts = [f"{metric_expr} AS {metric_alias}"]
    group_parts: list[str] = []
    for dimension in dimensions:
        field = dimension_field(dimension)
        alias = dimension_id(dimension)
        select_parts.insert(0, f"{field} AS {alias}")
        group_parts.append(field)

    entities = mdl.get("entities") if isinstance(mdl.get("entities"), list) else []
    table = "semantic_model"
    for entity in entities:
        if isinstance(entity, dict) and entity.get("table"):
            table = safe_identifier(entity.get("table"), fallback="semantic_model")
            break
    where_parts: list[str] = []
    for key, value in filters.items():
        field = safe_identifier(key, fallback="filter")
        if isinstance(value, list):
            literals = ", ".join(sql_literal(item) for item in value[:20])
            where_parts.append(f"{field} IN ({literals})")
        elif value not in (None, ""):
            where_parts.append(f"{field} = {sql_literal(value)}")
    start = time_range.get("start") or time_range.get("from")
    end = time_range.get("end") or time_range.get("to")
    time_field = metric.get("time_field") or metric.get("timeField") or ""
    if time_field and start:
        where_parts.append(f"{safe_identifier(time_field)} >= {sql_literal(start)}")
    if time_field and end:
        where_parts.append(f"{safe_identifier(time_field)} < {sql_literal(end)}")

    sql = f"SELECT {', '.join(select_parts)} FROM {table}"
    if where_parts:
        sql += f" WHERE {' AND '.join(where_parts)}"
    if group_parts:
        sql += f" GROUP BY {', '.join(group_parts)}"
    sql += f" LIMIT {max(1, min(int(limit or 100), 500))}"
    return sql


def synthetic_rows(metric: dict[str, Any], dimensions: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    metric_key = metric_id(metric)
    if not dimensions:
        return [{metric_key: 128}]
    rows: list[dict[str, Any]] = []
    labels = ["核心项", "增长项", "稳定项"]
    for index, label in enumerate(labels[: max(1, min(limit, 3))], start=1):
        row = {metric_key: 128 - index * 17}
        for dimension in dimensions:
            row[dimension_id(dimension)] = label
        rows.append(row)
    return rows


def redacted(value: Any) -> Any:
    return redact_sensitive(value)
