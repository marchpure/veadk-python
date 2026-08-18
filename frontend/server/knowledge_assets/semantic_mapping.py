# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Deterministic semantic mapping for native AgentKit knowledge assets.

The mapper is intentionally schema-first. It never opens database connections and
never requires credentials; callers pass previously captured schema/profile
metadata from the Studio Knowledge Asset Store.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MappingModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class EvidenceItem(MappingModel):
    kind: str
    title: str = ""
    content: str = ""
    table: str | None = None
    field: str | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class FieldSeed(MappingModel):
    id: str
    entity_id: str
    table: str
    name: str
    source_field: str
    data_type: str = "unknown"
    role: Literal[
        "primary_key",
        "foreign_key",
        "time",
        "measure",
        "dimension",
        "attribute",
        "denied",
    ] = "attribute"
    nullable: bool = True
    is_pii: bool = False
    policy: Literal["allow", "mask", "deny"] = "allow"
    evidence: list[EvidenceItem] = Field(default_factory=list)


class EntitySeed(MappingModel):
    id: str
    name: str
    table: str
    schema_name: str | None = None
    primary_key: str | None = None
    fields: list[FieldSeed] = Field(default_factory=list)
    row_count: int | None = None
    role: Literal["entity", "association"] = "entity"
    evidence: list[EvidenceItem] = Field(default_factory=list)


class RelationshipSeed(MappingModel):
    id: str
    name: str
    label: str
    from_entity: str
    to_entity: str
    join_fields: list[dict[str, str]] = Field(default_factory=list)
    cardinality: str = "many-to-one"
    relationship_type: str = "foreign_key"
    evidence: list[EvidenceItem] = Field(default_factory=list)


class MetricSeed(MappingModel):
    id: str
    name: str
    entity_id: str
    field: str | None = None
    kind: Literal["count", "count_distinct", "sum", "avg"] = "sum"
    formula: str
    definition: str
    time_field: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class DimensionSeed(MappingModel):
    id: str
    name: str
    entity_id: str
    field: str
    kind: Literal["category", "time"] = "category"
    description: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)


class SemanticSeed(MappingModel):
    schema_version: str = "agentkit.semantic_seed.v1"
    domain: str = "business"
    entities: list[EntitySeed] = Field(default_factory=list)
    relationships: list[RelationshipSeed] = Field(default_factory=list)
    fields: list[FieldSeed] = Field(default_factory=list)
    candidate_metrics: list[MetricSeed] = Field(default_factory=list)
    candidate_dimensions: list[DimensionSeed] = Field(default_factory=list)
    policies: dict[str, Any] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_PII_FIELD_RE = re.compile(
    r"(customer|cust|contact|phone|tel|mobile|email|address|addr|passport|"
    r"idcard|identity|member[_-]?card|marketvipcard|buyer|recipient|consignee)",
    re.IGNORECASE,
)
_TIME_FIELD_RE = re.compile(
    r"(^|_)(date|time|dt|day|month|year|created|updated|paid|sell|order)(_|$)",
    re.IGNORECASE,
)
_ID_FIELD_RE = re.compile(r"(^id$|_id$|id$|uuid|guid|no$|number$)", re.IGNORECASE)
_NUMERIC_RE = re.compile(
    r"(int|integer|number|numeric|decimal|double|float|real|money|amount|price|qty|quantity|count)",
    re.IGNORECASE,
)
_STRING_RE = re.compile(r"(char|text|string|varchar|nvarchar|clob)", re.IGNORECASE)
_DATE_RE = re.compile(r"(date|time|timestamp|datetime)", re.IGNORECASE)
_DIMENSION_HINT_RE = re.compile(
    r"(status|state|type|category|channel|region|country|city|store|shop|brand|"
    r"department|dept|level|grade|gender|source)",
    re.IGNORECASE,
)


