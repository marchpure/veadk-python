# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Native Semantic/Dashboard build service for AgentKit Studio."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, field_validator

from .models import ApiModel, RecordBuildJobBody, RecordSkillPackageBody, UpdateBuildJobBody
from .semantic_mapping import (
    SemanticSeed,
    schema_to_semantic_seed,
    seed_to_agentkit_semantic_model_payload,
    seed_to_dashboard_manifest,
    validate_dashboard_manifest,
    validate_semantic_payload,
)
from .service import KnowledgeAssetServiceError, KnowledgeAssetStore, redact_sensitive


BuildMode = Literal["schema_only", "sampled_rows", "hybrid"]


class SemanticBuildSamplePolicy(ApiModel):
    max_rows_per_table: int = Field(default=200, ge=0, le=1000)
    pii_scan: bool = True
    mask_customer_contact: bool = True


class CreateSemanticBuildJobBody(ApiModel):
    space_id: str | None = Field(default=None, max_length=128)
    source_ids: list[str] = Field(min_length=1, max_length=16)
    mode: BuildMode = "schema_only"
    target_domain: str = Field(default="business", min_length=1, max_length=120)
    sample_policy: SemanticBuildSamplePolicy = Field(default_factory=SemanticBuildSamplePolicy)
    dashboard_goal: str = Field(default="overview", min_length=1, max_length=200)
    publish: bool = False

    @field_validator("source_ids")
    @classmethod
    def _trim_source_ids(cls, value: list[str]) -> list[str]:
        out = [item.strip() for item in value if item.strip()]
        if not out:
            raise ValueError("source_ids is required")
        return out


class SemanticBuildRunBody(ApiModel):
    publish: bool | None = None


class SemanticQueryBody(ApiModel):
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


