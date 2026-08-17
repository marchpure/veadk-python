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

"""Authorization and normalization for Byaan Data Studio assets."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from .gateways import (
    MOCK_ASSETS,
    DataStudioGateway,
    datastudio_api_key,
    datastudio_base_url,
    mock_enabled,
    require_configured,
)
from .models import DataStudioAsset, DataStudioAssetType, DataStudioConfig


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


def configured_origin(config: DataStudioConfig) -> str:
    if not config.embedUrl:
        return ""
    parsed = urlsplit(config.embedUrl)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_asset(raw: dict[str, Any]) -> dict[str, Any]:
    asset = DataStudioAsset.model_validate(raw)
    payload = asset.model_dump(mode="json")
    payload["query_url"] = _absolute_query_url(asset)
    return payload


def normalize_assets_payload(raw: Any, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    data = raw.get("data") if isinstance(raw, dict) else None
    envelope = data if isinstance(data, dict) else raw
    if isinstance(envelope, dict):
        candidates = envelope.get("items") or envelope.get("assets") or []
        total = envelope.get("total")
        next_cursor = envelope.get("next_cursor") or envelope.get("nextCursor")
    else:
        candidates = envelope if isinstance(envelope, list) else []
        total = None
        next_cursor = None
    if isinstance(candidates, dict):
        candidates = candidates.get("items") or candidates.get("assets") or []
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
        "page": page,
        "pageSize": page_size,
        "nextCursor": str(next_cursor) if next_cursor else None,
        "mock": mock_enabled(),
    }


async def proxy_external_assets(
    request: Request,
    *,
    gateway: DataStudioGateway | None = None,
) -> dict[str, Any]:
    page = _positive_int(request.query_params.get("page"), 1)
    page_size = min(_positive_int(request.query_params.get("page_size"), 20), 100)
    if mock_enabled():
        q = (request.query_params.get("q") or "").strip().lower()
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
            "nextCursor": str(start + page_size) if start + page_size < len(assets) else None,
            "mock": True,
        }

    require_configured()
    return normalize_assets_payload(
        await (gateway or DataStudioGateway()).list_assets(dict(request.query_params)),
        page=page,
        page_size=page_size,
    )


async def proxy_external_asset(
    asset_type: DataStudioAssetType,
    asset_id: str,
    *,
    gateway: DataStudioGateway | None = None,
) -> dict[str, Any]:
    if mock_enabled():
        for asset in MOCK_ASSETS:
            if asset.asset_type == asset_type and asset.asset_id == asset_id:
                return normalize_asset(asset.model_dump(mode="json"))
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Data Studio asset not found")

    require_configured()
    return normalize_asset(await (gateway or DataStudioGateway()).get_asset(asset_type, asset_id))


def _absolute_query_url(asset: DataStudioAsset) -> str:
    query_url = (asset.query_url or "").strip()
    base_url = datastudio_base_url()
    if query_url.startswith("http://") or query_url.startswith("https://"):
        return query_url
    if query_url.startswith("/") and base_url:
        return f"{base_url}{query_url}"
    if base_url:
        return f"{base_url}/api/external/assets/{asset.asset_type}/{asset.asset_id}/query"
    return query_url


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError:
        return default
    return parsed if parsed > 0 else default
