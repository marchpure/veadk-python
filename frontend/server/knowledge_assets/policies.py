"""Server-owned policies for Skill Draft and Manifest writes."""

from __future__ import annotations

from .contracts import SkillManifest
from .repository import KnowledgeAssetRepositoryError


def validate_manifest_policy(manifest: SkillManifest) -> None:
    if not manifest.spec.contract.operations:
        raise KnowledgeAssetRepositoryError(
            "VALIDATION_ERROR",
            "SkillManifest 至少需要一个 typed operation。",
            details={"field": "spec.contract.operations"},
        )
    names = [operation.name for operation in manifest.spec.contract.operations]
    if len(names) != len(set(names)):
        raise KnowledgeAssetRepositoryError(
            "VALIDATION_ERROR",
            "SkillManifest operation 名称不能重复。",
            details={"field": "spec.contract.operations"},
        )
    if manifest.metadata.id == "":
        raise KnowledgeAssetRepositoryError(
            "VALIDATION_ERROR",
            "SkillManifest metadata.id 不能为空。",
            details={"field": "metadata.id"},
        )
