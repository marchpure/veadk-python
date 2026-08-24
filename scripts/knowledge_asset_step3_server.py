"""Stable local STEP 3 integration server entrypoint."""

from frontend.server.knowledge_assets.runtime import create_app

app = create_app(
    repository_path=".veadk/knowledge-assets-step3.sqlite3",
    identity_resolver=lambda request: ("workspace-step3", "editor"),
)
