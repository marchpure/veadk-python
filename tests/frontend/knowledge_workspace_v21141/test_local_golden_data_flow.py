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
