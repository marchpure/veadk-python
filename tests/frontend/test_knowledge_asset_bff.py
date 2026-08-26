from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from contextlib import nullcontext
from threading import Lock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.application import _ImmutableResourceResolver
from frontend.server.knowledge_assets.contracts import (
    EvaluationRun,
    PolicyGateResult,
    SkillResult,
    SkillViewManifest,
    SkillViewRevision,
    ViewIntent,
    ChartViewModel,
    ChartSeries,
    LegacySkillManifestInput,
    SkillManifest,
    StorageRef,
    SchemaRef,
    adapt_legacy_manifest,
)
from frontend.server.knowledge_assets.ports import (
    ArtifactPutRequest,
    FailClosedArtifactStore,
    NotConfiguredAdapterError,
)
from frontend.server.knowledge_assets.repository import (
    SqliteKnowledgeAssetRepository,
)
from frontend.server.knowledge_assets.routes import mount_knowledge_asset_routes
from frontend.server.knowledge_assets.sources_golden import (
    AccessContext,
    SourceGoldenApplication,
)
from frontend.server.knowledge_assets.workers import JobFramework, JobLeaseError
from frontend.server.knowledge_domains.service import DomainService
from frontend.server.skill_authoring.models import (
    AgentAnswer,
    AgentIntent,
    AgentRuntimeEvent,
    AuthoringEvent,
    AuthoringOperation,
    BuildPlan,
    ContextEnvelope,
    DraftManifest,
    DraftRevision,
    FreshnessPolicy,
    KnowledgeKindSpec,
    OutputContract,
    ResourceRef as AuthoringResourceRef,
    ResolvedResource,
    Scope,
    SkillKind,
    SkillAuthoringError,
)
from frontend.server.skill_authoring.ports import (
    InMemoryResourceResolver,
    JsonFileAuthoringRepository,
    LocalPlanningHarness,
    NoopWorker3Executor,
)
from frontend.server.knowledge_assets.authoring_repository import (
    PostgresAuthoringRepository,
    SqliteAuthoringRepository,
)


def build_client(
    sources_golden: SourceGoldenApplication | None = None,
    mcp_profiles: dict[str, dict[str, object]] | None = None,
) -> TestClient:
    if sources_golden is not None and mcp_profiles:
        sources_golden._mcp_profiles.update(mcp_profiles)
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(
            SqliteKnowledgeAssetRepository(":memory:"),
            sources_golden=sources_golden,
        ),
        identity_resolver=lambda request: ("workspace-test", "editor"),
    )
    return TestClient(app)


def test_authoring_default_model_budget_allows_real_runner_tool_turn(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("MODEL_AGENT_TIMEOUT_MS", raising=False)
    application = KnowledgeAssetApplication(SqliteKnowledgeAssetRepository(":memory:"))

    envelope = application._authoring_envelope(
        {"prompt": "请创建一个分析 Skill"},
        caller_id="workspace-test",
        workspace_id="workspace-test",
        request_id="req_budget",
    )

    assert envelope.budget.timeout_ms == 120_000


@pytest.mark.asyncio
async def test_postgres_authoring_event_sequence_is_allocated_under_operation_lock():
    class Cursor:
        def __init__(self):
            self.statements: list[tuple[str, tuple[object, ...]]] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement, parameters):
            self.statements.append((" ".join(statement.split()), parameters))

        def fetchone(self):
            return {"latest": 4}

    class Connection:
        def __init__(self):
            self.cursor_value = Cursor()
            self.transactions = 0

        def cursor(self):
            return self.cursor_value

        def transaction(self):
            self.transactions += 1
            return nullcontext()

    connection = Connection()
    repository = PostgresAuthoringRepository(connection, Lock())

    await repository.save_event(
        AuthoringEvent(
            operation_id="op_pg",
            event_type="answer.delta",
            sequence=1,
            payload={"text": "hello"},
        )
    )

    assert connection.transactions == 1
    assert "pg_advisory_xact_lock" in connection.cursor_value.statements[0][0]
    insert = connection.cursor_value.statements[-1]
    assert insert[1][2] == 5
    assert json.loads(insert[1][3])["sequence"] == 5


@pytest.mark.asyncio
async def test_sqlite_generation_lease_survives_second_repository_instance(
    tmp_path: Path,
):
    database = tmp_path / "authoring.sqlite3"
    first_assets = SqliteKnowledgeAssetRepository(database)
    second_assets = SqliteKnowledgeAssetRepository(database)
    first = SqliteAuthoringRepository(first_assets._connection, first_assets._lock)
    second = SqliteAuthoringRepository(second_assets._connection, second_assets._lock)
    operation = AuthoringOperation(
        operation_id="op_durable_generation_1",
        operation_type="answer",
        status="queued",
        caller_id="user_1",
        workspace_id="workspace_1",
        conversation_id="conversation_1",
        trace_id="trace_1",
    )
    lane = "workspace_1\0user_1\0conversation_1"

    claimed = await first.claim_generation(lane, operation, idempotency_key="send-1")
    assert claimed == (operation.operation_id, True, "claimed")

    competing = operation.model_copy(update={"operation_id": "op_durable_generation_2"})
    assert await second.claim_generation(lane, competing, idempotency_key="send-2") == (
        operation.operation_id,
        False,
        "active",
    )

    await first.save_operation(operation.model_copy(update={"status": "succeeded"}))
    assert await second.claim_generation(lane, competing, idempotency_key="send-2") == (
        competing.operation_id,
        True,
        "claimed",
    )
    await second.release_generation(competing.operation_id)