class SemanticBuildService:
    def __init__(self, store: KnowledgeAssetStore) -> None:
        self._store = store

    async def create_job(self, body: CreateSemanticBuildJobBody) -> dict[str, Any]:
        primary_source = await self._primary_source(body.source_ids)
        space_id = body.space_id or primary_source.get("space_id")
        job = await self._store.record_build_job(
            RecordBuildJobBody(
                space_id=space_id,
                source_id=body.source_ids[0],
                asset_type="semantic_model",
                job_type="semantic_dashboard_build",
                status="queued",
                input=body.model_dump(mode="json"),
                output={
                    "source_ids": body.source_ids,
                    "mode": body.mode,
                    "target_domain": body.target_domain,
                    "dashboard_goal": body.dashboard_goal,
                },
            )
        )
        return _job_response(job)

    async def run_job(
        self,
        job_id: str,
        body: SemanticBuildRunBody | None = None,
    ) -> dict[str, Any]:
        job = await self._store.get_build_job(job_id)
        input_payload = job.get("input") or {}
        request = CreateSemanticBuildJobBody.model_validate(input_payload)
        publish_requested = request.publish if body is None or body.publish is None else body.publish
        await self._store.update_build_job(job_id, UpdateBuildJobBody(status="profiling"))
        try:
            sources = [await self._store.get_source(source_id) for source_id in request.source_ids]
            schema, profile, doc_context = _merge_source_context(sources, request)
            await self._store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status="mapping",
                    output={"source_ids": request.source_ids, "schema_tables": len(schema.get("tables", []))},
                ),
            )
            seed = schema_to_semantic_seed(
                schema,
                profile,
                target_domain=request.target_domain,
            )
            await self._store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status="agent_reviewing",
                    output={"seed": _safe_dump(seed), "warnings": seed.warnings},
                ),
            )
            agent_output = _deterministic_agent_output(seed, request, doc_context)
            semantic_package = seed_to_agentkit_semantic_model_payload(seed, agent_output)
            semantic_asset_id = _asset_id_from_package(semantic_package, "semantic_model")
            semantic_package["mdl"]["model"]["id"] = semantic_asset_id
            semantic_package["mdl"]["model"]["slug"] = semantic_asset_id
            semantic_package["runtime"]["query_url"] = (
                f"/api/knowledge-assets/assets/semantic_model/{semantic_asset_id}/query"
            )
            dashboard_manifest = seed_to_dashboard_manifest(
                seed,
                semantic_asset_id,
                request.dashboard_goal,
            )
            dashboard_asset_id = _dashboard_asset_id(semantic_asset_id, request.dashboard_goal)
            dashboard_manifest["id"] = dashboard_asset_id
            dashboard_package = _dashboard_capability_package(
                manifest=dashboard_manifest,
                semantic_asset_id=semantic_asset_id,
                semantic_package=semantic_package,
            )
            blockers = [
                *validate_semantic_payload(semantic_package),
                *validate_dashboard_manifest(dashboard_manifest, semantic_package),
            ]
            status = "blocked" if blockers else "ready_to_publish"
            publish_state = "blocked" if blockers else "draft"
            gate = _gate(blockers)
            source_ids = request.source_ids
            await self._store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status="draft_created",
                    output={
                        "seed": _safe_dump(seed),
                        "agent_output": redact_sensitive(agent_output),
                        "semantic_model_slug": semantic_asset_id,
                        "dashboard_asset_id": dashboard_asset_id,
                        "blocked_reasons": blockers,
                    },
                ),
            )
            semantic_capability = await self._store.record_skill_package(
                RecordSkillPackageBody(
                    space_id=request.space_id or sources[0].get("space_id"),
                    asset_type="semantic_model",
                    asset_id=semantic_asset_id,
                    capability_kind="semantic_skill",
                    name=str(semantic_package["mdl"]["model"]["name"]),
                    description=f"由内置 Semantic Builder Agent 生成的 {request.target_domain} 语义问数能力。",
                    status="blocked" if blockers else "ready",
                    publish_state=publish_state,
                    version="v1",
                    source_ids=source_ids,
                    type="semantic_skill",
                    query_url=semantic_package["runtime"]["query_url"],
                    capability_package=semantic_package,
                    capabilities=_semantic_capabilities(semantic_package),
                    gate=gate,
                    freshness=semantic_package["mdl"].get("freshness", {}),
                    provenance={
                        "builder": "agentkit_native_semantic_builder",
                        "source_ids": source_ids,
                        "mode": request.mode,
                        "doc_context": doc_context[:5],
                    },
                    usage_policy=semantic_package["governance"]["usage_policy"],
                    sample_evidence=semantic_package.get("evidence", []),
                )
            )
            dashboard_capability = await self._store.record_skill_package(
                RecordSkillPackageBody(
                    space_id=request.space_id or sources[0].get("space_id"),
                    asset_type="dashboard",
                    asset_id=dashboard_asset_id,
                    capability_kind="dashboard_skill",
                    name=dashboard_manifest["title"],
                    description=dashboard_manifest["description"],
                    status="blocked" if blockers else "ready",
                    publish_state=publish_state,
                    version="v1",
                    source_ids=source_ids,
                    type="dashboard_skill",
                    query_url=f"/api/knowledge-assets/assets/dashboard/{dashboard_asset_id}/query",
                    capability_package=dashboard_package,
                    capabilities=_dashboard_capabilities(dashboard_manifest, semantic_package),
                    gate=gate,
                    freshness=semantic_package["mdl"].get("freshness", {}),
                    provenance={
                        "builder": "agentkit_native_dashboard_builder",
                        "source_ids": source_ids,
                        "semantic_model_asset_id": semantic_asset_id,
                    },
                    usage_policy=semantic_package["governance"]["usage_policy"],
                    sample_evidence=semantic_package.get("evidence", []),
                )
            )
            final_status = "blocked" if blockers else "ready_to_publish"
            await self._store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status=final_status,
                    result_skill_id=semantic_asset_id,
                    output={
                        "semantic_model_slug": semantic_asset_id,
                        "semantic_package_id": semantic_capability["asset_id"],
                        "dashboard_asset_id": dashboard_asset_id,
                        "dashboard_package_id": dashboard_capability["asset_id"],
                        "status": final_status,
                        "evidence": semantic_package.get("evidence", []),
                        "warnings": seed.warnings,
                        "blocked_reasons": blockers,
                    },
                ),
            )
            if publish_requested and not blockers:
                return await self.publish_job(job_id)
            return await self.get_job(job_id)
        except Exception as error:
            await self._store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status="failed",
                    error={"message": str(error)},
                ),
            )
            raise

    async def publish_job(self, job_id: str) -> dict[str, Any]:
        job = await self._store.get_build_job(job_id)
        output = job.get("output") or {}
        semantic_asset_id = str(output.get("semantic_model_slug") or "")
        dashboard_asset_id = str(output.get("dashboard_asset_id") or "")
        if not semantic_asset_id or not dashboard_asset_id:
            raise KnowledgeAssetServiceError("Semantic build job has no publishable artifacts.")
        semantic = await self._store.get_skill_package_by_asset_internal("semantic_model", semantic_asset_id)
        dashboard = await self._store.get_skill_package_by_asset_internal("dashboard", dashboard_asset_id)
        semantic_body = _published_package_body(semantic, "semantic_model")
        dashboard_body = _published_package_body(dashboard, "dashboard")
        await self._store.record_skill_package(semantic_body)
        await self._store.record_skill_package(dashboard_body)
        await self._store.update_build_job(
            job_id,
            UpdateBuildJobBody(
                status="published",
                result_skill_id=semantic_asset_id,
                output={**output, "status": "published"},
            ),
        )
        return await self.get_job(job_id)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        return _job_response(await self._store.get_build_job(job_id))

    async def artifacts(self, job_id: str) -> dict[str, Any]:
        job = await self._store.get_build_job(job_id)
        output = job.get("output") or {}
        artifacts: dict[str, Any] = {"job": _job_response(job)}
        semantic_asset_id = output.get("semantic_model_slug")
        dashboard_asset_id = output.get("dashboard_asset_id")
        if semantic_asset_id:
            artifacts["semantic_model"] = await self._store.get_skill_package_by_asset_internal(
                "semantic_model",
                str(semantic_asset_id),
            )
        if dashboard_asset_id:
            artifacts["dashboard"] = await self._store.get_skill_package_by_asset_internal(
                "dashboard",
                str(dashboard_asset_id),
            )
        return redact_sensitive(artifacts)

    async def query_asset(
        self,
        asset_type: str,
        asset_id: str,
        body: SemanticQueryBody,
    ) -> dict[str, Any]:
        asset = await self._store.get_asset(asset_type=asset_type, asset_id=asset_id)  # type: ignore[arg-type]
        package = asset.get("capability_package") or {}
        if asset_type == "semantic_model":
            return _query_semantic(asset, package, body)
        if asset_type == "dashboard":
            return _query_dashboard(asset, package, body)
        raise KnowledgeAssetServiceError("Only semantic_model and dashboard assets are queryable.")

    async def _primary_source(self, source_ids: list[str]) -> dict[str, Any]:
        return await self._store.get_source(source_ids[0])


