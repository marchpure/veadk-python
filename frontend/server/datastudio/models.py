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


class NormalizedAssetPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[dict[str, Any]]
    total: int
    page: int
    pageSize: int
    nextCursor: str | None = None
    mock: bool = False
