# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""HTTP request models for the Studio knowledge asset store."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contract import (
    KnowledgeAssetPublishState,
    KnowledgeAssetType,
    KnowledgeCapabilityKind,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class CreateSpaceBody(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSpaceBody(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class CreateSourceBody(ApiModel):
    space_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    provider: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    uri: str | None = Field(default=None, max_length=4096)
    status: str = Field(default="pending", min_length=1, max_length=80)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSourceStatusBody(ApiModel):
    status: str = Field(min_length=1, max_length=80)
    status_reason: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class SaveCredentialBody(ApiModel):
    credentials: dict[str, Any] = Field(min_length=1)
    status: str = Field(default="connected", min_length=1, max_length=80)
    expires_at: str | None = Field(default=None, max_length=128)


class RecordIndexedDocumentBody(ApiModel):
    source_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(min_length=1, max_length=256)
    document_id: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=512)
    uri: str | None = Field(default=None, max_length=4096)
    status: str = Field(default="indexed", min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordSnapshotBody(ApiModel):
    asset_type: KnowledgeAssetType
    asset_id: str = Field(min_length=1, max_length=256)
    capability_kind: KnowledgeCapabilityKind
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="ready", min_length=1, max_length=80)
    publish_state: KnowledgeAssetPublishState = "draft"
    source_id: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=128)
    gate: dict[str, Any] | None = None
    consumers: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    capability_package: dict[str, Any] = Field(default_factory=dict)
    query_url: str | None = Field(default=None, max_length=4096)
    freshness: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    usage_policy: dict[str, Any] = Field(default_factory=dict)
    sample_evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("consumers")
    @classmethod
    def _trim_consumers(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class RecordSkillPackageBody(RecordSnapshotBody):
    package_id: str | None = Field(default=None, max_length=256)
    space_id: str | None = Field(default=None, max_length=128)


__all__ = [
    "CreateSourceBody",
    "CreateSpaceBody",
    "RecordIndexedDocumentBody",
    "RecordSkillPackageBody",
    "RecordSnapshotBody",
    "SaveCredentialBody",
    "UpdateSourceStatusBody",
    "UpdateSpaceBody",
]
