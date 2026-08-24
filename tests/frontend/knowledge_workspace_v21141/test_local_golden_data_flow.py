from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.contracts import SourceCleanPayload, SourceProfilePayload
from frontend.server.knowledge_assets.repository import SqliteKnowledgeAssetRepository
from frontend.server.knowledge_assets.routes import mount_knowledge_asset_routes


def test_markdown_profile_clean_and_golden_revision(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "notes.md"
    source.write_text("# Title\n\nsame\nsame\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    revision = application._register_local_source(str(source), workspace_id="ws", request_id="r")
    assert revision is not None
    profile = application._run_profile(
        SourceProfilePayload(source_revision_id=revision.id, sample_limit=10), "r"
    )
    assert profile.status == "succeeded"
    assert profile.profile_run.structure_ref is not None
    assert profile.profile_run.estimated_cost_ref is not None
    assert profile.profile_run.sensitive_classification == []
    cleaned = application._run_clean(
        SourceCleanPayload(source_revision_id=revision.id, recipe_id="recipe-md"), "ws"
    )
    assert cleaned.status == "succeeded"
    assert cleaned.golden_asset_revision is not None
    assert repository.latest_golden_asset_revision("ws").storage_ref.sha256 == (
        cleaned.golden_asset_revision.storage_ref.sha256
    )
    assert (tmp_path / ".veadk/knowledge-assets/artifacts").exists()


def test_csv_cleaning_is_deduplicated_and_represented_as_jsonl(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "rows.csv"
    source.write_text("name,amount\n Alice ,1\nAlice,1\nBob,2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    revision = application._register_local_source(str(source), workspace_id="ws", request_id="r")
    assert revision is not None and revision.source_type == "csv"
    cleaned = application._run_clean(
        SourceCleanPayload(source_revision_id=revision.id, recipe_id="recipe-csv"), "ws"
    )
    artifact = Path(".veadk/knowledge-assets/artifacts") / (
        f"{cleaned.golden_asset_revision.storage_ref.sha256}.jsonl"
    )
    assert artifact.read_text(encoding="utf-8").count('"name": "Alice"') == 1
    assert cleaned.golden_asset_revision.asset_kind == "dataset"


def test_csv_profile_classifies_sensitive_columns_without_storing_values(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "people.csv"
    source.write_text("name,email,phone\nAlice,a@example.com,123\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    revision = application._register_local_source(str(source), workspace_id="ws", request_id="r")

    profile = application._run_profile(
        SourceProfilePayload(source_revision_id=revision.id, sample_limit=10), "r"
    )

    assert profile.profile_run.sensitive_classification == ["email", "phone"]
    assert "a@example.com" not in profile.profile_run.report_ref.uri


def test_bff_local_markdown_flow_returns_readable_golden_revision(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "brief.md"
    source.write_text("# Brief\n\nRevenue is stable.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(repository),
        identity_resolver=lambda request: ("ws", "editor"),
    )
    client = TestClient(app)
    headers = {"X-Request-ID": "bff-1", "Idempotency-Key": "bff-create"}
    created = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.create",
            "payload": {
                "workspaceId": "ws",
                "name": "Brief",
                "description": "",
                "sourceRefs": [str(source)],
            },
        },
        headers=headers,
    )
    assert created.status_code == 200
    source_id = repository._connection.execute(
        "SELECT id FROM source_revisions"
    ).fetchone()["id"]
    profiled = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "source.profile",
            "payload": {"sourceRevisionId": source_id, "sampleLimit": 10},
        },
        headers={"X-Request-ID": "bff-2", "Idempotency-Key": "bff-profile"},
    )
    assert profiled.json()["accepted"] is True
    cleaned = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "source.clean",
            "payload": {"sourceRevisionId": source_id, "recipeId": "bff-recipe"},
        },
        headers={"X-Request-ID": "bff-3", "Idempotency-Key": "bff-clean"},
    )
    golden = cleaned.json()["result"]["goldenAssetRevision"]
    assert cleaned.json()["accepted"] is True
    assert golden["storageRef"]["uri"].startswith("local://golden/")
    assert repository.latest_golden_asset_revision("ws").id == golden["id"]


def test_golden_revisions_are_append_only_and_tombstones_hide_revoked_assets(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "notes.md"
    source.write_text("first\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    first_source = application._register_local_source(str(source), workspace_id="ws", request_id="r")
    first = application._run_clean(
        SourceCleanPayload(source_revision_id=first_source.id, recipe_id="r1"), "ws"
    ).golden_asset_revision
    source.write_text("second\n", encoding="utf-8")
    second_source = application._register_local_source(str(source), workspace_id="ws", request_id="r2")
    second = application._run_clean(
        SourceCleanPayload(source_revision_id=second_source.id, recipe_id="r2"), "ws"
    ).golden_asset_revision
    assert first.revision == 1
    assert second.revision == 2
    assert repository.latest_golden_asset_revision("ws").id == second.id
    repository.revoke_asset(second.id, "ws", "revoke-1", "permission revoked")
    assert repository.latest_golden_asset_revision("ws").id == first.id
    tombstone = repository._connection.execute(
        "SELECT reason FROM asset_tombstones WHERE asset_id = ?", (second.id,)
    ).fetchone()
    assert tombstone["reason"] == "permission revoked"


def test_bff_permission_revocation_tombstones_asset_in_authenticated_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "notes.md"
    source.write_text("permissioned knowledge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(repository),
        identity_resolver=lambda request: ("ws-authenticated", "editor"),
    )
    client = TestClient(app)
    revision = KnowledgeAssetApplication(repository)._register_local_source(
        str(source), workspace_id="ws-authenticated", request_id="source-1"
    )
    golden = KnowledgeAssetApplication(repository)._run_clean(
        SourceCleanPayload(source_revision_id=revision.id, recipe_id="permission-recipe"),
        "ws-authenticated",
    ).golden_asset_revision

    response = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "resource.revoke",
            "payload": {
                "resourceId": golden.id,
                "reason": "permission revoked",
            },
        },
        headers={"X-Request-ID": "revoke-1", "Idempotency-Key": "revoke-command"},
    )

    assert response.status_code == 200
    assert repository.latest_golden_asset_revision("ws-authenticated") is None
    tombstone = repository._connection.execute(
        "SELECT workspace_id, reason, request_id FROM asset_tombstones WHERE asset_id = ?",
        (golden.id,),
    ).fetchone()
    assert dict(tombstone) == {
        "workspace_id": "ws-authenticated",
        "reason": "permission revoked",
        "request_id": "revoke-1",
    }


def test_failed_refresh_preserves_last_good_golden_revision(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "refresh.md"
    source.write_text("stable knowledge\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    draft_response = application.create_skill_draft(
        {
            "workspace_id": "ws-refresh",
            "name": "Refreshable",
            "description": "",
            "source_refs": [str(source)],
        },
        request_id="draft-1",
        idempotency_key="draft-refresh",
    )
    draft_id = draft_response.result.draft.id
    source_id = repository._connection.execute(
        "SELECT id FROM source_revisions"
    ).fetchone()["id"]
    first = application._run_clean(
        SourceCleanPayload(source_revision_id=source_id, recipe_id="first"),
        "ws-refresh",
    ).golden_asset_revision

    source.write_bytes(b"\xff\xfe not valid utf-8")
    refreshed = application.unsupported(
        "refresh.run",
        "refresh-1",
        {"skill_id": draft_id, "trigger": "manual"},
        workspace_id="ws-refresh",
    )

    assert refreshed.accepted is False
    assert refreshed.result.status == "failed"
    assert refreshed.result.error.code == "SOURCE_READ_FAILED"
    assert repository.latest_golden_asset_revision("ws-refresh").id == first.id


def test_schema_drift_refresh_is_blocked_and_last_good_remains_visible(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "schema.csv"
    source.write_text("name,amount\nAlice,1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    created = application.create_skill_draft(
        {
            "workspace_id": "ws-schema",
            "name": "Schema",
            "description": "",
            "source_refs": [str(source)],
        },
        request_id="schema-draft",
        idempotency_key="schema-draft",
    )
    source_id = repository._connection.execute(
        "SELECT id FROM source_revisions"
    ).fetchone()["id"]
    first = application._run_clean(
        SourceCleanPayload(source_revision_id=source_id, recipe_id="schema-first"),
        "ws-schema",
    ).golden_asset_revision
    source.write_text("name,amount,currency\nAlice,1,USD\n", encoding="utf-8")

    refreshed = application.unsupported(
        "refresh.run",
        "schema-refresh",
        {"skill_id": created.result.draft.id, "trigger": "manual"},
        workspace_id="ws-schema",
    )

    assert refreshed.result.error.code == "SCHEMA_CHANGED"
    assert repository.latest_golden_asset_revision("ws-schema").id == first.id


def test_same_schema_refresh_publishes_new_revision_from_staging(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "refresh-success.md"
    source.write_text("version one\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    created = application.create_skill_draft(
        {
            "workspace_id": "ws-refresh-success",
            "name": "Refresh",
            "description": "",
            "source_refs": [str(source)],
        },
        request_id="refresh-draft",
        idempotency_key="refresh-draft",
    )
    source_id = repository._connection.execute(
        "SELECT id FROM source_revisions"
    ).fetchone()["id"]
    first = application._run_clean(
        SourceCleanPayload(source_revision_id=source_id, recipe_id="first"),
        "ws-refresh-success",
    ).golden_asset_revision
    source.write_text("version two\n", encoding="utf-8")

    refreshed = application.unsupported(
        "refresh.run",
        "refresh-success",
        {"skill_id": created.result.draft.id, "trigger": "manual"},
        workspace_id="ws-refresh-success",
    )

    assert refreshed.accepted is True
    assert refreshed.result.status == "succeeded"
    assert refreshed.result.refresh_run.staging_ref is not None
    assert refreshed.result.refresh_run.last_good_revision == first.revision + 1
    assert repository.latest_golden_asset_revision("ws-refresh-success").revision == 2