def test_source_golden_commands_run_real_stdio_mcp_chain(tmp_path: Path) -> None:
    data_path = tmp_path / "metrics.json"
    data_path.write_text(
        json.dumps(
            [
                {"service": "edge", "cpuPercent": 21.0},
                {"service": "worker", "cpuPercent": 48.0},
            ]
        ),
        encoding="utf-8",
    )
    server = (
        Path(__file__).parents[1]
        / "fixtures"
        / "knowledge_workspace_v21141"
        / "mcp_sdk_infrastructure_server.py"
    ).resolve()
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
        mcp_profiles={
            "infra-local": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(server)],
                "env": {"MCP_FIXTURE_DATA_PATH": str(data_path)},
                "cwd": str(tmp_path),
                "startupTimeoutSeconds": 5,
                "callTimeoutSeconds": 5,
                "toolAllowlist": ["infrastructure.metrics"],
                "outputBytes": 1000000,
            }
        },
    )
    client = build_client(source_golden)
    connection = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "source-golden.connection.create",
            "payload": {
                "connectorKey": "mcp_custom",
                "displayName": "Infrastructure MCP",
                "scope": "team",
                "mcpProfileId": "infra-local",
                "toolAllowlist": ["infrastructure.metrics"],
            },
        },
        headers={
            "X-Request-ID": "bff-mcp-connection",
            "Idempotency-Key": "bff-mcp-connection",
        },
    )
    assert connection.status_code == 200
    connection_payload = connection.json()
    assert connection_payload["accepted"] is True
    connection_result = connection_payload["result"]
    for forbidden in ("configuration", "secretRef", "command", "args", "env", "cwd"):
        assert forbidden not in connection_result["connection"]
    assert connection_result["connection"]["status"] == "ready"
    assert connection_result["discovery"]["resources"][0]["name"] == (
        "infrastructure.metrics"
    )

    resource_id = connection_result["discovery"]["resources"][0]["id"]
    ingested = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "source-golden.ingest",
            "payload": {
                "connectionId": connection_result["connection"]["id"],
                "resourceId": resource_id,
                "recipeOperations": ["trim"],
                "toolArguments": {"service": "all"},
            },
        },
        headers={
            "X-Request-ID": "bff-mcp-ingest",
            "Idempotency-Key": "bff-mcp-ingest",
        },
    )
    assert ingested.status_code == 200
    ingest_result = ingested.json()["result"]
    assert ingest_result["sourceRevision"]["sourceType"] == "mcp"
    assert ingest_result["goldenAssetRevision"]["revision"] == 1
    assert ingest_result["goldenAssetRevision"]["lineage"]["toolArguments"] == {
        "service": "all"
    }
    bootstrap = client.get(
        "/api/knowledge-assets/v1/bootstrap",
        headers={"X-Request-ID": "bff-mcp-bootstrap"},
    )
    assert bootstrap.status_code == 200
    public_connection = next(
        item
        for item in bootstrap.json()["connections"]
        if item["id"] == connection_result["connection"]["id"]
    )
    assert public_connection["displayName"] == "Infrastructure MCP"
    assert public_connection["connectorKey"] == "mcp_custom"
    assert public_connection["status"] == "ready"
    assert public_connection["discoveredResources"]
    assert public_connection["goldenRevisionIds"] == [
        ingest_result["goldenAssetRevision"]["id"]
    ]
    for forbidden in ("configuration", "secretRef", "command", "args", "env", "cwd"):
        assert forbidden not in public_connection


def test_authoring_failure_returns_server_error_envelope(tmp_path: Path) -> None:
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
    )
    client = build_client(source_golden)
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-authoring.start",
            "payload": {
                "prompt": "hello",
                "resourceRefs": [
                    {
                        "kind": "golden_asset",
                        "object_id": "missing-asset",
                        "revision": "missing-revision",
                        "scope": "personal",
                    }
                ],
                "fixedRevisions": ["missing-revision"],
                "requestedKind": "knowledge",
            },
        },
        headers={
            "X-Request-ID": "authoring-error-envelope",
            "Idempotency-Key": "authoring-error-envelope",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert payload["result"]["status"] == "failed"
    assert payload["result"]["error"]["code"] == "GOLDEN_REVISION_NOT_FOUND"
    assert payload["result"]["error"]["message"] == (
        "Golden revision does not exist in the authenticated workspace."
    )


def test_authoring_patch_command_creates_idempotent_new_draft_revision(
    tmp_path: Path,
) -> None:
    ref = AuthoringResourceRef(
        kind="golden_asset",
        object_id="asset-orders",
        revision="golden-orders-r1",
        scope=Scope.PERSONAL,
    )
    resolver = InMemoryResourceResolver(
        [
            ResolvedResource(
                ref=ref,
                display_name="Orders",
                provider_revision=ref.revision,
                schema_digest="schema-orders-r1",
                capabilities=("read",),
                semantic_fields=("order_id", "amount"),
            )
        ]
    )
    resolver.grant("workspace-test", "workspace-test", ref)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources.sqlite3",
        artifact_root=tmp_path / "source-artifacts",
        source_root=tmp_path,
    )
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(
            repository,
            sources_golden=source_golden,
            authoring_resolver=resolver,
            authoring_model_gateway=LocalPlanningHarness(),
            authoring_worker3=NoopWorker3Executor(),
        ),
        identity_resolver=lambda _request: ("workspace-test", "editor"),
    )
    client = TestClient(app)
    start = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-authoring.start",
            "payload": {
                "prompt": "[analysis] summarize orders",
                "resourceRefs": [ref.model_dump(mode="json")],
                "fixedRevisions": [ref.revision],
                "requestedKind": "analysis",
            },
        },
        headers={
            "X-Request-ID": "start-patch-test",
            "Idempotency-Key": "start-patch-test",
        },
    )
    assert start.status_code == 200
    original = start.json()["result"]["draft"]
    request = {
        "command": "skill-authoring.patch",
        "payload": {
            "draftId": original["draft_id"],
            "baseRevision": original["revision"],
            "patch": {"patchType": "set_title", "title": "Updated orders"},
        },
    }
    headers = {
        "X-Request-ID": "patch-test",
        "Idempotency-Key": "patch-test",
    }
    first = client.post(
        "/api/knowledge-assets/v1/commands", json=request, headers=headers
    )
    replay = client.post(
        "/api/knowledge-assets/v1/commands", json=request, headers=headers
    )

    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert first.json()["result"]["draft"]["revision"] == 2
    assert first.json()["result"]["draft"]["manifest"]["name"] == "Updated orders"
    assert first.json()["result"]["patch"]["status"] == "accepted"
    assert replay.json()["operationId"] == first.json()["operationId"]
    assert replay.json()["result"]["draft"]["revision"] == 2


def test_immutable_html_route_is_authorized_and_integrity_checked(
    tmp_path: Path,
) -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    artifact_root = tmp_path / "kind-runtime"
    content = b"<!doctype html><article><h1>Live data</h1></article>"
    digest = __import__("hashlib").sha256(content).hexdigest()
    path = artifact_root / "views" / f"{digest}.html"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    draft = repository.create_skill_draft(
        workspace_id="workspace-test",
        name="Live dashboard",
        description="",
        source_refs=[],
        request_id="artifact-draft",
        idempotency_key="artifact-draft",
    )[0]
    view = SkillViewRevision(
        id="view-live",
        skill_revision_id=f"{draft.id}:1",
        revision=1,
        manifest=SkillViewManifest(
            id="manifest-live",
            skill_revision_id=f"{draft.id}:1",
            renderer_ref="renderer://dashboard/v1",
            view_model_schema_ref=SchemaRef(
                uri="local://schema/live",
                version="1",
                sha256="0" * 64,
            ),
            allowed_components=["DashboardView"],
        ),
        intent=ViewIntent(
            id="intent-live",
            skill_id=draft.id,
            skill_revision=1,
            template="dashboard",
            purpose="overview",
            result_ref="local://result/live",
        ),
        view_model={
            "template": "dashboard",
            "fields": [],
            "kpis": [],
            "rows": [],
            "dataRef": {
                "uri": "local://data/live",
                "kind": "object",
                "sha256": "1" * 64,
                "mediaType": "application/json",
                "bytes": 1,
            },
        },
        result_ref=StorageRef(
            uri=(
                "/api/knowledge-assets/v1/workspaces/workspace-test/"
                f"skill-view-revisions/view-live/artifacts/{digest}"
            ),
            kind="bundle",
            sha256=digest,
            media_type="text/html",
            bytes=len(content),
        ),
        created_at="2026-08-25T00:00:00Z",
    )
    repository.save_skill_view_revision(view)
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(
            repository, artifact_roots=(artifact_root,)
        ),
        identity_resolver=lambda request: (
            request.headers.get("X-Test-Workspace", "workspace-test"),
            "editor",
        ),
    )
    client = TestClient(app)
    url = (
        "/api/knowledge-assets/v1/workspaces/workspace-test/"
        f"skill-view-revisions/view-live/artifacts/{digest}"
    )
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["etag"] == f'"sha256:{digest}"'
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert (
        client.get(url, headers={"X-Test-Workspace": "workspace-other"}).status_code
        == 404
    )
    path.write_bytes(content + b"corrupt")
    assert client.get(url).status_code == 500


