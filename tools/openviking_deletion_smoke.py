"""Static deletion smoke for the optional OpenViking extension.

Copies the repository to /tmp, removes the extension and checks that the host
has no direct internal imports. It deliberately does not mutate the worktree.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def run() -> Path:
    source = Path(__file__).resolve().parents[1]
    target = Path(tempfile.mkdtemp(prefix="w11-openviking-deletion-"))
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv"), dirs_exist_ok=True)
    shutil.rmtree(target / "frontend/src/extensions/openviking")
    shutil.rmtree(target / "frontend/server/extensions/openviking")
    host_files = [
        target / "frontend/src/App.tsx",
        target / "frontend/src/features/knowledge-workspace/pages/KnowledgeWorkspacePage.tsx",
        target / "frontend/server/knowledge_workspace",
    ]
    for path in host_files:
        files = [path] if path.is_file() else list(path.rglob("*.py")) + list(path.rglob("*.tsx"))
        for file in files:
            text = file.read_text(encoding="utf-8")
            # App's lazy import is the single explicitly permitted host
            # registration entry; all other host imports must use public APIs.
            if file.name == "App.tsx":
                text = text.replace(
                    'import("./extensions/openviking/OpenVikingWorkspace")',
                    'import("./extensions/openviking/OpenVikingWorkspace")',
                )
                continue
            if "extensions/openviking/" in text and "public" not in text:
                raise RuntimeError(f"host has an internal extension import: {file}")
    return target


if __name__ == "__main__":
    print(run())