def schema_to_semantic_seed(
    schema: dict[str, Any],
    profiles: dict[str, Any] | None = None,
    *,
    target_domain: str | None = None,
) -> SemanticSeed:
    """Map a database schema/profile snapshot into a conservative seed."""

    profiles = profiles or {}
    tables = _normalize_tables(schema)
    fks = _normalize_foreign_keys(schema, tables)
    fk_table_counts = _fk_table_counts(fks)
    table_by_name = {_table_key(table): table for table in tables}
    pure_join_tables = {
        _table_key(table)
        for table in tables
        if _is_pure_join_table(table, fks, fk_table_counts.get(_table_key(table), 0))
    }

    entities: list[EntitySeed] = []
    all_fields: list[FieldSeed] = []
    dimensions: list[DimensionSeed] = []
    metrics: list[MetricSeed] = []
    evidence: list[EvidenceItem] = []
    warnings: list[str] = []
    denied_fields: list[dict[str, str]] = []
    masked_fields: list[dict[str, str]] = []

    fk_fields_by_table: dict[str, set[str]] = defaultdict(set)
    for fk in fks:
        for field_name in fk.get("constrained_columns", []):
            fk_fields_by_table[str(fk.get("table") or "")].add(str(field_name))

    entity_id_by_table: dict[str, str] = {}
    for table in tables:
        table_key = _table_key(table)
        if table_key in pure_join_tables:
            evidence.append(
                EvidenceItem(
                    kind="association_table",
                    title="Pure relationship table",
                    content=f"{table_key} has only relationship keys and no business fields.",
                    table=table_key,
                )
            )
            continue

        entity_id = _stable_slug(str(table.get("name") or table_key))
        entity_id_by_table[table_key] = entity_id
        pk = _primary_key(table)
        profile = _table_profile(profiles, table_key)
        entity = EntitySeed(
            id=entity_id,
            name=_titleize(str(table.get("name") or table_key)),
            table=str(table.get("name") or table_key),
            schema_name=_optional_text(table.get("schema") or table.get("schema_name")),
            primary_key=pk,
            row_count=_optional_int(profile.get("row_count") or profile.get("rows")),
            role="association"
            if fk_table_counts.get(table_key, 0) >= 2 and _business_field_count(table) > 0
            else "entity",
            evidence=[
                EvidenceItem(
                    kind="schema_table",
                    title="Table mapped to entity",
                    content=f"Table {table_key} was mapped to entity {entity_id}.",
                    table=table_key,
                )
            ],
        )
        for column in _columns(table):
            field = _field_seed(
                table=table,
                entity_id=entity_id,
                column=column,
                primary_key=pk,
                fk_fields=fk_fields_by_table.get(table_key, set()),
                profile=_column_profile(profile, str(column.get("name") or "")),
            )
            entity.fields.append(field)
            all_fields.append(field)
            if field.policy == "deny":
                denied_fields.append({"entity": entity_id, "field": field.name})
            elif field.policy == "mask":
                masked_fields.append({"entity": entity_id, "field": field.name})
        entities.append(entity)

    relationships = _relationship_seeds(fks, entity_id_by_table, pure_join_tables, table_by_name)
    time_field_by_entity = _first_time_field(all_fields)

    for field in all_fields:
        if field.policy != "allow":
            continue
        if field.role == "time":
            dim = DimensionSeed(
                id=_stable_slug(f"{field.entity_id}_{field.name}"),
                name=_titleize(field.name),
                entity_id=field.entity_id,
                field=field.name,
                kind="time",
                description=f"Time dimension from {field.table}.{field.name}.",
                evidence=field.evidence,
            )
            dimensions.append(dim)
            continue
        if _is_dimension_field(field, profiles):
            dimensions.append(
                DimensionSeed(
                    id=_stable_slug(f"{field.entity_id}_{field.name}"),
                    name=_titleize(field.name),
                    entity_id=field.entity_id,
                    field=field.name,
                    kind="category",
                    description=f"Categorical dimension from {field.table}.{field.name}.",
                    evidence=field.evidence,
                )
            )
        if _is_metric_field(field):
            metric_id = _stable_slug(f"{field.entity_id}_{field.name}_sum")
            metrics.append(
                MetricSeed(
                    id=metric_id,
                    name=_titleize(field.name),
                    entity_id=field.entity_id,
                    field=field.name,
                    kind="sum",
                    formula=f"sum({field.name})",
                    definition=f"Sum of {field.table}.{field.name}.",
                    time_field=time_field_by_entity.get(field.entity_id),
                    evidence=field.evidence,
                )
            )

    for entity in entities:
        if entity.primary_key:
            metrics.insert(
                0,
                MetricSeed(
                    id=_stable_slug(f"{entity.id}_count"),
                    name=f"{entity.name} Count",
                    entity_id=entity.id,
                    field=entity.primary_key,
                    kind="count_distinct",
                    formula=f"count_distinct({entity.primary_key})",
                    definition=f"Count of distinct {entity.name} records.",
                    time_field=time_field_by_entity.get(entity.id),
                    evidence=entity.evidence,
                ),
            )

    if not metrics:
        warnings.append("No safe numeric metric candidates were found.")
    if denied_fields or masked_fields:
        evidence.append(
            EvidenceItem(
                kind="policy",
                title="PII fields denied or masked",
                content="Sensitive customer/contact fields were removed from metric and dimension candidates.",
                metadata={"denied_fields": denied_fields, "masked_fields": masked_fields},
            )
        )

    return SemanticSeed(
        domain=_stable_slug(target_domain or str(schema.get("domain") or "business")),
        entities=entities,
        relationships=relationships,
        fields=all_fields,
        candidate_metrics=_dedupe_metrics(metrics),
        candidate_dimensions=_dedupe_dimensions(dimensions),
        policies={
            "raw_sql_fallback": False,
            "row_level_default": "schema_only",
            "denied_fields": denied_fields,
            "masked_fields": masked_fields,
            "deny_patterns": [
                "customer",
                "contact",
                "phone",
                "address",
                "passport",
                "member card",
            ],
            "permission_hint": "仅允许通过受治理语义层查询聚合指标；客户、联系和证件字段默认拒绝或脱敏。",
        },
        freshness=_freshness(schema, profiles),
        evidence=evidence,
        warnings=warnings,
    )