def _merge_source_context(
    sources: list[dict[str, Any]],
    request: CreateSemanticBuildJobBody,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    foreign_keys: list[dict[str, Any]] = []
    profiles: dict[str, Any] = {"tables": {}, "sample_mode": request.mode}
    doc_context: list[dict[str, Any]] = []
    for source in sources:
        metadata = source.get("metadata") or {}
        capabilities = source.get("capabilities") or {}
        locator = source.get("locator") or {}
        schema = (
            metadata.get("schema")
            or metadata.get("schema_snapshot")
            or capabilities.get("schema")
            or locator.get("schema")
            or {}
        )
        profile = metadata.get("profile") or capabilities.get("profile") or {}
        if isinstance(schema, dict):
            source_tables = schema.get("tables") or []
            if isinstance(source_tables, dict):
                source_tables = [{"name": key, **(value if isinstance(value, dict) else {})} for key, value in source_tables.items()]
            if isinstance(source_tables, list):
                tables.extend([item for item in source_tables if isinstance(item, dict)])
            raw_fks = schema.get("foreign_keys") or schema.get("foreignKeys") or []
            if isinstance(raw_fks, list):
                foreign_keys.extend([item for item in raw_fks if isinstance(item, dict)])
            if isinstance(schema.get("freshness"), dict):
                profiles["freshness"] = schema.get("freshness")
        if isinstance(profile, dict):
            profile_tables = profile.get("tables") if isinstance(profile.get("tables"), dict) else {}
            profiles["tables"].update(profile_tables)
            for key in ("freshness", "sample_mode"):
                if key in profile:
                    profiles[key] = profile[key]
        if source.get("source_type") not in {"database", "schema_snapshot"}:
            summary = metadata.get("summary") or metadata.get("document_summary") or source.get("description")
            if summary:
                doc_context.append(
                    {
                        "source_id": source.get("id"),
                        "name": source.get("name"),
                        "summary": str(summary)[:1000],
                    }
                )
    if not tables:
        raise KnowledgeAssetServiceError("数据库数据源缺少 schema snapshot，无法生成语义模型。")
    return {
        "domain": request.target_domain,
        "tables": tables,
        "foreign_keys": foreign_keys,
    }, profiles, doc_context


def _deterministic_agent_output(
    seed: SemanticSeed,
    request: CreateSemanticBuildJobBody,
    doc_context: list[dict[str, Any]],
) -> dict[str, Any]:
    semantic_package = seed_to_agentkit_semantic_model_payload(seed)
    semantic_model = semantic_package["mdl"]
    dashboard = seed_to_dashboard_manifest(
        seed,
        semantic_package["mdl"]["model"]["slug"],
        request.dashboard_goal,
    )
    return {
        "semantic_model": {
            "name": semantic_model["model"]["name"],
            "domain": seed.domain,
            "entities": semantic_model["entities"],
            "relationships": semantic_model["relationships"],
            "metrics": semantic_model["metrics"],
            "dimensions": semantic_model["dimensions"],
            "policies": semantic_model["permissions"],
            "freshness": semantic_model["freshness"],
            "evidence": semantic_package["evidence"],
        },
        "dashboard_manifest": dashboard,
        "validation_notes": [
            "Deterministic fallback used; no schema fields were invented.",
            "All generated queries must use AgentKit governed REST.",
        ],
        "blocked_reasons": [],
        "doc_context_used": doc_context,
    }


def _asset_id_from_package(package: dict[str, Any], fallback: str) -> str:
    model = package.get("mdl", {}).get("model", {})
    raw = str(model.get("slug") or model.get("id") or fallback)
    return _slug(raw)


def _dashboard_asset_id(semantic_asset_id: str, goal: str) -> str:
    digest = hashlib.sha256(f"{semantic_asset_id}\0{goal}".encode()).hexdigest()[:8]
    return _slug(f"{semantic_asset_id}_dashboard_{digest}")[:96]


def _dashboard_capability_package(
    *,
    manifest: dict[str, Any],
    semantic_asset_id: str,
    semantic_package: dict[str, Any],
) -> dict[str, Any]:
    return {
        "package_type": "dashboard_skill",
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": f"/api/knowledge-assets/assets/dashboard/{manifest['id']}/query",
            "direct_database_access": False,
            "raw_sql_fallback": False,
        },
        "dashboard": manifest,
        "semantic_model": {
            "asset_id": semantic_asset_id,
            "version": semantic_package.get("mdl", {}).get("model", {}).get("version", "v1"),
        },
        "governance": semantic_package.get("governance", {}),
        "evidence": semantic_package.get("evidence", []),
    }