@pytest.mark.asyncio
async def test_mixed_context_resolves_exact_authorized_revisions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "metrics.csv"
    source.write_text("service,cpu\nedge,21\n", encoding="utf-8")
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources.sqlite3",
        artifact_root=tmp_path / "source-artifacts",
        source_root=tmp_path,
    )
    access = AccessContext(
        workspace_id="workspace-test",
        principal_id="workspace-test",
        role="editor",
    )
    connection = source_golden.create_connection(
        access,
        connector_key="csv",
        display_name="Metrics",
        scope="personal",
        configuration={"sourceRef": "metrics.csv"},
        secret_ref=None,
        idempotency_key="mixed-source",
        trace_id="mixed-source",
    )
    ingested = source_golden.ingest(
        access,
        connection_id=connection.connection.id,
        resource_id=connection.connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="mixed-ingest",
        trace_id="mixed-ingest",
    )
    repository = SqliteKnowledgeAssetRepository(":memory:")
    draft = repository.create_skill_draft(
        workspace_id="workspace-test",
        name="Mixed context",
        description="",
        source_refs=[],
        request_id="mixed-draft",
        idempotency_key="mixed-draft",
    )[0]
    artifact_digest = "a" * 64
    view = SkillViewRevision(
        id="view-mixed",
        skill_revision_id=f"{draft.id}:1",
        revision=1,
        manifest=SkillViewManifest(
            id="manifest-mixed",
            skill_revision_id=f"{draft.id}:1",
            renderer_ref="renderer://dashboard/v1",
            view_model_schema_ref=SchemaRef(
                uri="schema://mixed", version="1", sha256="b" * 64
            ),
            allowed_components=["DashboardView"],
        ),
        intent=ViewIntent(
            id="intent-mixed",
            skill_id=draft.id,
            skill_revision=1,
            template="dashboard",
            purpose="overview",
            result_ref="local://mixed",
        ),
        view_model={
            "template": "dashboard",
            "fields": [],
            "kpis": [],
            "rows": [],
            "dataRef": {
                "uri": "local://mixed",
                "kind": "object",
                "sha256": "c" * 64,
                "mediaType": "application/json",
                "bytes": 1,
            },
        },
        result_ref=StorageRef(
            uri="/api/knowledge-assets/v1/mixed",
            kind="bundle",
            sha256=artifact_digest,
            media_type="text/html",
            bytes=1,
        ),
        created_at="2026-08-25T00:00:00Z",
    )
    repository.save_skill_view_revision(view)
    domains = DomainService(tmp_path / "domains.sqlite3")
    knowledge = domains.create_knowledge_base(
        "workspace-test", "Policies", "", "personal"
    )["contextRef"]
    uploaded = domains.add_source(
        knowledge["objectId"],
        filename="policy.md",
        title="Policy",
        description="",
        tags="",
        media_type="text/markdown",
        content=b"# Policy\n\nUse exact revisions.",
        chunk_strategy="heading",
    )
    domain_document = uploaded["documentContextRef"]
    semantic = domains.save_semantic(
        "semantic-sales",
        "model Sales {\n dimension region : string\n}",
        0,
        workspace_id="workspace-test",
    )["contextRef"]
    graph = domains.mutate_graph(
        "graph-sales",
        {
            "operation": "upsert_entity",
            "entity": {"id": "customer", "type": "Customer"},
        },
        "workspace-test",
    )["contextRef"]
    refs = (
        AuthoringResourceRef(
            kind="document",
            object_id=ingested.source_revision.resource_id,
            revision=ingested.source_revision.id,
            scope=Scope.PERSONAL,
        ),
        AuthoringResourceRef(
            kind="golden_asset",
            object_id=ingested.golden_asset_revision.asset_id,
            revision=ingested.golden_asset_revision.id,
            scope=Scope.PERSONAL,
        ),
        AuthoringResourceRef(
            kind=domain_document["kind"],
            object_id=domain_document["objectId"],
            revision=domain_document["revision"],
            scope=domain_document["scope"],
        ),
        AuthoringResourceRef(
            kind=knowledge["kind"],
            object_id=knowledge["objectId"],
            revision=knowledge["revision"],
            scope=knowledge["scope"],
        ),
        AuthoringResourceRef(
            kind=semantic["kind"],
            object_id=semantic["objectId"],
            revision=semantic["revision"],
            scope=semantic["scope"],
        ),
        AuthoringResourceRef(
            kind=graph["kind"],
            object_id=graph["objectId"],
            revision=graph["revision"],
            scope=graph["scope"],
        ),
        AuthoringResourceRef(
            kind="skill",
            object_id=draft.id,
            revision=f"{draft.id}:1",
            scope=Scope.PERSONAL,
        ),
        AuthoringResourceRef(
            kind="artifact",
            object_id=view.id,
            revision=view.id,
            scope=Scope.PERSONAL,
        ),
    )
    envelope = ContextEnvelope(
        caller_id="workspace-test",
        workspace_id="workspace-test",
        prompt="Use exact context",
        resource_refs=refs,
        fixed_revisions=tuple(ref.revision for ref in refs),
        current_skill_id=draft.id,
        current_view_id=view.id,
        current_component_id="kpi-revenue",
        comment_ids=("comment-1",),
    )
    resolved = await _ImmutableResourceResolver(
        source_golden, repository, domains
    ).resolve(envelope, refs)
    assert [item.ref for item in resolved.resources] == list(refs)
    assert resolved.context_digest

    mutable = refs[2].model_copy(update={"revision": "latest"})
    with pytest.raises(SkillAuthoringError):
        await _ImmutableResourceResolver(source_golden, repository, domains).resolve(
            envelope.model_copy(
                update={
                    "resource_refs": (mutable,),
                    "fixed_revisions": ("latest",),
                    "current_skill_id": None,
                    "current_view_id": None,
                    "current_component_id": None,
                    "comment_ids": (),
                }
            ),
            (mutable,),
        )

    wrong_scope = refs[2].model_copy(update={"scope": Scope.TEAM})
    with pytest.raises(SkillAuthoringError):
        await _ImmutableResourceResolver(source_golden, repository, domains).resolve(
            envelope.model_copy(
                update={
                    "resource_refs": (wrong_scope,),
                    "fixed_revisions": (wrong_scope.revision,),
                    "current_skill_id": None,
                    "current_view_id": None,
                    "current_component_id": None,
                    "comment_ids": (),
                }
            ),
            (wrong_scope,),
        )


