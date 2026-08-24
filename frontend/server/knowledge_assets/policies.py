"""Server-owned policies for Skill Draft and Manifest writes."""

from __future__ import annotations

from .contracts import SkillManifest
from .repository import KnowledgeAssetRepositoryError


def validate_manifest_policy(manifest: SkillManifest) -> None:
    if not manifest.actions:
        raise KnowledgeAssetRepositoryError(
            "VALIDATION_ERROR",
            "Manifest 至少需要一个 action。",
            details={"field": "actions"},
        )
    names = [action.name for action in manifest.actions]
    if len(names) != len(set(names)):
        raise KnowledgeAssetRepositoryError(
            "VALIDATION_ERROR",
            "Manifest action 名称不能重复。",
            details={"field": "actions"},
        )
    required = set(manifest.schema.required)
    properties = set(manifest.schema.properties)
    if not required <= properties:
        raise KnowledgeAssetRepositoryError(
            "VALIDATION_ERROR",
            "Manifest required 字段必须存在于 properties。",
            details={"field": "schema.required"},
        )