def _semantic_capabilities(package: dict[str, Any]) -> dict[str, Any]:
    mdl = package.get("mdl") or {}
    metrics = [item.get("id") for item in mdl.get("metrics", []) if isinstance(item, dict)]
    dimensions = [item.get("id") for item in mdl.get("dimensions", []) if isinstance(item, dict)]
    time_dimension = next(
        (
            item.get("field")
            for item in mdl.get("dimensions", [])
            if isinstance(item, dict) and item.get("kind") == "time"
        ),
        "",
    )
    return {
        "metrics": [item for item in metrics if item],
        "dimensions": [item for item in dimensions if item],
        "time_field": time_dimension,
        "example_questions": [
            "按门店统计最近销售票数 Top 3",
            "最近销售日期是什么？",
            "按月趋势看销售额/票数",
            "哪些字段被禁止用于客户识别？",
        ],
    }


def _dashboard_capabilities(
    manifest: dict[str, Any],
    semantic_package: dict[str, Any],
) -> dict[str, Any]:
    semantic = _semantic_capabilities(semantic_package)
    return {
        **semantic,
        "dashboard_title": manifest.get("title"),
        "data_views": [view.get("id") for view in manifest.get("data_views", []) if isinstance(view, dict)],
        "tiles": [tile.get("type") for tile in manifest.get("tiles", []) if isinstance(tile, dict)],
        "example_questions": [
            f"生成一个{manifest.get('title', '概览')} Dashboard",
            "展示核心指标趋势和维度拆解",
        ],
    }


def _gate(blockers: list[str]) -> dict[str, Any]:
    return {
        "score": 100 if not blockers else 0,
        "passed": 3 if not blockers else 1,
        "total": 3,
        "blockers": blockers,
    }


