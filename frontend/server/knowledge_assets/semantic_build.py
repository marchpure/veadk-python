# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Native Semantic/Dashboard build service for AgentKit Studio."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
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
            sources = await self._sources_for_asset(asset)
            return await asyncio.to_thread(_query_semantic, asset, package, body, sources)
        if asset_type == "dashboard":
            sources = await self._sources_for_asset(asset)
            return await asyncio.to_thread(_query_dashboard, asset, package, body, sources)
        raise KnowledgeAssetServiceError("Only semantic_model and dashboard assets are queryable.")

    async def _primary_source(self, source_ids: list[str]) -> dict[str, Any]:
        return await self._store.get_source(source_ids[0])

    async def _sources_for_asset(self, asset: dict[str, Any]) -> list[dict[str, Any]]:
        source_ids = _safe_list(
            asset.get("provenance", {}).get("source_ids")
            or asset.get("capability_package", {}).get("source_ids")
            or asset.get("capabilities", {}).get("source_ids")
        )
        sources: list[dict[str, Any]] = []
        for source_id in source_ids:
            try:
                sources.append(await self._store.get_source_internal(source_id))
            except Exception:
                continue
        return sources


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
    sources: list[dict[str, Any]] | None = None,
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
    execution_mode = "schema_only"
    execution_error_code = ""
    rows: list[dict[str, Any]]
    snapshot_context = _resolve_snapshot_query_context(sources or [], asset, package)
    if snapshot_context:
        metric = _select_snapshot_metric(snapshot_context, metric, body.metric, body.question)
        selected_dimensions = _select_snapshot_dimensions(
            snapshot_context,
            selected_dimensions,
            requested_dimensions,
            body.question,
        )
        sql = _compile_sql(
            mdl,
            metric,
            selected_dimensions,
            body,
            snapshot_context=snapshot_context,
        )
        executed = _execute_duckdb_snapshot_query(snapshot_context, sql)
        if executed["ok"]:
            rows = executed["rows"]
            execution_mode = "local_sanitized_snapshot"
        else:
            rows = _synthetic_rows(metric, selected_dimensions, body)
            execution_error_code = str(executed.get("code") or "snapshot_query_failed")
    else:
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
            "execution": {
                "mode": execution_mode,
                "governed_rest": True,
                "direct_database_access": False,
                **({"fallback_reason": execution_error_code} if execution_error_code else {}),
            },
        },
        "mock": False,
    }


