from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.repository import (
    SqliteKnowledgeAssetRepository,
)
from frontend.server.knowledge_assets.routes import mount_knowledge_asset_routes


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

    created = client.post("/api/knowledge-assets/v1/commands", json=body, headers=headers)
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

    replay = client.post("/api/knowledge-assets/v1/commands", json=body, headers=headers)
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
    assert "does not match any of the expected tags" in unknown.json()["details"]["validation"]

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
                "actions": [{"name": "answer", "description": "Answer a policy question"}],
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
    assert saved_json["result"]["draft"]["manifest"]["actions"][0]["name"] == "answer"

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
        headers={"X-Request-ID": "request-policy-create", "Idempotency-Key": "policy-create-1"},
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
        headers={"X-Request-ID": "request-policy-invalid", "Idempotency-Key": "policy-invalid-1"},
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
        headers={"X-Request-ID": "request-policy-save", "Idempotency-Key": "policy-save-1"},
    )
    assert saved.status_code == 200
    stale = client.post(
        "/api/knowledge-assets/v1/commands",
        json={"command": "skill-draft.save-manifest", "payload": valid},
        headers={"X-Request-ID": "request-policy-stale", "Idempotency-Key": "policy-stale-1"},
    )
    assert stale.status_code == 409
    assert stale.headers["content-type"].startswith("application/problem+json")
    assert stale.json()["code"] == "CONFLICT"
