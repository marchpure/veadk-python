from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.contracts import (
    LegacySkillManifestInput,
    SkillManifest,
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
from frontend.server.knowledge_assets.workers import JobFramework, JobLeaseError


def build_client() -> TestClient:
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(
            SqliteKnowledgeAssetRepository(":memory:")
        ),
        identity_resolver=lambda request: ("workspace-test", "editor"),
    )
    return TestClient(app)


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

    first = client.post(
        "/api/knowledge-assets/v1/commands", json=body, headers=headers
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["accepted"] is False
    assert first_payload["result"]["resultType"] == "skill-authoring.start"
    assert first_payload["result"]["status"] == "credential_blocked"
    assert first_payload["result"]["operation"]["error_code"] == "credential_blocked"
    assert first_payload["result"]["draft"] is None
    assert [
        item["event_type"] for item in first_payload["result"]["events"]
    ] == ["operation_created", "credential_blocked"]

    replay = client.post(
        "/api/knowledge-assets/v1/commands", json=body, headers=headers
    )
    assert replay.status_code == 200
    replay_payload = replay.json()
    assert replay_payload["operationId"] == first_payload["operationId"]
    assert replay_payload["result"]["operation"]["operation_id"] == (
        first_payload["operationId"]
    )
    read_back = client.get(
        f"/api/knowledge-assets/v1/authoring/operations/{first_payload['operationId']}",
        headers={"X-Request-ID": "authoring-read-1"},
    )
    assert read_back.status_code == 200
    assert read_back.json()["operation"]["status"] == "credential_blocked"
    assert read_back.json()["events"][1]["event_type"] == "credential_blocked"
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
        "failed" if command in {"refresh.run", "skill-draft.run"} else "not_ready"
    )
    assert body["result"]["status"] == expected_status
    expected_code = (
        "SKILL_NOT_FOUND"
        if command == "refresh.run"
        else "SKILL_DRAFT_NOT_FOUND"
        if command == "skill-draft.run"
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
