from __future__ import annotations

import sqlite3
import time

import pytest

from frontend.server.knowledge_assets.contract_runtime import validate_state_transition
from frontend.server.knowledge_assets.repository import SqliteKnowledgeAssetRepository
from frontend.server.knowledge_assets.workers import JobFramework
from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.contracts import SkillDraftRunPayload


def test_step3_state_machine_covers_budget_and_evaluation_lifecycle() -> None:
    validate_state_transition("draft", "planning")
    validate_state_transition("planning", "awaiting_input")
    validate_state_transition("awaiting_input", "running")
    validate_state_transition("running", "partially_succeeded")
    validate_state_transition("partially_succeeded", "ready_for_evaluation")
    validate_state_transition("ready_for_evaluation", "evaluating")
    validate_state_transition("evaluating", "publishable")

    with pytest.raises(ValueError, match="invalid state transition"):
        validate_state_transition("published", "running")
    with pytest.raises(ValueError, match="invalid state transition"):
        validate_state_transition("cancelled", "running")


def test_existing_step2_database_replays_step3_migration(tmp_path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        );
        INSERT INTO schema_migrations(version, applied_at)
        VALUES ('001_knowledge_assets', CURRENT_TIMESTAMP);
        """
    )
    connection.close()

    repository = SqliteKnowledgeAssetRepository(database)
    tables = {
        row[0]
        for row in repository._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    migrations = {
        row[0]
        for row in repository._connection.execute(
            "SELECT version FROM schema_migrations"
        )
    }
    assert {"skill_results", "skill_view_revisions"} <= tables
    assert "assistant_patch_history" in tables
    assert "skill_view_shares" in tables
    assert "002_step3_views" in migrations
    assert "003_assistant_patch_history" in migrations
    assert "004_step3_shares" in migrations


def test_cancelled_builder_operation_is_fail_closed() -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    operation_id = "run-" + __import__("hashlib").sha256(
        b"cancel-before-run"
    ).hexdigest()[:24]
    repository.create_operation(operation_id, "request")
    repository.cancel_operation(operation_id, "cancel")

    response = application.unsupported(
        "skill-draft.run",
        "request",
        SkillDraftRunPayload(
            draft_id="missing",
            revision=1,
            trace_id="trace",
        ).model_dump(mode="python"),
        idempotency_key="cancel-before-run",
    )
    assert response.accepted is False
    assert response.operation_id == operation_id
    assert response.result is not None
    assert response.result.status == "cancelled"


def test_terminal_operation_cannot_be_overwritten_after_cancel() -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    repository.create_operation("run-race", "request")
    repository.cancel_operation("run-race", "cancel")
    repository.append_operation_event(
        "run-race",
        __import__(
            "frontend.server.knowledge_assets.contracts",
            fromlist=["OperationEvent"],
        ).OperationEvent(
            operation_id="run-race",
            event_id="run-race:late-success",
            sequence=2,
            occurred_at="2026-08-25T00:00:00Z",
            type="succeeded",
            terminal=True,
        ),
        status="succeeded",
    )
    operation = repository.operation("run-race")
    assert operation is not None
    assert operation.status == "cancelled"
    assert [event.type for event in operation.events] == ["cancelled"]


def test_async_builder_cancel_during_execution_does_not_commit_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    entered = __import__("threading").Event()
    release = __import__("threading").Event()

    def checkpoint() -> None:
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr(application, "_execution_checkpoint", checkpoint)
    operation_id = "run-" + __import__("hashlib").sha256(
        b"async-cancel"
    ).hexdigest()[:24]
    repository.create_operation(operation_id, "request")
    application._builder_executor.submit(
        application._complete_builder_operation,
        SkillDraftRunPayload(
            draft_id="missing",
            revision=1,
            trace_id="trace",
        ),
        "request",
        operation_id,
        "workspace-local",
    )
    assert entered.wait(timeout=2)
    cancelled = repository.cancel_operation(operation_id, "cancel")
    assert cancelled.status == "cancelled"
    release.set()
    for _ in range(20):
        operation = repository.operation(operation_id)
        if operation is not None and operation.events and operation.events[-1].terminal:
            break
        time.sleep(0.01)
    operation = repository.operation(operation_id)
    assert operation is not None
    assert operation.status == "cancelled"
    assert operation.events[-1].type == "cancelled"


def test_async_builder_operation_reaches_terminal_state() -> None:
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    operation_id = "run-" + __import__("hashlib").sha256(
        b"async-terminal"
    ).hexdigest()[:24]
    repository.create_operation(operation_id, "request")
    application._builder_executor.submit(
        application._complete_builder_operation,
        SkillDraftRunPayload(
            draft_id="missing",
            revision=1,
            trace_id="trace",
        ),
        "request",
        operation_id,
        "workspace-local",
    )
    for _ in range(100):
        operation = repository.operation(operation_id)
        if operation is not None and operation.events and operation.events[-1].terminal:
            break
        time.sleep(0.01)
    operation = repository.operation(operation_id)
    assert operation is not None
    assert operation.status == "failed"
    assert operation.events[-1].type == "failed"


def test_job_framework_restores_lease_and_events_from_sqlite(tmp_path) -> None:
    repository = SqliteKnowledgeAssetRepository(tmp_path / "jobs.sqlite3")
    first = JobFramework(connection=repository._connection, lock=repository._lock)
    job = first.enqueue(
        job_type="skill-draft.run",
        idempotency_key="restart-proof",
        profile="test",
    )
    first.lease(job_id=job.job_id, owner="worker", ttl_seconds=30)
    first.heartbeat(job_id=job.job_id, owner="worker", ttl_seconds=30)

    restored = JobFramework(connection=repository._connection, lock=repository._lock)
    replay = restored.enqueue(
        job_type="skill-draft.run",
        idempotency_key="restart-proof",
        profile="test",
    )
    assert replay.job_id == job.job_id
    assert replay.status == "running"
    assert [event.event_type for event in restored.events(job.job_id)] == [
        "enqueued",
        "leased",
        "heartbeat",
    ]
