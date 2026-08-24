"""Content-addressed local object store for Worker 3 runtime outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from frontend.server.knowledge_assets.contracts import StorageRef


class ContentAddressedStore:
    """Store immutable execution payloads by SHA-256.

    This is a local adapter, not a production object store. It gives Main a
    narrow port with the same immutability and digest semantics needed for
    production storage.
    """

    def __init__(self, root: str | Path = ".veadk/knowledge-assets/kind-runtime") -> None:
        self.root = Path(root)

    def write_json(self, category: str, payload: Any) -> StorageRef:
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self.write_bytes(category, content, media_type="application/json", suffix=".json")

    def write_text(self, category: str, text: str, *, media_type: str = "text/plain") -> StorageRef:
        return self.write_bytes(category, text.encode("utf-8"), media_type=media_type, suffix=".txt")

    def write_bytes(
        self,
        category: str,
        content: bytes,
        *,
        media_type: str,
        suffix: str,
    ) -> StorageRef:
        digest = hashlib.sha256(content).hexdigest()
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(content)
        return StorageRef(
            uri=f"local://kind-runtime/{category}/{digest}",
            kind="object" if media_type != "text/html" else "bundle",
            sha256=digest,
            media_type=media_type,
            bytes=len(content),
        )