@pytest.mark.asyncio
async def test_immutable_resolver_accepts_owned_authoring_draft_before_main_sync(
    tmp_path: Path,
) -> None:
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources.sqlite3",
        artifact_root=tmp_path / "source-artifacts",
        source_root=tmp_path,
    )
    authoring_repository = JsonFileAuthoringRepository(tmp_path / "authoring.json")
    draft = DraftRevision(
        draft_id="draft-authoring-only",
        revision=1,
        manifest=DraftManifest(
            name="Authoring draft",
            description="Awaiting Worker 3 projection",
            kind=SkillKind.KNOWLEDGE,
            kind_spec=KnowledgeKindSpec(
                citation_intent=("source_revision",),
                retrieval_mode="hybrid",
            ),
            inputs=(),
            outputs=(OutputContract(name="answer", type="answer"),),
            dependencies=(),
            permissions=(),
            freshness=FreshnessPolicy(),
        ),
        plan=BuildPlan(
            plan_id="plan-authoring-only",
            intent=SkillKind.KNOWLEDGE,
            purpose="Verify execution binding.",
            nodes=(
                {"node_id": "resolve_intent", "role": "intent_resolution"},
                {
                    "node_id": "resolve_context",
                    "role": "context_resolution",
                    "depends_on": ("resolve_intent",),
                },
                {
                    "node_id": "worker3_execution",
                    "role": "worker3_execution",
                    "depends_on": ("resolve_context",),
                },
            ),
            outputs=(OutputContract(name="answer", type="answer"),),
            kind_spec=KnowledgeKindSpec(
                citation_intent=("source_revision",),
                retrieval_mode="hybrid",
            ),
            plan_digest="plan-authoring-only",
        ),
        owner_id="workspace-test",
        workspace_id="workspace-test",
        scope=Scope.PERSONAL,
        digest="draft-authoring-only",
    )
    await authoring_repository.save_draft(draft)
    envelope = ContextEnvelope(
        caller_id="workspace-test",
        workspace_id="workspace-test",
        prompt="execute fixed SkillDraft revision",
        current_skill_id=draft.draft_id,
    )

    resolved = await _ImmutableResourceResolver(
        source_golden,
        SqliteKnowledgeAssetRepository(":memory:"),
        authoring_repository=authoring_repository,
    ).resolve(envelope, ())

    assert resolved.envelope.current_skill_id == draft.draft_id


def test_source_golden_mcp_rejects_browser_process_execution_fields(
    tmp_path: Path,
) -> None:
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
    )
    response = build_client(source_golden).post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "source-golden.connection.create",
            "payload": {
                "connectorKey": "mcp_custom",
                "displayName": "Unsafe MCP",
                "mcpProfileId": "not-registered",
                "configuration": {
                    "command": "/bin/sh",
                    "args": ["-c", "true"],
                    "cwd": "/",
                },
            },
        },
        headers={"X-Request-ID": "bff-mcp-unsafe", "Idempotency-Key": "bff-mcp-unsafe"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "MCP_CLIENT_EXECUTION_FIELDS_FORBIDDEN"


def test_authoring_resolves_real_golden_revision_before_model_gate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "metrics.csv"
    source.write_text("service,cpu\nedge,21\nworker,48\n", encoding="utf-8")
    source_golden = SourceGoldenApplication(
        database_path=tmp_path / "sources-golden.sqlite3",
        artifact_root=tmp_path / "artifacts",
        source_root=tmp_path,
    )
    created = source_golden.create_connection(
        AccessContext(
            workspace_id="workspace-test", principal_id="workspace-test", role="editor"
        ),
        connector_key="csv",
        display_name="Infrastructure CSV",
        scope="team",
        configuration={"sourceRef": "metrics.csv"},
        secret_ref=None,
        idempotency_key="authoring-source",
        trace_id="authoring-source-trace",
    )
    ingested = source_golden.ingest(
        AccessContext(
            workspace_id="workspace-test", principal_id="workspace-test", role="editor"
        ),
        connection_id=created.connection.id,
        resource_id=created.connection.discovered_resources[0].id,
        recipe_operations=["trim"],
        idempotency_key="authoring-golden",
        trace_id="authoring-golden-trace",
    )
    client = build_client(source_golden)
    revision = ingested.golden_asset_revision
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-authoring.start",
            "payload": {
                "prompt": "Compare infrastructure CPU by service.",
                "resourceRefs": [
                    {
                        "kind": "golden_asset",
                        "object_id": revision.asset_id,
                        "revision": revision.id,
                        "scope": "team",
                    }
                ],
                "fixedRevisions": [revision.id],
                "requestedKind": "analysis",
            },
        },
        headers={
            "X-Request-ID": "authoring-real-context",
            "Idempotency-Key": "authoring-real-context",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["status"] == "credential_blocked"
    assert payload["result"]["operation"]["context_digest"]
    assert payload["result"]["operation"]["context_digest"] != ""


def test_create_skill_draft_persists_and_replays_projection() -> None:
    client = build_client()
    headers = {
        "X-Request-ID": "request-1",
        "Idempotency-Key": "draft-create-1",
    }
    body = {
        "command": "skill-draft.create",
        "payload": {
            "workspaceId": "workspace-test",
            "name": "Policy Skill",
            "description": "Answer policy questions",
            "sourceRefs": [],
        },
    }

    created = client.post(
        "/api/knowledge-assets/v1/commands", json=body, headers=headers
    )
    assert created.status_code == 200
    result = created.json()
    assert result["accepted"] is True
    assert result["operationId"]
    assert result["result"]["draft"]["viewState"] == "debug"

    operation = client.get(
        f"/api/knowledge-assets/v1/operations/{result['operationId']}",
        headers={"X-Request-ID": "request-2"},
    )
    assert operation.status_code == 200
    assert operation.json()["status"] == "succeeded"
    assert [event["sequence"] for event in operation.json()["events"]] == [1, 2]
    assert operation.json()["events"][-1]["terminal"] is True

    bootstrap = client.get(
        "/api/knowledge-assets/v1/bootstrap",
        headers={"X-Request-ID": "request-3"},
    )
    assert bootstrap.status_code == 200
    assert bootstrap.json()["resources"][0]["id"] == result["result"]["draft"]["id"]

    replay = client.post(
        "/api/knowledge-assets/v1/commands", json=body, headers=headers
    )
    assert replay.status_code == 200
    assert replay.json()["operationId"] == result["operationId"]
    assert replay.json()["result"]["draft"]["id"] == result["result"]["draft"]["id"]


def test_command_union_rejects_unknown_commands_and_extra_payload() -> None:
    client = build_client()
    headers = {
        "X-Request-ID": "request-invalid",
        "Idempotency-Key": "invalid-1",
    }
    unknown = client.post(
        "/api/knowledge-assets/v1/commands",
        json={"command": "workspace.mutation", "payload": {}},
        headers=headers,
    )
    assert unknown.status_code == 422
    assert unknown.headers["content-type"].startswith("application/problem+json")
    assert unknown.json()["code"] == "VALIDATION_ERROR"
    assert (
        "does not match any of the expected tags"
        in unknown.json()["details"]["validation"]
    )

    extra = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.create",
            "payload": {
                "workspaceId": "workspace-test",
                "name": "Policy Skill",
                "description": "",
                "sourceRefs": [],
                "unknown": True,
            },
        },
        headers=headers,
    )
    assert extra.status_code == 422
    assert extra.headers["content-type"].startswith("application/problem+json")
    assert extra.json()["code"] == "VALIDATION_ERROR"
    assert "unknown" in extra.json()["details"]["validation"]


