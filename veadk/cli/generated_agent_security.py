# Copyright (c) 2025 Beijing Volcano Engine Technology Co., Ltd. and/or its affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Security policy for backend-generated AgentDraft projects."""

from __future__ import annotations

from veadk.cli.generated_agent_codegen import AgentDraft


class DebugPolicyError(ValueError):
    """Raised when an AgentDraft violates backend generation policy."""


def validate_project_policy(draft: AgentDraft) -> None:
    for asset in draft.dataAssets:
        if asset.source != "datastudio":
            continue
        if asset.dataStudioAssetType not in {"dashboard", "semantic_model"}:
            raise DebugPolicyError("Data Studio asset is missing type")
        if not asset.dataStudioAssetId.strip():
            raise DebugPolicyError("Data Studio asset is missing id")
        if asset.dataStudioMcpUrl.strip():
            raise DebugPolicyError("Data Studio assets use REST query_url, not MCP URL")
        if asset.dataStudioQueryUrl.strip() and "/api/external/assets/" not in asset.dataStudioQueryUrl:
            raise DebugPolicyError("Data Studio query URL must target /api/external/assets")
