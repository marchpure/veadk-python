"""Runtime composition for the real Knowledge Asset Studio BFF."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request

from .application import KnowledgeAssetApplication
from .postgres_repository import PostgresKnowledgeAssetRepository
from .repository import SqliteKnowledgeAssetRepository
from .routes import mount_knowledge_asset_routes
from .sources_golden import SourceGoldenApplication
from frontend.server.skill_authoring.ports import (
    McpToolBundle,
    VeADKModelGateway,
)


class _MainMcpToolProvider:
    """Expose only persisted, authorized W1 MCP configs to the W2 gateway."""

    def __init__(self, source_golden: SourceGoldenApplication) -> None:
        self._source_golden = source_golden

    async def tools_for(self, context) -> McpToolBundle:
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            StdioConnectionParams,
            StdioServerParameters,
        )
        from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
        from .sources_golden import AccessContext

        revision_ids = [
            ref.revision
            for ref in context.envelope.resource_refs
            if ref.kind == "golden_asset"
        ]
        configurations = self._source_golden.mcp_tool_configurations(
            AccessContext(
                workspace_id=context.envelope.workspace_id,
                principal_id=context.envelope.caller_id,
                role="editor",
            ),
            revision_ids,
        )
        if not configurations:
            return McpToolBundle(tools=(), schemas={}, credentialed=False)
        toolsets = []
        schemas: dict[str, object] = {}
        for configuration in configurations:
            env = configuration.get("env")
            if env is not None and (
                not isinstance(env, dict)
                or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in env.items()
                )
            ):
                raise RuntimeError("MCP profile env must be a string mapping")
            args = configuration["args"]
            if not all(isinstance(item, str) for item in args):
                raise RuntimeError("MCP profile args must be strings")
            allowlist = configuration.get("toolAllowlist", [])
            if not isinstance(allowlist, list) or not all(
                isinstance(item, str) for item in allowlist
            ):
                raise RuntimeError("MCP profile toolAllowlist must be strings")
            toolsets.append(
                McpToolset(
                    connection_params=StdioConnectionParams(
                        server_params=StdioServerParameters(
                            command=configuration["command"],
                            args=args,
                            cwd=configuration.get("cwd"),
                            env=env,
                        )
                    ),
                    tool_filter=allowlist,
                )
            )
            schemas.update({item: {"source": "W1 persisted MCP schema"} for item in allowlist})
        return McpToolBundle(
            tools=tuple(toolsets),
            schemas=schemas,
            credentialed=True,
        )


def create_app(
    *,
    repository_path: str | Path = ".veadk/knowledge-assets.sqlite3",
    identity_resolver: Callable[[Request], tuple[str, str]] | None = None,
    mcp_profiles: dict[str, dict[str, object]] | None = None,
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
    repository_path = Path(repository_path).resolve() if not (
        isinstance(repository_path, str)
        and (
            repository_path.startswith("postgres://")
            or repository_path.startswith("postgresql://")
        )
    ) else repository_path
    runtime_root = (
        Path(repository_path).parent / "sources-golden"
        if isinstance(repository_path, Path)
        else Path(".veadk/knowledge-assets/sources-golden").resolve()
    )
    repository = (
        PostgresKnowledgeAssetRepository(repository_path)
        if isinstance(repository_path, str)
        and (
            repository_path.startswith("postgres://")
            or repository_path.startswith("postgresql://")
        )
        else SqliteKnowledgeAssetRepository(repository_path)
    )
    sources_golden = SourceGoldenApplication(
        database_path=runtime_root / "sources-golden.sqlite3",
        artifact_root=runtime_root / "artifacts",
        source_root=runtime_root / "sources",
        mcp_profiles=mcp_profiles,
    )
    authoring_gateway = VeADKModelGateway(
        mcp_tools=_MainMcpToolProvider(sources_golden),
        model_name=os.getenv("MODEL_AGENT_MODEL") or os.getenv("MODEL_AGENT_NAME"),
        model_api_base=os.getenv("MODEL_AGENT_API_BASE") or os.getenv("OPENAI_BASE_URL"),
        model_api_key=os.getenv("MODEL_AGENT_API_KEY") or os.getenv("OPENAI_API_KEY"),
    )
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(
            repository,
            sources_golden=sources_golden,
            authoring_model_gateway=authoring_gateway,
        ),
        identity_resolver=identity_resolver,
    )
    return app
