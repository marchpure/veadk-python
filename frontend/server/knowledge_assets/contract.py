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

"""Frozen Knowledge Asset Registry contract for Knowledge Center sessions.

Session A implements this registry. Sessions B and C must treat this module as
read-only and consume only the metadata envelopes defined here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, TypedDict

KnowledgeAssetType = Literal["knowledge_resource", "semantic_model", "dashboard"]
KnowledgeCapabilityKind = Literal[
    "retrieval_binding",
    "semantic_skill",
    "dashboard_skill",
]
KnowledgeAssetPublishState = Literal[
    "draft",
    "validating",
    "blocked",
    "published",
    "archived",
]


class KnowledgeAssetGateEnvelope(TypedDict):
    """Governance gate summary for external asset consumption."""

    score: int
    passed: int
    total: int
    blockers: list[str]


class KnowledgeAssetMetadataEnvelope(TypedDict):
    """Stable metadata envelope for AgentKit Knowledge Center capabilities."""

    schema_version: Literal["knowledge_asset.metadata.v1"]
    asset_type: KnowledgeAssetType
    asset_id: str
    capability_kind: KnowledgeCapabilityKind
    name: str
    description: str | None
    status: str
    publish_state: KnowledgeAssetPublishState
    gate: KnowledgeAssetGateEnvelope | None
    version: str | None
    consumers: list[str]
    capabilities: Mapping[str, Any]
    capability_package: Mapping[str, Any]
    query_url: str | None
    freshness: Mapping[str, Any]
    provenance: Mapping[str, Any]
    usage_policy: Mapping[str, Any]
    sample_evidence: list[Mapping[str, Any]]


class KnowledgeAssetListEnvelope(TypedDict):
    """Paged registry response carrying only metadata, never credentials."""

    schema_version: Literal["knowledge_asset.list.v1"]
    items: list[KnowledgeAssetMetadataEnvelope]
    total: int
    next_cursor: str | None
    mock: bool


class KnowledgeAssetRegistry(Protocol):
    """Read-only registry for selectable Agent capabilities."""

    async def list_assets(
        self,
        *,
        query: str = "",
        asset_types: Sequence[KnowledgeAssetType] = (),
        capability_kinds: Sequence[KnowledgeCapabilityKind] = (),
        cursor: str | None = None,
        limit: int = 20,
    ) -> KnowledgeAssetListEnvelope:
        """Return published capability metadata visible to the caller."""

    async def get_asset(
        self,
        *,
        asset_type: KnowledgeAssetType,
        asset_id: str,
    ) -> KnowledgeAssetMetadataEnvelope:
        """Return one metadata envelope or raise the implementation's not-found error."""
