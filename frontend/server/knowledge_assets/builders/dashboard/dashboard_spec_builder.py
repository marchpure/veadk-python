"""Build native Dashboard Skill specs from AskData evidence."""

from __future__ import annotations

from typing import Any

from .common import dimension_id, metric_id, now_iso, safe_identifier, stable_slug


def build_dashboard_spec(
    *,
    dashboard_asset_id: str,
    semantic_asset: dict[str, Any],
    askdata_result: dict[str, Any],
    title: str,
    description: str,
    intent: str,
) -> dict[str, Any]:
    data = askdata_result.get("data") if isinstance(askdata_result, dict) else {}
    metric = data.get("metric") if isinstance(data, dict) else {}
    dimensions = data.get("dimensions") if isinstance(data, dict) else []
    metric_key = safe_identifier(metric.get("id") if isinstance(metric, dict) else "", fallback="metric")
    dimension_keys = [
        safe_identifier(item.get("id") or item.get("field"), fallback="dimension")
        for item in dimensions
        if isinstance(item, dict)
    ]
    semantic_asset_id = str(semantic_asset.get("asset_id") or "")
    now = now_iso()
    data_views = [
        {
            "id": "primary_metric",
            "kind": "semantic_metric",
            "question": intent or f"查看 {metric_key}",
            "semantic_model": semantic_asset_id,
            "metric": metric_key,
            "dimensions": dimension_keys,
            "filters": [],
            "rows": data.get("rows") if isinstance(data.get("rows"), list) else [],
            "returnedCount": data.get("returnedCount") if isinstance(data, dict) else 0,
            "sql": data.get("sql") if isinstance(data, dict) else "",
            "metricDefinition": data.get("metricDefinition") if isinstance(data, dict) else "",
            "policyDecision": data.get("policyDecision") if isinstance(data, dict) else {},
            "freshness": data.get("freshness") if isinstance(data, dict) else {},
            "evidence": data.get("evidence") if isinstance(data, dict) else [],
            "lineage": data.get("lineage") if isinstance(data, dict) else [],
        }
    ]
    if dimension_keys:
        data_views.append(
            {
                "id": "breakdown_table",
                "kind": "semantic_metric",
                "question": f"按 {', '.join(dimension_keys[:3])} 拆解 {metric_key}",
                "semantic_model": semantic_asset_id,
                "metric": metric_key,
                "dimensions": dimension_keys[:3],
                "filters": [],
                "limit": 50,
                "rows": data.get("rows") if isinstance(data.get("rows"), list) else [],
                "returnedCount": data.get("returnedCount") if isinstance(data, dict) else 0,
                "sql": data.get("sql") if isinstance(data, dict) else "",
                "metricDefinition": data.get("metricDefinition") if isinstance(data, dict) else "",
                "policyDecision": data.get("policyDecision") if isinstance(data, dict) else {},
                "freshness": data.get("freshness") if isinstance(data, dict) else {},
                "evidence": data.get("evidence") if isinstance(data, dict) else [],
                "lineage": data.get("lineage") if isinstance(data, dict) else [],
            }
        )
    filters = [
        {
            "id": f"filter_{dimension}",
            "type": "select",
            "dimension": dimension,
            "label": dimension,
        }
        for dimension in dimension_keys[:3]
    ]
    tiles = [
        {
            "id": "tile_primary_metric",
            "type": "kpi",
            "title": title,
            "data_view_id": "primary_metric",
        }
    ]
    layout = [{"tile_id": "tile_primary_metric", "x": 0, "y": 0, "w": 4, "h": 2}]
    if len(data_views) > 1:
        tiles.append(
            {
                "id": "tile_breakdown_table",
                "type": "table",
                "title": "维度拆解",
                "data_view_id": "breakdown_table",
            }
        )
        layout.append({"tile_id": "tile_breakdown_table", "x": 0, "y": 2, "w": 8, "h": 5})

    return {
        "schema": "agentkit.dashboard.manifest.v1",
        "id": dashboard_asset_id,
        "title": title,
        "description": description,
        "generated_at": now,
        "semantic_model": {
            "asset_id": semantic_asset_id,
            "version": semantic_asset.get("version") or "v1",
        },
        "semantic_bindings": [
            {
                "id": f"binding_{stable_slug(semantic_asset_id)}",
                "model_slug": semantic_asset_id,
                "model_version": semantic_asset.get("version") or "v1",
                "allowed_metrics": [metric_key],
                "allowed_dimensions": dimension_keys,
                "readiness": "published",
            }
        ],
        "data_views": data_views,
        "filters": filters,
        "drilldowns": [
            {
                "from": "primary_metric",
                "to": "breakdown_table",
                "dimensions": dimension_keys[:3],
            }
        ]
        if dimension_keys
        else [],
        "tiles": tiles,
        "layout": layout,
        "policies": {
            "raw_sql_fallback": False,
            "direct_database_access": False,
            "uses_only_defined_metrics_and_dimensions": True,
        },
    }


def fallback_dashboard_spec(
    *,
    dashboard_asset_id: str,
    semantic_asset: dict[str, Any],
    title: str,
    description: str,
) -> dict[str, Any]:
    package = semantic_asset.get("capability_package") or {}
    mdl = package.get("mdl") if isinstance(package, dict) else {}
    metrics = [item for item in mdl.get("metrics", []) if isinstance(item, dict)] if isinstance(mdl, dict) else []
    dimensions = [item for item in mdl.get("dimensions", []) if isinstance(item, dict)] if isinstance(mdl, dict) else []
    askdata = {
        "data": {
            "metric": {"id": metric_id(metrics[0]) if metrics else "metric"},
            "dimensions": [{"id": dimension_id(dim)} for dim in dimensions[:1]],
            "sql": "",
            "metricDefinition": "",
            "policyDecision": {"decision": "allow", "raw_sql_fallback": False},
            "freshness": semantic_asset.get("freshness") or {},
            "evidence": semantic_asset.get("sample_evidence") or [],
        }
    }
    return build_dashboard_spec(
        dashboard_asset_id=dashboard_asset_id,
        semantic_asset=semantic_asset,
        askdata_result=askdata,
        title=title,
        description=description,
        intent=title,
    )
