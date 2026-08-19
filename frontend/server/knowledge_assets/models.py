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
    default_knowledge_base_id: str | None = Field(default=None, max_length=256)
    region: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSpaceBody(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    default_knowledge_base_id: str | None = Field(default=None, max_length=256)
    region: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] | None = None


class CreateSourceBody(ApiModel):
    space_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    provider: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    uri: str | None = Field(default=None, max_length=4096)
    locator: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="registered", min_length=1, max_length=80)
    default_index_policy: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportSourceBody(ApiModel):
    space_id: str = Field(min_length=1, max_length=128)
    source_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    uri: str | None = Field(default=None, max_length=4096)
    target_knowledge_base_id: str | None = Field(default=None, max_length=256)
    region: str | None = Field(default=None, max_length=128)
    provider: str | None = Field(default=None, max_length=120)
    content: str | None = None
    content_format: str | None = Field(default=None, max_length=40)
    file: dict[str, Any] = Field(default_factory=dict)
    schema_payload: dict[str, Any] = Field(default_factory=dict, alias="schema")
    locator: dict[str, Any] = Field(default_factory=dict)
    credential_ref: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSourceStatusBody(ApiModel):
    status: str = Field(min_length=1, max_length=80)
    status_reason: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class CreateSourceResourceBody(ApiModel):
    asset_space_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    resource_id: str | None = Field(default=None, max_length=256)
    source_type: str = Field(min_length=1, max_length=80)
    provider: str | None = Field(default=None, max_length=120)
    uri: str | None = Field(default=None, max_length=4096)
    provider_ref: str | None = Field(default=None, max_length=512)
    content_hash: str | None = Field(default=None, max_length=256)
    tags: list[str] = Field(default_factory=list)
    permission_scope: str = Field(default="private", min_length=1, max_length=80)
    freshness: dict[str, Any] = Field(default_factory=dict)
    sync_status: str = Field(default="registered", min_length=1, max_length=80)
    last_synced_at: str | None = Field(default=None, max_length=128)
    error_summary: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def _trim_tags(cls, value: list[str]) -> list[str]:
        return [item.strip()[:80] for item in value if item.strip()]


class UpdateSourceResourceBody(ApiModel):
    uri: str | None = Field(default=None, max_length=4096)
    provider_ref: str | None = Field(default=None, max_length=512)
    content_hash: str | None = Field(default=None, max_length=256)
    tags: list[str] | None = None
    permission_scope: str | None = Field(default=None, min_length=1, max_length=80)
    freshness: dict[str, Any] | None = None
    sync_status: str | None = Field(default=None, min_length=1, max_length=80)
    last_synced_at: str | None = Field(default=None, max_length=128)
    error_summary: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None

    @field_validator("tags")
    @classmethod
    def _trim_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return [item.strip()[:80] for item in value if item.strip()]


class SaveCredentialBody(ApiModel):
    credentials: dict[str, Any] = Field(min_length=1)
    provider: str | None = Field(default=None, max_length=120)
    auth_mode: str = Field(default="none", min_length=1, max_length=80)
    status: str = Field(default="connected", min_length=1, max_length=80)
    expires_at: str | None = Field(default=None, max_length=128)


class RecordIndexedDocumentBody(ApiModel):
    source_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(min_length=1, max_length=256)
    knowledge_base_id: str | None = Field(default=None, max_length=256)
    provider_doc_id: str | None = Field(default=None, max_length=256)
    document_id: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=512)
    uri: str | None = Field(default=None, max_length=4096)
    sync_status: str | None = Field(default=None, max_length=80)
    status: str = Field(default="indexed", min_length=1, max_length=80)
    last_synced_at: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecordSnapshotBody(ApiModel):
    asset_type: KnowledgeAssetType = "knowledge_resource"
    asset_id: str | None = Field(default=None, max_length=256)
    capability_kind: KnowledgeCapabilityKind = "retrieval_binding"
    name: str = Field(default="Snapshot", min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="ready", min_length=1, max_length=80)
    publish_state: KnowledgeAssetPublishState = "draft"
    source_id: str | None = Field(default=None, max_length=128)
    kind: str = Field(default="knowledge_asset", min_length=1, max_length=80)
    artifact_uri: str | None = Field(default=None, max_length=4096)
    schema_payload: dict[str, Any] = Field(default_factory=dict, alias="schema")
    profile: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = Field(default=None, max_length=256)
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
    type: str | None = Field(default=None, max_length=80)
    source_ids: list[str] = Field(default_factory=list)
    snapshot_ids: list[str] = Field(default_factory=list)


class RecordBuildJobBody(ApiModel):
    space_id: str | None = Field(default=None, max_length=128)
    source_id: str | None = Field(default=None, max_length=128)
    asset_type: KnowledgeAssetType | None = None
    asset_id: str | None = Field(default=None, max_length=256)
    job_type: str = Field(default="build_capability", min_length=1, max_length=80)
    status: str = Field(default="running", min_length=1, max_length=80)
    logs_ref: str | None = Field(default=None, max_length=4096)
    result_skill_id: str | None = Field(default=None, max_length=256)
    error: dict[str, Any] | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class UpdateBuildJobBody(ApiModel):
    status: str = Field(min_length=1, max_length=80)
    logs_ref: str | None = Field(default=None, max_length=4096)
    result_skill_id: str | None = Field(default=None, max_length=256)
    error: dict[str, Any] | None = None
    output: dict[str, Any] | None = None


class BuildSemanticSkillBody(ApiModel):
    space_id: str | None = Field(default=None, max_length=128)
    source_ids: list[str] = Field(default_factory=list)
    snapshot_ids: list[str] = Field(default_factory=list)
    name: str = Field(default="Generated Semantic Skill", min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    intent: str = Field(default="", max_length=2000)
    target_domain: str = Field(default="", max_length=200)
    publish: bool = False

    @field_validator("source_ids", "snapshot_ids")
    @classmethod
    def _clean_ids(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class QueryExternalAssetBody(ApiModel):
    metric: str = Field(default="", max_length=256)
    dimension: str | None = Field(default=None, max_length=256)
    grain: str | None = Field(default=None, max_length=128)
    filters: dict[str, Any] = Field(default_factory=dict)
    time_range: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=1000)
    question: str = Field(default="", max_length=2000)


class ShareDashboardBody(ApiModel):
    title: str | None = Field(default=None, max_length=300)
    visibility: str = Field(default="local_link", max_length=40)
    expires_at: str | None = Field(default=None, max_length=128)
    dashboard_html: str | None = Field(default=None, max_length=2_000_000)
    dashboard_spec: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CreateSourceResourceBody",
    "CreateSourceBody",
    "CreateSpaceBody",
    "ImportSourceBody",
    "RecordIndexedDocumentBody",
    "RecordBuildJobBody",
    "RecordSkillPackageBody",
    "RecordSnapshotBody",
    "SaveCredentialBody",
    "BuildSemanticSkillBody",
    "QueryExternalAssetBody",
    "ShareDashboardBody",
    "UpdateBuildJobBody",
    "UpdateSourceResourceBody",
    "UpdateSourceStatusBody",
    "UpdateSpaceBody",
]
