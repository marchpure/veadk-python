"""Write native Dashboard Skill packages from Semantic Skill evidence."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, field_validator

from ...models import ApiModel, RecordBuildJobBody, RecordSkillPackageBody, UpdateBuildJobBody
from ...service import KnowledgeAssetStore, redact_sensitive
from .askdata_query_service import AskDataQueryBody, AskDataQueryService
from .common import now_iso, safe_identifier, stable_slug
from .dashboard_spec_builder import build_dashboard_spec, fallback_dashboard_spec


class DashboardSkillBuildBody(ApiModel):
    space_id: str | None = Field(default=None, max_length=128)
    semantic_asset_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    intent: str = Field(default="核心指标看板", min_length=1, max_length=1000)
    metric: str | None = Field(default=None, max_length=200)
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_range: dict[str, Any] = Field(default_factory=dict)
    mode: str = Field(default="summary", max_length=80)
    conversation_id: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=128)
    query_evidence_hash: str | None = Field(default=None, max_length=256)
    publish: bool = True

    @field_validator("dimensions")
    @classmethod
    def _trim_dimensions(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class DashboardSkillWriter:
    def __init__(self, store: KnowledgeAssetStore) -> None:
        self._store = store
        self._askdata = AskDataQueryService(store)

    async def build(self, body: DashboardSkillBuildBody) -> dict[str, Any]:
        semantic_asset = await self._store.get_asset(
            asset_type="semantic_model",
            asset_id=body.semantic_asset_id,
        )
        dashboard_asset_id = stable_slug(
            f"{body.semantic_asset_id}-{body.name}-dashboard",
            fallback="dashboard",
        )
        job = await self._store.record_build_job(
            RecordBuildJobBody(
                space_id=body.space_id,
                asset_type="dashboard",
                asset_id=dashboard_asset_id,
                job_type="dashboard_skill_build",
                status="running",
                input=body.model_dump(mode="json"),
            )
        )
        try:
            askdata_result = await self._askdata.query(
                AskDataQueryBody(
                    semantic_asset_id=body.semantic_asset_id,
                    metric=body.metric,
                    dimensions=body.dimensions,
                    filters=body.filters,
                    time_range=body.time_range,
                    question=body.intent,
                    limit=100,
                    mode=body.mode,
                )
            )
            blocked = askdata_result.get("status") == "blocked"
            if blocked:
                dashboard_spec = fallback_dashboard_spec(
                    dashboard_asset_id=dashboard_asset_id,
                    semantic_asset=semantic_asset,
                    title=body.name,
                    description=body.description or "",
                )
            else:
                dashboard_spec = build_dashboard_spec(
                    dashboard_asset_id=dashboard_asset_id,
                    semantic_asset=semantic_asset,
                    askdata_result=askdata_result,
                    title=body.name,
                    description=body.description or "",
                    intent=body.intent,
                )
            package = _dashboard_package(
                dashboard_asset_id=dashboard_asset_id,
                semantic_asset=semantic_asset,
                dashboard_spec=dashboard_spec,
                askdata_result=askdata_result,
                body=body,
            )
            publish_state = "blocked" if blocked else "published" if body.publish else "draft"
            status = "blocked" if blocked else "ready"
            stored = await self._store.record_skill_package(
                RecordSkillPackageBody(
                    space_id=body.space_id,
                    asset_type="dashboard",
                    asset_id=dashboard_asset_id,
                    capability_kind="dashboard_skill",
                    name=body.name,
                    description=body.description,
                    status=status,
                    publish_state=publish_state,
                    version="v1",
                    source_ids=_safe_string_list(semantic_asset.get("provenance", {}).get("source_ids")),
                    type="dashboard_skill",
                    query_url=f"/api/knowledge-assets/assets/dashboard/{dashboard_asset_id}/query",
                    capability_package=package,
                    capabilities=_capabilities(dashboard_spec, askdata_result),
                    gate={
                        "score": 0 if blocked else 100,
                        "passed": 2 if blocked else 4,
                        "total": 4,
                        "blockers": ["AskData policy denied this dashboard intent."] if blocked else [],
                    },
                    freshness=_freshness(askdata_result),
                    provenance={
                        "builder": "agentkit_native_dashboard_skill_writer",
                        "semantic_model_asset_id": body.semantic_asset_id,
                        "askdata_query_status": askdata_result.get("status"),
                        **_dashboard_tool_provenance(body),
                    },
                    usage_policy={
                        "permission_hint": _policy_hint(askdata_result),
                        "raw_sql_fallback": False,
                        "direct_database_access": False,
                    },
                    sample_evidence=_safe_evidence(askdata_result),
                    metadata={"generated_from": "askdata"},
                )
            )
            final_job = await self._store.update_build_job(
                job["id"],
                UpdateBuildJobBody(
                    status="blocked" if blocked else "succeeded",
                    result_skill_id=stored["asset_id"],
                    output={
                        "dashboard_asset_id": stored["asset_id"],
                        "publish_state": stored["publish_state"],
                        "askdata_status": askdata_result.get("status"),
                        "preview": {
                            "tiles": dashboard_spec.get("tiles", []),
                            "filters": dashboard_spec.get("filters", []),
                            "data_views": dashboard_spec.get("data_views", []),
                        },
                    },
                ),
            )
            return {
                "schema": "agentkit.dashboard_skill_build.v1",
                "job_id": final_job["id"],
                "status": final_job["status"],
                "dashboard_asset_id": stored["asset_id"],
                "dashboard": stored,
                "askdata": askdata_result,
                "preview": final_job.get("output", {}).get("preview", {}),
                "mock": False,
            }
        except Exception as error:
            await self._store.update_build_job(
                job["id"],
                UpdateBuildJobBody(
                    status="failed",
                    error={"message": str(redact_sensitive(str(error)))},
                ),
            )
            raise


def _dashboard_package(
    *,
    dashboard_asset_id: str,
    semantic_asset: dict[str, Any],
    dashboard_spec: dict[str, Any],
    askdata_result: dict[str, Any],
    body: DashboardSkillBuildBody,
) -> dict[str, Any]:
    query_url = f"/api/knowledge-assets/assets/dashboard/{dashboard_asset_id}/query"
    return redact_sensitive(
        {
            "package_type": "dashboard_skill",
            "runtime": {
                "transport": "agentkit_governed_rest",
                "query_url": query_url,
                "direct_database_access": False,
                "raw_sql_fallback": False,
            },
            "manifest": {
                "schema": "agentkit.skill.manifest.v1",
                "name": body.name,
                "asset_id": dashboard_asset_id,
                "capability_kind": "dashboard_skill",
                "semantic_model_asset_id": semantic_asset["asset_id"],
                "artifacts": [
                    "manifest.json",
                    "dashboard_spec.json",
                    "tools/query_dashboard_metric.py",
                    "policies/dashboard_policy.json",
                    "evals/dashboard_cases.json",
                ],
            },
            "dashboard": dashboard_spec,
            "artifacts": {
                "manifest.json": {
                    "schema": "agentkit.dashboard_skill.manifest.v1",
                    "asset_id": dashboard_asset_id,
                    "name": body.name,
                    "query_url": query_url,
                },
                "SKILL.md": _skill_md(body, dashboard_asset_id),
                "dashboard_spec.json": dashboard_spec,
                "tools/query_dashboard_metric.py": _tool_py(query_url),
                "policies/dashboard_policy.json": {
                    "raw_sql_fallback": False,
                    "direct_database_access": False,
                    "policyDecision": askdata_result.get("data", {}).get("policyDecision", {}),
                },
                "evals/dashboard_cases.json": {
                    "schema": "agentkit.dashboard.evals.v1",
                    "cases": [
                        {
                            "id": "askdata_seed",
                            "intent": body.intent,
                            "must_include": ["sql", "policyDecision", "freshness", "metricDefinition"],
                        }
                    ],
                },
            },
            "semantic_model": {
                "asset_id": semantic_asset["asset_id"],
                "version": semantic_asset.get("version") or "v1",
            },
            "provenance": {
                "semantic_asset_id": semantic_asset["asset_id"],
                **_dashboard_tool_provenance(body),
            },
            "askdata_seed": askdata_result,
            "evals": {
                "suite": {
                    "contract_version": "evaluation.suite_version.v1",
                    "cases": [],
                }
            },
        }
    )


def _dashboard_tool_provenance(body: DashboardSkillBuildBody) -> dict[str, str]:
    out: dict[str, str] = {}
    if body.conversation_id:
        out["conversation_id"] = body.conversation_id
    if body.tool_call_id:
        out["tool_call_id"] = body.tool_call_id
    if body.query_evidence_hash:
        out["query_evidence_hash"] = body.query_evidence_hash
    return out


def _tool_py(query_url: str) -> str:
    return f'''"""Typed governed REST tool for an AgentKit Dashboard Skill."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

