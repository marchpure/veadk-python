from pathlib import Path
import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets.runtime import _MainWorker3Executor, create_app
from frontend.server.knowledge_assets.repository import SqliteKnowledgeAssetRepository
from frontend.server.knowledge_assets.template_registry import (
    SqliteTemplateRegistry,
    template_ref,
)
from frontend.server.knowledge_assets.workers import JobFramework
from frontend.server.skill_authoring.models import (
    Budget,
    BuildPlan,
    DraftManifest,
    FreshnessPolicy,
    InputContract,
    OutputContract,
    PlanNode,
    ResolvedResource,
    ResourceRef,
    Scope,
    SkillKind,
    SopKindSpec,
    TemplateSelection,
    Worker3ExecutionRequest,
    digest,
)


def test_runtime_composition_requires_authenticated_identity_resolver() -> None:
    with pytest.raises(ValueError, match="identity_resolver"):
        create_app(repository_path=":memory:")


def test_runtime_composition_reaches_real_bff(tmp_path: Path) -> None:
    app = create_app(
        repository_path=tmp_path / "assets.sqlite3",
        identity_resolver=lambda request: ("workspace-runtime", "editor"),
    )
    response = TestClient(app).get(
        "/api/knowledge-assets/v1/bootstrap",
        headers={"X-Request-ID": "runtime-bootstrap"},
    )
    assert response.status_code == 200
    assert response.json()["access"]["spaceId"] == "workspace-runtime"
    specs = response.json()["workspaceData"]["templateSpecs"]
    assert len(specs) == 6
    assert {item["templateId"] for item in specs} == {
        "dashboard",
        "semantic",
        "sop",
        "knowledge",
        "graph-ontology",
        "monitoring",
    }
    for spec in specs:
        assert spec["templateRef"]["templateId"] == spec["templateId"]
        assert spec["templateRef"]["version"] == spec["version"]
        assert len(spec["templateRef"]["digest"]) == 64


def test_runtime_composes_source_golden_and_template_routes(tmp_path: Path) -> None:
    app = create_app(
        repository_path=tmp_path / "assets.sqlite3",
        identity_resolver=lambda request: ("workspace-runtime", "editor"),
    )
    client = TestClient(app)

    catalog = client.get("/api/source-golden/v1/catalog")
    templates = client.get("/api/knowledge-assets/v1/templates")
    markdown = client.get(
        "/api/knowledge-assets/v1/templates/dashboard/versions/1.0.0/spec.md"
    )

    assert catalog.status_code == 200
    assert catalog.json()["total"] == 37
    assert templates.status_code == 200
    assert len(templates.json()["templates"]) == 6
    assert markdown.status_code == 200
    assert "```template-spec+json" in markdown.text


def test_runtime_composition_accepts_signed_webhook_delivery(tmp_path: Path) -> None:
    secret = "combined-runtime-webhook-secret"
    schema = json.dumps(
        {
            "type": "object",
            "required": ["sku", "stock"],
            "properties": {
                "sku": {"type": "string"},
                "stock": {"type": "integer"},
            },
            "additionalProperties": False,
        }
    ).encode()
    client = TestClient(
        create_app(
            repository_path=tmp_path / "assets.sqlite3",
            identity_resolver=lambda request: ("workspace-runtime", "editor"),
            secret_resolver=lambda reference: (
                secret if reference == "secret://workspace-runtime/webhook" else None
            ),
        )
    )
    uploaded = client.post(
        "/api/source-golden/v1/uploads",
        files={"upload": ("event.schema.json", schema, "application/json")},
    )
    assert uploaded.status_code == 201
    created = client.post(
        "/api/source-golden/v1/connections",
        headers={
            "Idempotency-Key": "combined-webhook-create",
            "X-Request-ID": "combined-webhook-create",
        },
        json={
            "connectorKey": "webhook",
            "displayName": "Combined webhook",
            "scope": "team",
            "configuration": {
                "listenPath": "/inventory/events",
                "schemaRef": uploaded.json()["sourceRef"],
                "rateLimitPerMinute": 2,
            },
            "secretRef": "secret://workspace-runtime/webhook",
        },
    )
    assert created.status_code == 201
    connection_id = created.json()["connection"]["id"]
    body = b'{"sku":"A-1","stock":8}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    delivered = client.post(
        "/api/source-golden/v1/webhooks/workspaces/workspace-runtime"
        f"/connections/{connection_id}/inventory/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Id": "combined-delivery-1",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Trace-Id": "combined-webhook-delivery",
        },
    )

    assert delivered.status_code == 202
    assert delivered.json()["eventType"] == "webhook.delivery.accepted"
    assert delivered.json()["traceId"] == "combined-webhook-delivery"


