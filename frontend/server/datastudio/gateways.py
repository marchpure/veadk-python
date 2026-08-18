# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Server-side Byaan Data Studio gateway."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

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
        gate={"score": 92, "passed": 3, "total": 3, "blockers": []},
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
        query_url="/api/external/assets/dashboard/gmv-dashboard-demo/query",
        freshness={"sla": "T+1", "last_updated": "2026-08-16T00:00:00+08:00"},
        provenance={"owner": "Data Studio Demo", "source": "mock"},
        usage_policy={
            "permission_hint": "仅可查询聚合指标；用户手机号等字段已脱敏。",
            "masked_fields": ["buyer_phone", "buyer_id"],
            "export_allowed": False,
        },
        sample_evidence=[
            {
                "type": "sql",
                "content": "select channel, sum(gmv) from ads_trade group by channel",
            }
        ],
    ),
    DataStudioAsset(
        asset_type="semantic_model",
        asset_id="retention-model-demo",
        name="用户留存语义模型",
        description="沉淀活跃、留存、复购相关指标与用户生命周期维度。",
        status="published",
        publish_state="published",
        gate={"score": 88, "passed": 4, "total": 4, "blockers": []},
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
        query_url="/api/external/assets/semantic_model/retention-model-demo/query",
        freshness={"sla": "T+1"},
        provenance={"owner": "Data Studio Demo", "source": "mock"},
        usage_policy={
            "permission_hint": "禁止明细用户导出；仅返回聚合结果和证据。",
            "masked_fields": ["user_id"],
            "export_allowed": False,
        },
        sample_evidence=[
            {
                "type": "metric",
                "content": "retention_1d = retained_users_1d / new_users",
            }
        ],
    ),
]


@dataclass(frozen=True)
class DataStudioRuntimeConfig:
    base_url: str = ""
    api_key: str = ""
    embed_url: str = ""


def mock_enabled() -> bool:
    return os.getenv("DATASTUDIO_MOCK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def datastudio_base_url() -> str:
    return datastudio_runtime_config().base_url


def datastudio_api_key() -> str:
    return datastudio_runtime_config().api_key


def datastudio_embed_url() -> str:
    config = datastudio_runtime_config()
    return config.embed_url or config.base_url


def datastudio_runtime_config() -> DataStudioRuntimeConfig:
    explicit = DataStudioRuntimeConfig(
        base_url=_clean_url(os.getenv("DATASTUDIO_BASE_URL", "")),
        api_key=os.getenv("DATASTUDIO_API_KEY", "").strip(),
        embed_url=_clean_url(os.getenv("DATASTUDIO_EMBED_URL", "")),
    )
    if explicit.base_url and explicit.api_key:
        return explicit

    byaan_env = DataStudioRuntimeConfig(
        base_url=_clean_url(os.getenv("BYAAN_BASE_URL", "") or os.getenv("BYAAN_BACKEND_URL", "")),
        api_key=os.getenv("BYAAN_MCP_API_KEY", "").strip(),
        embed_url=_clean_url(
            os.getenv("BYAAN_FRONTEND_URL", "")
            or os.getenv("FRONTEND_URL", "")
            or os.getenv("PUBLIC_BASE_URL", "")
        ),
    )
    if byaan_env.base_url and byaan_env.api_key:
        return DataStudioRuntimeConfig(
            base_url=byaan_env.base_url,
            api_key=byaan_env.api_key,
            embed_url=explicit.embed_url or byaan_env.embed_url,
        )

    discovered = _discover_local_byaan_runtime()
    if discovered.base_url and discovered.api_key:
        return DataStudioRuntimeConfig(
            base_url=discovered.base_url,
            api_key=discovered.api_key,
            embed_url=explicit.embed_url or discovered.embed_url,
        )

    return explicit


def gateway_headers() -> dict[str, str]:
    key = datastudio_api_key()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def require_configured() -> None:
    if mock_enabled():
        return
    config = datastudio_runtime_config()
    if not config.base_url or not config.api_key:
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
                params=_byaan_list_params(params),
                headers=gateway_headers(),
            )
        return _response_payload(response)

    async def get_asset(
        self, asset_type: DataStudioAssetType, asset_id: str
    ) -> dict[str, Any]:
        target = f"{datastudio_base_url()}/api/external/assets/{asset_type}/{asset_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(target, headers=gateway_headers())
        payload = _response_payload(response)
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            payload = data
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Invalid Data Studio asset payload")
        return payload


def _byaan_list_params(params: Mapping[str, str]) -> dict[str, str]:
    mapped: dict[str, str] = {"types": "dashboard,semantic_model"}
    query = (params.get("q") or params.get("query") or "").strip()
    if query:
        mapped["q"] = query
    page_size = _positive_int(params.get("page_size") or params.get("pageSize"), 20)
    page = _positive_int(params.get("page"), 1)
    cursor = (params.get("cursor") or "").strip()
    mapped["limit"] = str(min(page_size, 100))
    if cursor:
        mapped["cursor"] = cursor
    elif page > 1:
        mapped["cursor"] = str((page - 1) * page_size)
    return mapped


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _discover_local_byaan_runtime() -> DataStudioRuntimeConfig:
    if os.getenv("DATASTUDIO_AUTO_DISCOVER", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return DataStudioRuntimeConfig()

    for line in _process_command_lines():
        if "BYAAN_" not in line and "DATASTUDIO_" not in line:
            continue
        if "server.main:app" not in line and "byaan" not in line.lower():
            continue

        base_url = _clean_url(
            _extract_env_value(line, "DATASTUDIO_BASE_URL")
            or _extract_env_value(line, "BYAAN_BASE_URL")
            or _extract_env_value(line, "BYAAN_BACKEND_URL")
        )
        api_key = (
            _extract_env_value(line, "DATASTUDIO_API_KEY")
            or _extract_env_value(line, "BYAAN_MCP_API_KEY")
        ).strip()
        embed_url = _clean_url(
            _extract_env_value(line, "DATASTUDIO_EMBED_URL")
            or _extract_env_value(line, "BYAAN_FRONTEND_URL")
            or _extract_env_value(line, "FRONTEND_URL")
            or _extract_env_value(line, "PUBLIC_BASE_URL")
        )
        if base_url and api_key and _is_loopback_http_url(base_url):
            if embed_url and not _is_loopback_http_url(embed_url):
                embed_url = ""
            return DataStudioRuntimeConfig(
                base_url=base_url,
                api_key=api_key,
                embed_url=embed_url,
            )

    return DataStudioRuntimeConfig()


def _process_command_lines() -> list[str]:
    commands = (
        ("ps", "eww", "-A", "-o", "command="),
        ("ps", "eww", "ax", "-o", "command="),
    )
    for command in commands:
        try:
            output = subprocess.check_output(
                command,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        return output.splitlines()
    return []


def _extract_env_value(line: str, name: str) -> str:
    match = re.search(r"(?:^|\s)" + re.escape(name) + r"=([^\s]+)", line)
    return match.group(1) if match else ""


def _clean_url(value: str) -> str:
    return value.strip().strip("\"'").rstrip("/")


def _is_loopback_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def _response_payload(response: httpx.Response) -> Any:
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Byaan authentication failed")
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="Byaan Data Studio is unreachable")
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()
