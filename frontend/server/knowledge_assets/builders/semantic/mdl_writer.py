"""Wren-inspired MDL writer for packaged Semantic Skills."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .metric_dimension_candidates import CandidateSet
from .schema_graph import SchemaGraph, slugify


def write_mdl(
    graph: SchemaGraph,
    candidates: CandidateSet,
    *,
    model_id: str,
    display_name: str,
    version: str = "v1",
    datasource_kind: str = "database",
) -> dict[str, Any]:
    entities = []
    for table in graph.tables:
        entity_id = slugify(table.name)
        entities.append(
            {
                "id": entity_id,
                "name": entity_id,
                "business_name": table.name.replace("_", " ").title(),
                "table": table.name,
                "schema": table.schema or "",
                "entity_type": table.table_type,
                "primary_key": table.primary_key[0] if table.primary_key else "",
                "fields": [
                    {
                        "name": column.name,
                        "source_field": column.name,
                        "type": column.data_type,
                        "role": column.role,
                        "nullable": column.nullable,
                        "pii": column.pii,
                    }
                    for column in table.columns
                ],
                "properties": {
                    "row_count": table.row_count,
                    "business_fields": table.business_fields,
                },
            }
        )

    relationships = [
        {
            "id": rel.id,
            "from": slugify(rel.from_table),
            "to": slugify(rel.to_table),
            "label": _relationship_label(rel.from_table, rel.to_table),
            "join_fields": [{"from": rel.from_column, "to": rel.to_column}],
            "cardinality": rel.cardinality,
            "confidence": rel.confidence,
            "evidence": rel.evidence,
        }
        for rel in graph.relationships
    ]

    metrics = [
        {
            "id": metric.id,
            "name": metric.name,
            "business_name": metric.name.replace("_", " ").title(),
            "entity": metric.entity,
            "field": metric.field,
            "definition": metric.definition,
            "kind": "measure",
            "formula": metric.formula,
            "time_field": metric.time_field,
            "default_grain": "month" if metric.time_field else "",
            "dimensions": metric.dimensions,
            "certification": "draft",
            "confidence": metric.confidence,
            "lineage": metric.evidence,
        }
        for metric in candidates.metrics
    ]
    dimensions = [
        {
            "id": dimension.id,
            "name": dimension.name,
            "entity": dimension.entity,
            "entityId": dimension.entity,
            "field": dimension.field,
            "role": dimension.role,
            "description": f"{dimension.role.title()} field {dimension.field}.",
            "confidence": dimension.confidence,
            "lineage": dimension.evidence,
        }
        for dimension in candidates.dimensions
    ]

    return {
        "schema": "byaan.mdl.v1",
        "model": {
            "id": model_id,
            "slug": model_id,
            "name": display_name,
            "version": version,
            "datasource_kind": datasource_kind,
        },
        "entities": entities,
        "relationships": relationships,
        "metrics": metrics,
        "dimensions": dimensions,
        "permissions": {
            "schema": "agentkit.semantic_skill.permissions.v1",
            **candidates.policies,
        },
        "freshness": candidates.freshness,
        "evidence": candidates.evidence,
        "warnings": candidates.warnings,
        "candidate_summary": {
            "table_count": len(graph.tables),
            "relationship_count": len(graph.relationships),
            "metric_count": len(metrics),
            "dimension_count": len(dimensions),
        },
    }


def mdl_file_set(mdl: dict[str, Any]) -> dict[str, Any]:
    fields = []
    for entity in mdl.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        for field in entity.get("fields") or []:
            if isinstance(field, dict):
                fields.append({"entity": entity.get("id") or "", **field})
    return {
        "mdl/models.json": {
            "schema": mdl.get("schema") or "byaan.mdl.v1",
            "model": mdl.get("model") or {},
            "entities": mdl.get("entities") or [],
        },
        "mdl/fields.json": {"schema": "byaan.mdl.fields.v1", "fields": fields},
        "mdl/relationships.json": {
            "schema": "byaan.mdl.relationships.v1",
            "relationships": mdl.get("relationships") or [],
        },
        "mdl/metrics.json": {
            "schema": "byaan.mdl.metrics.v1",
            "metrics": mdl.get("metrics") or [],
        },
        "mdl/dimensions.json": {
            "schema": "byaan.mdl.dimensions.v1",
            "dimensions": mdl.get("dimensions") or [],
        },
        "mdl/permissions.json": {
            "schema": "byaan.mdl.permissions.v1",
            "permissions": mdl.get("permissions") or {},
        },
        "mdl/freshness.json": {
            "schema": "byaan.mdl.freshness.v1",
            "model": mdl.get("model") or {},
            "freshness": mdl.get("freshness") or {},
        },
    }


def _relationship_label(from_table: str, to_table: str) -> str:
    return f"{from_table.replace('_', ' ')} belongs to {to_table.replace('_', ' ')}"