def test_runtime_template_copy_persists_across_restart(tmp_path: Path) -> None:
    repository_path = tmp_path / "assets.sqlite3"

    def identity(_request):
        return "workspace-runtime", "editor"

    client = TestClient(
        create_app(repository_path=repository_path, identity_resolver=identity)
    )

    copied = client.post(
        "/api/knowledge-assets/v1/templates/dashboard/versions/1.0.0:copy",
        headers={"X-Request-ID": "copy-template"},
        json={
            "newTemplateId": "workspace-dashboard",
            "newVersion": "1.0.0",
            "displayName": "Workspace Dashboard",
        },
    )

    assert copied.status_code == 201
    assert copied.json()["builtin"] is False
    assert copied.json()["ownerWorkspaceId"] == "workspace-runtime"

    restarted = TestClient(
        create_app(repository_path=repository_path, identity_resolver=identity)
    )
    restored = restarted.get(
        "/api/knowledge-assets/v1/templates/workspace-dashboard/versions/1.0.0"
    )
    assert restored.status_code == 200
    assert restored.json()["displayName"] == "Workspace Dashboard"


def test_sop_template_execution_binds_manifest_content_and_tool_lineage(
    tmp_path: Path,
) -> None:
    content = "diagnostic procedure evidence"
    content_digest = hashlib.sha256(content.encode()).hexdigest()
    schema_digest = "a" * 64
    source_digest = "b" * 64
    resource_ref = ResourceRef(
        kind="golden_asset",
        object_id="golden-tool",
        revision="golden-tool:1",
        scope=Scope.TEAM,
    )
    resolved = ResolvedResource(
        ref=resource_ref,
        display_name="Diagnostic tool evidence",
        provider_revision="source-tool:1",
        schema_digest=schema_digest,
        content_digest=content_digest,
        capabilities=("golden_data.read",),
    )
    sop = SopKindSpec(
        trigger="Investigate an operational alert",
        scope="Authorized workspace resources",
        input_fields=({"name": "request", "label": "Request", "value_type": "string"},),
        steps=(
            {
                "id": "inspect",
                "title": "Inspect evidence",
                "instruction": "Read the pinned evidence and propose an action.",
                "evidence_requirements": ({"kind": "source_citation"},),
                "failure_mode": "propose_action",
            },
        ),
        outputs=(
            {
                "name": "result",
                "description": "Reviewable result",
                "value_type": "object",
            },
        ),
        failure_handling="Stop when required evidence is missing.",
        action_proposal="Require confirmation before an external write.",
    )
    nodes = (
        PlanNode(node_id="resolve_intent", role="intent_resolution"),
        PlanNode(
            node_id="resolve_context",
            role="context_resolution",
            depends_on=("resolve_intent",),
        ),
        PlanNode(
            node_id="execute",
            role="worker3_execution",
            depends_on=("resolve_context",),
        ),
    )
    plan_payload = {
        "plan_id": "plan-sop-integration",
        "intent": SkillKind.SOP,
        "purpose": "Build an evidence-backed SOP",
        "nodes": nodes,
        "inputs": (InputContract(name="request", type="string"),),
        "outputs": (OutputContract(name="observation", type="observation"),),
        "dependencies": (resource_ref,),
        "kind_spec": sop,
        "data_refs": (resource_ref,),
        "lineage": (resource_ref,),
        "layout_intent": "document",
    }
    plan = BuildPlan(
        **plan_payload,
        plan_digest=digest({"plan": "sop-integration"}),
    )
    draft_manifest = DraftManifest(
        name="Operational SOP",
        description="Evidence-backed operational procedure",
        kind=SkillKind.SOP,
        kind_spec=sop,
        inputs=plan.inputs,
        outputs=plan.outputs,
        dependencies=(resource_ref,),
        permissions=("golden_data.read",),
        freshness=FreshnessPolicy(),
    )
    registry = SqliteTemplateRegistry(tmp_path / "templates.sqlite3")
    selected = TemplateSelection.model_validate(
        template_ref(registry.get("sop", "1.0.0", "workspace-runtime")).model_dump()
    )
    golden = SimpleNamespace(
        id="golden-tool:1",
        asset_kind="knowledge",
        revision=1,
        schema_digest=schema_digest,
        storage_ref=SimpleNamespace(
            uri="local://golden/tool",
            sha256=content_digest,
            media_type="text/plain",
            bytes=len(content.encode()),
        ),
        lineage=SimpleNamespace(
            source_revision_id="source-tool:1",
            recipe_id="recipe-tool",
            profile_run_id="profile-tool",
            lineage_digest="c" * 64,
        ),
        owner=SimpleNamespace(
            workspace_id="workspace-runtime", principal_id="workspace-runtime"
        ),
        permissions=SimpleNamespace(version=1),
        freshness_at="2026-08-26T00:00:00Z",
        last_good=True,
    )

    class FakeSourceGolden:
        def golden_revision(self, _context, revision_id):
            assert revision_id == golden.id
            return golden

        def golden_asset_content(self, _context, revision_id):
            assert revision_id == golden.id
            return content.encode()

        def golden_origin_resource(self, _context, revision_id):
            assert revision_id == golden.id
            return (
                SimpleNamespace(resource_type="tool", id="diagnostic-tool"),
                SimpleNamespace(id="source-tool:1", source_digest=source_digest),
            )

    repository = SqliteKnowledgeAssetRepository(tmp_path / "assets.sqlite3")
    executor = _MainWorker3Executor(
        repository=repository,
        source_golden=FakeSourceGolden(),
        artifact_root=tmp_path / "dashboard-workspaces",
        template_registry=registry,
    )
    request = Worker3ExecutionRequest(
        operation_id="operation-sop-integration",
        draft_id="draft-sop-integration",
        draft_revision=1,
        skill_kind=SkillKind.SOP,
        workspace_id="workspace-runtime",
        caller_id="workspace-runtime",
        dependencies=(resource_ref,),
        data_refs=(resource_ref,),
        lineage=(resource_ref,),
        budget=Budget(),
        freshness=FreshnessPolicy(),
        draft_manifest=draft_manifest,
        build_plan=plan,
        trace_id="trace-sop-integration",
        selected_template=selected,
        resolved_resources=(resolved,),
    )

    accepted = asyncio.run(executor.request_execution(request))

    assert accepted.state in {"accepted", "queued"}
    row = repository._connection.execute(
        "SELECT manifest_json FROM skill_draft_revisions "
        "WHERE draft_id = ? AND revision = 1",
        ("draft-sop-integration",),
    ).fetchone()
    manifest = json.loads(row["manifest_json"])
    assert manifest["spec"]["kind"] == "sop"
    assert manifest["spec"]["templateRef"] == selected.model_dump(
        mode="json", by_alias=True
    )
    assert manifest["spec"]["defaultRenderer"] == "sop"
    assert {
        (item["kind"], item["digest"])
        for item in manifest["spec"]["contextRevisionRefs"]
    } == {
        ("golden_asset", content_digest),
        ("tool", source_digest),
    }

    missing_metadata = asyncio.run(
        executor.request_execution(
            request.model_copy(
                update={
                    "operation_id": "operation-sop-missing-metadata",
                    "resolved_resources": (),
                }
            )
        )
    )
    assert missing_metadata.state == "failed"
    assert "lacks authorized resolved metadata" in (missing_metadata.reason or "")


