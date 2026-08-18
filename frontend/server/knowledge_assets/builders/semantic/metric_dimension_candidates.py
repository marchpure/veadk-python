"""Metric, dimension, policy, and evidence candidates for Semantic Skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema_graph import (
    SchemaGraph,
    TableNode,
    is_identifier_name,
    is_numeric_type,
    is_pii_name,
    is_text_type,
    is_time_type,
    slugify,
)


@dataclass(frozen=True)
class MetricCandidate:
    id: str
    name: str
    entity: str
    field: str
    formula: str
    definition: str
    time_field: str = ""
    dimensions: list[str] = field(default_factory=list)
    confidence: float = 0.65
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DimensionCandidate:
    id: str
    name: str
    entity: str
    field: str
    role: str = "dimension"
    confidence: float = 0.6
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateSet:
    metrics: list[MetricCandidate]
    dimensions: list[DimensionCandidate]
    policies: dict[str, Any]
    freshness: dict[str, Any]
    evidence: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


def generate_candidates(
    graph: SchemaGraph,
    *,
    target_name: str = "",
    profile: dict[str, Any] | None = None,
    source_ids: list[str] | None = None,
    snapshot_ids: list[str] | None = None,
) -> CandidateSet:
    facts = [table for table in graph.tables if table.table_type in {"fact", "association"}]
    if not facts and graph.tables:
        facts = [graph.tables[0]]
    dimensions = _dimension_candidates(graph)
    metrics = _metric_candidates(facts, dimensions)
    policies = _policies(graph)
    evidence: list[dict[str, Any]] = [
        {
            "kind": "schema_graph",
            "tables": len(graph.tables),
            "relationships": len(graph.relationships),
            "source_ids": source_ids or [],
            "snapshot_ids": snapshot_ids or [],
            "confidence": 0.8 if graph.tables else 0.0,
        }
    ]
    for metric in metrics:
        evidence.extend(metric.evidence)
    freshness = _freshness(profile or {}, snapshot_ids or [])
    warnings = list(graph.warnings)
    if not metrics:
        warnings.append("未找到可用指标候选。请提供包含数值字段或主键的 schema snapshot。")
    return CandidateSet(
        metrics=metrics,
        dimensions=dimensions,
        policies=policies,
        freshness=freshness,
        evidence=evidence,
        warnings=warnings,
    )


def _metric_candidates(
    fact_tables: list[TableNode],
    dimensions: list[DimensionCandidate],
) -> list[MetricCandidate]:
    out: list[MetricCandidate] = []
    dimension_ids = [dimension.id for dimension in dimensions[:8]]
    for table in fact_tables:
        entity_id = slugify(table.name)
        time_field = next(
            (column.name for column in table.columns if is_time_type(column.data_type, column.name)),
            "",
        )
        pk = table.primary_key[0] if table.primary_key else ""
        if pk:
            out.append(
                MetricCandidate(
                    id=slugify(f"{table.name}_count"),
                    name=f"{table.name} count",
                    entity=entity_id,
                    field=pk,
                    formula=f"count_distinct({pk})",
                    definition=f"Count distinct {pk} records from {table.name}.",
                    time_field=time_field,
                    dimensions=dimension_ids,
                    confidence=0.82,
                    evidence=[
                        {
                            "kind": "primary_key_metric",
                            "table": table.name,
                            "field": pk,
                            "formula": f"count_distinct({pk})",
                            "confidence": 0.82,
                        }
                    ],
                )
            )
        for column in table.columns:
            if column.pii or column.primary_key or is_identifier_name(column.name):
                continue
            if not is_numeric_type(column.data_type, column.name):
                continue
            metric_id = slugify(f"{table.name}_{column.name}_sum")
            out.append(
                MetricCandidate(
                    id=metric_id,
                    name=f"{table.name} {column.name} sum",
                    entity=entity_id,
                    field=column.name,
                    formula=f"sum({column.name})",
                    definition=f"Sum of {column.name} from {table.name}.",
                    time_field=time_field,
                    dimensions=dimension_ids,
                    confidence=0.72,
                    evidence=[
                        {
                            "kind": "numeric_field_metric",
                            "table": table.name,
                            "field": column.name,
                            "type": column.data_type,
                            "formula": f"sum({column.name})",
                            "confidence": 0.72,
                        }
                    ],
                )
            )
    return _unique_by_id(out)[:12]


def _dimension_candidates(graph: SchemaGraph) -> list[DimensionCandidate]:
    out: list[DimensionCandidate] = []
    for table in graph.tables:
        entity_id = slugify(table.name)
        for column in table.columns:
            if column.pii:
                continue
            role = "time" if is_time_type(column.data_type, column.name) else "dimension"
            if role != "time" and (
                column.primary_key
                or is_identifier_name(column.name)
                or not (is_text_type(column.data_type, column.name) or _low_cardinality(column.profile))
            ):
                continue
            dim_id = slugify(f"{table.name}_{column.name}")
            out.append(
                DimensionCandidate(
                    id=dim_id,
                    name=f"{table.name} {column.name}",
                    entity=entity_id,
                    field=column.name,
                    role=role,
                    confidence=0.8 if role == "time" else 0.68,
                    evidence=[
                        {
                            "kind": "time_dimension" if role == "time" else "field_dimension",
                            "table": table.name,
                            "field": column.name,
                            "type": column.data_type,
                            "confidence": 0.8 if role == "time" else 0.68,
                        }
                    ],
                )
            )
    return _unique_by_id(out)[:30]


def _policies(graph: SchemaGraph) -> dict[str, Any]:
    masked: list[dict[str, str]] = []
    denied: list[dict[str, str]] = []
    for table in graph.tables:
        for column in table.columns:
            if column.pii or is_pii_name(column.name):
                item = {
                    "entity": slugify(table.name),
                    "table": table.name,
                    "field": column.name,
                    "reason": "PII pattern matched; default deny/mask for customer/contact identity.",
                }
                masked.append(item)
                denied.append(item)
    return {
        "permission_hint": "只允许通过受治理 REST 查询聚合指标；禁止绕过策略读取原始行级身份字段。",
        "masked_fields": masked,
        "denied_fields": denied,
        "raw_sql_fallback": False,
        "deny_patterns": [
            "customer",
            "contact",
            "phone",
            "address",
            "passport",
            "member card",
            "客户",
            "电话",
            "地址",
        ],
    }


def _freshness(profile: dict[str, Any], snapshot_ids: list[str]) -> dict[str, Any]:
    snapshot = profile.get("snapshot") if isinstance(profile.get("snapshot"), dict) else {}
    return {
        "status": snapshot.get("status") or profile.get("freshness_status") or "snapshot",
        "snapshot_ids": snapshot_ids,
        "snapshot_id": snapshot.get("id") or profile.get("snapshot_id") or (snapshot_ids[0] if snapshot_ids else ""),
        "snapshot_hash": snapshot.get("hash") or profile.get("snapshot_hash") or "",
        "data_through": snapshot.get("data_through") or profile.get("data_through") or "",
    }


def _low_cardinality(profile: dict[str, Any]) -> bool:
    for key in ("distinct_count", "distinct", "cardinality", "ndv"):
        value = profile.get(key)
        try:
            return int(value) <= 200
        except (TypeError, ValueError):
            continue
    return False


def _unique_by_id(items: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return out

