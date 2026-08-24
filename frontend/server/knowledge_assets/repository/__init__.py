"""Persistence boundary for Knowledge Asset metadata and operation history."""

from .sqlite import (
    KnowledgeAssetRepository,
    KnowledgeAssetRepositoryError,
    SqliteKnowledgeAssetRepository,
)

__all__ = [
    "KnowledgeAssetRepository",
    "KnowledgeAssetRepositoryError",
    "SqliteKnowledgeAssetRepository",
]
