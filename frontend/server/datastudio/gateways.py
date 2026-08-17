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

"""Server-side Byaan Data Studio gateway.

The browser calls /web/datastudio/* on the VeADK server. This module keeps the
Byaan API key in the server process and proxies only the read-only external
asset contract used by Knowledge Center and Agent creation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx
from fastapi import HTTPException

from .models import DataStudioAsset, DataStudioAssetType


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


def gateway_headers() -> dict[str, str]:
    key = datastudio_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}", "X-API-Key": key}


def require_configured() -> None:
    if mock_enabled():
        return
    if not datastudio_base_url() or not datastudio_api_key():
        raise HTTPException(
            status_code=409,
            detail="DATASTUDIO_BASE_URL or DATASTUDIO_API_KEY is not configured",
        )


class DataStudioGateway:
    async def list_assets(self, params: Mapping[str, str]) -> Any:
        target = f"{datastudio_base_url()}/api/external/assets"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                target,
                params=dict(params),
                headers=gateway_headers(),
            )
        return _response_payload(response)

    async def get_asset(self, asset_type: DataStudioAssetType, asset_id: str) -> dict[str, Any]:
        target = f"{datastudio_base_url()}/api/external/assets/{asset_type}/{asset_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(target, headers=gateway_headers())
        payload = _response_payload(response)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Invalid Data Studio asset payload")
        return payload


def _response_payload(response: httpx.Response) -> Any:
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Byaan authentication failed")
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="Byaan Data Studio is unreachable")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()