def test_skill_authoring_start_is_typed_and_fail_closed_without_w1() -> None:
    client = build_client()
    headers = {
        "X-Request-ID": "authoring-request-1",
        "Idempotency-Key": "authoring-start-1",
    }
    body = {
        "command": "skill-authoring.start",
        "payload": {
            "prompt": "Compare infrastructure service health by day",
            "requestedKind": "analysis",
        },
    }

    first = client.post("/api/knowledge-assets/v1/commands", json=body, headers=headers)
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["accepted"] is False
    assert first_payload["result"]["resultType"] == "skill-authoring.start"
    assert first_payload["result"]["status"] == "credential_blocked"
    assert first_payload["result"]["operation"]["error_code"] == "credential_blocked"
    assert first_payload["result"]["draft"] is None
    assert [item["event_type"] for item in first_payload["result"]["events"]] == [
        "operation_created",
        "credential_blocked",
    ]

    replay = client.post(
        "/api/knowledge-assets/v1/commands", json=body, headers=headers
    )
    assert replay.status_code == 200
    replay_payload = replay.json()
    assert replay_payload["operationId"] == first_payload["operationId"]
    assert (
        replay_payload["result"]["operation"]["operation_id"]
        == (first_payload["operationId"])
    )
    read_back = client.get(
        f"/api/knowledge-assets/v1/authoring/operations/{first_payload['operationId']}",
        headers={"X-Request-ID": "authoring-read-1"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["operation"]["status"] == "credential_blocked"
    assert read_back.json()["events"][1]["event_type"] == "credential_blocked"

    stream = client.get(
        (
            "/api/knowledge-assets/v1/authoring/operations/"
            f"{first_payload['operationId']}/events"
        ),
        headers={
            "X-Request-ID": "authoring-events-1",
            "Last-Event-ID": f"{first_payload['operationId']}:1",
        },
    )
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache"
    assert f"id: {first_payload['operationId']}:2" in stream.text
    assert "event: operation.failed" in stream.text
    assert '"event_id":' in stream.text
    assert '"trace_id":' in stream.text
    assert '"public_summary":' in stream.text


def test_authoring_operation_read_is_scoped_to_authenticated_workspace() -> None:
    def identity(request):
        return request.headers.get("X-Test-Workspace", "workspace-a"), "editor"

    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=application,
        identity_resolver=identity,
    )
    client = TestClient(app)
    headers = {
        "X-Test-Workspace": "workspace-a",
        "X-Request-ID": "authoring-scope-request",
        "Idempotency-Key": "authoring-scope-idempotency",
    }
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-authoring.start",
            "payload": {"prompt": "你好"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    operation_id = response.json()["operationId"]

    same_workspace = client.get(
        f"/api/knowledge-assets/v1/authoring/operations/{operation_id}",
        headers={"X-Test-Workspace": "workspace-a"},
    )
    assert same_workspace.status_code == 200

    other_workspace = client.get(
        f"/api/knowledge-assets/v1/authoring/operations/{operation_id}",
        headers={"X-Test-Workspace": "workspace-b"},
    )
    assert other_workspace.status_code == 404
    assert other_workspace.json()["code"] == "OPERATION_NOT_FOUND"


def test_authoring_stream_starts_one_routed_operation_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    class AnswerGateway:
        execution_evidence = None

        async def route(self, context):
            assert context.envelope.prompt == "你好"
            return AgentIntent(action="answer")

        async def answer(self, context, *, event_sink=None):
            del context
            if event_sink is not None:
                await event_sink(
                    AgentRuntimeEvent(
                        type="answer.delta",
                        public_summary="正在回答",
                        payload={"text": "你好"},
                        session_id="session-bff-stream",
                        trace_id="trace-bff-stream",
                    )
                )
            return AgentAnswer(status="succeeded", text="你好，我可以帮你。")

    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(
        repository,
        authoring_resolver=InMemoryResourceResolver(),
        authoring_model_gateway=AnswerGateway(),
        authoring_worker3=NoopWorker3Executor(),
    )
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=application,
        identity_resolver=lambda _request: ("workspace-test", "editor"),
    )
    client = TestClient(app)
    body = {
        "command": "skill-authoring.start",
        "payload": {"prompt": "你好"},
    }
    headers = {
        "X-Request-ID": "stream-start-request",
        "Idempotency-Key": "stream-start-idempotency",
        "Accept": "text/event-stream",
    }

    first = client.post(
        "/api/knowledge-assets/v1/streams",
        json=body,
        headers=headers,
    )

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    operation_id = first.headers["x-operation-id"]
    assert f"id: {operation_id}:1" in first.text
    assert "event: answer.delta" in first.text
    assert "event: operation.completed" in first.text

    replay = client.post(
        "/api/knowledge-assets/v1/streams",
        json=body,
        headers={**headers, "Last-Event-ID": f"{operation_id}:1"},
    )
    assert replay.status_code == 200
    assert replay.headers["x-operation-id"] == operation_id
    assert f"id: {operation_id}:1" not in replay.text
    assert "event: operation.completed" in replay.text


def test_authoring_stream_accepts_browser_camel_case_resource_references() -> None:
    client = build_client()

    response = client.post(
        "/api/knowledge-assets/v1/streams",
        json={
            "command": "skill-authoring.start",
            "payload": {
                "prompt": "Create an analysis Skill from this fixed revision.",
                "requestedKind": "analysis",
                "resourceRefs": [
                    {
                        "kind": "golden_asset",
                        "objectId": "golden-browser-contract",
                        "revision": "golden-browser-contract-r1",
                        "scope": "personal",
                    }
                ],
                "fixedRevisions": ["golden-browser-contract-r1"],
            },
        },
        headers={
            "X-Request-ID": "browser-resource-contract",
            "Idempotency-Key": "browser-resource-contract",
            "Accept": "text/event-stream",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-operation-id"].startswith("op_")
    assert "event: operation.failed" in response.text


def test_evaluation_quality_commands_use_typed_bff_and_fail_closed_for_candidates() -> (
    None
):
    client = build_client()
    suite = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "evaluation-suite.create",
            "payload": {
                "suiteId": "suite-bff",
                "skillId": "skill-bff",
                "cases": [
                    {
                        "id": "candidate-1",
                        "source": "agent_candidate",
                        "category": "normal",
                        "input": {"question": "non-sales question"},
                        "expected": {"answer": "ok"},
                        "provenanceRef": "agent-generation://trace-1",
                    }
                ],
            },
        },
        headers={"X-Request-ID": "eval-suite", "Idempotency-Key": "eval-suite"},
    )
    assert suite.status_code == 200
    assert suite.json()["result"]["status"] == "succeeded"
    assert suite.json()["result"]["suite"]["version"] == 1

    run = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "evaluation-run.start",
            "payload": {
                "suiteId": "suite-bff",
                "suiteVersion": 1,
                "provenance": {
                    "suiteId": "suite-bff",
                    "suiteVersion": 1,
                    "environment": "test",
                    "skillDraftRevision": "skill-bff:1",
                    "executorVersion": "executor@test",
                    "rendererVersion": "renderer@test",
                    "dataAsOf": "2026-08-25T00:00:00Z",
                },
            },
        },
        headers={"X-Request-ID": "eval-run", "Idempotency-Key": "eval-run"},
    )
    assert run.status_code == 200
    assert run.json()["accepted"] is False
    assert run.json()["result"]["status"] == "failed"
    assert run.json()["result"]["error"]["code"] == (
        "AGENT_CANDIDATE_CONFIRMATION_REQUIRED"
    )


