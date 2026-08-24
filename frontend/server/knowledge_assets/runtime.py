"""Runtime composition for the real Knowledge Asset Studio BFF."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request

from .application import KnowledgeAssetApplication
from .repository import SqliteKnowledgeAssetRepository
from .routes import mount_knowledge_asset_routes


def create_app(
    *,
    repository_path: str | Path = ".veadk/knowledge-assets.sqlite3",
    identity_resolver: Callable[[Request], tuple[str, str]] | None = None,
) -> FastAPI:
    """Compose the browser BFF with durable local metadata persistence.

    Authentication remains owned by the host Studio. The host supplies the
    authenticated workspace/role resolver; no browser-provided identity is
    trusted by this factory.
    """

    if identity_resolver is None:
        raise ValueError("an authenticated identity_resolver is required")
    app = FastAPI(
        title="Knowledge Asset Studio BFF",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(
            SqliteKnowledgeAssetRepository(repository_path)
        ),
        identity_resolver=identity_resolver,
    )
    return app
