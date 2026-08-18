# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Authorization and normalization for Byaan Data Studio assets."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from .gateways import (
    MOCK_ASSETS,
    DataStudioGateway,
    datastudio_api_key,
    datastudio_base_url,
    datastudio_embed_url,
    mock_enabled,
    require_configured,
)
from .models import DataStudioAsset, DataStudioAssetType, DataStudioConfig


def config_payload() -> DataStudioConfig:
    base_url = datastudio_base_url()
    mock = mock_enabled()
    embed_url = datastudio_embed_url()
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
    payload["query_url"] = _safe_query_url(asset)
    return payload


def normalize_assets_payload(
    raw: Any, *, page: int = 1, page_size: int = 20
) -> dict[str, Any]:
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
        raise HTTPException(status_code=404, detail="Data Studio asset not found")

    require_configured()
    return normalize_asset(await (gateway or DataStudioGateway()).get_asset(asset_type, asset_id))


def _safe_query_url(asset: DataStudioAsset) -> str:
    query_url = (asset.query_url or "").strip()
    fallback = f"/api/external/assets/{asset.asset_type}/{asset.asset_id}/query"
    if not query_url:
        return fallback

    parsed = urlsplit(query_url)
    if query_url.startswith("/"):
        if parsed.scheme or parsed.netloc:
            raise HTTPException(
                status_code=502,
                detail="Invalid Data Studio query URL: protocol-relative URL",
            )
        if not parsed.path.startswith("/api/external/assets/"):
            raise HTTPException(
                status_code=502,
                detail="Invalid Data Studio query URL path",
            )
        return query_url

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=502, detail="Invalid Data Studio query URL")

    base_url = datastudio_base_url()
    base = urlsplit(base_url)
    if not base.scheme or not base.netloc:
        raise HTTPException(status_code=502, detail="DATASTUDIO_BASE_URL is invalid")
    if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
        raise HTTPException(
            status_code=502,
            detail="Data Studio query URL origin does not match DATASTUDIO_BASE_URL",
        )
    if not parsed.path.startswith("/api/external/assets/"):
        raise HTTPException(
            status_code=502,
            detail="Invalid Data Studio query URL path",
        )
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError:
        return default
    return parsed if parsed > 0 else default