def test_evaluation_run_without_real_executor_is_explicitly_failed() -> None:
    client = build_client()
    created = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "evaluation-suite.create",
            "payload": {
                "suiteId": "suite-no-executor",
                "skillId": "skill-no-executor",
                "cases": [
                    {
                        "id": "manual-1",
                        "source": "manual",
                        "category": "normal",
                        "input": {"question": "non-sales question"},
                        "expected": {"answer": "ok"},
                    }
                ],
            },
        },
        headers={
            "X-Request-ID": "suite-no-executor",
            "Idempotency-Key": "suite-no-executor",
        },
    ).json()
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "evaluation-run.start",
            "payload": {
                "suiteId": "suite-no-executor",
                "suiteVersion": created["result"]["suite"]["version"],
                "provenance": {
                    "suiteId": "suite-no-executor",
                    "suiteVersion": 1,
                    "environment": "test",
                    "skillDraftRevision": "skill-no-executor:1",
                    "executorVersion": "executor@test",
                    "rendererVersion": "renderer@test",
                    "dataAsOf": "2026-08-25T00:00:00Z",
                },
            },
        },
        headers={
            "X-Request-ID": "run-no-executor",
            "Idempotency-Key": "run-no-executor",
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert response.json()["result"]["status"] == "failed"
    assert response.json()["result"]["error"]["code"] == (
        "EVALUATION_EXECUTOR_NOT_CONFIGURED"
    )
    assert response.json()["result"]["run"]["status"] == "failed"


def test_operation_events_replay_after_sequence_and_cancel_is_terminal() -> None:
    client = build_client()
    headers = {"X-Request-ID": "request-stream", "Idempotency-Key": "stream-1"}
    created = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.create",
            "payload": {
                "workspaceId": "workspace-test",
                "name": "Policy Skill",
                "description": "",
                "sourceRefs": [],
            },
        },
        headers=headers,
    ).json()
    operation_id = created["operationId"]
    events = client.get(
        f"/api/knowledge-assets/v1/operations/{operation_id}/events",
        headers={"Last-Event-ID": "1", "X-Request-ID": "request-events"},
    )
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in events.text
    assert "succeeded" in events.text

    cancelled = client.post(
        f"/api/knowledge-assets/v1/operations/{operation_id}:cancel",
        headers={"X-Request-ID": "request-cancel", "Idempotency-Key": "cancel-1"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "succeeded"


def test_save_manifest_validates_revision_persists_manifest_and_records_audit() -> None:
    client = build_client()
    create = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.create",
            "payload": {
                "workspaceId": "workspace-test",
                "name": "Policy Skill",
                "description": "",
                "sourceRefs": [],
            },
        },
        headers={
            "X-Request-ID": "request-create-manifest",
            "Idempotency-Key": "create-manifest-1",
        },
    ).json()
    draft = create["result"]["draft"]
    payload = {
        "command": "skill-draft.save-manifest",
        "payload": {
            "draftId": draft["id"],
            "baseRevision": draft["revision"],
            "manifest": {
                "name": "Policy Skill",
                "version": "1.0.0",
                "description": "Answer policy questions",
                "actions": [
                    {"name": "answer", "description": "Answer a policy question"}
                ],
                "schema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "User question"}
                    },
                    "required": ["question"],
                    "additionalProperties": False,
                },
            },
        },
    }
    saved = client.post(
        "/api/knowledge-assets/v1/commands",
        json=payload,
        headers={
            "X-Request-ID": "request-save-manifest",
            "Idempotency-Key": "save-manifest-1",
        },
    )
    assert saved.status_code == 200
    saved_json = saved.json()
    assert saved_json["result"]["draft"]["revision"] == 2
    saved_manifest = saved_json["result"]["draft"]["manifest"]
    assert saved_manifest["spec"]["kind"] == "knowledge"
    assert saved_manifest["spec"]["kindSpec"]["kind"] == "knowledge"
    assert saved_manifest["spec"]["contract"]["operations"][0]["name"] == "answer"

    operation_id = saved_json["operationId"]
    operation = client.get(
        f"/api/knowledge-assets/v1/operations/{operation_id}",
        headers={"X-Request-ID": "request-operation-manifest"},
    )
    assert operation.status_code == 200
    assert operation.json()["audit"][0]["action"] == "skill-draft.save-manifest"
    assert operation.json()["audit"][0]["outcome"] == "succeeded"
    audit = client.get(
        f"/api/knowledge-assets/v1/operations/{operation_id}/audit",
        headers={"X-Request-ID": "request-audit-manifest"},
    )
    assert audit.status_code == 200
    assert audit.json()["operationId"] == operation_id
    assert audit.json()["items"][0]["requestId"] == "request-save-manifest"

    bootstrap = client.get(
        "/api/knowledge-assets/v1/bootstrap",
        headers={"X-Request-ID": "request-bootstrap-manifest"},
    )
    assert bootstrap.json()["resources"][0]["revision"] == 2


