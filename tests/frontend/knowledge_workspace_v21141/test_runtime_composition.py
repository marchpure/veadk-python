from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets.runtime import create_app
from frontend.server.knowledge_assets.repository import SqliteKnowledgeAssetRepository
from frontend.server.knowledge_assets.workers import JobFramework


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


def test_job_events_resume_after_checkpoint() -> None:
    framework = JobFramework()
    job = framework.enqueue(
        job_type="refresh", idempotency_key="resume-1", profile="test"
    )
    leased = framework.lease(job_id=job.job_id, owner="worker")
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
