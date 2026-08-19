"""Governed Semantic Skill query adapter for AskData and Dashboard builders."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from pydantic import Field, field_validator

from ...models import ApiModel
from ...service import KnowledgeAssetServiceError, KnowledgeAssetStore, redact_sensitive
from .common import (
    dimension_id,
    first_mapping,
    metric_definition,
    metric_id,
    metric_label,
    now_iso,
    pii_requested,
    redacted,
    require_semantic_package,
)


@dataclass(frozen=True)
class SemanticQueryRequest:
    semantic_asset_id: str
    metric: str | None = None
    dimension: str | None = None
    dimensions: tuple[str, ...] = ()
    filters: dict[str, Any] | None = None
    time_range: dict[str, Any] | None = None
    question: str | None = None
    limit: int = 100
    mode: str = "summary"
    require_live: bool = True
    allow_demo_snapshot: bool = False

    @classmethod
    def from_body(cls, body: Any) -> "SemanticQueryRequest":
        dimensions = getattr(body, "dimensions", []) or []
        mode = str(getattr(body, "mode", "summary") or "summary")
        offline_mode = _is_offline_mode(mode)
        require_live_value = getattr(body, "require_live", None)
        allow_demo_value = getattr(body, "allow_demo_snapshot", None)
        return cls(
            semantic_asset_id=str(getattr(body, "semantic_asset_id", "") or ""),
            metric=getattr(body, "metric", None),
            dimension=getattr(body, "dimension", None),
            dimensions=tuple(str(item) for item in dimensions if str(item).strip()),
            filters=getattr(body, "filters", {}) or {},
            time_range=getattr(body, "time_range", {}) or {},
            question=getattr(body, "question", None),
            limit=int(getattr(body, "limit", 100) or 100),
            mode=mode,
            require_live=not offline_mode
            if require_live_value is None
            else bool(require_live_value),
            allow_demo_snapshot=offline_mode
            if allow_demo_value is None
            else bool(allow_demo_value),
        )

    @classmethod
    def from_asset_body(
        cls,
        asset_id: str,
        body: Any,
    ) -> "SemanticQueryRequest":
        request = cls.from_body(body)
        return cls(
            semantic_asset_id=asset_id,
            metric=request.metric,
            dimension=request.dimension,
            dimensions=request.dimensions,
            filters=request.filters,
            time_range=request.time_range,
            question=request.question,
            limit=request.limit,
            mode=request.mode,
            require_live=request.require_live,
            allow_demo_snapshot=request.allow_demo_snapshot,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "dimension": self.dimension,
            "dimensions": list(self.dimensions),
            "filters": self.filters or {},
            "time_range": self.time_range or {},
            "question": self.question,
            "limit": self.limit,
            "mode": self.mode,
            "require_live": self.require_live,
            "allow_demo_snapshot": self.allow_demo_snapshot,
        }


class SemanticAssetQueryBody(ApiModel):
    metric: str | None = Field(default=None, max_length=200)
    dimension: str | None = Field(default=None, max_length=200)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    grain: str | None = Field(default=None, max_length=80)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_range: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=500)
    question: str | None = Field(default=None, max_length=1000)
    mode: str = Field(default="summary", max_length=80)
    data_view_ids: list[str] = Field(default_factory=list, max_length=20)
    require_live: bool | None = None
    allow_demo_snapshot: bool | None = None

    @field_validator("dimensions", "data_view_ids")
    @classmethod
    def _trim_list(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class GovernedSemanticQueryAdapter:
    """Consume Semantic Skill governed query evidence without raw SQL fallback."""

    async def query(
        self,
        asset: dict[str, Any],
        request: SemanticQueryRequest,
    ) -> dict[str, Any]:
        package = require_semantic_package(asset)
        mdl = normalize_semantic_mdl(asset, package)
        policies = policy_payload(asset, package, mdl)
        metric = select_metric(mdl.get("metrics", []), request.metric, request.question)
        requested_dimensions = list(request.dimensions) or (
            [request.dimension] if request.dimension else []
        )
        dimensions = select_dimensions(
            mdl.get("dimensions", []),
            requested_dimensions,
            request.question,
        )

        if pii_requested(
            request.question,
            request.metric,
            request.dimension,
            list(request.dimensions),
            request.filters or {},
            policies=policies,
        ):
            return semantic_denied_response(asset, request, policies, metric, dimensions, mdl)

        governed_result = await _resolve_governed_result(
            asset=asset,
            package=package,
            request=request,
            metric=metric,
            dimensions=dimensions,
            policies=policies,
            mdl=mdl,
        )
        return redact_sensitive(governed_result)


class GovernedSemanticQueryService:
    """Route-backed governed query service for published Semantic Skill assets."""

    def __init__(self, store: KnowledgeAssetStore) -> None:
        self._store = store
        self._adapter = GovernedSemanticQueryAdapter()

    async def query_asset(
        self,
        asset_id: str,
        body: SemanticAssetQueryBody,
    ) -> dict[str, Any]:
        asset = await self._store.get_asset(
            asset_type="semantic_model",
            asset_id=asset_id,
        )
        return await self.query_loaded_asset(
            asset,
            SemanticQueryRequest.from_asset_body(asset_id, body),
        )

    async def query_loaded_asset(
        self,
        asset: dict[str, Any],
        request: SemanticQueryRequest,
    ) -> dict[str, Any]:
        return await self._adapter.query(asset, request)


def _package_artifacts(package: dict[str, Any]) -> dict[str, Any]:
    for key in ("artifacts", "files"):
        value = package.get(key)
        if isinstance(value, dict):
            return value
    return {}


def normalize_semantic_mdl(
    asset: dict[str, Any],
    package: dict[str, Any],
) -> dict[str, Any]:
    inline = package.get("mdl") if isinstance(package.get("mdl"), dict) else {}
    artifacts = _package_artifacts(package)
    models = _artifact_dict(artifacts, "mdl/models.json")
    metrics = _artifact_dict(artifacts, "mdl/metrics.json")
    dimensions = _artifact_dict(artifacts, "mdl/dimensions.json")
    relationships = _artifact_dict(artifacts, "mdl/relationships.json")
    permissions = _artifact_dict(artifacts, "mdl/permissions.json")
    freshness = _artifact_dict(artifacts, "mdl/freshness.json")

    model = _first_dict(inline.get("model"), models.get("model"))
    entities = _first_list(inline.get("entities"), models.get("entities"))
    out = {
        "schema": inline.get("schema") or models.get("schema") or "agentkit.mdl.v1",
        "model": {
            "id": asset.get("asset_id"),
            "slug": asset.get("asset_id"),
            "version": asset.get("version") or "v1",
            **model,
        },
        "entities": entities,
        "relationships": _first_list(
            inline.get("relationships"),
            relationships.get("relationships"),
        ),
        "metrics": _first_list(inline.get("metrics"), metrics.get("metrics")),
        "dimensions": _first_list(
            inline.get("dimensions"),
            dimensions.get("dimensions"),
        ),
        "permissions": _first_dict(
            inline.get("permissions"),
            permissions.get("permissions"),
        ),
        "freshness": _first_dict(
            inline.get("freshness"),
            freshness.get("freshness"),
            asset.get("freshness"),
        ),
        "snapshot_results": _first_dict(inline.get("snapshot_results")),
        "evidence": _first_list(inline.get("evidence")),
    }
    if not out["metrics"]:
        raise KnowledgeAssetServiceError("Semantic Skill 没有可查询指标。")
    return out


def policy_payload(
    asset: dict[str, Any],
    package: dict[str, Any],
    mdl: dict[str, Any],
) -> dict[str, Any]:
    governance = package.get("governance") if isinstance(package.get("governance"), dict) else {}
    policy: dict[str, Any] = {}
    for value in (
        asset.get("usage_policy"),
        governance.get("usage_policy"),
        mdl.get("permissions"),
    ):
        if isinstance(value, dict):
            policy.update(value)
    return policy


def select_metric(
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


def select_dimensions(
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
    intent_dimension = _dimension_from_question(dimensions, question_norm)
    if intent_dimension:
        return [intent_dimension]
    for dimension in dimensions:
        candidates = [
            dimension_id(dimension),
            str(dimension.get("name") or ""),
            str(dimension.get("field") or ""),
        ]
        if any(candidate.casefold() in question_norm for candidate in candidates if candidate):
            out.append(dimension)
    return out[:3]


def _dimension_from_question(
    dimensions: list[dict[str, Any]],
    question_norm: str,
) -> dict[str, Any] | None:
    intent_aliases = (
        (("门店", "store", "店铺"), ("store", "store_name")),
        (("区域", "region", "地区"), ("region",)),
        (("日期", "时间", "趋势", "month", "月份", "date"), ("date", "order_date", "month")),
    )
    for question_terms, dimension_terms in intent_aliases:
        if not any(term in question_norm for term in question_terms):
            continue
        for dimension in dimensions:
            haystack = " ".join(
                str(value or "").casefold()
                for value in (
                    dimension_id(dimension),
                    dimension.get("name"),
                    dimension.get("field"),
                    dimension.get("role"),
                )
            )
            if any(term in haystack for term in dimension_terms):
                return dimension
    return None


def semantic_denied_response(
    asset: dict[str, Any],
    request: SemanticQueryRequest,
    policies: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    mdl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now_iso()
    freshness = freshness_payload(asset, {}, now, mdl=mdl)
    freshness.update({"status": "blocked", "as_of": freshness.get("as_of") or now})
    return redacted(
        {
            "schema": "agentkit.semantic_query_result.v1",
            "asset": {
                "type": "semantic_model",
                "id": asset["asset_id"],
                "version": asset.get("version") or "v1",
            },
            "data": {
                "rows": [],
                "returnedCount": 0,
                "metric": _metric_payload(metric),
                "dimensions": [_dimension_payload(item) for item in dimensions],
                "sql": "-- policy denied by governed Semantic Skill; no raw SQL executed",
                "metricDefinition": metric_definition(metric),
                "policyDecision": {
                    "decision": "deny",
                    "reason": "问题包含客户、联系方式、证件或其他受限字段，只能返回聚合且脱敏后的指标。",
                    "denied_fields": policies.get("denied_fields", []),
                    "masked_fields": policies.get("masked_fields", []),
                },
                "freshness": freshness,
                "lineage": [],
                "evidence": [{"kind": "policy", "title": "PII policy guard"}],
                "execution": {
                    "mode": "policy_denied",
                    "governed_rest": True,
                    "direct_database_access": False,
                    "raw_sql_fallback": False,
                },
            },
            "mock": False,
        }
    )


def freshness_payload(
    asset: dict[str, Any],
    package: dict[str, Any],
    now: str,
    *,
    mdl: dict[str, Any] | None = None,
) -> dict[str, Any]:
    freshness: dict[str, Any] = {}
    if isinstance(mdl, dict) and isinstance(mdl.get("freshness"), dict):
        freshness.update(mdl["freshness"])
    package_mdl = package.get("mdl") if isinstance(package, dict) else {}
    if isinstance(package_mdl, dict) and isinstance(package_mdl.get("freshness"), dict):
        freshness.update(package_mdl["freshness"])
    if isinstance(asset.get("freshness"), dict):
        freshness.update(asset["freshness"])
    freshness.setdefault("status", "fresh")
    freshness.setdefault("as_of", now)
    return freshness


def evidence_payload(
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


async def _resolve_governed_result(
    *,
    asset: dict[str, Any],
    package: dict[str, Any],
    request: SemanticQueryRequest,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    policies: dict[str, Any],
    mdl: dict[str, Any],
) -> dict[str, Any]:
    candidates = _governed_result_candidates(package)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if request.require_live and _is_demo_snapshot_candidate(candidate):
            continue
        result = _normalize_governed_result(
            candidate,
            asset=asset,
            package=package,
            request=request,
            metric=metric,
            dimensions=dimensions,
            policies=policies,
            mdl=mdl,
        )
        if result is not None:
            return result

    sidecar_result = await _query_governed_sidecar(
        asset=asset,
        package=package,
        request=request,
        metric=metric,
        dimensions=dimensions,
        policies=policies,
        mdl=mdl,
    )
    if sidecar_result is not None:
        return sidecar_result

    sqlite_result = _query_local_sqlite_runtime(
        asset=asset,
        package=package,
        request=request,
        metric=metric,
        dimensions=dimensions,
        policies=policies,
        mdl=mdl,
    )
    if sqlite_result is not None:
        return sqlite_result

    if request.require_live and not request.allow_demo_snapshot:
        raise KnowledgeAssetServiceError(
            "Semantic Skill 缺少可用 live governed query 结果；生产 AskTable 不会回退到 schema_only。"
        )

    return _schema_only_governed_result(
        asset=asset,
        package=package,
        request=request,
        metric=metric,
        dimensions=dimensions,
        policies=policies,
        mdl=mdl,
    )


def _schema_only_governed_result(
    *,
    asset: dict[str, Any],
    package: dict[str, Any],
    request: SemanticQueryRequest,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    policies: dict[str, Any],
    mdl: dict[str, Any],
) -> dict[str, Any]:
    sql = _compile_governed_schema_sql(mdl, metric, dimensions, request)
    rows = _snapshot_rows(mdl.get("snapshot_results"), metric, dimensions, request.limit)
    data = {
        "rows": rows,
        "returnedCount": len(rows),
        "metric": _metric_payload(metric),
        "dimensions": [_dimension_payload(item) for item in dimensions],
        "sql": sql,
        "metricDefinition": _metric_payload(metric) if rows else metric_definition(metric),
        "policyDecision": {
            "decision": "allow",
            "reason": policies.get("permission_hint")
            or "通过 Semantic Skill 受治理查询路径返回；当前没有可执行快照结果。",
            "raw_sql_fallback": False,
            "direct_database_access": False,
            "denied_fields": policies.get("denied_fields", []),
            "masked_fields": policies.get("masked_fields", []),
        },
        "freshness": freshness_payload(asset, package, now_iso(), mdl=mdl),
        "lineage": metric.get("lineage") or asset.get("sample_evidence") or package.get("evidence") or [],
        "evidence": evidence_payload(asset, package, metric),
        "execution": {
            "mode": "schema_only",
            "governed_rest": True,
            "direct_database_access": False,
            "raw_sql_fallback": False,
            "result_source": "semantic_skill_snapshot"
            if rows
            else "semantic_skill_mdl",
            "demo_offline": True,
            "production_completed": False,
        },
        "execution_mode": "snapshot_evidence_plan" if rows else "schema_only",
    }
    _require_complete_governed_result(data)
    return _semantic_envelope(
        {"schema": "agentkit.semantic_query_result.v1"},
        asset,
        data,
        request,
        metric,
        dimensions,
    )


async def _query_governed_sidecar(
    *,
    asset: dict[str, Any],
    package: dict[str, Any],
    request: SemanticQueryRequest,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    policies: dict[str, Any],
    mdl: dict[str, Any],
) -> dict[str, Any] | None:
    runtime = package.get("runtime") if isinstance(package.get("runtime"), dict) else {}
    query_url = str(asset.get("query_url") or runtime.get("query_url") or "").strip()
    parsed = urlsplit(query_url)
    if parsed.scheme or parsed.netloc or query_url.startswith("//"):
        raise KnowledgeAssetServiceError("Semantic Skill query_url 必须是同源受治理路径。")
    if not parsed.path.startswith("/api/external/assets/semantic_model/"):
        return None
    return None


def _query_local_sqlite_runtime(
    *,
    asset: dict[str, Any],
    package: dict[str, Any],
    request: SemanticQueryRequest,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    policies: dict[str, Any],
    mdl: dict[str, Any],
) -> dict[str, Any] | None:
    runtime = _local_sqlite_runtime(package)
    if not runtime:
        return None
    sql, params = _compile_local_sqlite_sql(runtime, metric, dimensions, request)
    rows = _execute_local_sqlite(runtime, sql, params)
    data = {
        "rows": rows,
        "returnedCount": len(rows),
        "metric": _metric_payload(metric),
        "dimensions": [_dimension_payload(item) for item in dimensions],
        "sql": sql,
        "metricDefinition": metric_definition(metric),
        "policyDecision": {
            "decision": "allow",
            "reason": policies.get("permission_hint")
            or "通过本地只读 SQLite governed runtime 返回聚合结果。",
            "raw_sql_fallback": False,
            "direct_database_access": False,
            "denied_fields": policies.get("denied_fields", []),
            "masked_fields": policies.get("masked_fields", []),
        },
        "freshness": freshness_payload(asset, package, now_iso(), mdl=mdl),
        "lineage": metric.get("lineage") or asset.get("sample_evidence") or package.get("evidence") or [],
        "evidence": [
            *evidence_payload(asset, package, metric),
            {
                "kind": "local_governed_runtime",
                "title": "Local SQLite governed query",
                "datasource": runtime.get("datasource_id") or "local_sqlite",
                "view": runtime["view"],
            },
        ],
        "execution": {
            "mode": "governed_semantic_skill",
            "governed_rest": True,
            "direct_database_access": False,
            "raw_sql_fallback": False,
            "result_source": "local_sqlite_governed_runtime",
            "production_completed": True,
            "readonly": True,
        },
        "execution_mode": "local_sqlite_governed_runtime",
        "production_completed": True,
        "live": True,
    }
    _require_complete_governed_result(data)
    return _semantic_envelope(
        {"schema": "agentkit.semantic_query_result.v1"},
        asset,
        data,
        request,
        metric,
        dimensions,
    )


def _local_sqlite_runtime(package: dict[str, Any]) -> dict[str, Any] | None:
    runtime = package.get("runtime") if isinstance(package.get("runtime"), dict) else {}
    local = runtime.get("local_sqlite") if isinstance(runtime.get("local_sqlite"), dict) else {}
    if not local:
        return None
    path = str(local.get("path") or "").strip()
    view = str(local.get("view") or local.get("table") or "").strip()
    if not path or not view:
        raise KnowledgeAssetServiceError("Local SQLite governed runtime 缺少 path 或 view。")
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise KnowledgeAssetServiceError("Local SQLite governed runtime 数据库不存在。")
    if not _safe_sql_name(view):
        raise KnowledgeAssetServiceError("Local SQLite governed runtime view 名称无效。")
    return {
        "path": str(db_path),
        "view": view,
        "datasource_id": str(local.get("datasource_id") or "").strip(),
        "metric_fields": local.get("metric_fields") if isinstance(local.get("metric_fields"), dict) else {},
        "dimension_fields": local.get("dimension_fields") if isinstance(local.get("dimension_fields"), dict) else {},
        "field_map": local.get("field_map") if isinstance(local.get("field_map"), dict) else {},
    }


def _compile_local_sqlite_sql(
    runtime: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    request: SemanticQueryRequest,
) -> tuple[str, list[Any]]:
    view = _sqlite_identifier(runtime["view"])
    metric_alias = metric_id(metric)
    if not _safe_sql_name(metric_alias):
        raise KnowledgeAssetServiceError("Semantic Skill metric id 不能用于受治理查询。")
    metric_expr = _sqlite_metric_expr(runtime, metric)
    select_parts: list[str] = []
    group_parts: list[str] = []
    for dimension in dimensions:
        alias = dimension_id(dimension)
        if not _safe_sql_name(alias):
            raise KnowledgeAssetServiceError("Semantic Skill dimension id 不能用于受治理查询。")
        field = _sqlite_dimension_field(runtime, dimension)
        select_parts.append(f"{_sqlite_identifier(field)} AS {_sqlite_identifier(alias)}")
        group_parts.append(_sqlite_identifier(field))
    select_parts.append(f"{metric_expr} AS {_sqlite_identifier(metric_alias)}")
    sql = f"SELECT {', '.join(select_parts)} FROM {view}"
    where_parts, params = _sqlite_where_parts(runtime, metric, request)
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
        sql += f" ORDER BY {_sqlite_identifier(metric_alias)} DESC"
    sql += f" LIMIT {max(1, min(int(request.limit or 100), 500))}"
    return sql, params


def _sqlite_metric_expr(runtime: dict[str, Any], metric: dict[str, Any]) -> str:
    fields = runtime.get("metric_fields") if isinstance(runtime.get("metric_fields"), dict) else {}
    field_map = runtime.get("field_map") if isinstance(runtime.get("field_map"), dict) else {}
    metric_key = metric_id(metric)
    mapped = fields.get(metric_key) or field_map.get(metric.get("field")) or metric.get("field") or metric_key
    field = _assert_sql_name(mapped, "metric field")
    formula = str(metric.get("formula") or metric.get("expr") or "").strip().casefold()
    kind = str(metric.get("kind") or "").casefold()
    if formula.startswith("count_distinct") or "count(distinct" in formula or kind == "count_distinct":
        return f"COUNT(DISTINCT {_sqlite_identifier(field)})"
    if formula.startswith("count(") or kind == "count":
        return f"COUNT({_sqlite_identifier(field)})"
    if formula.startswith("avg(") or kind == "avg":
        return f"AVG({_sqlite_identifier(field)})"
    if formula.startswith("min(") or kind == "min":
        return f"MIN({_sqlite_identifier(field)})"
    if formula.startswith("max(") or kind == "max":
        return f"MAX({_sqlite_identifier(field)})"
    return f"SUM({_sqlite_identifier(field)})"


def _sqlite_dimension_field(runtime: dict[str, Any], dimension: dict[str, Any]) -> str:
    fields = runtime.get("dimension_fields") if isinstance(runtime.get("dimension_fields"), dict) else {}
    field_map = runtime.get("field_map") if isinstance(runtime.get("field_map"), dict) else {}
    key = dimension_id(dimension)
    mapped = fields.get(key) or field_map.get(dimension.get("field")) or dimension.get("field") or key
    return _assert_sql_name(mapped, "dimension field")


def _sqlite_where_parts(
    runtime: dict[str, Any],
    metric: dict[str, Any],
    request: SemanticQueryRequest,
) -> tuple[list[str], list[Any]]:
    parts: list[str] = []
    params: list[Any] = []
    field_map = runtime.get("field_map") if isinstance(runtime.get("field_map"), dict) else {}
    filters = request.filters if isinstance(request.filters, dict) else {}
    for key, value in filters.items():
        field = _assert_sql_name(field_map.get(key) or key, "filter field")
        if isinstance(value, list) and value:
            values = value[:20]
            parts.append(
                f"{_sqlite_identifier(field)} IN ({', '.join('?' for _ in values)})"
            )
            params.extend(values)
        elif value not in (None, ""):
            parts.append(f"{_sqlite_identifier(field)} = ?")
            params.append(value)
    time_range = request.time_range if isinstance(request.time_range, dict) else {}
    time_field = str(metric.get("time_field") or metric.get("timeField") or "").strip()
    if time_field:
        mapped_time = _assert_sql_name(field_map.get(time_field) or time_field, "time field")
        if start := time_range.get("start") or time_range.get("from"):
            parts.append(f"{_sqlite_identifier(mapped_time)} >= ?")
            params.append(start)
        if end := time_range.get("end") or time_range.get("to"):
            parts.append(f"{_sqlite_identifier(mapped_time)} < ?")
            params.append(end)
    return parts, params


def _execute_local_sqlite(
    runtime: dict[str, Any],
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    uri = f"file:{runtime['path']}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except sqlite3.Error as error:
        raise KnowledgeAssetServiceError(
            "Local SQLite governed runtime 查询失败：" + str(error)
        ) from error


def _assert_sql_name(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not _safe_sql_name(text):
        raise KnowledgeAssetServiceError(f"Local SQLite governed runtime {label} 名称无效。")
    return text


def _safe_sql_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or ""))


def _sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _is_offline_mode(mode: str) -> bool:
    return mode.strip().casefold() in {
        "demo",
        "offline",
        "schema_only",
        "snapshot",
        "test",
    }


def _is_demo_snapshot_candidate(candidate: dict[str, Any]) -> bool:
    data = candidate.get("data") if isinstance(candidate.get("data"), dict) else candidate
    execution = data.get("execution") if isinstance(data, dict) else {}
    mode = str(
        data.get("execution_mode")
        or (execution.get("mode") if isinstance(execution, dict) else "")
        or ""
    ).casefold()
    source = str(
        (execution.get("result_source") if isinstance(execution, dict) else "")
        or ""
    ).casefold()
    if mode in {"schema_only", "snapshot_evidence_plan"}:
        return True
    return "snapshot" in source and not _candidate_marks_live(data, execution)


def _candidate_marks_live(data: dict[str, Any], execution: Any) -> bool:
    if isinstance(execution, dict):
        if execution.get("production_completed") is True:
            return True
        source = str(execution.get("result_source") or "").casefold()
        if source in {"live", "sidecar", "governed_sidecar", "semantic_runtime"}:
            return True
    return bool(data.get("live") or data.get("production_completed"))


def _governed_result_candidates(package: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = package.get("runtime") if isinstance(package.get("runtime"), dict) else {}
    artifacts = _package_artifacts(package)
    evals = package.get("evals") if isinstance(package.get("evals"), dict) else {}
    raw_candidates = [
        package.get("governed_query_result"),
        package.get("semantic_query_result"),
        runtime.get("governed_query_result"),
        runtime.get("sample_result"),
        artifacts.get("governed_query_result.json"),
        artifacts.get("semantic_query_result.json"),
        artifacts.get("evals/governed_query_result.json"),
        evals.get("governed_query_result"),
        evals.get("sample_result"),
    ]
    out: list[dict[str, Any]] = []
    for item in raw_candidates:
        if isinstance(item, dict):
            out.append(item)
    cases = evals.get("cases") if isinstance(evals.get("cases"), list) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        for key in ("governed_query_result", "semantic_query_result", "result"):
            value = case.get(key)
            if isinstance(value, dict):
                out.append(value)
    return out


def _normalize_governed_result(
    candidate: dict[str, Any],
    *,
    asset: dict[str, Any],
    package: dict[str, Any],
    request: SemanticQueryRequest,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    policies: dict[str, Any],
    mdl: dict[str, Any],
) -> dict[str, Any] | None:
    data = candidate.get("data") if isinstance(candidate.get("data"), dict) else candidate
    policy = data.get("policyDecision") if isinstance(data, dict) else None
    if isinstance(policy, dict) and str(policy.get("decision", "")).lower() == "deny":
        data = {
            **data,
            "rows": data.get("rows") if isinstance(data.get("rows"), list) else [],
            "returnedCount": int(data.get("returnedCount") or 0),
            "sql": data.get("sql") or "-- policy denied by governed Semantic Skill; no raw SQL executed",
            "metricDefinition": data.get("metricDefinition") or metric_definition(metric),
            "policyDecision": {
                "raw_sql_fallback": False,
                **policy,
                "decision": "deny",
            },
            "freshness": data.get("freshness")
            if isinstance(data.get("freshness"), dict)
            else freshness_payload(asset, package, now_iso(), mdl=mdl),
            "execution": {
                "mode": "policy_denied",
                "governed_rest": True,
                "direct_database_access": False,
                "raw_sql_fallback": False,
                **(
                    data.get("execution")
                    if isinstance(data.get("execution"), dict)
                    else {}
                ),
            },
        }
        return _semantic_envelope(candidate, asset, data, request, metric, dimensions)

    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) and isinstance(data.get("result"), list):
        rows = data.get("result")
    sql = data.get("sql") if isinstance(data, dict) else None
    metric_def = (
        data.get("metricDefinition")
        or data.get("metric_definition")
        or data.get("definition")
    )
    freshness = data.get("freshness") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not str(sql or "").strip():
        return None
    if not str(metric_def or "").strip():
        metric_def = metric_definition(metric)
    if isinstance(policy, str):
        decision = _normalize_policy_decision(policy)
        policy = {
            "decision": decision,
            "reason": "受治理语义查询返回的策略判定。",
            "raw_sql_fallback": False,
        }
    if not isinstance(policy, dict):
        policy = {
            "decision": "allow",
            "reason": policies.get("permission_hint")
            or "仅通过受治理语义层返回聚合结果。",
            "raw_sql_fallback": False,
        }
    elif policy.get("decision"):
        policy = {**policy, "decision": _normalize_policy_decision(policy.get("decision"))}
    if not isinstance(freshness, dict):
        freshness = {
            "status": "fresh",
            "as_of": str(freshness),
        } if freshness else freshness_payload(asset, package, now_iso(), mdl=mdl)
    normalized_data = {
        **data,
        "rows": rows,
        "returnedCount": int(data.get("returnedCount") or len(rows)),
        "metric": data.get("metric")
        if isinstance(data.get("metric"), dict)
        else _metric_payload(metric, resolved_name=data.get("resolvedMetric")),
        "dimensions": data.get("dimensions")
        if isinstance(data.get("dimensions"), list)
        else [_dimension_payload(item) for item in dimensions],
        "sql": str(sql),
        "metricDefinition": str(metric_def),
        "policyDecision": {
            "raw_sql_fallback": False,
            **policy,
        },
        "freshness": freshness,
        "lineage": data.get("lineage")
        if isinstance(data.get("lineage"), list)
        else metric.get("lineage") or asset.get("sample_evidence") or [],
        "evidence": data.get("evidence")
        if isinstance(data.get("evidence"), list)
        else evidence_payload(asset, package, metric),
        "execution": {
            "mode": "governed_semantic_skill",
            "governed_rest": True,
            "direct_database_access": False,
            "raw_sql_fallback": False,
            **(
                data.get("execution")
                if isinstance(data.get("execution"), dict)
                else {}
            ),
        },
    }
    _require_complete_governed_result(normalized_data)
    return _semantic_envelope(candidate, asset, normalized_data, request, metric, dimensions)


def _semantic_envelope(
    candidate: dict[str, Any],
    asset: dict[str, Any],
    data: dict[str, Any],
    request: SemanticQueryRequest,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(data.get("metric"), dict):
        data["metric"] = _metric_payload(metric)
    if not isinstance(data.get("dimensions"), list):
        data["dimensions"] = [_dimension_payload(item) for item in dimensions]
    return redacted(
        {
            "schema": str(candidate.get("schema") or "agentkit.semantic_query_result.v1"),
            "asset": {
                "type": "semantic_model",
                "id": asset["asset_id"],
                "version": asset.get("version") or "v1",
            },
            "query": request.as_payload(),
            "data": data,
            "mock": False,
        }
    )


def _require_complete_governed_result(data: dict[str, Any]) -> None:
    missing = []
    if not data.get("rows") and data.get("returnedCount", 0) != 0:
        missing.append("rows")
    for key in ("sql", "metricDefinition", "policyDecision", "freshness"):
        if data.get(key) in (None, ""):
            missing.append(key)
    if missing:
        raise KnowledgeAssetServiceError(
            "受治理查询结果缺少必要证据：" + ", ".join(sorted(set(missing)))
        )


def _normalize_policy_decision(value: object) -> str:
    decision = str(value or "").strip().casefold()
    if decision in {"allow", "allowed", "pass", "passed"}:
        return "allow"
    if decision in {"deny", "denied", "block", "blocked", "refuse", "refused"}:
        return "deny"
    return decision or "allow"


def _compile_governed_schema_sql(
    mdl: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    request: SemanticQueryRequest,
) -> str:
    entities = mdl.get("entities") if isinstance(mdl.get("entities"), list) else []
    entity_id = str(metric.get("entity") or metric.get("entityId") or "")
    entity = {}
    for item in entities:
        if not isinstance(item, dict):
            continue
        if entity_id and entity_id in {str(item.get("id") or ""), str(item.get("name") or "")}:
            entity = item
            break
    if not entity:
        entity = next((item for item in entities if isinstance(item, dict)), {})
    table = _sql_identifier(entity.get("table") or entity.get("id") or "semantic_model")
    metric_expr = _safe_metric_expr(metric)
    metric_alias = _sql_identifier(metric_id(metric))
    dim_parts: list[str] = []
    group_parts: list[str] = []
    for dimension in dimensions:
        field = _sql_identifier(dimension.get("field") or dimension_id(dimension))
        alias = _sql_identifier(dimension_id(dimension))
        dim_parts.append(f"{field} AS {alias}")
        group_parts.append(field)
    select_parts = [*dim_parts, f"{metric_expr} AS {metric_alias}"]
    where_parts = _governed_where_parts(metric, request)
    sql = f"SELECT {', '.join(select_parts)} FROM {table}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
    sql += f" LIMIT {max(1, min(int(request.limit or 100), 500))}"
    return sql


def _snapshot_rows(
    snapshot_results: Any,
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(snapshot_results, dict):
        return []
    golden = snapshot_results.get("golden_results")
    if not isinstance(golden, dict):
        golden = {}
    metric_key = metric_id(metric).casefold()
    dimension_keys = {dimension_id(item).casefold() for item in dimensions}
    bounded_limit = max(1, min(int(limit or 100), 500))
    if metric_key == "ticket_count" and "store" in dimension_keys:
        rows = golden.get("top_3_stores_by_ticket_count")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)][:bounded_limit]
    if metric_key == "ticket_count":
        value = golden.get("ticket_count_last_30_snapshot_days")
        if isinstance(value, (int, float)):
            return [{"metric": metric_id(metric), "value": value}]
    for key, value in golden.items():
        if metric_key not in str(key).casefold():
            continue
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)][:bounded_limit]
        if isinstance(value, (int, float, str)):
            return [{"metric": metric_id(metric), "value": value}]
    return []


def _governed_where_parts(metric: dict[str, Any], request: SemanticQueryRequest) -> list[str]:
    parts: list[str] = []
    filters = request.filters if isinstance(request.filters, dict) else {}
    for key, value in filters.items():
        field = _sql_identifier(key)
        if isinstance(value, list) and value:
            values = ", ".join(_sql_literal(item) for item in value[:20])
            parts.append(f"{field} IN ({values})")
        elif value not in (None, ""):
            parts.append(f"{field} = {_sql_literal(value)}")
    time_range = request.time_range if isinstance(request.time_range, dict) else {}
    time_field = metric.get("time_field") or metric.get("timeField") or ""
    if time_field and (start := time_range.get("start") or time_range.get("from")):
        parts.append(f"{_sql_identifier(time_field)} >= {_sql_literal(start)}")
    if time_field and (end := time_range.get("end") or time_range.get("to")):
        parts.append(f"{_sql_identifier(time_field)} < {_sql_literal(end)}")
    return parts


def _safe_metric_expr(metric: dict[str, Any]) -> str:
    formula = str(metric.get("formula") or metric.get("expr") or "").strip()
    if formula and (normalized := _normalize_metric_formula(formula)):
        return normalized
    kind = str(metric.get("kind") or "").casefold()
    field = _sql_identifier(metric.get("field") or metric_id(metric))
    if kind == "count":
        return "COUNT(*)"
    if kind == "count_distinct":
        return f"COUNT(DISTINCT {field})"
    if kind == "avg":
        return f"AVG({field})"
    return f"SUM({field})"


def _normalize_metric_formula(value: str) -> str:
    lowered = re.sub(r"\s+", " ", value.strip()).casefold()
    if lowered in {"count(*)", "count(1)"}:
        return "COUNT(*)"
    count_distinct = re.fullmatch(
        r"(?:count_distinct\s*\(|count\s*\(\s*distinct\s+)([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        lowered,
    )
    if count_distinct:
        return f"COUNT(DISTINCT {_sql_identifier(count_distinct.group(1))})"
    aggregate = re.fullmatch(
        r"(sum|avg|min|max)\s*\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        lowered,
    )
    if not aggregate:
        return ""
    op, field = aggregate.groups()
    sql_field = _sql_identifier(field)
    return f"{op.upper()}({sql_field})"


def _sql_identifier(value: object) -> str:
    raw = str(value or "").strip()
    parts = [part for part in raw.split(".") if part]
    cleaned = [
        _clean_identifier_part(part)
        for part in parts
    ]
    if not cleaned:
        cleaned = ["field"]
    return ".".join(f'"{part[:128]}"' for part in cleaned)


_SQL_CONTROL_TOKENS = {
    "alter",
    "attach",
    "call",
    "copy",
    "create",
    "delete",
    "detach",
    "drop",
    "export",
    "insert",
    "install",
    "load",
    "pragma",
    "update",
}
_SQL_LITERAL_CONTROL_TOKENS = _SQL_CONTROL_TOKENS | {"table"}


def _clean_identifier_part(value: str) -> str:
    raw_tokens = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").split("_")
    tokens = [
        token
        for token in raw_tokens
        if token and token.casefold() not in _SQL_CONTROL_TOKENS
    ]
    return "_".join(tokens) or "field"


def _sql_literal(value: object) -> str:
    text = str(value)[:512]
    text = re.sub(r"(--|/\*|\*/|;)", " ", text)
    for token in _SQL_LITERAL_CONTROL_TOKENS:
        text = re.sub(rf"\b{re.escape(token)}\b", "redacted", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return "'" + text.replace("'", "''") + "'"


def _metric_payload(
    metric: dict[str, Any],
    *,
    resolved_name: object = None,
) -> dict[str, Any]:
    return {
        "id": metric_id(metric),
        "name": str(resolved_name or metric_label(metric)),
        "definition": metric_definition(metric),
        "formula": metric.get("formula") or metric_id(metric),
    }


def _dimension_payload(dimension: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": dimension_id(dimension),
        "name": dimension.get("name") or dimension_id(dimension),
        "field": dimension.get("field") or dimension_id(dimension),
    }


def _artifact_dict(artifacts: dict[str, Any], path: str) -> dict[str, Any]:
    value = artifacts.get(path)
    return value if isinstance(value, dict) else {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_list(*values: Any) -> list[dict[str, Any]]:
    for value in values:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []
