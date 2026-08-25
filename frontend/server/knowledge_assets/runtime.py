"""Runtime composition for the real Knowledge Asset Studio BFF."""

from __future__ import annotations

import os
import asyncio
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request

from .application import KnowledgeAssetApplication
from .postgres_repository import PostgresKnowledgeAssetRepository
from .repository import SqliteKnowledgeAssetRepository
from .routes import mount_knowledge_asset_routes
from .sources_golden import SourceGoldenApplication
from frontend.server.knowledge_domains import mount_domain_routes
from frontend.server.knowledge_domains.service import DomainService
from .contract_data import SkillDraftRevision
from .contracts import (
    AnalysisKindSpec,
    CompatibilityTargets,
    GoldenAssetRevision,
    KnowledgeKindSpec,
    OwnerRef,
    PermissionRef,
    SchemaRef,
    SemanticKindSpec,
    SkillContract,
    SkillDependencies,
    SkillManifest,
    SkillMetadata,
    SkillOperation,
    SkillDraft,
    SkillSpec,
    GraphOntologyKindSpec,
    MonitoringKindSpec,
    StorageRef,
    now_iso,
)
from .kind_runtime import (
    ContentAddressedStore,
    ExecutionBudget,
    KindExecutionRequest,
    KindRuntime,
)
from .kind_runtime.dashboard_artifacts import (
    DashboardArtifactRequest,
    DashboardBuildPlan,
    DashboardChartPlan,
    DashboardInsightPlan,
    DashboardKpiPlan,
    DashboardTablePlan,
    generate_dashboard_artifact,
)
from frontend.server.skill_authoring.models import (
    Worker3ExecutionAccepted,
    Worker3ExecutionRequest,
)
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
            schemas.update(
                {item: {"source": "W1 persisted MCP schema"} for item in allowlist}
            )
        return McpToolBundle(
            tools=tuple(toolsets),
            schemas=schemas,
            credentialed=True,
        )