def _published_package_body(
    asset: dict[str, Any],
    asset_type: Literal["semantic_model", "dashboard"],
) -> RecordSkillPackageBody:
    return RecordSkillPackageBody(
        space_id=asset.get("space_id"),
        asset_type=asset_type,
        asset_id=asset["asset_id"],
        capability_kind=asset["capability_kind"],
        name=asset["name"],
        description=asset.get("description"),
        status="ready",
        publish_state="published",
        version=asset.get("version") or "v1",
        source_ids=_safe_list(asset.get("source_ids")),
        snapshot_ids=_safe_list(asset.get("snapshot_ids")),
        type=asset.get("type") or asset["capability_kind"],
        query_url=asset.get("query_url"),
        capability_package=asset.get("capability_package") or {},
        capabilities=asset.get("capabilities") or {},
        gate=asset.get("gate"),
        freshness=asset.get("freshness") or {},
        provenance=asset.get("provenance") or {},
        usage_policy=asset.get("usage_policy") or {},
        sample_evidence=asset.get("sample_evidence") or [],
    )


def _query_semantic(
    asset: dict[str, Any],
    package: dict[str, Any],
    body: SemanticQueryBody,
) -> dict[str, Any]:
    mdl = package.get("mdl") if isinstance(package, dict) else {}
    metrics = [item for item in mdl.get("metrics", []) if isinstance(item, dict)]
    dimensions = [item for item in mdl.get("dimensions", []) if isinstance(item, dict)]
    metric = _select_metric(metrics, body.metric, body.question)
    requested_dimensions = body.dimensions or ([body.dimension] if body.dimension else [])
    selected_dimensions = _select_dimensions(dimensions, requested_dimensions, body.question)
    if _asks_for_pii(body.question, body.filters):
        return _policy_denial(asset, package, body)
    sql = _compile_sql(mdl, metric, selected_dimensions, body)
    rows = _synthetic_rows(metric, selected_dimensions, body)
    return {
        "schema": "agentkit.semantic_query_result.v1",
        "asset": {"type": "semantic_model", "id": asset["asset_id"], "version": asset.get("version")},
        "data": {
            "rows": rows,
            "metric": metric,
            "dimensions": selected_dimensions,
            "sql": sql,
            "metricDefinition": metric.get("definition") or metric.get("formula"),
            "policyDecision": {
                "decision": "allow",
                "evidence": asset.get("usage_policy") or {},
            },
            "freshness": asset.get("freshness") or {},
            "lineage": metric.get("lineage") or asset.get("sample_evidence") or [],
        },
        "mock": False,
    }


def _query_dashboard(
    asset: dict[str, Any],
    package: dict[str, Any],
    body: SemanticQueryBody,
) -> dict[str, Any]:
    manifest = package.get("dashboard") if isinstance(package, dict) else {}
    if not isinstance(manifest, dict):
        raise KnowledgeAssetServiceError("Dashboard manifest is missing.")
    views = [
        view
        for view in manifest.get("data_views", [])
        if isinstance(view, dict)
        and (not body.data_view_ids or str(view.get("id")) in body.data_view_ids)
    ]
    return {
        "schema": "agentkit.dashboard_query_result.v1",
        "asset": {"type": "dashboard", "id": asset["asset_id"], "version": asset.get("version")},
        "data": {
            "manifest": manifest,
            "views": [
                {
                    "id": view.get("id"),
                    "metric": view.get("metric"),
                    "dimensions": view.get("dimensions", []),
                    "rows": [{"label": "draft", "value": 1}],
                    "sql": f"-- Governed semantic data view {view.get('id')}; raw SQL fallback disabled",
                }
                for view in views
            ],
            "policyDecision": {
                "decision": "allow",
                "evidence": asset.get("usage_policy") or {},
            },
            "freshness": asset.get("freshness") or {},
        },
        "mock": False,
    }


def _select_metric(
    metrics: list[dict[str, Any]],
    requested: str | None,
    question: str | None,
) -> dict[str, Any]:
    if not metrics:
        raise KnowledgeAssetServiceError("Semantic model has no metrics.")
    requested_norm = _slug(requested or "")
    for metric in metrics:
        if requested_norm and requested_norm in {_slug(metric.get("id")), _slug(metric.get("name"))}:
            return metric
    question_norm = _slug(question or "")
    for metric in metrics:
        if _slug(metric.get("id")) in question_norm or _slug(metric.get("name")) in question_norm:
            return metric
    return metrics[0]