def seed_to_agentkit_semantic_model_payload(
    seed: SemanticSeed,
    agent_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the packaged Semantic Skill payload consumed by AgentKit codegen."""

    agent_output = agent_output or {}
    semantic = agent_output.get("semantic_model") if isinstance(agent_output, dict) else {}
    name = str(semantic.get("name") if isinstance(semantic, dict) else "" or "").strip()
    model_id = _semantic_asset_id(seed, name)
    metrics = _metric_payloads(seed)
    dimensions = _dimension_payloads(seed)
    entities = [
        {
            "id": entity.id,
            "name": entity.name,
            "table": entity.table,
            "schema": entity.schema_name,
            "primary_key": entity.primary_key,
            "role": entity.role,
            "row_count": entity.row_count,
            "fields": [
                {
                    "id": field.id,
                    "name": field.name,
                    "source_field": field.source_field,
                    "type": field.data_type,
                    "role": field.role,
                    "nullable": field.nullable,
                    "policy": field.policy,
                }
                for field in entity.fields
            ],
        }
        for entity in seed.entities
    ]
    relationships = [
        {
            "id": relationship.id,
            "name": relationship.name,
            "label": relationship.label,
            "from": relationship.from_entity,
            "to": relationship.to_entity,
            "join_fields": relationship.join_fields,
            "cardinality": relationship.cardinality,
            "relationship_type": relationship.relationship_type,
        }
        for relationship in seed.relationships
    ]
    allowed_metrics = [metric["id"] for metric in metrics]
    allowed_dimensions = [dimension["id"] for dimension in dimensions]
    return {
        "package_type": "semantic_skill",
        "source": "agentkit_native_semantic_builder",
        "mdl": {
            "schema": "agentkit.mdl.v1",
            "model": {
                "id": model_id,
                "slug": model_id,
                "name": name or f"{_titleize(seed.domain)} Semantic Skill",
                "domain": seed.domain,
                "version": "v1",
            },
            "entities": entities,
            "relationships": relationships,
            "metrics": metrics,
            "dimensions": dimensions,
            "permissions": seed.policies,
            "freshness": seed.freshness,
        },
        "runtime": {
            "transport": "agentkit_governed_rest",
            "query_url": f"/api/knowledge-assets/assets/semantic_model/{model_id}/query",
            "direct_database_access": False,
            "raw_sql_fallback": False,
        },
        "governance": {
            "allowed_metrics": allowed_metrics,
            "allowed_dimensions": allowed_dimensions,
            "raw_sql_fallback": False,
            "usage_policy": seed.policies,
        },
        "evidence": [item.model_dump(mode="json") for item in seed.evidence],
    }


def seed_to_dashboard_manifest(
    seed: SemanticSeed,
    semantic_model_slug: str,
    goal: str,
) -> dict[str, Any]:
    """Create a structured DashboardManifest draft from a semantic seed."""

    metrics = seed.candidate_metrics[:4]
    dimensions = [dim for dim in seed.candidate_dimensions if dim.kind == "category"][:4]
    time_dimension = next(
        (dim for dim in seed.candidate_dimensions if dim.kind == "time"),
        None,
    )
    title = _titleize(goal or f"{seed.domain} overview")
    data_views: list[dict[str, Any]] = []
    tiles: list[dict[str, Any]] = []
    layout: list[dict[str, int | str]] = []

    for index, metric in enumerate(metrics[:3]):
        view_id = _stable_slug(f"kpi_{metric.id}")
        data_views.append(
            {
                "id": view_id,
                "kind": "semantic_metric",
                "semantic_model": semantic_model_slug,
                "metric": metric.id,
                "dimensions": [],
                "filters": [],
            }
        )
        tiles.append(
            {
                "id": _stable_slug(f"tile_{view_id}"),
                "type": "kpi_card",
                "title": metric.name,
                "data_view_id": view_id,
            }
        )
        layout.append({"tile_id": _stable_slug(f"tile_{view_id}"), "x": index * 4, "y": 0, "w": 4, "h": 2})

    if metrics and time_dimension:
        view_id = _stable_slug(f"trend_{metrics[0].id}")
        data_views.append(
            {
                "id": view_id,
                "kind": "semantic_metric",
                "semantic_model": semantic_model_slug,
                "metric": metrics[0].id,
                "dimensions": [time_dimension.id],
                "grain": "month",
                "filters": [],
            }
        )
        tiles.append(
            {
                "id": _stable_slug(f"tile_{view_id}"),
                "type": "trend_line",
                "title": f"{metrics[0].name} Trend",
                "data_view_id": view_id,
            }
        )
        layout.append({"tile_id": _stable_slug(f"tile_{view_id}"), "x": 0, "y": 2, "w": 8, "h": 4})

    if metrics and dimensions:
        view_id = _stable_slug(f"top_{metrics[0].id}_{dimensions[0].id}")
        data_views.append(
            {
                "id": view_id,
                "kind": "semantic_metric",
                "semantic_model": semantic_model_slug,
                "metric": metrics[0].id,
                "dimensions": [dimensions[0].id],
                "limit": 10,
                "filters": [],
            }
        )
        tiles.append(
            {
                "id": _stable_slug(f"tile_{view_id}"),
                "type": "top_dimensions",
                "title": f"Top {dimensions[0].name}",
                "data_view_id": view_id,
            }
        )
        layout.append({"tile_id": _stable_slug(f"tile_{view_id}"), "x": 8, "y": 2, "w": 4, "h": 4})

        table_view_id = _stable_slug(f"table_{metrics[0].id}")
        data_views.append(
            {
                "id": table_view_id,
                "kind": "semantic_metric",
                "semantic_model": semantic_model_slug,
                "metric": metrics[0].id,
                "dimensions": [dim.id for dim in dimensions[:3]],
                "limit": 50,
                "filters": [],
            }
        )
        tiles.append(
            {
                "id": _stable_slug(f"tile_{table_view_id}"),
                "type": "breakdown_table",
                "title": "Breakdown",
                "data_view_id": table_view_id,
            }
        )
        layout.append({"tile_id": _stable_slug(f"tile_{table_view_id}"), "x": 0, "y": 6, "w": 12, "h": 5})

    filters = []
    if time_dimension:
        filters.append({"id": "time_range", "type": "time_range", "dimension": time_dimension.id})
    for dim in dimensions[:3]:
        filters.append({"id": _stable_slug(f"filter_{dim.id}"), "type": "select", "dimension": dim.id})

    return {
        "schema": "agentkit.dashboard.manifest.v1",
        "id": _stable_slug(f"dashboard_{semantic_model_slug}_{goal or seed.domain}")[:96],
        "title": title,
        "description": f"Auto-generated dashboard draft for {seed.domain}.",
        "semantic_model": {"asset_id": semantic_model_slug, "version": "v1"},
        "semantic_bindings": [
            {"metric": metric.id, "dimensions": [dim.id for dim in dimensions[:3]]}
            for metric in metrics
        ],
        "data_views": data_views,
        "filters": filters,
        "tiles": tiles,
        "layout": layout,
        "policies": {
            "raw_sql_fallback": False,
            "uses_only_defined_metrics_and_dimensions": True,
        },
    }


def validate_semantic_payload(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    mdl = payload.get("mdl") if isinstance(payload, dict) else None
    if not isinstance(mdl, dict):
        return ["Semantic payload is missing mdl."]
    if not mdl.get("entities"):
        blockers.append("Semantic model has no entities.")
    if not mdl.get("metrics"):
        blockers.append("Semantic model has no safe metrics.")
    permissions = mdl.get("permissions") if isinstance(mdl.get("permissions"), dict) else {}
    for field in permissions.get("denied_fields", []):
        if isinstance(field, dict) and not field.get("field"):
            blockers.append("Denied field policy is malformed.")
    return blockers


def validate_dashboard_manifest(
    manifest: dict[str, Any],
    semantic_payload: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    mdl = semantic_payload.get("mdl") if isinstance(semantic_payload, dict) else {}
    metric_ids = {
        str(item.get("id"))
        for item in mdl.get("metrics", [])
        if isinstance(item, dict) and item.get("id")
    }
    dimension_ids = {
        str(item.get("id"))
        for item in mdl.get("dimensions", [])
        if isinstance(item, dict) and item.get("id")
    }
    for view in manifest.get("data_views", []):
        if not isinstance(view, dict):
            blockers.append("Dashboard data_view is malformed.")
            continue
        metric = str(view.get("metric") or "")
        if metric and metric not in metric_ids:
            blockers.append(f"Dashboard data_view references unknown metric: {metric}")
        for dimension in view.get("dimensions", []):
            if str(dimension) not in dimension_ids:
                blockers.append(f"Dashboard data_view references unknown dimension: {dimension}")
        if view.get("raw_sql"):
            blockers.append("Dashboard data_view must not use raw_sql fallback.")
    if not manifest.get("tiles"):
        blockers.append("Dashboard manifest has no tiles.")
    return blockers


def _normalize_tables(schema: dict[str, Any]) -> list[dict[str, Any]]:
    raw = schema.get("tables")
    if isinstance(raw, dict):
        return [
            {"name": key, **(value if isinstance(value, dict) else {})}
            for key, value in raw.items()
        ]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(schema.get("schema"), dict):
        return _normalize_tables(schema["schema"])
    return []


def _normalize_foreign_keys(
    schema: dict[str, Any],
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = schema.get("foreign_keys") or schema.get("foreignKeys") or []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_fk(item)
            if normalized:
                out.append(normalized)
    for table in tables:
        table_name = str(table.get("name") or "")
        for key in ("foreign_keys", "foreignKeys", "fks"):
            raw_table_fks = table.get(key)
            if not isinstance(raw_table_fks, list):
                continue
            for item in raw_table_fks:
                if isinstance(item, dict):
                    normalized = _normalize_fk({"table": table_name, **item})
                    if normalized:
                        out.append(normalized)
    return out


def _normalize_fk(item: dict[str, Any]) -> dict[str, Any] | None:
    table = item.get("table") or item.get("source_table") or item.get("from_table")
    referred_table = (
        item.get("referred_table")
        or item.get("target_table")
        or item.get("to_table")
        or item.get("references")
    )
    constrained = (
        item.get("constrained_columns")
        or item.get("columns")
        or item.get("from_columns")
        or item.get("source_columns")
    )
    referred = (
        item.get("referred_columns")
        or item.get("target_columns")
        or item.get("to_columns")
    )
    if isinstance(constrained, str):
        constrained = [constrained]
    if isinstance(referred, str):
        referred = [referred]
    if not table or not referred_table or not constrained or not referred:
        return None
    return {
        "name": item.get("name") or item.get("constraint_name") or "",
        "table": str(table),
        "referred_table": str(referred_table),
        "constrained_columns": [str(value) for value in constrained],
        "referred_columns": [str(value) for value in referred],
    }


def _table_key(table: dict[str, Any]) -> str:
    return str(table.get("name") or table.get("table") or "").strip()


def _columns(table: dict[str, Any]) -> list[dict[str, Any]]:
    raw = table.get("columns") or table.get("fields") or []
    if isinstance(raw, dict):
        return [{"name": key, **(value if isinstance(value, dict) else {})} for key, value in raw.items()]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _primary_key(table: dict[str, Any]) -> str | None:
    raw = table.get("primary_keys") or table.get("primary_key") or table.get("primaryKey")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list) and raw:
        return str(raw[0])
    for column in _columns(table):
        if column.get("primary_key") or column.get("primaryKey"):
            return str(column.get("name"))
    return None


def _field_seed(
    *,
    table: dict[str, Any],
    entity_id: str,
    column: dict[str, Any],
    primary_key: str | None,
    fk_fields: set[str],
    profile: dict[str, Any],
) -> FieldSeed:
    table_name = _table_key(table)
    name = str(column.get("name") or column.get("field") or "").strip()
    data_type = str(column.get("type") or column.get("data_type") or "unknown")
    nullable = bool(column.get("nullable", True))
    pii = bool(column.get("pii")) or bool(_PII_FIELD_RE.search(name))
    policy: Literal["allow", "mask", "deny"] = "allow"
    role = "attribute"
    if pii:
        policy = "deny" if _is_direct_identifier(name) else "mask"
        role = "denied"
    elif name == primary_key:
        role = "primary_key"
    elif name in fk_fields:
        role = "foreign_key"
    elif _DATE_RE.search(data_type) or _TIME_FIELD_RE.search(name):
        role = "time"
    elif _NUMERIC_RE.search(data_type) and not _ID_FIELD_RE.search(name):
        role = "measure"
    elif _STRING_RE.search(data_type) or _DIMENSION_HINT_RE.search(name):
        role = "dimension"
    evidence = [
        EvidenceItem(
            kind="schema_field",
            title="Column mapped to field",
            content=f"{table_name}.{name} ({data_type}) mapped as {role}.",
            table=table_name,
            field=name,
            metadata={"distinct_count": profile.get("distinct_count")},
        )
    ]
    return FieldSeed(
        id=_stable_slug(f"{entity_id}_{name}"),
        entity_id=entity_id,
        table=table_name,
        name=name,
        source_field=name,
        data_type=data_type,
        role=role,  # type: ignore[arg-type]
        nullable=nullable,
        is_pii=pii,
        policy=policy,
        evidence=evidence,
    )


def _relationship_seeds(
    fks: list[dict[str, Any]],
    entity_id_by_table: dict[str, str],
    pure_join_tables: set[str],
    table_by_name: dict[str, dict[str, Any]],
) -> list[RelationshipSeed]:
    relationships: list[RelationshipSeed] = []
    for fk in fks:
        from_table = str(fk.get("table") or "")
        to_table = str(fk.get("referred_table") or "")
        if from_table in pure_join_tables:
            # The pure join table becomes a direct many-to-many relationship
            # between the two referenced tables. Create this after grouping.
            continue
        from_entity = entity_id_by_table.get(from_table)
        to_entity = entity_id_by_table.get(to_table)
        if not from_entity or not to_entity:
            continue
        label = _business_relationship_label(from_table, to_table, fk)
        relationships.append(
            RelationshipSeed(
                id=_stable_slug(f"{from_entity}_to_{to_entity}_{'_'.join(fk['constrained_columns'])}"),
                name=label,
                label=label,
                from_entity=from_entity,
                to_entity=to_entity,
                join_fields=[
                    {"from": left, "to": right}
                    for left, right in zip(
                        fk["constrained_columns"],
                        fk["referred_columns"],
                        strict=False,
                    )
                ],
                cardinality="many-to-one",
                evidence=[
                    EvidenceItem(
                        kind="foreign_key",
                        title="Foreign key mapped to relationship",
                        content=f"{from_table}.{fk['constrained_columns']} references {to_table}.{fk['referred_columns']}.",
                        table=from_table,
                    )
                ],
            )
        )
    for join_table in sorted(pure_join_tables):
        join_fks = [fk for fk in fks if fk.get("table") == join_table]
        if len(join_fks) != 2:
            continue
        left_table = str(join_fks[0]["referred_table"])
        right_table = str(join_fks[1]["referred_table"])
        left_entity = entity_id_by_table.get(left_table)
        right_entity = entity_id_by_table.get(right_table)
        if not left_entity or not right_entity:
            continue
        label = _business_relationship_label(left_table, right_table, {"table": join_table})
        relationships.append(
            RelationshipSeed(
                id=_stable_slug(f"{left_entity}_{right_entity}_{join_table}"),
                name=label,
                label=label,
                from_entity=left_entity,
                to_entity=right_entity,
                join_fields=[
                    {
                        "through": join_table,
                        "from": join_fks[0]["referred_columns"][0],
                        "to": join_fks[1]["referred_columns"][0],
                    }
                ],
                cardinality="many-to-many",
                relationship_type="association_table",
                evidence=[
                    EvidenceItem(
                        kind="association_table",
                        title="Join table mapped to relationship",
                        content=f"{join_table} connects {left_table} and {right_table}.",
                        table=join_table,
                    )
                ],
            )
        )
    return relationships


def _business_relationship_label(
    from_table: str,
    to_table: str,
    fk: dict[str, Any],
) -> str:
    raw = str(fk.get("name") or "").strip()
    if raw and raw.lower() not in {"foreign_key", "fk"}:
        return _titleize(raw)
    from_label = _titleize(from_table)
    to_label = _titleize(to_table)
    return f"{from_label} to {to_label}"


def _fk_table_counts(fks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for fk in fks:
        counts[str(fk.get("table") or "")] += 1
    return counts


def _is_pure_join_table(table: dict[str, Any], fks: list[dict[str, Any]], fk_count: int) -> bool:
    if fk_count != 2:
        return False
    table_name = _table_key(table)
    fk_fields = {
        field
        for fk in fks
        if fk.get("table") == table_name
        for field in fk.get("constrained_columns", [])
    }
    business = [
        col
        for col in _columns(table)
        if str(col.get("name") or "") not in fk_fields
        and str(col.get("name") or "").lower() not in {"created_at", "updated_at"}
    ]
    return not business


def _business_field_count(table: dict[str, Any]) -> int:
    return sum(
        1
        for col in _columns(table)
        if not _ID_FIELD_RE.search(str(col.get("name") or ""))
    )


def _table_profile(profiles: dict[str, Any], table_name: str) -> dict[str, Any]:
    candidates = [
        profiles.get(table_name),
        (profiles.get("tables") or {}).get(table_name)
        if isinstance(profiles.get("tables"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _column_profile(profile: dict[str, Any], field_name: str) -> dict[str, Any]:
    columns = profile.get("columns") or profile.get("fields") or {}
    if isinstance(columns, dict):
        value = columns.get(field_name)
        return value if isinstance(value, dict) else {}
    if isinstance(columns, list):
        for item in columns:
            if isinstance(item, dict) and item.get("name") == field_name:
                return item
    return {}


def _first_time_field(fields: list[FieldSeed]) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in fields:
        if field.role == "time" and field.entity_id not in out:
            out[field.entity_id] = field.name
    return out


def _is_metric_field(field: FieldSeed) -> bool:
    return field.role == "measure" and field.policy == "allow" and not _ID_FIELD_RE.search(field.name)


def _is_dimension_field(field: FieldSeed, _profiles: dict[str, Any]) -> bool:
    if field.role == "dimension":
        return True
    return bool(_DIMENSION_HINT_RE.search(field.name)) and field.policy == "allow"


def _is_direct_identifier(name: str) -> bool:
    return bool(
        re.search(
            r"(phone|tel|mobile|email|address|addr|passport|idcard|identity|member[_-]?card|marketvipcard)",
            name,
            re.IGNORECASE,
        )
    )


def _freshness(schema: dict[str, Any], profiles: dict[str, Any]) -> dict[str, Any]:
    freshness = schema.get("freshness") if isinstance(schema.get("freshness"), dict) else {}
    profile_freshness = profiles.get("freshness") if isinstance(profiles.get("freshness"), dict) else {}
    return {
        "status": freshness.get("status") or profile_freshness.get("status") or "schema_snapshot",
        "snapshot_id": freshness.get("snapshot_id") or profile_freshness.get("snapshot_id") or schema.get("snapshot_id"),
        "snapshot_hash": freshness.get("snapshot_hash") or profile_freshness.get("snapshot_hash") or schema.get("snapshot_hash"),
        "data_through": freshness.get("data_through") or profile_freshness.get("data_through"),
        "sample_mode": profiles.get("sample_mode") or "schema_only",
    }


def _metric_payloads(seed: SemanticSeed) -> list[dict[str, Any]]:
    dimension_ids = [dimension.id for dimension in seed.candidate_dimensions[:6]]
    return [
        {
            "id": metric.id,
            "name": metric.name,
            "business_name": metric.name,
            "entity": metric.entity_id,
            "field": metric.field,
            "kind": metric.kind,
            "formula": metric.formula,
            "definition": metric.definition,
            "time_field": metric.time_field,
            "dimensions": metric.dimensions or dimension_ids,
            "lineage": [item.model_dump(mode="json") for item in metric.evidence],
        }
        for metric in seed.candidate_metrics
    ]


def _dimension_payloads(seed: SemanticSeed) -> list[dict[str, Any]]:
    return [
        {
            "id": dimension.id,
            "name": dimension.name,
            "entity": dimension.entity_id,
            "field": dimension.field,
            "kind": dimension.kind,
            "description": dimension.description,
        }
        for dimension in seed.candidate_dimensions
    ]


def _dedupe_metrics(metrics: list[MetricSeed]) -> list[MetricSeed]:
    out: list[MetricSeed] = []
    seen: set[str] = set()
    for metric in metrics:
        if metric.id in seen:
            continue
        seen.add(metric.id)
        out.append(metric)
    return out[:24]


def _dedupe_dimensions(dimensions: list[DimensionSeed]) -> list[DimensionSeed]:
    out: list[DimensionSeed] = []
    seen: set[str] = set()
    for dimension in dimensions:
        if dimension.id in seen:
            continue
        seen.add(dimension.id)
        out.append(dimension)
    return out[:48]


def _semantic_asset_id(seed: SemanticSeed, name: str = "") -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                seed.domain,
                ",".join(entity.id for entity in seed.entities),
                ",".join(metric.id for metric in seed.candidate_metrics),
                name,
            ]
        ).encode()
    ).hexdigest()[:10]
    return _stable_slug(f"{seed.domain}_semantic_{digest}")


def _stable_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        slug = "asset"
    if slug[0].isdigit():
        slug = f"a_{slug}"
    return slug[:96]


def _titleize(value: str) -> str:
    text = re.sub(r"[_\-]+", " ", str(value)).strip()
    return " ".join(part[:1].upper() + part[1:].lower() for part in text.split()) or "Untitled"


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "DimensionSeed",
    "EntitySeed",
    "EvidenceItem",
    "FieldSeed",
    "MetricSeed",
    "RelationshipSeed",
    "SemanticSeed",
    "schema_to_semantic_seed",
    "seed_to_agentkit_semantic_model_payload",
    "seed_to_dashboard_manifest",
    "validate_dashboard_manifest",
    "validate_semantic_payload",
]
