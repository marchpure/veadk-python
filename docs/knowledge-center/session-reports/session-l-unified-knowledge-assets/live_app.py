from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from frontend.server.knowledge_assets import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.repository import KnowledgeAssetRepository
from frontend.server.knowledge_assets.service import KnowledgeAssetStore


def create_app() -> FastAPI:
    db_path = Path(
        os.environ.get(
            "SESSION_L_KNOWLEDGE_ASSET_DB",
            "/tmp/session-l-knowledge-assets.db",
        )
    )
    app = FastAPI()
    service = KnowledgeAssetStore(repository=KnowledgeAssetRepository(db_path))
    mount_knowledge_asset_routes(app, service=service)

    @app.get("/web/auth-config")
    async def auth_config() -> dict[str, object]:
        return {"providers": []}

    @app.get("/web/access")
    async def access() -> dict[str, object]:
        return {
            "role": "admin",
            "telemetry": {"userId": "session-l-live", "accountId": "local"},
            "capabilities": {
                "createAgents": True,
                "manageAgents": True,
                "runtimeScope": "all",
            },
        }

    @app.get("/web/ui-config")
    async def ui_config() -> dict[str, object]:
        return {
            "studio": False,
            "version": "session-l-live",
            "provider": "volcengine",
            "defaultView": "chat",
            "agentsSource": "local",
            "branding": {"title": "AgentKit Studio", "logoUrl": ""},
            "features": {
                "newChat": True,
                "search": True,
                "skillCenter": True,
                "history": True,
                "addAgent": True,
                "manageAgents": True,
                "agentUsage": False,
                "addAgentkit": True,
            },
        }

    @app.get("/web/runtime-config")
    async def runtime_config() -> dict[str, object]:
        return {"available": False}

    @app.get("/list-apps")
    async def list_apps() -> list[str]:
        return []

    @app.get("/apps")
    async def apps() -> list[object]:
        return []

    return app


app = create_app()