def test_save_manifest_rejects_policy_and_stale_revision() -> None:
    client = build_client()
    created = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.create",
            "payload": {
                "workspaceId": "workspace-test",
                "name": "Policy Skill",
                "description": "",
                "sourceRefs": [],
            },
        },
        headers={
            "X-Request-ID": "request-policy-create",
            "Idempotency-Key": "policy-create-1",
        },
    ).json()["result"]["draft"]
    invalid = {
        "command": "skill-draft.save-manifest",
        "payload": {
            "draftId": created["id"],
            "baseRevision": 1,
            "manifest": {
                "name": "Policy Skill",
                "version": "1.0.0",
                "description": "",
                "actions": [],
                "schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        },
    }
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json=invalid,
        headers={
            "X-Request-ID": "request-policy-invalid",
            "Idempotency-Key": "policy-invalid-1",
        },
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"

    valid = invalid["payload"].copy()
    valid["manifest"] = {
        **invalid["payload"]["manifest"],
        "actions": [{"name": "answer", "description": ""}],
    }
    saved = client.post(
        "/api/knowledge-assets/v1/commands",
        json={"command": "skill-draft.save-manifest", "payload": valid},
        headers={
            "X-Request-ID": "request-policy-save",
            "Idempotency-Key": "policy-save-1",
        },
    )
    assert saved.status_code == 200
    stale = client.post(
        "/api/knowledge-assets/v1/commands",
        json={"command": "skill-draft.save-manifest", "payload": valid},
        headers={
            "X-Request-ID": "request-policy-stale",
            "Idempotency-Key": "policy-stale-1",
        },
    )
    assert stale.status_code == 409
    assert stale.headers["content-type"].startswith("application/problem+json")
    assert stale.json()["code"] == "CONFLICT"


def test_legacy_adapter_normalizes_to_canonical_discriminated_manifest() -> None:
    manifest = adapt_legacy_manifest(
        LegacySkillManifestInput(
            name="Knowledge",
            version="1.0.0",
            actions=[{"name": "answer", "description": "answer"}],
        ),
        draft_id="skill-draft-test",
        workspace_id="workspace-test",
    )
    assert isinstance(manifest, SkillManifest)
    assert manifest.kind == "Skill"
    assert manifest.spec.kind == "knowledge"
    assert manifest.spec.kind_spec.kind == "knowledge"
    assert manifest.spec.contract.operations[0].name == "answer"
    assert "actions" not in manifest.model_dump(mode="json")


def test_publish_and_reinvoke_require_and_consume_real_revision_evidence() -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=application,
        identity_resolver=lambda request: ("workspace-test", "editor"),
    )
    client = TestClient(app)
    created = repository.create_skill_draft(
        workspace_id="workspace-test",
        name="Infrastructure health",
        description="",
        source_refs=[],
        request_id="draft-request",
        idempotency_key="draft-key",
    )[0]
    manifest = adapt_legacy_manifest(
        LegacySkillManifestInput(
            name="Infrastructure health",
            version="1.0.0",
            actions=[{"name": "answer", "description": "answer"}],
        ),
        draft_id=created.id,
        workspace_id=created.workspace_id,
    )
    draft = repository.save_manifest(
        draft_id=created.id,
        base_revision=created.revision,
        manifest=manifest,
        request_id="manifest-request",
        idempotency_key="manifest-key",
    )[0]
    revision_id = f"{draft.id}:{draft.revision}"
    view = SkillViewRevision(
        id="view-publishable",
        skill_revision_id=revision_id,
        revision=1,
        manifest=SkillViewManifest(
            id="view-manifest",
            skill_revision_id=revision_id,
            renderer_ref="renderer://chart/v1",
            view_model_schema_ref=SchemaRef(
                uri="local://schema/view",
                version="1",
                sha256="0" * 64,
            ),
            allowed_components=["ChartView"],
        ),
        intent=ViewIntent(
            id="view-intent",
            skill_id=draft.id,
            skill_revision=draft.revision,
            template="chart",
            purpose="compare",
            result_ref="local://result/infrastructure",
        ),
        view_model=ChartViewModel(
            title="Infrastructure health",
            x_field="service",
            y_field="cpu",
            series=[ChartSeries(name="cpu", points=[("edge", 0.2)])],
            data_ref=StorageRef(
                uri="local://golden/infrastructure",
                kind="object",
                sha256="1" * 64,
                media_type="application/json",
                bytes=1,
            ),
        ),
        created_at="2026-08-25T00:00:00Z",
    )
    repository.save_skill_view_revision(view)
    result = SkillResult(
        id="result-infrastructure",
        skill_id=draft.id,
        skill_revision=draft.revision,
        kind="analysis",
        output_schema_ref=SchemaRef(
            uri="local://schema/output",
            version="1",
            sha256="2" * 64,
        ),
        result_ref=StorageRef(
            uri="local://result/infrastructure",
            kind="object",
            sha256="3" * 64,
            media_type="application/json",
            bytes=1,
        ),
        trace_id="trace-infrastructure",
    )
    repository.save_skill_result(result)
    evaluation = EvaluationRun(
        id="evaluation-infrastructure",
        suite_id="suite-infrastructure",
        suite_version=1,
        skill_revision_id=revision_id,
        status="succeeded",
        score=1.0,
        started_at="2026-08-25T00:00:00Z",
        finished_at="2026-08-25T00:00:01Z",
    )
    gate = PolicyGateResult(
        id="gate-evaluation-infrastructure",
        skill_revision_id=revision_id,
        evaluation_run_id=evaluation.id,
        decision="publishable",
        machine_reasons=["EVAL_SCORE_AT_OR_ABOVE_THRESHOLD"],
        checked_at="2026-08-25T00:00:02Z",
    )
    repository.save_evaluation_run(evaluation)
    repository.save_policy_gate_result(gate)
    published = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "publication.publish",
            "payload": {
                "draftId": draft.id,
                "revision": draft.revision,
                "semver": "1.0.0",
            },
        },
        headers={"X-Request-ID": "publish-request", "Idempotency-Key": "publish-key"},
    ).json()
    assert published["accepted"] is True
    version = published["result"]["publishedVersion"]
    assert version["id"] == f"published://{draft.id}:1.0.0"
    bootstrap = client.get("/api/knowledge-assets/v1/bootstrap").json()
    assert bootstrap["publications"] == [
        {
            "id": version["id"],
            "skillId": draft.id,
            "revision": str(draft.revision),
            "version": "1.0.0",
            "status": "published",
        }
    ]
    invoked = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "invocation.start",
            "payload": {
                "skillVersionId": version["id"],
                "skillViewRevisionId": view.id,
                "inputRef": {
                    "uri": "local://input/request",
                    "kind": "object",
                    "sha256": "4" * 64,
                    "mediaType": "application/json",
                    "bytes": 1,
                },
                "callerId": "new-session",
            },
        },
        headers={"X-Request-ID": "invoke-request", "Idempotency-Key": "invoke-key"},
    ).json()
    assert invoked["accepted"] is True
    assert invoked["result"]["status"] == "succeeded"
    assert invoked["result"]["invocation"]["skillVersionId"] == version["id"]