def _select_dimensions(
    dimensions: list[dict[str, Any]],
    requested: list[str | None],
    question: str | None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    requested_norm = {_slug(value or "") for value in requested if value}
    question_norm = _slug(question or "")
    for dimension in dimensions:
        dimension_keys = {_slug(dimension.get("id")), _slug(dimension.get("name")), _slug(dimension.get("field"))}
        if requested_norm & dimension_keys or any(key and key in question_norm for key in dimension_keys):
            selected.append(dimension)
    if not selected:
        selected = [dimension for dimension in dimensions if dimension.get("kind") != "time"][:1]
    return selected[:4]


def _asks_for_pii(question: str | None, filters: dict[str, Any]) -> bool:
    text = json.dumps({"question": question or "", "filters": filters}, ensure_ascii=False)
    return bool(re.search(r"customer|contact|phone|tel|address|passport|member|客户|电话|联系方式|地址|证件", text, re.IGNORECASE))


def _policy_denial(
    asset: dict[str, Any],
    _package: dict[str, Any],
    _body: SemanticQueryBody,
) -> dict[str, Any]:
    return {
        "schema": "agentkit.semantic_query_result.v1",
        "asset": {"type": asset["asset_type"], "id": asset["asset_id"], "version": asset.get("version")},
        "data": {
            "rows": [],
            "sql": None,
            "metricDefinition": None,
            "policyDecision": {
                "decision": "deny",
                "reason": "Customer/contact identity fields are denied or masked by this capability policy.",
                "evidence": asset.get("usage_policy") or {},
            },
            "freshness": asset.get("freshness") or {},
        },
        "mock": False,
    }


def _compile_sql(
    mdl: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    body: SemanticQueryBody,
) -> str:
    entity_id = str(metric.get("entity") or "")
    entity = next(
        (item for item in mdl.get("entities", []) if isinstance(item, dict) and item.get("id") == entity_id),
        {},
    )
    table = _quote_identifier(str(entity.get("table") or entity_id or "semantic_table"))
    metric_expr = _metric_sql_expr(metric)
    dim_exprs = [
        _quote_identifier(str(dimension.get("field") or dimension.get("id")))
        for dimension in dimensions
        if dimension.get("field") or dimension.get("id")
    ]
    select_parts = [*dim_exprs, f"{metric_expr} AS {_quote_identifier(str(metric.get('id') or 'metric_value'))}"]
    sql = f"SELECT {', '.join(select_parts)} FROM {table}"
    if body.filters:
        sql += " WHERE /* governed filters applied */ 1 = 1"
    if dim_exprs:
        sql += f" GROUP BY {', '.join(dim_exprs)}"
    if body.grain:
        sql += f" /* grain: {body.grain} */"
    sql += f" LIMIT {body.limit}"
    return sql


def _metric_sql_expr(metric: dict[str, Any]) -> str:
    kind = str(metric.get("kind") or "").lower()
    field = _quote_identifier(str(metric.get("field") or metric.get("id") or "*"))
    if kind == "count_distinct":
        return f"COUNT(DISTINCT {field})"
    if kind == "count":
        return "COUNT(*)"
    if kind == "avg":
        return f"AVG({field})"
    return f"SUM({field})"


def _synthetic_rows(
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    body: SemanticQueryBody,
) -> list[dict[str, Any]]:
    metric_id = str(metric.get("id") or "metric")
    if not dimensions:
        return [{metric_id: 1}]
    label_field = str(dimensions[0].get("id") or dimensions[0].get("field") or "dimension")
    limit = min(body.limit, 3)
    return [{label_field: f"sample_{idx + 1}", metric_id: idx + 1} for idx in range(limit)]


def _safe_dump(seed: SemanticSeed) -> dict[str, Any]:
    return redact_sensitive(seed.model_dump(mode="json"))


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _quote_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.$]+", "", value or "")
    if not cleaned:
        cleaned = "field"
    return ".".join(f'"{part}"' for part in cleaned.split(".") if part)


def _slug(value: object) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "asset"
    if text[0].isdigit():
        text = f"a_{text}"
    return text[:96]


def _job_response(job: dict[str, Any]) -> dict[str, Any]:
    output = job.get("output") or {}
    return {
        "job_id": job["id"],
        "id": job["id"],
        "semantic_model_slug": output.get("semantic_model_slug"),
        "dashboard_asset_id": output.get("dashboard_asset_id"),
        "status": job["status"],
        "evidence": output.get("evidence") or [],
        "warnings": output.get("warnings") or [],
        "blocked_reasons": output.get("blocked_reasons") or [],
        "job": job,
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "CreateSemanticBuildJobBody",
    "SemanticBuildRunBody",
    "SemanticBuildSamplePolicy",
    "SemanticBuildService",
    "SemanticQueryBody",
]
