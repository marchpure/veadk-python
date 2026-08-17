# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Server-side Data Studio gateway for VeADK Studio.

The browser calls /web/datastudio/* on the VeADK server. This module keeps the
Byaan API key in the server process and proxies only the read-only external
asset contract used by Knowledge Center and Agent creation.
"""

from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


DataStudioAssetType = Literal["dashboard", "semantic_model"]
PublishState = Literal["draft", "validating", "blocked", "published", "archived"]


class DataStudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    baseUrl: str = ""
    embedUrl: str = ""
    mock: bool = False


class DataStudioGate(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: float | None = None
    passed: bool | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)


class DataStudioAsset(BaseModel):
    model_config = ConfigDict(extra="allow")

    asset_type: DataStudioAssetType
    asset_id: str
    name: str
    description: str = ""
    status: str = ""
    publish_state: PublishState
    gate: dict[str, Any] = Field(default_factory=dict)
    version: str = ""
    consumers: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    freshness: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    usage_policy: dict[str, Any] = Field(default_factory=dict)
    sample_evidence: list[dict[str, Any]] = Field(default_factory=list)


MOCK_ASSETS: list[DataStudioAsset] = [
    DataStudioAsset(
        asset_type="dashboard",
        asset_id="gmv-dashboard-demo",
        name="交易经营看板",
        description="按渠道、地区和商品层级分析 GMV、订单量与转化趋势。",
        status="published",
        publish_state="published",
        gate={"score": 92, "passed": True, "checks": [{"name": "指标口径", "passed": True}]},
        version="v2026.08.01",
        consumers=["agent"],
        capabilities={
            "metrics": ["GMV", "订单量", "转化率"],
            "dimensions": ["渠道", "地区", "商品类目"],
            "time_field": "pay_date",
            "example_questions": [
                "上周各渠道 GMV 排名如何？",
                "华东地区订单转化率为什么下降？",
            ],
        },
        freshness={"sla": "T+1", "last_updated": "2026-08-16T00:00:00+08:00"},
        provenance={"owner": "Data Studio Demo", "source": "mock"},
        usage_policy={
            "permission_hint": "仅可查询聚合指标；用户手机号等字段已脱敏。",
            "masked_fields": ["buyer_phone", "buyer_id"],
            "export_allowed": False,
        },
        sample_evidence=[
            {"type": "sql", "content": "select channel, sum(gmv) from ads_trade group by channel"}
        ],
    ),
    DataStudioAsset(
        asset_type="semantic_model",
        asset_id="retention-model-demo",
        name="用户留存语义模型",
        description="沉淀活跃、留存、复购相关指标与用户生命周期维度。",
        status="published",
        publish_state="published",
        gate={"score": 88, "passed": True, "checks": [{"name": "权限策略", "passed": True}]},
        version="v2026.08.10",
        consumers=["agent"],
        capabilities={
            "metrics": ["DAU", "次日留存率", "7 日复购率"],
            "dimensions": ["端", "会员等级", "注册渠道"],
            "time_field": "event_date",
            "example_questions": [
                "最近 30 天新用户次日留存趋势如何？",
                "不同会员等级 7 日复购率差异是多少？",
            ],
        },
        freshness={"sla": "T+1"},
        provenance={"owner": "Data Studio Demo", "source": "mock"},
        usage_policy={
            "permission_hint": "禁止明细用户导出；仅返回聚合结果和证据。",
            "masked_fields": ["user_id"],
            "export_allowed": False,
        },
        sample_evidence=[
            {"type": "metric", "content": "retention_1d = retained_users_1d / new_users"}
        ],
    ),
]


def mock_enabled() -> bool:
    return os.getenv("DATASTUDIO_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}


def datastudio_base_url() -> str:
    return os.getenv("DATASTUDIO_BASE_URL", "").strip().rstrip("/")


def datastudio_api_key() -> str:
    return os.getenv("DATASTUDIO_API_KEY", "").strip()


def datastudio_mcp_url(asset_type: str | None = None, asset_id: str | None = None) -> str:
    explicit = os.getenv("DATASTUDIO_MCP_URL", "").strip()
    if explicit:
        return explicit
    base = datastudio_base_url()
    if not base:
        return ""
    if asset_type and asset_id:
        return f"{base}/api/mcp/assets/{asset_type}/{asset_id}"
    return f"{base}/api/mcp"


def config_payload() -> DataStudioConfig:
    base_url = datastudio_base_url()
    mock = mock_enabled()
    embed_url = os.getenv("DATASTUDIO_EMBED_URL", "").strip().rstrip("/") or base_url
    configured = bool(embed_url and (mock or (base_url and datastudio_api_key())))
    return DataStudioConfig(
        configured=configured,
        baseUrl=base_url if configured else "",
        embedUrl=embed_url if configured else "",
        mock=mock,
    )


def require_configured() -> None:
    if mock_enabled():
        return
    if not datastudio_base_url() or not datastudio_api_key():
        raise HTTPException(
            status_code=409,
            detail="DATASTUDIO_BASE_URL or DATASTUDIO_API_KEY is not configured",
        )


def configured_origin(config: DataStudioConfig) -> str:
    if not config.embedUrl:
        return ""
    parsed = urlsplit(config.embedUrl)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def gateway_headers() -> dict[str, str]:
    key = datastudio_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}", "X-API-Key": key}


def normalize_asset(raw: dict[str, Any]) -> dict[str, Any]:
    asset = DataStudioAsset.model_validate(raw)
    payload = asset.model_dump(mode="json")
    payload["mcp_url"] = raw.get("mcp_url") or datastudio_mcp_url(
        asset.asset_type, asset.asset_id
    )
    return payload


def normalize_assets_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        candidates = raw.get("assets") or raw.get("items") or raw.get("data") or []
        total = raw.get("total")
        page = raw.get("page")
        page_size = raw.get("page_size") or raw.get("pageSize")
    else:
        candidates = raw if isinstance(raw, list) else []
        total = None
        page = None
        page_size = None
    if isinstance(candidates, dict):
        candidates = candidates.get("assets") or candidates.get("items") or []
    assets = [
        normalize_asset(item)
        for item in candidates
        if isinstance(item, dict)
        and item.get("asset_type") in {"dashboard", "semantic_model"}
        and item.get("publish_state") == "published"
    ]
    return {
        "assets": assets,
        "total": int(total) if isinstance(total, int) else len(assets),
        "page": int(page) if isinstance(page, int) else 1,
        "pageSize": int(page_size) if isinstance(page_size, int) else len(assets),
        "mock": mock_enabled(),
    }


async def proxy_external_assets(request: Request) -> dict[str, Any]:
    if mock_enabled():
        q = (request.query_params.get("q") or "").strip().lower()
        page = max(1, int(request.query_params.get("page", "1") or "1"))
        page_size = max(1, min(100, int(request.query_params.get("page_size", "20") or "20")))
        assets = [normalize_asset(asset.model_dump(mode="json")) for asset in MOCK_ASSETS]
        if q:
            assets = [
                asset
                for asset in assets
                if q in asset["name"].lower() or q in asset.get("description", "").lower()
            ]
        start = (page - 1) * page_size
        return {
            "assets": assets[start : start + page_size],
            "total": len(assets),
            "page": page,
            "pageSize": page_size,
            "mock": True,
        }

    require_configured()
    target = f"{datastudio_base_url()}/api/external/assets"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            target,
            params=dict(request.query_params),
            headers=gateway_headers(),
        )
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Byaan authentication failed")
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="Byaan Data Studio is unreachable")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return normalize_assets_payload(response.json())


async def proxy_external_asset(asset_type: DataStudioAssetType, asset_id: str) -> dict[str, Any]:
    if mock_enabled():
        for asset in MOCK_ASSETS:
            if asset.asset_type == asset_type and asset.asset_id == asset_id:
                return normalize_asset(asset.model_dump(mode="json"))
        raise HTTPException(status_code=404, detail="Data Studio asset not found")

    require_configured()
    target = f"{datastudio_base_url()}/api/external/assets/{asset_type}/{asset_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(target, headers=gateway_headers())
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Byaan authentication failed")
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="Byaan Data Studio is unreachable")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    raw = response.json()
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="Invalid Data Studio asset payload")
    return normalize_asset(raw)
