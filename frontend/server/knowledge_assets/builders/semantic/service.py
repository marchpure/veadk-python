"""Build job orchestration for schema/source to Semantic Skill packages."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

from ...models import RecordBuildJobBody, RecordSkillPackageBody, UpdateBuildJobBody
from ...service import KnowledgeAssetServiceError, KnowledgeAssetStore
from .metric_dimension_candidates import CandidateSet, generate_candidates
from .mdl_writer import write_mdl
from .schema_graph import SchemaGraph, build_schema_graph, slugify
from .skill_package_writer import build_capability_package, eval_suite


@dataclass(frozen=True)
class SemanticSkillBuildRequest:
    space_id: str | None
    source_ids: list[str]
    snapshot_ids: list[str]
    name: str
    description: str
    intent: str
    target_domain: str
    publish: bool = False


class SemanticSkillBuildService:
    def __init__(self, store: KnowledgeAssetStore) -> None:
        self._store = store

    async def build(self, request: SemanticSkillBuildRequest) -> dict[str, Any]:
        job = await self.enqueue(request)
        return await self.run_job(job["id"], request, raise_on_failed=True)

    async def enqueue(self, request: SemanticSkillBuildRequest) -> dict[str, Any]:
        if not request.source_ids and not request.snapshot_ids:
            raise KnowledgeAssetServiceError("需要选择数据库 source 或 schema snapshot。")
        primary_source = request.source_ids[0] if request.source_ids else None
        asset_id = _asset_id(request.name, request.source_ids, request.snapshot_ids)
        return await self._store.record_build_job(
            RecordBuildJobBody(
                space_id=request.space_id,
                source_id=primary_source,
                asset_type="semantic_model",
                asset_id=asset_id,
                job_type="semantic_skill",
                status="queued",
                input={
                    "source_ids": request.source_ids,
                    "snapshot_ids": request.snapshot_ids,
                    "intent": request.intent,
                    "target_domain": request.target_domain,
                    "publish_requested": request.publish,
                },
                output={
                    "semantic_skill_asset_id": asset_id,
                    "generation_mode": "queued",
                    "model_status": "pending",
                },
            )
        )

    async def run_job(
        self,
        job_id: str,
        request: SemanticSkillBuildRequest,
        *,
        raise_on_failed: bool = False,
    ) -> dict[str, Any]:
        asset_id = _asset_id(request.name, request.source_ids, request.snapshot_ids)
        await self._store.update_build_job(
            job_id,
            UpdateBuildJobBody(
                status="running",
                output={
                    "semantic_skill_asset_id": asset_id,
                    "generation_mode": "running",
                    "model_status": "pending",
                },
            ),
        )
        try:
            result = await self._run(job_id, asset_id, request)
            return result
        except Exception as error:
            blocked = isinstance(error, SemanticBuildBlocked)
            status = "blocked" if blocked else "failed"
            await self._store.update_build_job(
                job_id,
                UpdateBuildJobBody(
                    status=status,
                    error={
                        "code": "SEMANTIC_BUILD_BLOCKED" if blocked else "SEMANTIC_BUILD_FAILED",
                        "message": str(error),
                    },
                    output={"asset_id": asset_id},
                ),
            )
            if blocked or not raise_on_failed:
                return await self._store.get_build_job(job_id)
            raise

    async def _run(
        self,
        job_id: str,
        asset_id: str,
        request: SemanticSkillBuildRequest,
    ) -> dict[str, Any]:
        sources = [await self._store.get_source(source_id) for source_id in request.source_ids]
        snapshots = await self._load_snapshots(request)
        schema, profile, snapshot_ids = _merge_snapshots(snapshots)
        if not schema:
            raise SemanticBuildBlocked("需要 schema snapshot 或数据库 introspection 结果。")

        graph = build_schema_graph(schema, profile)
        if not graph.tables:
            raise SemanticBuildBlocked("schema snapshot 中没有可用表或字段。")
        candidates = generate_candidates(
            graph,
            target_name=request.name,
            profile=profile,
            source_ids=request.source_ids,
            snapshot_ids=snapshot_ids,
        )
        mdl = write_mdl(
            graph,
            candidates,
            model_id=asset_id,
            display_name=request.name,
            datasource_kind=_datasource_kind(sources),
        )
        _apply_semantic_reference(mdl, profile)
        _apply_snapshot_results(mdl, profile)
        document_contexts = _document_contexts(sources)
        if document_contexts:
            mdl.setdefault("evidence", []).append(
                {
                    "kind": "document_context",
                    "source_count": len(document_contexts),
                    "sources": document_contexts,
                    "confidence": 0.55,
                }
            )
        configured = model_configured()
        deterministic_allowed = _deterministic_live_allowed()
        generation_mode = (
            "deterministic_schema_builder"
            if configured or deterministic_allowed
            else "deterministic_skeleton"
        )
        package = build_capability_package(
            asset_id=asset_id,
            display_name=request.name,
            mdl=mdl,
            source_ids=request.source_ids,
            snapshot_ids=snapshot_ids,
            generation_mode=generation_mode,
            model_configured=configured,
        )
        metrics = [str(metric.get("id")) for metric in mdl.get("metrics") or [] if isinstance(metric, dict)]
        dimensions = [str(dim.get("id")) for dim in mdl.get("dimensions") or [] if isinstance(dim, dict)]
        gate = _gate(
            graph,
            candidates,
            mdl=mdl,
            configured=configured,
            deterministic_allowed=deterministic_allowed,
        )
        publish_state = "published" if request.publish and not gate["blockers"] else "draft"
        status = "ready" if not gate["blockers"] else "blocked"
        skill = await self._store.record_skill_package(
            RecordSkillPackageBody(
                space_id=request.space_id,
                asset_type="semantic_model",
                asset_id=asset_id,
                capability_kind="semantic_skill",
                name=request.name,
                description=request.description or "由 AgentKit Semantic Builder 从 schema snapshot 生成。",
                status=status,
                publish_state=publish_state,
                type="semantic_skill",
                source_ids=request.source_ids,
                snapshot_ids=snapshot_ids,
                artifact_uri=f"knowledge-assets://semantic-skills/{asset_id}",
                version="v1",
                gate=gate,
                capability_package=package,
                query_url=f"/api/external/assets/semantic_model/{asset_id}/query",
                capabilities={
                    "metrics": metrics,
                    "dimensions": dimensions,
                    "time_field": _first_time_field(mdl),
                    "relationships": [rel.get("id") for rel in mdl.get("relationships") or [] if isinstance(rel, dict)],
                    "eval_cases": [case["case_id"] for case in eval_suite(asset_id, metrics, dimensions)["cases"]],
                    "generation_mode": generation_mode,
                },
                freshness=mdl.get("freshness") or {},
                provenance={
                    "builder": "agentkit.semantic_builder.v1",
                    "source_ids": request.source_ids,
                    "snapshot_ids": snapshot_ids,
                    "target_domain": request.target_domain,
                    "document_contexts": document_contexts,
                    "model_configured": configured,
                    "references": {
                        "wren": "wren-mdl schema fields/models/relationships concept",
                        "semantica": "schema graph and evidence/confidence architecture",
                        "byaan": "semantic model/governed query capability envelope",
                    },
                },
                usage_policy=mdl.get("permissions") or {},
                sample_evidence=mdl.get("evidence") or [],
                metadata={
                    "intent": request.intent,
                    "warnings": candidates.warnings,
                    "blocked_reasons": gate["blockers"],
                },
            )
        )
        job_status = "succeeded" if not gate["blockers"] else "blocked"
        return await self._store.update_build_job(
            job_id,
            UpdateBuildJobBody(
                status=job_status,
                result_skill_id=skill["asset_id"],
                output={
                    "semantic_skill_asset_id": skill["asset_id"],
                    "publish_state": skill["publish_state"],
                    "status": skill["status"],
                    "gate": gate,
                    "metrics": metrics,
                    "dimensions": dimensions,
                    "generation_mode": generation_mode,
                    "model_configured": configured,
                    "model_status": "configured" if configured else "not_configured",
                    "warnings": candidates.warnings,
                    "artifact_uri": f"knowledge-assets://semantic-skills/{asset_id}",
                },
            ),
        )

    async def _load_snapshots(self, request: SemanticSkillBuildRequest) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for snapshot_id in request.snapshot_ids:
            snapshots.append(await self._store.get_snapshot(snapshot_id))
        if not snapshots:
            for source_id in request.source_ids:
                source_snapshots = await self._store.list_snapshots(source_id=source_id)
                snapshots.extend(source_snapshots)
        return snapshots


class SemanticBuildBlocked(RuntimeError):
    pass


def model_configured() -> bool:
    key_names = (
        "MODEL_AGENT_API_KEY",
        "ARK_API_KEY",
        "OPENAI_API_KEY",
        "VEADK_SEMANTIC_BUILDER_API_KEY",
    )
    return any(bool(os.getenv(name, "").strip()) for name in key_names)


def _deterministic_live_allowed() -> bool:
    return os.getenv("VEADK_SEMANTIC_BUILDER_DETERMINISTIC", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _merge_snapshots(snapshots: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if not snapshots:
        return {}, {}, []
    tables: list[dict[str, Any]] = []
    profiles: dict[str, Any] = {"tables": {}}
    snapshot_ids: list[str] = []
    for snapshot in snapshots:
        snapshot_ids.append(str(snapshot.get("id")))
        schema = snapshot.get("schema") if isinstance(snapshot.get("schema"), dict) else {}
        profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
        if isinstance(schema.get("tables"), list):
            tables.extend([item for item in schema["tables"] if isinstance(item, dict)])
        elif isinstance(schema.get("schemas"), list) or isinstance(schema.get("fields"), list):
            tables.extend(_normalize_tables(schema))
        if isinstance(profile.get("tables"), dict):
            profiles["tables"].update(profile["tables"])
        elif profile:
            table_name = str(schema.get("name") or schema.get("table") or "").strip()
            if table_name:
                profiles["tables"][table_name] = profile
            else:
                profiles.update(profile)
    if tables:
        return {"tables": tables}, profiles, snapshot_ids
    schema = snapshots[0].get("schema") if isinstance(snapshots[0].get("schema"), dict) else {}
    profile = snapshots[0].get("profile") if isinstance(snapshots[0].get("profile"), dict) else {}
    return schema, profile, snapshot_ids


def _normalize_tables(schema: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(schema.get("schemas"), list):
        out: list[dict[str, Any]] = []
        for namespace in schema["schemas"]:
            if not isinstance(namespace, dict):
                continue
            namespace_name = namespace.get("name") or namespace.get("schema")
            for table in namespace.get("tables") or []:
                if isinstance(table, dict):
                    out.append({**table, "schema": table.get("schema") or namespace_name})
        return out
    if isinstance(schema.get("fields"), list):
        return [{"name": schema.get("name") or schema.get("table") or "source", "columns": schema.get("fields")}]
    return []


def _asset_id(name: str, source_ids: list[str], snapshot_ids: list[str]) -> str:
    slug = slugify(name, fallback="")
    if slug:
        return slug[:80]
    digest = hashlib.sha256("|".join([*source_ids, *snapshot_ids]).encode()).hexdigest()[:10]
    return f"semantic_skill_{digest}"


def _datasource_kind(sources: list[dict[str, Any]]) -> str:
    for source in sources:
        provider = str(source.get("provider") or "").strip().lower()
        source_type = str(source.get("source_type") or "").strip().lower()
        if provider:
            return provider
        if source_type:
            return source_type
    return "database"


def _document_contexts(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for source in sources:
        source_type = str(source.get("source_type") or "").strip().lower()
        if source_type in {"database", "schema_snapshot"}:
            continue
        contexts.append(
            {
                "source_id": str(source.get("id") or ""),
                "source_type": source_type,
                "provider": _safe_text(source.get("provider"), 80),
                "name": _safe_text(source.get("name"), 160),
                "description": _safe_text(source.get("description"), 500),
                "status": _safe_text(source.get("status"), 80),
            }
        )
    return contexts[:8]


def _safe_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def _gate(
    graph: SchemaGraph,
    candidates: CandidateSet,
    *,
    mdl: dict[str, Any],
    configured: bool,
    deterministic_allowed: bool,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = list(candidates.warnings)
    if not configured and not deterministic_allowed:
        blockers.append("模型未配置：只能生成 deterministic_skeleton 草案，不能发布。")
    if not graph.tables:
        blockers.append("缺少 schema tables。")
    if not candidates.metrics and not _items(mdl.get("metrics")):
        blockers.append("缺少可用指标候选。")
    score = 100 - len(blockers) * 30 - len(warnings) * 5
    return {
        "score": max(0, min(100, score)),
        "passed": 0 if blockers else 4,
        "total": 4,
        "blockers": blockers,
        "warnings": warnings,
    }


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_time_field(mdl: dict[str, Any]) -> str:
    for metric in mdl.get("metrics") or []:
        if isinstance(metric, dict) and metric.get("time_field"):
            return str(metric["time_field"])
    for dim in mdl.get("dimensions") or []:
        if isinstance(dim, dict) and dim.get("role") == "time":
            return str(dim.get("field") or dim.get("id") or "")
    return ""


def _apply_semantic_reference(mdl: dict[str, Any], profile: dict[str, Any]) -> None:
    reference = profile.get("semantic_reference") or profile.get("semantic_model")
    if not isinstance(reference, dict):
        return
    base_entity = str((mdl.get("entities") or [{}])[0].get("id") or "")
    alias_entity = _reference_alias_entities(mdl, reference)
    reference_dimensions = []
    for item in reference.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        dim_id = str(item.get("id") or "").strip()
        field = str(item.get("field") or "").strip()
        if not dim_id or not field:
            continue
        entity, field_name = _split_reference_field(field, base_entity, alias_entity)
        reference_dimensions.append(
            {
                "id": slugify(dim_id),
                "name": dim_id.replace("_", " ").title(),
                "entity": entity,
                "entityId": entity,
                "field": field_name,
                "role": "time" if "date" in dim_id.lower() or "date" in field_name.lower() else "dimension",
                "description": f"Reference dimension from sanitized semantic snapshot: {field}.",
                "confidence": 0.95,
                "lineage": [
                    {
                        "kind": "semantic_reference_dimension",
                        "source_field": field,
                        "confidence": 0.95,
                    }
                ],
            }
        )
    existing_dimensions = {
        str(item.get("id"))
        for item in mdl.get("dimensions") or []
        if isinstance(item, dict)
    }
    mdl["dimensions"] = [
        *[item for item in reference_dimensions if item["id"] not in existing_dimensions],
        *(mdl.get("dimensions") or []),
    ]

    default_time = next(
        (
            str(item.get("field") or "")
            for item in reference_dimensions
            if item.get("role") == "time"
        ),
        "",
    )
    reference_metrics = []
    dimension_ids = [str(item.get("id")) for item in reference_dimensions]
    for item in reference.get("metrics") or []:
        if not isinstance(item, dict):
            continue
        metric_id = str(item.get("id") or "").strip()
        formula = str(item.get("formula") or "").strip()
        if not metric_id or not formula:
            continue
        reference_metrics.append(
            {
                "id": slugify(metric_id),
                "name": str(item.get("name") or metric_id),
                "business_name": str(item.get("name") or metric_id).replace("_", " ").title(),
                "entity": _metric_entity_from_formula(formula, base_entity, alias_entity),
                "field": _metric_field_from_formula(formula),
                "definition": str(item.get("definition") or ""),
                "kind": "measure",
                "formula": formula,
                "time_field": default_time,
                "default_grain": str(item.get("grain") or "month"),
                "dimensions": dimension_ids,
                "unit": str(item.get("unit") or ""),
                "certification": "approved" if item.get("approved") is True else "blocked",
                "confidence": 0.97 if item.get("approved") is True else 0.75,
                "lineage": [
                    {
                        "kind": "semantic_reference_metric",
                        "approved": bool(item.get("approved")),
                        "version": item.get("version"),
                        "confidence": 0.97 if item.get("approved") is True else 0.75,
                    }
                ],
            }
        )
    existing_metrics = {
        str(item.get("id"))
        for item in mdl.get("metrics") or []
        if isinstance(item, dict)
    }
    mdl["metrics"] = [
        *[item for item in reference_metrics if item["id"] not in existing_metrics],
        *(mdl.get("metrics") or []),
    ]

    policy = reference.get("policy") if isinstance(reference.get("policy"), dict) else {}
    if policy:
        permissions = mdl.setdefault("permissions", {})
        denied_fields = permissions.setdefault("denied_fields", [])
        if isinstance(denied_fields, list):
            for field in policy.get("deny_fields") or []:
                denied_fields.append(
                    {
                        "field": str(field),
                        "reason": "Denied by sanitized semantic reference policy.",
                    }
                )
        if policy.get("relative_time_anchor"):
            mdl.setdefault("freshness", {})["relative_time_anchor"] = policy["relative_time_anchor"]
    provenance = reference.get("provenance") if isinstance(reference.get("provenance"), dict) else {}
    if provenance:
        freshness = mdl.setdefault("freshness", {})
        for source_key, target_key in (
            ("data_through", "data_through"),
            ("source", "semantic_reference_source"),
        ):
            if provenance.get(source_key):
                freshness[target_key] = provenance[source_key]


def _apply_snapshot_results(mdl: dict[str, Any], profile: dict[str, Any]) -> None:
    results: dict[str, Any] = {}
    for key in ("snapshot_results", "golden_results"):
        value = profile.get(key)
        if isinstance(value, dict):
            results.setdefault("golden_results", {}).update(value)
    validation = profile.get("validation_report")
    if isinstance(validation, dict):
        golden_queries = validation.get("golden_queries")
        if isinstance(golden_queries, dict):
            results.setdefault("golden_results", {}).update(golden_queries)
        if validation.get("relative_time_anchor"):
            results["relative_time_anchor"] = validation["relative_time_anchor"]
    if results:
        mdl["snapshot_results"] = results


def _split_reference_field(
    value: str,
    fallback_entity: str,
    alias_entity: dict[str, str] | None = None,
) -> tuple[str, str]:
    parts = [part for part in value.split(".") if part]
    if len(parts) >= 2:
        alias = slugify(parts[-2])
        return (alias_entity or {}).get(alias, alias), parts[-1]
    return fallback_entity, value


def _metric_entity_from_formula(
    formula: str,
    fallback_entity: str,
    alias_entity: dict[str, str],
) -> str:
    cleaned = formula.replace("(", " ").replace(")", " ").replace(",", " ")
    for token in cleaned.split():
        if "." not in token:
            continue
        alias = slugify(token.split(".")[0])
        if alias in alias_entity:
            return alias_entity[alias]
    return fallback_entity


def _metric_field_from_formula(formula: str) -> str:
    cleaned = formula.replace("(", " ").replace(")", " ").replace(",", " ")
    for token in cleaned.split():
        if "." in token:
            return token.split(".")[-1]
    return ""


def _reference_alias_entities(mdl: dict[str, Any], reference: dict[str, Any]) -> dict[str, str]:
    entities = [item for item in mdl.get("entities") or [] if isinstance(item, dict)]
    alias_fields: dict[str, set[str]] = {}
    for item in reference.get("dimensions") or []:
        if isinstance(item, dict):
            _collect_alias_field(alias_fields, str(item.get("field") or ""))
    for item in reference.get("metrics") or []:
        if isinstance(item, dict):
            formula = str(item.get("formula") or "")
            for token in formula.replace("(", " ").replace(")", " ").replace(",", " ").split():
                _collect_alias_field(alias_fields, token)

    mapping: dict[str, str] = {}
    for alias, fields in alias_fields.items():
        best_entity = ""
        best_score = 0
        for entity in entities:
            entity_fields = {
                str(field.get("source_field") or field.get("name") or "").lower()
                for field in entity.get("fields") or []
                if isinstance(field, dict)
            }
            score = len({field.lower() for field in fields} & entity_fields)
            table_name = str(entity.get("table") or entity.get("id") or "").lower()
            if alias and alias in table_name:
                score += 1
            if score > best_score:
                best_score = score
                best_entity = str(entity.get("id") or "")
        if best_entity:
            mapping[alias] = best_entity
    return mapping


def _collect_alias_field(out: dict[str, set[str]], value: str) -> None:
    parts = [part.strip() for part in value.split(".") if part.strip()]
    if len(parts) < 2:
        return
    alias = slugify(parts[-2])
    field = parts[-1]
    if alias and field:
        out.setdefault(alias, set()).add(field)