class _MainWorker3Executor:
    """Compose W2's typed execution request with the frozen W3 runtime."""

    def __init__(
        self,
        *,
        repository,
        source_golden: SourceGoldenApplication,
        artifact_root: Path,
    ) -> None:
        self._repository = repository
        self._source_golden = source_golden
        self._artifact_root = artifact_root
        self._store = ContentAddressedStore(artifact_root.parent / "kind-runtime")
        self._runtime = KindRuntime(self._store)

    async def request_execution(self, request: Worker3ExecutionRequest):
        if request.draft_manifest is None or request.build_plan is None:
            return Worker3ExecutionAccepted(
                execution_id=request.operation_id,
                state="credential_blocked",
                reason="W2 execution request lacks its typed DraftManifest/BuildPlan.",
            )
        try:
            context = self._source_context(request)
            golden_records = [
                self._source_golden.golden_revision(context, ref.revision)
                for ref in request.data_refs
                if ref.kind == "golden_asset"
            ]
            if not golden_records:
                return Worker3ExecutionAccepted(
                    execution_id=request.operation_id,
                    state="credential_blocked",
                    reason="No authorized Golden revision was pinned for execution.",
                )
            contents = {
                record.id: self._source_golden.golden_asset_content(
                    context, record.id
                ).decode("utf-8")
                for record in golden_records
            }
            manifest = _canonical_manifest(request)
            self._repository.sync_authoring_draft(
                draft=SkillDraft(
                    id=request.draft_id,
                    workspace_id=request.workspace_id,
                    name=manifest.metadata.display_name,
                    description=manifest.metadata.description,
                    revision=request.draft_revision,
                    created_at=now_iso(),
                    updated_at=now_iso(),
                    manifest=manifest,
                ),
                status="running",
            )
            canonical_revisions = [
                _canonical_golden(record) for record in golden_records
            ]
            draft_revision = SkillDraftRevision(
                id=f"{request.draft_id}:{request.draft_revision}",
                skill_id=request.draft_id,
                revision=request.draft_revision,
                manifest=manifest,
                source_revision_refs=[
                    item.lineage.source_revision_id for item in golden_records
                ],
                golden_asset_revision_refs=[item.id for item in golden_records],
                status="running",
                created_at=now_iso(),
            )
            execution = await asyncio.to_thread(
                self._runtime.execute,
                KindExecutionRequest(
                    draft_revision=draft_revision,
                    caller_id=request.caller_id,
                    workspace_id=request.workspace_id,
                    golden_asset_revisions=canonical_revisions,
                    golden_asset_contents=contents,
                    data_access_revision_refs=draft_revision.source_revision_refs,
                    budget=ExecutionBudget(
                        max_steps=request.budget.max_steps,
                        max_bytes=10_000_000,
                        timeout_ms=min(request.budget.timeout_ms, 300_000),
                    ),
                    freshness_at=golden_records[0].freshness_at,
                    idempotency_key=request.operation_id,
                    trace_id=request.trace_id or request.operation_id,
                    now=now_iso(),
                ),
            )
            if execution.skill_result is not None:
                self._repository.save_skill_result(execution.skill_result)
            artifact = None
            if execution.status == "succeeded" and request.skill_kind == "analysis":
                artifact = await asyncio.to_thread(
                    self._build_dashboard,
                    request,
                    manifest,
                    canonical_revisions[0],
                    contents[golden_records[0].id],
                )
            view_revision = execution.skill_view_revision
            if view_revision is not None and artifact is not None:
                dashboard_html = Path(artifact.index_html_path).read_bytes()
                dashboard_ref = self._store.write_bytes(
                    "views",
                    dashboard_html,
                    media_type="text/html",
                    suffix=".html",
                )
                public_uri = (
                    f"/api/knowledge-assets/v1/workspaces/{request.workspace_id}"
                    f"/skill-view-revisions/{view_revision.id}"
                    f"/artifacts/{dashboard_ref.sha256}"
                )
                view_revision = view_revision.model_copy(
                    update={
                        "result_ref": dashboard_ref.model_copy(
                            update={"uri": public_uri}
                        )
                    }
                )
                execution = execution.model_copy(
                    update={"skill_view_revision": view_revision}
                )
            elif view_revision is not None and view_revision.result_ref is not None:
                public_uri = (
                    f"/api/knowledge-assets/v1/workspaces/{request.workspace_id}"
                    f"/skill-view-revisions/{view_revision.id}"
                    f"/artifacts/{view_revision.result_ref.sha256}"
                )
                view_revision = view_revision.model_copy(
                    update={
                        "result_ref": view_revision.result_ref.model_copy(
                            update={"uri": public_uri}
                        )
                    }
                )
                execution = execution.model_copy(
                    update={"skill_view_revision": view_revision}
                )
            if view_revision is not None:
                self._repository.save_skill_view_revision(view_revision)
            if execution.status == "succeeded":
                self._repository.update_skill_draft_revision_status(
                    request.draft_id, request.draft_revision, "ready_for_evaluation"
                )
            return Worker3ExecutionAccepted(
                execution_id=execution.operation_id,
                state="accepted" if execution.status == "succeeded" else "queued",
                reason=execution.message,
                artifact_result=(
                    artifact.model_dump(mode="json", by_alias=True)
                    if artifact is not None
                    else None
                ),
                execution_result=execution.model_dump(mode="json", by_alias=True),
            )
        except Exception as error:
            return Worker3ExecutionAccepted(
                execution_id=request.operation_id,
                state="failed",
                reason=f"Worker 3 execution failed closed: {error}",
            )

    @staticmethod
    def _source_context(request: Worker3ExecutionRequest):
        from .sources_golden import AccessContext

        return AccessContext(
            workspace_id=request.workspace_id,
            principal_id=request.caller_id,
            role="editor",
        )

    def _build_dashboard(
        self,
        request: Worker3ExecutionRequest,
        manifest: SkillManifest,
        golden: GoldenAssetRevision,
        content: str,
    ):
        plan = request.build_plan
        selected = list(plan.query_plan.selected_fields) if plan.query_plan else []
        metric = (
            (plan.metrics or tuple(selected[1:]))[0]
            if (plan.metrics or selected[1:])
            else "value"
        )
        dimension = (
            (plan.dimensions or tuple(selected[:1]))[0]
            if (plan.dimensions or selected[:1])
            else "label"
        )
        fields = list(dict.fromkeys([*selected, dimension, metric]))
        dashboard_plan = DashboardBuildPlan(
            build_plan_id=plan.plan_id,
            user_goal=plan.purpose,
            title=manifest.metadata.display_name,
            required_golden_revision_id=golden.id,
            data_query_ref=plan.query_plan.source_revision
            if plan.query_plan
            else golden.id,
            invocation_ref=f"invocation://{request.operation_id}",
            kpis=[
                DashboardKpiPlan(
                    key=metric,
                    label=metric,
                    field=metric,
                    aggregation="avg",
                    unit="",
                )
            ],
            chart=DashboardChartPlan(
                title=manifest.metadata.display_name,
                x_field=dimension,
                y_field=metric,
                aggregation="avg",
                chart_type="bar",
            ),
            table=DashboardTablePlan(fields=fields[:24]),
            insights=[DashboardInsightPlan(template=plan.purpose)],
            layout=["kpis", "chart", "table", "insights"],
        )
        return generate_dashboard_artifact(
            DashboardArtifactRequest(
                build_plan=dashboard_plan,
                skill_manifest=manifest,
                golden_asset_revision=golden,
                golden_asset_content=content,
                workspace_root=str(self._artifact_root),
                workspace_id=request.workspace_id,
                caller_id=request.caller_id,
                now=now_iso(),
                artifact_id=f"dashboard-{request.draft_id}-{request.draft_revision}",
            )
        )