QUERY_URL = {query_url!r}


def _query_url(path_or_url: str) -> str:
    base = os.environ["STUDIO_BASE_URL"].rstrip("/")
    parsed_base = urlparse(base)
    if parsed_base.scheme not in {{"http", "https"}} or not parsed_base.netloc:
        raise ValueError("STUDIO_BASE_URL must be an http(s) URL")
    candidate = (path_or_url or "").strip()
    if candidate.startswith("//"):
        raise ValueError("Governed dashboard URL must not be protocol-relative")
    if candidate.startswith("/"):
        url = urljoin(f"{{base}}/", candidate.lstrip("/"))
    else:
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme != parsed_base.scheme or parsed_candidate.netloc != parsed_base.netloc:
            raise ValueError("Governed dashboard URL must stay on Studio origin")
        url = candidate
    parsed_url = urlparse(url)
    if parsed_url.path.startswith("/api/knowledge-assets/assets/dashboard/") or parsed_url.path.startswith("/api/external/assets/dashboard/"):
        return url
    raise ValueError("Governed dashboard URL must target a dashboard asset query path")


def query_dashboard_metric(filters: dict[str, Any] | None = None, data_view_ids: list[str] | None = None) -> dict[str, Any]:
    bearer_value = os.environ["STUDIO_GOVERNED_QUERY_TOKEN"]
    response = requests.post(
        _query_url(QUERY_URL),
        json={{"filters": filters or {{}}, "data_view_ids": data_view_ids or []}},
        headers={{"Authorization": " ".join(("Bearer", bearer_value))}},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
'''


def _skill_md(body: DashboardSkillBuildBody, dashboard_asset_id: str) -> str:
    return "\n".join(
        [
            "---",
            f"name: {safe_identifier(dashboard_asset_id, fallback='dashboard')}",
            "description: AgentKit governed Dashboard Skill.",
            "---",
            "",
            "# Dashboard Skill",
            "",
            "Use the packaged dashboard artifacts and the governed REST query tool.",
            "Do not use direct database credentials, raw SQL fallback, or customer/contact fields.",
            "",
            "## Packaged Artifacts",
            "- `manifest.json`",
            "- `dashboard_spec.json`",
            "- `tools/query_dashboard_metric.py`",
            "- `policies/dashboard_policy.json`",
            "- `evals/dashboard_cases.json`",
        ]
    )


def _capabilities(dashboard_spec: dict[str, Any], askdata_result: dict[str, Any]) -> dict[str, Any]:
    data = askdata_result.get("data") if isinstance(askdata_result, dict) else {}
    metric = data.get("metric") if isinstance(data, dict) else {}
    dimensions = data.get("dimensions") if isinstance(data, dict) else []
    return {
        "metrics": [metric.get("id")] if isinstance(metric, dict) and metric.get("id") else [],
        "dimensions": [
            item.get("id")
            for item in dimensions
            if isinstance(item, dict) and item.get("id")
        ],
        "data_views": [
            item.get("id")
            for item in dashboard_spec.get("data_views", [])
            if isinstance(item, dict) and item.get("id")
        ],
        "filters": [
            item.get("id")
            for item in dashboard_spec.get("filters", [])
            if isinstance(item, dict) and item.get("id")
        ],
    }


def _freshness(askdata_result: dict[str, Any]) -> dict[str, Any]:
    data = askdata_result.get("data") if isinstance(askdata_result, dict) else {}
    freshness = data.get("freshness") if isinstance(data, dict) else {}
    return freshness if isinstance(freshness, dict) else {"status": "unknown", "as_of": now_iso()}


def _policy_hint(askdata_result: dict[str, Any]) -> str:
    data = askdata_result.get("data") if isinstance(askdata_result, dict) else {}
    decision = data.get("policyDecision") if isinstance(data, dict) else {}
    if isinstance(decision, dict) and decision.get("reason"):
        return str(decision["reason"])
    return "仅允许通过受治理语义层查询聚合指标。"


def _safe_evidence(askdata_result: dict[str, Any]) -> list[dict[str, Any]]:
    data = askdata_result.get("data") if isinstance(askdata_result, dict) else {}
    evidence = data.get("evidence") if isinstance(data, dict) else []
    return [item for item in evidence if isinstance(item, dict)][:10]


def _safe_string_list(value: Any) -> list[str]:
    return [str(item) for item in value if item] if isinstance(value, list) else []
