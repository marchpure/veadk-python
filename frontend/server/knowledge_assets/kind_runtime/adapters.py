"""Internal adapters for Worker 3 kind runtime integration."""

from __future__ import annotations

from pathlib import Path

from frontend.server.knowledge_assets.contracts import GoldenAssetRevision


class LocalGoldenAssetContentAdapter:
    """Read Golden Asset content from the local content-addressed artifact tree."""

    def __init__(self, artifact_root: str | Path = ".veadk/knowledge-assets/artifacts") -> None:
        self.artifact_root = Path(artifact_root)

    def read_many(self, revisions: list[GoldenAssetRevision]) -> dict[str, str]:
        contents: dict[str, str] = {}
        for revision in revisions:
            path = self.artifact_root / revision.storage_ref.sha256
            if path.exists():
                contents[revision.id] = path.read_text(encoding="utf-8")
        return contents