def _canonical_golden(record) -> GoldenAssetRevision:
    storage = StorageRef(
        uri=record.storage_ref.uri,
        kind="table",
        sha256=record.storage_ref.sha256,
        media_type=record.storage_ref.media_type,
        bytes=record.storage_ref.bytes,
    )
    return GoldenAssetRevision(
        id=record.id,
        asset_kind="dataset",
        revision=record.revision,
        schema_ref=SchemaRef(
            uri=f"schema://golden/{record.id}",
            version="1",
            sha256=record.schema_digest,
        ),
        storage_ref=storage,
        source_revision_refs=[record.lineage.source_revision_id],
        recipe_ref=record.lineage.recipe_id,
        quality_run_ref=record.lineage.profile_run_id,
        owner=OwnerRef(
            workspace_id=record.owner.workspace_id,
            principal_id=record.owner.principal_id,
        ),
        permissions_ref=PermissionRef(
            uri=f"permission://golden/{record.id}",
            version=str(record.permissions.version),
        ),
        lineage_digest=record.lineage.lineage_digest,
        freshness_at=record.freshness_at,
        last_good=record.last_good,
    )


def _canonical_manifest(request: Worker3ExecutionRequest) -> SkillManifest:
    draft = request.draft_manifest
    assert draft is not None
    plan = request.build_plan
    assert plan is not None
    digest = hashlib.sha256(
        json.dumps(plan.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    schema = SchemaRef(
        uri=f"schema://skill/{request.draft_id}", version="1", sha256=digest
    )
    kind = plan.intent.value
    if kind == "analysis":
        spec = AnalysisKindSpec(
            question=plan.purpose,
            query_plan_ref=(
                f"query-plan://readonly/{plan.query_plan.selected_fields[1]}/"
                f"{plan.query_plan.selected_fields[0]}"
                if plan.query_plan
                else "query-plan://readonly/value/label"
            ),
        )
    elif kind == "semantic":
        spec = SemanticKindSpec(
            metric_refs=list(plan.metrics),
            dimension_refs=list(plan.dimensions),
            relationship_refs=[],
        )
    elif kind == "knowledge":
        spec = KnowledgeKindSpec(
            source_revision_refs=[ref.revision for ref in plan.lineage],
            retrieval_mode="hybrid",
        )
    elif kind == "graph_ontology":
        spec = GraphOntologyKindSpec(
            entity_schema_ref=schema,
            relationship_schema_ref=schema,
        )
    else:
        spec = MonitoringKindSpec(
            metric_refs=list(plan.metrics) or ["value"],
            refresh_schedule_ref="schedule://manual",
            alert_policy_ref="policy://preview",
        )
    return SkillManifest(
        metadata=SkillMetadata(
            id=request.draft_id,
            version="1.0.0",
            display_name=draft.name,
            description=draft.description,
            owner=OwnerRef(
                workspace_id=request.workspace_id,
                principal_id=request.caller_id,
            ),
        ),
        spec=SkillSpec(
            kind=kind,
            contract=SkillContract(
                input_schema_ref=schema,
                output_schema_ref=schema,
                operations=[
                    SkillOperation(
                        name="execute",
                        input_schema_ref=schema,
                        output_schema_ref=schema,
                    )
                ],
            ),
            dependencies=SkillDependencies(
                golden_assets=[ref.revision for ref in plan.lineage]
            ),
            policy_ref=PermissionRef(
                uri=f"policy://workspace/{request.workspace_id}",
                version="1",
            ),
            runtime_ref=f"runtime://{kind}/v1",
            compatibility=CompatibilityTargets(targets=["agentkit"]),
            kind_spec=spec,
        ),
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
    repository_path = (
        Path(repository_path).resolve()
        if not (
            isinstance(repository_path, str)
            and (
                repository_path.startswith("postgres://")
                or repository_path.startswith("postgresql://")
            )
        )
        else repository_path
    )
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
    domain_service = DomainService(runtime_root / "knowledge-domains.sqlite3")
    authoring_gateway = VeADKModelGateway(
        mcp_tools=_MainMcpToolProvider(sources_golden),
        model_name=os.getenv("MODEL_AGENT_MODEL") or os.getenv("MODEL_AGENT_NAME"),
        model_api_base=os.getenv("MODEL_AGENT_API_BASE")
        or os.getenv("OPENAI_BASE_URL"),
        model_api_key=os.getenv("MODEL_AGENT_API_KEY") or os.getenv("OPENAI_API_KEY"),
    )
    application = KnowledgeAssetApplication(
        repository,
        sources_golden=sources_golden,
        domain_resolver=domain_service,
        authoring_model_gateway=authoring_gateway,
        authoring_worker3=_MainWorker3Executor(
            repository=repository,
            source_golden=sources_golden,
            artifact_root=runtime_root / "dashboard-workspaces",
        ),
        artifact_roots=(
            runtime_root / "kind-runtime",
            runtime_root / "dashboard-workspaces",
            Path(".veadk/knowledge-assets/bundles"),
        ),
    )
    mount_knowledge_asset_routes(
        app, application=application, identity_resolver=identity_resolver
    )
    mount_domain_routes(
        app,
        service=domain_service,
        identity_resolver=identity_resolver,
    )
    return app
