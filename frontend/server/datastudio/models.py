# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""HTTP models for Byaan Data Studio assets."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DataStudioAssetType = Literal["dashboard", "semantic_model"]
PublishState = Literal["draft", "validating", "blocked", "published", "archived"]


class DataStudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    baseUrl: str = ""
    embedUrl: str = ""
    mock: bool = False


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
    query_url: str | None = None
    freshness: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    usage_policy: dict[str, Any] = Field(default_factory=dict)
    sample_evidence: list[dict[str, Any]] = Field(default_factory=list)