def _query_dashboard(
    asset: dict[str, Any],
    package: dict[str, Any],
    body: SemanticQueryBody,
    sources: list[dict[str, Any]] | None = None,
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
    snapshot_context = _resolve_snapshot_query_context(sources or [], asset, package)
    return {
        "schema": "agentkit.dashboard_query_result.v1",
        "asset": {"type": "dashboard", "id": asset["asset_id"], "version": asset.get("version")},
        "data": {
            "manifest": manifest,
            "views": [
                _dashboard_view_query_result(view, snapshot_context)
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


def _dashboard_view_query_result(
    view: dict[str, Any],
    snapshot_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not snapshot_context:
        return {
            "id": view.get("id"),
            "metric": view.get("metric"),
            "dimensions": view.get("dimensions", []),
            "rows": [{"label": "draft", "value": 1}],
            "sql": f"-- Governed semantic data view {view.get('id')}; raw SQL fallback disabled",
            "execution": {"mode": "schema_only", "governed_rest": True},
        }
    metric = _metric_from_snapshot_context(snapshot_context, view.get("metric"))
    dimensions = [
        _dimension_from_snapshot_context(snapshot_context, value)
        for value in view.get("dimensions", [])
    ]
    dimensions = [item for item in dimensions if item]
    body = SemanticQueryBody(limit=int(view.get("limit") or 20))
    sql = _compile_sql(
        {"entities": snapshot_context.get("entities", [])},
        metric,
        dimensions,
        body,
        snapshot_context=snapshot_context,
    )
    executed = _execute_duckdb_snapshot_query(snapshot_context, sql)
    return {
        "id": view.get("id"),
        "metric": view.get("metric"),
        "dimensions": view.get("dimensions", []),
        "rows": executed["rows"] if executed["ok"] else [{"label": "draft", "value": 1}],
        "sql": sql,
        "execution": {
            "mode": "local_sanitized_snapshot" if executed["ok"] else "schema_only",
            "governed_rest": True,
            **({"fallback_reason": str(executed.get("code") or "snapshot_query_failed")} if not executed["ok"] else {}),
        },
    }


def _metric_from_snapshot_context(
    snapshot_context: dict[str, Any],
    metric_id: object,
) -> dict[str, Any]:
    requested = _slug(metric_id or "")
    for metric in snapshot_context.get("semantic_model", {}).get("metrics", []):
        if isinstance(metric, dict) and requested in {
            _slug(metric.get("id")),
            _slug(metric.get("name")),
        }:
            return _snapshot_metric_payload(metric)
    metrics = snapshot_context.get("semantic_model", {}).get("metrics", [])
    if metrics and isinstance(metrics[0], dict):
        return _snapshot_metric_payload(metrics[0])
    return {
        "id": "ticket_count",
        "name": "Ticket Count",
        "entity": "P_BL_SELL_HD",
        "field": "BILLID",
        "kind": "count_distinct",
        "formula": "count(distinct hd.BILLID)",
        "definition": "Count of distinct sales bill IDs.",
    }


def _select_snapshot_metric(
    snapshot_context: dict[str, Any],
    fallback: dict[str, Any],
    requested: str | None,
    question: str | None,
) -> dict[str, Any]:
    raw_metrics = snapshot_context.get("semantic_model", {}).get("metrics", [])
    metrics = [
        _snapshot_metric_payload(metric)
        for metric in raw_metrics
        if isinstance(metric, dict)
    ]
    if not metrics:
        return fallback
    requested_norm = _slug(requested or "")
    question_norm = _slug(question or "")
    for metric in metrics:
        if requested_norm and requested_norm in {_slug(metric.get("id")), _slug(metric.get("name"))}:
            return metric
    for metric in metrics:
        keys = {_slug(metric.get("id")), _slug(metric.get("name"))}
        if any(key and key in question_norm for key in keys):
            return metric
    if re.search(r"票|ticket|bill|单", question or "", re.IGNORECASE):
        for metric in metrics:
            if re.search(r"ticket|bill|count", str(metric.get("id") or metric.get("name")), re.IGNORECASE):
                return metric
    return metrics[0]


def _select_snapshot_dimensions(
    snapshot_context: dict[str, Any],
    fallback: list[dict[str, Any]],
    requested: list[str | None],
    question: str | None,
) -> list[dict[str, Any]]:
    raw_dimensions = snapshot_context.get("semantic_model", {}).get("dimensions", [])
    dimensions = [
        _snapshot_dimension_payload(dimension)
        for dimension in raw_dimensions
        if isinstance(dimension, dict)
    ]
    if not dimensions:
        return fallback
    requested_norm = {_slug(value or "") for value in requested if value}
    question_norm = _slug(question or "")
    selected: list[dict[str, Any]] = []
    for dimension in dimensions:
        keys = {_slug(dimension.get("id")), _slug(dimension.get("name")), _slug(dimension.get("field"))}
        if requested_norm & keys or any(key and key in question_norm for key in keys):
            selected.append(dimension)
    if not selected and re.search(r"门店|store|shop", question or "", re.IGNORECASE):
        selected = [
            dimension
            for dimension in dimensions
            if re.search(r"store|shop", str(dimension.get("id") or dimension.get("field")), re.IGNORECASE)
        ]
    if not selected:
        selected = [dimension for dimension in dimensions if dimension.get("kind") != "time"][:1]
    return selected[:4]


def _dimension_from_snapshot_context(
    snapshot_context: dict[str, Any],
    dimension_id: object,
) -> dict[str, Any] | None:
    requested = _slug(dimension_id or "")
    for dimension in snapshot_context.get("semantic_model", {}).get("dimensions", []):
        if isinstance(dimension, dict) and requested in {
            _slug(dimension.get("id")),
            _slug(dimension.get("name")),
            _slug(dimension.get("field")),
        }:
            return _snapshot_dimension_payload(dimension)
    return None


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


def _resolve_snapshot_query_context(
    sources: list[dict[str, Any]],
    asset: dict[str, Any],
    package: dict[str, Any],
) -> dict[str, Any] | None:
    for source in sources:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        locator = source.get("locator") if isinstance(source.get("locator"), dict) else {}
        capabilities = source.get("capabilities") if isinstance(source.get("capabilities"), dict) else {}
        raw_context = (
            metadata.get("query_context")
            or locator.get("query_context")
            or capabilities.get("query_context")
            or {}
        )
        context = dict(raw_context) if isinstance(raw_context, dict) else {}
        duckdb_path = (
            context.get("duckdb_path")
            or metadata.get("duckdb_path")
            or locator.get("duckdb_path")
            or _duckdb_path_from_manifest(metadata.get("manifest_path") or locator.get("manifest_path"))
        )
        if not duckdb_path:
            continue
        path = Path(str(duckdb_path)).expanduser()
        if not _is_safe_local_duckdb_path(path):
            continue
        context["duckdb_path"] = str(path)
        schema_name = context.get("schema") or metadata.get("schema_name")
        if not schema_name:
            schema_payload = metadata.get("schema") if isinstance(metadata.get("schema"), dict) else {}
            schema_name = schema_payload.get("schema")
        context["schema"] = _safe_identifier(str(schema_name or "main"))
        semantic_model = (
            context.get("semantic_model")
            or metadata.get("semantic_model")
            or package.get("semantic_model")
            or {}
        )
        if not isinstance(semantic_model, dict):
            semantic_model = {}
        context["semantic_model"] = semantic_model
        if not context.get("base_table"):
            context["base_table"] = _infer_base_table(package, semantic_model)
        if not context.get("base_alias"):
            context["base_alias"] = _infer_base_alias(context["base_table"])
        context["asset_freshness"] = asset.get("freshness") or {}
        return context
    return None


def _duckdb_path_from_manifest(value: object) -> str:
    if not value:
        return ""
    manifest_path = Path(str(value)).expanduser()
    if not manifest_path.exists() or not manifest_path.is_file():
        return ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    raw = manifest.get("uncompressed_duckdb", {}).get("path") or ""
    if not raw:
        return ""
    candidate = Path(str(raw))
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return str(candidate)


def _is_safe_local_duckdb_path(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        return False
    if resolved.suffix != ".duckdb":
        return False
    if not resolved.exists() or not resolved.is_file():
        return False
    return "sanitized" in str(resolved).lower()


def _infer_base_table(package: dict[str, Any], semantic_model: dict[str, Any]) -> str:
    metrics = semantic_model.get("metrics") if isinstance(semantic_model.get("metrics"), list) else []
    for metric in metrics:
        if isinstance(metric, dict):
            table = _table_from_formula(str(metric.get("formula") or ""))
            if table:
                return table
    mdl = package.get("mdl") if isinstance(package, dict) else {}
    entities = mdl.get("entities") if isinstance(mdl, dict) else []
    if isinstance(entities, list) and entities:
        first = entities[0]
        if isinstance(first, dict) and first.get("table"):
            return str(first["table"])
    return "P_BL_SELL_HD"


def _infer_base_alias(table: object) -> str:
    name = str(table or "").upper()
    if name.endswith("P_BL_SELL_HD") or name.endswith("SELL_HD"):
        return "hd"
    return _slug(name)[:8] or "base"


def _table_from_formula(formula: str) -> str:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\.", formula)
    if not match:
        return ""
    alias = match.group(1).lower()
    if alias == "hd":
        return "P_BL_SELL_HD"
    if alias == "dt":
        return "P_BL_SELL_DT"
    if alias == "store":
        return "P_ARC_STORE"
    return ""


def _compile_sql(
    mdl: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    body: SemanticQueryBody,
    *,
    snapshot_context: dict[str, Any] | None = None,
) -> str:
    if snapshot_context:
        return _compile_snapshot_sql(snapshot_context, metric, dimensions, body)
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


def _compile_snapshot_sql(
    snapshot_context: dict[str, Any],
    metric: dict[str, Any],
    dimensions: list[dict[str, Any]],
    body: SemanticQueryBody,
) -> str:
    schema_name = _safe_identifier(str(snapshot_context.get("schema") or "main"))
    base_table = _safe_identifier(str(snapshot_context.get("base_table") or "P_BL_SELL_HD"))
    base_alias = _safe_identifier(str(snapshot_context.get("base_alias") or "hd"))
    if _question_asks_latest_date(body.question):
        return _compile_latest_date_snapshot_sql(
            snapshot_context,
            dimensions,
            schema_name,
            base_table,
            base_alias,
        )
    monthly_trend = _question_asks_monthly_trend(body.question) or body.grain == "month"
    joins: dict[str, str] = {}
    dim_exprs: list[str] = []
    group_exprs: list[str] = []
    for dimension in dimensions:
        expr, alias, join_sql = _snapshot_dimension_sql(dimension, schema_name, base_alias)
        if join_sql:
            joins[join_sql] = join_sql
        if monthly_trend and dimension.get("kind") == "time":
            expr = f"DATE_TRUNC('month', {expr})"
            alias = f"{alias}_month" if not alias.endswith("_month") else alias
        dim_exprs.append(f"{expr} AS {_quote_identifier(alias)}")
        group_exprs.append(expr)
    metric_expr = _snapshot_metric_sql(metric, base_alias)
    metric_alias = _quote_identifier(str(metric.get("id") or "metric_value"))
    select_parts = [*dim_exprs, f"{metric_expr} AS {metric_alias}"]
    sql = (
        f"SELECT {', '.join(select_parts)} "
        f"FROM {_qualified_table(schema_name, base_table)} {base_alias}"
    )
    if joins:
        sql += " " + " ".join(joins.values())
    where = _snapshot_where_clauses(snapshot_context, body, base_alias)
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group_exprs:
        sql += f" GROUP BY {', '.join(group_exprs)}"
    if monthly_trend and group_exprs:
        sql += f" ORDER BY {group_exprs[0]} ASC"
    else:
        sql += f" ORDER BY {metric_alias} DESC"
    sql += f" LIMIT {max(1, min(int(body.limit), 500))}"
    return sql


def _compile_latest_date_snapshot_sql(
    snapshot_context: dict[str, Any],
    dimensions: list[dict[str, Any]],
    schema_name: str,
    base_table: str,
    base_alias: str,
) -> str:
    time_dimension = next(
        (
            dimension
            for dimension in dimensions
            if dimension.get("kind") == "time"
            or re.search(r"date|time", str(dimension.get("field") or dimension.get("id")), re.IGNORECASE)
        ),
        None,
    )
    if time_dimension is None:
        for dimension in snapshot_context.get("semantic_model", {}).get("dimensions", []):
            if isinstance(dimension, dict) and re.search(
                r"date|time",
                str(dimension.get("field") or dimension.get("id")),
                re.IGNORECASE,
            ):
                time_dimension = _snapshot_dimension_payload(dimension)
                break
    if time_dimension is None:
        time_dimension = {"id": "sell_date", "field": "hd.SELLDATE", "kind": "time"}
    expr, alias, join_sql = _snapshot_dimension_sql(time_dimension, schema_name, base_alias)
    sql = (
        f"SELECT MAX({expr}) AS {_quote_identifier(f'latest_{alias}')}"
        f" FROM {_qualified_table(schema_name, base_table)} {base_alias}"
    )
    if join_sql:
        sql += f" {join_sql}"
    sql += " LIMIT 1"
    return sql


def _snapshot_dimension_sql(
    dimension: dict[str, Any],
    schema_name: str,
    base_alias: str,
) -> tuple[str, str, str]:
    raw_field = str(dimension.get("field") or dimension.get("id") or "")
    alias = str(dimension.get("id") or raw_field.split(".")[-1] or "dimension")
    parts = [part for part in raw_field.split(".") if part]
    if len(parts) == 2:
        prefix, field = parts
        if prefix.lower() == "store":
            join_sql = (
                f"LEFT JOIN {_qualified_table(schema_name, 'P_ARC_STORE')} store "
                f"ON store.STOREID = {base_alias}.STOREID"
            )
            return f"store.{_quote_identifier(field)}", alias, join_sql
        if prefix.lower() in {"hd", base_alias.lower()}:
            return f"{base_alias}.{_quote_identifier(field)}", alias, ""
        if prefix.lower() == "dt":
            join_sql = (
                f"LEFT JOIN {_qualified_table(schema_name, 'P_BL_SELL_DT')} dt "
                f"ON dt.BILLID = {base_alias}.BILLID"
            )
            return f"dt.{_quote_identifier(field)}", alias, join_sql
    field = parts[-1] if parts else raw_field
    return f"{base_alias}.{_quote_identifier(field)}", alias, ""


def _snapshot_metric_sql(metric: dict[str, Any], base_alias: str) -> str:
    formula = str(metric.get("formula") or "")
    formula = formula.replace("count(distinct ", "COUNT(DISTINCT ")
    formula = formula.replace("sum(", "SUM(").replace("avg(", "AVG(")
    formula = re.sub(r"\bhd\.", f"{base_alias}.", formula, flags=re.IGNORECASE)
    if _is_safe_metric_expression(formula):
        return formula
    return _metric_sql_expr(metric).replace('"', f"{base_alias}.\"")


def _is_safe_metric_expression(value: str) -> bool:
    if not value or ";" in value or "--" in value or "/*" in value:
        return False
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9_().,\s*\"']+",
            value,
        )
    )


def _snapshot_where_clauses(
    snapshot_context: dict[str, Any],
    body: SemanticQueryBody,
    base_alias: str,
) -> list[str]:
    clauses: list[str] = []
    time_range = body.time_range if isinstance(body.time_range, dict) else {}
    start = _date_literal(time_range.get("start") or time_range.get("from"))
    end = _date_literal(time_range.get("end") or time_range.get("to"))
    if not start and _question_asks_recent(body.question):
        anchor = _date_literal(
            snapshot_context.get("asset_freshness", {}).get("data_through")
            or snapshot_context.get("semantic_model", {}).get("provenance", {}).get("data_through")
            or snapshot_context.get("semantic_model", {}).get("policy", {}).get("relative_time_anchor")
        )
        if anchor:
            start = f"{anchor} - INTERVAL 30 DAY"
            end = anchor
    if start:
        clauses.append(f"{base_alias}.SELLDATE >= {start}")
    if end:
        clauses.append(f"{base_alias}.SELLDATE <= {end}")
    return clauses


def _question_asks_recent(question: str | None) -> bool:
    return bool(re.search(r"recent|last|latest|最近|近[0-9一二三四五六七八九十]*|最新", question or "", re.IGNORECASE))


def _question_asks_latest_date(question: str | None) -> bool:
    text = question or ""
    return bool(
        re.search(r"最近.*(日期|date)|最新.*(日期|date)|latest.*date|max.*date", text, re.IGNORECASE)
    )


def _question_asks_monthly_trend(question: str | None) -> bool:
    text = question or ""
    return bool(re.search(r"按月|月趋势|monthly|month.*trend|trend", text, re.IGNORECASE))


def _date_literal(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return ""
    return f"DATE '{match.group(1)}'"


def _qualified_table(schema_name: str, table_name: str) -> str:
    return f"{_quote_identifier(schema_name)}.{_quote_identifier(table_name)}"


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


def _execute_duckdb_snapshot_query(
    snapshot_context: dict[str, Any],
    sql: str,
) -> dict[str, Any]:
    if not _is_safe_select_sql(sql):
        return {"ok": False, "rows": [], "code": "unsafe_compiled_sql"}
    binary = shutil.which("duckdb")
    if not binary:
        return {"ok": False, "rows": [], "code": "duckdb_unavailable"}
    path = Path(str(snapshot_context.get("duckdb_path") or ""))
    if not _is_safe_local_duckdb_path(path):
        return {"ok": False, "rows": [], "code": "snapshot_path_rejected"}
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    try:
        completed = subprocess.run(
            [binary, str(path), "-json", "-c", sql],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except Exception as error:
        return {"ok": False, "rows": [], "code": "snapshot_query_exception"}
    if completed.returncode != 0:
        return {"ok": False, "rows": [], "code": "snapshot_query_failed"}
    try:
        rows = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as error:
        return {"ok": False, "rows": [], "code": "invalid_snapshot_query_json"}
    if not isinstance(rows, list):
        return {"ok": False, "rows": [], "code": "invalid_snapshot_query_shape"}
    return {"ok": True, "rows": [row for row in rows if isinstance(row, dict)], "code": ""}


def _is_safe_select_sql(sql: str) -> bool:
    stripped = sql.strip()
    if not re.match(r"(?is)^select\b", stripped):
        return False
    forbidden = r"\b(insert|update|delete|drop|alter|create|copy|attach|detach|install|load|pragma|call|export)\b"
    if re.search(forbidden, stripped, re.IGNORECASE):
        return False
    return stripped.count(";") <= 1 and not re.search(r";\s*\S", stripped)


def _snapshot_metric_payload(metric: dict[str, Any]) -> dict[str, Any]:
    formula = str(metric.get("formula") or "")
    return {
        "id": str(metric.get("id") or "metric"),
        "name": str(metric.get("name") or metric.get("id") or "Metric"),
        "entity": _table_from_formula(formula) or "P_BL_SELL_HD",
        "field": _field_from_formula(formula) or "BILLID",
        "kind": _metric_kind_from_formula(formula),
        "formula": formula,
        "definition": str(metric.get("definition") or formula),
        "time_field": "SELLDATE",
        "lineage": [{"kind": "snapshot_semantic_model", "content": formula}],
    }


def _snapshot_dimension_payload(dimension: dict[str, Any]) -> dict[str, Any]:
    field = str(dimension.get("field") or dimension.get("id") or "")
    return {
        "id": str(dimension.get("id") or _slug(field)),
        "name": str(dimension.get("name") or dimension.get("id") or field),
        "entity": _table_from_formula(field) or "",
        "field": field,
        "kind": "time" if re.search(r"date|time", field, re.IGNORECASE) else "category",
    }


def _field_from_formula(formula: str) -> str:
    match = re.search(r"\.([A-Za-z_][A-Za-z0-9_]*)", formula)
    return match.group(1) if match else ""


def _metric_kind_from_formula(formula: str) -> str:
    lowered = formula.lower()
    if "count(distinct" in lowered:
        return "count_distinct"
    if "count(" in lowered:
        return "count"
    if "avg(" in lowered:
        return "avg"
    return "sum"


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


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "", value or "")
    return cleaned or "main"


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