def test_sqlite_migration_chain_has_monotonic_template_head(tmp_path: Path) -> None:
    repository = SqliteKnowledgeAssetRepository(tmp_path / "migrations.sqlite3")
    applied = {
        row["version"]
        for row in repository._connection.execute(
            "SELECT version FROM schema_migrations"
        )
    }

    assert "007_authoring_generation_leases" in applied
    assert "008_template_specs" in applied
    assert repository._connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name = 'template_spec_versions'"
    ).fetchone()

    repository._migrate()
    replayed = [
        row["version"]
        for row in repository._connection.execute(
            "SELECT version FROM schema_migrations "
            "WHERE version IN ('007_authoring_generation_leases', '008_template_specs')"
        )
    ]
    assert replayed == ["007_authoring_generation_leases", "008_template_specs"]


def test_job_events_resume_after_checkpoint() -> None:
    framework = JobFramework()
    job = framework.enqueue(
        job_type="refresh", idempotency_key="resume-1", profile="test"
    )
    framework.lease(job_id=job.job_id, owner="worker")
    framework.heartbeat(job_id=job.job_id, owner="worker")
    checkpoint = framework.checkpoint(
        job_id=job.job_id, owner="worker", after_sequence=2
    )
    assert checkpoint.outbox_sequence == 3
    replayed = framework.resume(after_sequence=2)
    assert [event.event_type for event in replayed] == ["heartbeat"]


def test_existing_sqlite_profile_table_is_upgraded_in_place(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE profile_runs (
          id TEXT PRIMARY KEY,
          source_revision_id TEXT NOT NULL,
          status TEXT NOT NULL,
          sample_ref_json TEXT,
          report_ref_json TEXT,
          quality_score REAL,
          error_code TEXT,
          started_at TEXT NOT NULL,
          finished_at TEXT
        );
        """
    )
    connection.close()

    repository = SqliteKnowledgeAssetRepository(path)
    columns = {
        row["name"]
        for row in repository._connection.execute("PRAGMA table_info(profile_runs)")
    }
    assert {
        "structure_ref_json",
        "sensitive_classification_json",
        "estimated_cost_ref_json",
    } <= columns