def test_manifest_kind_discriminator_rejects_mismatched_kind_spec() -> None:
    with pytest.raises(ValueError, match="spec.kind must match"):
        SkillManifest.model_validate(
            {
                "metadata": {
                    "id": "skill-1",
                    "version": "1.0.0",
                    "displayName": "Skill",
                    "owner": {
                        "workspaceId": "workspace-test",
                        "principalId": "tester",
                    },
                },
                "spec": {
                    "kind": "knowledge",
                    "contract": {
                        "inputSchemaRef": {
                            "uri": "schema://input",
                            "version": "1",
                            "sha256": "0" * 64,
                        },
                        "outputSchemaRef": {
                            "uri": "schema://output",
                            "version": "1",
                            "sha256": "0" * 64,
                        },
                    },
                    "policyRef": {"uri": "policy://test", "version": "1"},
                    "runtimeRef": "runtime://test",
                    "kindSpec": {
                        "kind": "semantic",
                        "metricRefs": [],
                    },
                },
            }
        )


@pytest.mark.parametrize(
    ("command", "payload"),
    [
        ("source.profile", {"sourceRevisionId": "source-1", "sampleLimit": 10}),
        ("source.clean", {"sourceRevisionId": "source-1", "recipeId": "recipe-1"}),
        (
            "skill-draft.run",
            {"draftId": "draft-1", "revision": 1, "traceId": "trace-1"},
        ),
        (
            "publication.publish",
            {"draftId": "draft-1", "revision": 1, "semver": "1.0.0"},
        ),
        ("refresh.run", {"skillId": "skill-1", "trigger": "manual"}),
        (
            "invocation.start",
            {
                "skillVersionId": "version-1",
                "inputRef": {
                    "uri": "object://input",
                    "kind": "object",
                    "sha256": "0" * 64,
                    "mediaType": "application/json",
                },
                "callerId": "caller-1",
            },
        ),
    ],
)
def test_registered_not_ready_commands_return_typed_failure(
    command: str, payload: dict[str, object]
) -> None:
    client = build_client()
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={"command": command, "payload": payload},
        headers={
            "X-Request-ID": f"request-{command}",
            "Idempotency-Key": f"key-{command}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    expected_status = (
        "failed"
        if command in {"refresh.run", "skill-draft.run", "publication.publish"}
        else "not_ready"
    )
    assert body["result"]["status"] == expected_status
    expected_code = (
        "SKILL_NOT_FOUND"
        if command == "refresh.run"
        else "SKILL_DRAFT_NOT_FOUND"
        if command == "skill-draft.run"
        else "DRAFT_REVISION_NOT_FOUND"
        if command == "publication.publish"
        else "COMMAND_NOT_READY"
    )
    assert body["result"]["error"]["code"] == expected_code


def test_sqlite_migration_replay_and_revision_pointers() -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    repository._migrate()
    draft, _ = repository.create_skill_draft(
        workspace_id="workspace-test",
        name="Skill",
        description="",
        source_refs=[],
        request_id="request",
        idempotency_key="create",
    )
    assert (
        repository.current_pointer(object_type="skill_draft", object_id=draft.id) == 1
    )
    assert (
        repository.last_good_pointer(object_type="skill_draft", object_id=draft.id) == 1
    )
    table_names = {
        row[0]
        for row in repository._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "schema_migrations",
        "jobs",
        "job_events",
        "outbox_events",
        "dead_letters",
    } <= table_names


def test_job_framework_enforces_idempotency_lease_retry_dead_letter_and_outbox() -> (
    None
):
    now = [datetime(2026, 8, 24, tzinfo=timezone.utc)]
    framework = JobFramework(now=lambda: now[0], retry_base_seconds=2)
    first = framework.enqueue(
        job_type="source.profile",
        idempotency_key="same",
        profile="test",
        max_attempts=2,
    )
    replay = framework.enqueue(
        job_type="source.profile",
        idempotency_key="same",
        profile="test",
        max_attempts=2,
    )
    assert replay.job_id == first.job_id
    leased = framework.lease(job_id=first.job_id, owner="worker-a", ttl_seconds=10)
    assert leased.status == "leased"
    with pytest.raises(JobLeaseError):
        framework.lease(job_id=first.job_id, owner="worker-b")
    assert (
        framework.heartbeat(job_id=first.job_id, owner="worker-a").status == "running"
    )
    retried = framework.fail(job_id=first.job_id, owner="worker-a", reason="temporary")
    assert retried.status == "queued"
    assert retried.next_attempt_at is not None
    framework.lease(job_id=first.job_id, owner="worker-a")
    dead = framework.fail(job_id=first.job_id, owner="worker-a", reason="permanent")
    assert dead.status == "dead_letter"
    assert framework.dead_letter(first.job_id)["reason"] == "permanent"
    assert [event.sequence for event in framework.events(first.job_id)] == list(
        range(1, len(framework.events(first.job_id)) + 1)
    )
    assert len(framework.outbox()) == len(framework.events(first.job_id))


def test_bff_prefer_async_builder_returns_and_persists_terminal_operation() -> None:
    client = build_client()
    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.run",
            "payload": {
                "draftId": "missing-async-draft",
                "revision": 1,
                "traceId": "async-http",
            },
        },
        headers={
            "X-Request-ID": "async-http-request",
            "Idempotency-Key": "async-http-key",
            "Prefer": "respond-async",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["result"] is None
    operation_id = body["operationId"]
    for _ in range(100):
        operation = client.get(
            f"/api/knowledge-assets/v1/operations/{operation_id}",
            headers={"X-Request-ID": "async-http-poll"},
        ).json()
        if operation["status"] in {"failed", "cancelled", "succeeded"}:
            break
    assert operation["status"] == "failed"
    assert operation["events"][-1]["terminal"] is True
    assert operation["events"][-1]["type"] == "failed"


def test_production_adapters_fail_closed() -> None:
    adapter = FailClosedArtifactStore()
    with pytest.raises(NotConfiguredAdapterError) as error:
        adapter.put(
            ArtifactPutRequest(
                key="key",
                content=b"data",
                content_type="application/octet-stream",
                profile="production",
            )
        )
    assert error.value.code == "NOT_CONFIGURED"
