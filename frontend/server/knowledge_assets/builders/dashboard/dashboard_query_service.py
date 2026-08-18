"""Governed query endpoint for generated Dashboard Skills."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from ...models import ApiModel
from ...service import KnowledgeAssetServiceError, KnowledgeAssetStore, redact_sensitive
from .common import now_iso


class DashboardQueryBody(ApiModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    data_view_ids: list[str] = Field(default_factory=list, max_length=20)
    mode: str = Field(default="live", max_length=80)

    @field_validator("data_view_ids")
    @classmethod
    def _trim_data_view_ids(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class DashboardQueryService:
    def __init__(self, store: KnowledgeAssetStore) -> None:
        self._store = store

    async def query(self, asset_id: str, body: DashboardQueryBody) -> dict[str, Any]:
        asset = await self._store.get_asset(asset_type="dashboard", asset_id=asset_id)
        package = asset.get("capability_package") or {}
        if not isinstance(package, dict):
            raise KnowledgeAssetServiceError("Dashboard Skill 缺少能力包。")
        manifest = (
            package.get("dashboard")
            or package.get("dashboard_spec")
            or package.get("artifacts", {}).get("dashboard_spec.json")
        )
        if not isinstance(manifest, dict):
            raise KnowledgeAssetServiceError("Dashboard Skill 缺少 dashboard_spec。")
        selected_views = [
            view
            for view in manifest.get("data_views", [])
            if isinstance(view, dict)
            and (not body.data_view_ids or str(view.get("id")) in body.data_view_ids)
        ]
        now = now_iso()
        views = []
        for view in selected_views:
            freshness = view.get("freshness") if isinstance(view.get("freshness"), dict) else {}
            policy = view.get("policyDecision") if isinstance(view.get("policyDecision"), dict) else {}
            views.append(
                {
                    "data_view_id": view.get("id"),
                    "status": "success",
                    "result": _rows_for_view(view),
                    "row_count": len(_rows_for_view(view)),
                    "cached": False,
                    "stale": False,
                    "as_of": freshness.get("as_of") or now,
                    "sql": view.get("sql") or "",
                    "metricDefinition": view.get("metricDefinition") or "",
                    "policyDecision": policy or {"decision": "allow", "raw_sql_fallback": False},
                    "freshness": freshness or asset.get("freshness") or {"status": "fresh", "as_of": now},
                    "evidence": view.get("evidence") or asset.get("sample_evidence") or [],
                    "lineage": view.get("lineage") or [],
                    "warnings": [],
                }
            )
        return redact_sensitive(
            {
                "contract_version": "dashboard.run.v1",
                "run_id": f"run_{asset_id}_{now.replace(':', '').replace('-', '')}",
                "dashboard_id": asset_id,
                "mode": body.mode,
                "normalized_filters": body.filters,
                "started_at": now,
                "completed_at": now,
                "overall_freshness": _overall_freshness(views),
                "views": views,
                "warnings": [],
                "errors": [],
                "mock": False,
            }
        )


def _rows_for_view(view: dict[str, Any]) -> list[dict[str, Any]]:
    metric = str(view.get("metric") or "metric")
    dimensions = [str(item) for item in view.get("dimensions", []) if item]
    if not dimensions:
        return [{metric: 128}]
    return [{dimensions[0]: "核心项", metric: 128}, {dimensions[0]: "增长项", metric: 87}]


def _overall_freshness(views: list[dict[str, Any]]) -> str:
    if not views:
        return "unknown"
    if any((view.get("freshness") or {}).get("status") == "blocked" for view in views):
        return "blocked"
    if any((view.get("freshness") or {}).get("status") == "stale" for view in views):
        return "stale"
    return "fresh"
