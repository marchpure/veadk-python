from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from frontend.server.knowledge_assets.application import KnowledgeAssetApplication
from frontend.server.knowledge_assets.contracts import (
    SkillOperation,
    SkillDraftRunPayload,
    SourceCleanPayload,
    SourceProfilePayload,
)
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


def test_bff_skill_draft_run_builds_typed_knowledge_view_from_golden_asset(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "policy.md"
    source.write_text("# Policy\n\nRevenue is stable.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    app = FastAPI()
    mount_knowledge_asset_routes(
        app,
        application=KnowledgeAssetApplication(repository),
        identity_resolver=lambda request: ("ws", "editor"),
    )
    client = TestClient(app)

    created = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.create",
            "payload": {
                "workspaceId": "ws",
                "name": "Policy",
                "description": "Answer policy questions",
                "sourceRefs": [str(source)],
            },
        },
        headers={"X-Request-ID": "run-create", "Idempotency-Key": "run-create"},
    )
    draft = created.json()["result"]["draft"]
    source_id = repository._connection.execute(
        "SELECT id FROM source_revisions"
    ).fetchone()["id"]
    cleaned = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "source.clean",
            "payload": {"sourceRevisionId": source_id, "recipeId": "run-clean"},
        },
        headers={"X-Request-ID": "run-clean", "Idempotency-Key": "run-clean"},
    )
    golden = cleaned.json()["result"]["goldenAssetRevision"]
    manifest = {
        "apiVersion": "knowledge.veadk.io/v1alpha1",
        "kind": "Skill",
        "metadata": {
            "id": draft["id"],
            "version": "1.0.0",
            "displayName": "Policy",
            "description": "Answer policy questions",
            "owner": {"workspaceId": "ws", "principalId": "local"},
        },
        "spec": {
            "kind": "knowledge",
            "contract": {
                "inputSchemaRef": {
                    "uri": "local://schema/input",
                    "version": "1",
                    "sha256": "0" * 64,
                },
                "outputSchemaRef": {
                    "uri": "local://schema/output",
                    "version": "1",
                    "sha256": "0" * 64,
                },
                "operations": [
                    {
                        "name": "answer",
                        "description": "Answer from the attached Golden Asset",
                        "inputSchemaRef": {
                            "uri": "local://schema/input",
                            "version": "1",
                            "sha256": "0" * 64,
                        },
                        "outputSchemaRef": {
                            "uri": "local://schema/output",
                            "version": "1",
                            "sha256": "0" * 64,
                        },
                    }
                ],
            },
            "dependencies": {"goldenAssets": [golden["id"]]},
            "policyRef": {"uri": "permission://workspace/ws", "version": "1"},
            "runtimeRef": "runtime://knowledge/v1",
            "kindSpec": {
                "kind": "knowledge",
                "retrievalMode": "keyword",
                "sourceRevisionRefs": [source_id],
            },
        },
    }
    saved = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.save-manifest",
            "payload": {
                "draftId": draft["id"],
                "baseRevision": draft["revision"],
                "manifest": manifest,
            },
        },
        headers={"X-Request-ID": "run-save", "Idempotency-Key": "run-save"},
    )
    assert saved.status_code == 200
    revision = saved.json()["result"]["draft"]["revision"]

    partial = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.run",
            "payload": {
                "draftId": draft["id"],
                "revision": revision,
                "traceId": "trace-partial",
                "maxSteps": 1,
                "budget": 1000,
            },
        },
        headers={"X-Request-ID": "run-partial", "Idempotency-Key": "run-partial"},
    )
    assert partial.status_code == 200
    assert partial.json()["accepted"] is False
    assert partial.json()["result"]["status"] == "partially_succeeded"
    partial_operation_id = partial.json()["operationId"]

    ran = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "skill-draft.retry",
            "payload": {
                "draftId": draft["id"],
                "revision": revision,
                "traceId": "trace-real-knowledge",
                "maxSteps": 3,
                "budget": 1000,
                "retryOfOperationId": partial_operation_id,
            },
        },
        headers={"X-Request-ID": "run-execute", "Idempotency-Key": "run-execute"},
    )

    assert ran.status_code == 200
    assert ran.json()["accepted"] is True
    result = ran.json()["result"]
    assert result["status"] == "ready_for_evaluation"
    assert result["skillResult"]["resultRef"]["sha256"]
    assert result["viewIntent"]["template"] == "knowledge"
    assert result["skillViewRevision"]["viewModel"]["answer"] == (
        "# Policy\nRevenue is stable."
    )
    assert result["skillViewRevision"]["manifest"]["cspProfile"] == "trusted-renderer-v1"
    assert ran.json()["operationId"].startswith("run-")
    operation = client.get(
        f"/api/knowledge-assets/v1/operations/{ran.json()['operationId']}",
        headers={"X-Request-ID": "read-run-operation"},
    )
    assert operation.status_code == 200
    assert [event["type"] for event in operation.json()["events"]] == [
        "accepted",
        "progress",
        "succeeded",
    ]

    evaluated = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "evaluation.run",
            "payload": {
                "targetId": draft["id"],
                "suiteId": "policy-suite",
                "environment": "test",
                "caseIds": ["answer-policy"],
            },
        },
        headers={"X-Request-ID": "run-evaluation", "Idempotency-Key": "run-evaluation"},
    )
    assert evaluated.status_code == 200
    evaluation = evaluated.json()["result"]
    assert evaluation["status"] == "succeeded"
    assert evaluation["evaluationRun"]["dataRevisionRefs"] == [golden["id"]]
    assert evaluation["evaluationRun"]["caseResults"][0]["status"] == "passed"
    assert evaluation["policyGateResult"]["decision"] == "publishable"
    assert evaluation["policyGateResult"]["machineReasons"] == [
        "EVAL_SCORE_AT_OR_ABOVE_THRESHOLD",
        "SKILL_RESULT_BOUND_TO_CURRENT_REVISION",
        "SKILL_VIEW_BOUND_TO_CURRENT_REVISION",
    ]

    invoked = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "invocation.start",
            "payload": {
                "skillVersionId": f"test://{draft['id']}:{revision}",
                "skillViewRevisionId": repository._connection.execute(
                    "SELECT id FROM skill_view_revisions WHERE skill_revision_id = ?",
                    (evaluation["evaluationRun"]["skillRevisionId"],),
                ).fetchone()["id"],
                "inputRef": {
                    "uri": "inline://question",
                    "kind": "inline",
                    "sha256": "0" * 64,
                    "mediaType": "application/json",
                },
                "callerId": "acceptance-test",
            },
        },
        headers={"X-Request-ID": "run-invocation", "Idempotency-Key": "run-invocation"},
    )
    assert invoked.status_code == 200
    invocation = invoked.json()["result"]["invocation"]
    assert invoked.json()["result"]["status"] == "succeeded"
    assert invocation["skillViewRevisionId"].startswith("view-")
    assert invocation["status"] == "succeeded"
    assert invoked.json()["result"]["skillResult"]["id"].startswith("result-")
    assert invoked.json()["result"]["dataRevisionRefs"] == [golden["id"]]

    exported = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "artifact.export",
            "payload": {"resourceId": draft["id"], "format": "json"},
        },
        headers={"X-Request-ID": "run-export", "Idempotency-Key": "run-export"},
    )
    assert exported.status_code == 200
    export_result = exported.json()["result"]
    assert export_result["status"] == "succeeded"
    assert export_result["artifactRef"]["sha256"] == result["skillResult"]["resultRef"]["sha256"]
    assert export_result["artifactRef"]["uri"].startswith("local://export/")

    exported_csv = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "artifact.export",
            "payload": {"resourceId": draft["id"], "format": "csv"},
        },
        headers={"X-Request-ID": "run-export-csv", "Idempotency-Key": "run-export-csv"},
    )
    assert exported_csv.status_code == 200
    assert exported_csv.json()["result"]["status"] == "succeeded"
    assert exported_csv.json()["result"]["artifactRef"]["mediaType"] == "text/csv"
    assert exported_csv.json()["result"]["artifactRef"]["uri"].endswith(".csv")

    shared = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "resource.share",
            "payload": {"resourceId": draft["id"]},
        },
        headers={"X-Request-ID": "run-share", "Idempotency-Key": "run-share"},
    )
    assert shared.status_code == 200
    share_result = shared.json()["result"]
    assert share_result["status"] == "succeeded"
    assert share_result["shareGrant"]["permission"] == "read"
    assert share_result["shareGrant"]["skillViewRevisionId"] == invocation["skillViewRevisionId"]

    rejected = client.post(
        "/api/knowledge-assets/v1/commands",
        json={
            "command": "invocation.start",
            "payload": {
                "skillVersionId": f"test://{draft['id']}:{revision}",
                "skillViewRevisionId": "view-missing",
                "inputRef": {
                    "uri": "inline://question",
                    "kind": "inline",
                    "sha256": "0" * 64,
                    "mediaType": "application/json",
                },
                "callerId": "acceptance-test",
            },
        },
        headers={"X-Request-ID": "run-invocation-missing", "Idempotency-Key": "run-invocation-missing"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["result"]["status"] == "failed"
    assert rejected.json()["result"]["error"]["code"] == "SKILL_VIEW_REVISION_NOT_FOUND"


def test_assistant_turn_validates_context_returns_diff_and_reruns(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "assistant.md"
    source.write_text("Answer from source.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    draft, _ = repository.create_skill_draft(
        workspace_id="ws",
        name="Assistant",
        description="before",
        source_refs=[str(source)],
        request_id="create",
        idempotency_key="create",
    )
    revision = application._register_local_source(
        str(source), workspace_id="ws", request_id="source"
    )
    assert revision is not None
    cleaned = application._run_clean(
        SourceCleanPayload(source_revision_id=revision.id, recipe_id="clean"), "ws"
    )
    manifest = draft.manifest.model_copy(
        update={
            "spec": draft.manifest.spec.model_copy(
                update={
                    "contract": draft.manifest.spec.contract.model_copy(
                        update={
                            "operations": [
                                SkillOperation(
                                    name="answer",
                                    input_schema_ref=draft.manifest.spec.contract.input_schema_ref,
                                    output_schema_ref=draft.manifest.spec.contract.output_schema_ref,
                                )
                            ]
                        }
                    )
                }
            )
        }
    )
    manifest = manifest.model_copy(
        update={
            "spec": manifest.spec.model_copy(
                update={
                    "dependencies": manifest.spec.dependencies.model_copy(
                        update={"golden_assets": [cleaned.golden_asset_revision.id]}
                    )
                }
            )
        }
    )
    draft, _ = repository.save_manifest(
        draft_id=draft.id,
        base_revision=draft.revision,
        manifest=manifest,
        request_id="save",
        idempotency_key="save",
    )
    result = application.unsupported(
        "assistant.turn",
        "assistant-request",
        {
            "text": "rename this skill",
            "context": {
                "skillId": draft.id,
                "viewRevisionId": "view-before",
                "selectedIds": [],
                "schemaRef": "local://schema/input",
                "permissionScope": "permission://workspace/ws",
            },
            "patch": {
                "patchId": "patch-1",
                "skillId": draft.id,
                "baseRevision": draft.revision,
                "operation": "set_description",
                "value": "after",
            },
        },
        workspace_id="ws",
    )
    assert result.accepted is True
    assistant = result.result
    assert assistant.result_type == "assistant.turn"
    assert assistant.status == "succeeded"
    assert assistant.diff.before == "before"
    assert assistant.diff.after == "after"
    assert assistant.diff.next_revision == draft.revision + 1
    assert assistant.rerun.status == "ready_for_evaluation"
    assert assistant.rerun.skill_result.kind == "knowledge"
    undo = application.unsupported(
        "assistant.turn",
        "assistant-undo",
        {
            "text": "undo",
            "context": {
                "skillId": draft.id,
                "viewRevisionId": "view-before",
                "selectedIds": [],
                "schemaRef": "local://schema/input",
                "permissionScope": "permission://workspace/ws",
            },
            "patch": {
                "patchId": "patch-undo",
                "skillId": draft.id,
                "baseRevision": assistant.diff.next_revision,
                "operation": "set_description",
                "value": "ignored-by-undo",
                "undoToken": assistant.diff.undo_token,
            },
        },
        workspace_id="ws",
    )
    assert undo.result.status == "succeeded"
    assert undo.result.diff.before == "after"
    assert undo.result.diff.after == "before"
    assert undo.result.rerun.status == "ready_for_evaluation"


def test_evaluation_sources_are_content_addressed_and_candidates_block_gate(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "evaluation.md"
    source.write_text("Evaluation source.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    draft, _ = repository.create_skill_draft(
        workspace_id="ws",
        name="Evaluation",
        description="",
        source_refs=[str(source)],
        request_id="create",
        idempotency_key="create",
    )
    registered = application._register_local_source(
        str(source), workspace_id="ws", request_id="source"
    )
    assert registered is not None
    cleaned = application._run_clean(
        SourceCleanPayload(source_revision_id=registered.id, recipe_id="clean"), "ws"
    )
    manifest = draft.manifest.model_copy(
        update={
            "spec": draft.manifest.spec.model_copy(
                update={
                    "dependencies": draft.manifest.spec.dependencies.model_copy(
                        update={"golden_assets": [cleaned.golden_asset_revision.id]}
                    ),
                    "contract": draft.manifest.spec.contract.model_copy(
                        update={
                            "operations": [
                                SkillOperation(
                                    name="answer",
                                    input_schema_ref=draft.manifest.spec.contract.input_schema_ref,
                                    output_schema_ref=draft.manifest.spec.contract.output_schema_ref,
                                )
                            ]
                        }
                    ),
                }
            )
        }
    )
    draft, _ = repository.save_manifest(
        draft_id=draft.id,
        base_revision=draft.revision,
        manifest=manifest,
        request_id="save",
        idempotency_key="save",
    )
    executed = application._run_skill_draft(
        SkillDraftRunPayload(
            draft_id=draft.id,
            revision=draft.revision,
            trace_id="evaluation-apply-execution",
        ),
        request_id="evaluation-apply-execution",
    )
    assert executed.status == "ready_for_evaluation"
    evaluated = application.unsupported(
        "evaluation.apply",
        "evaluation-apply",
        {
            "targetId": draft.id,
            "suiteId": "mixed-suite",
            "environment": "test",
            "cases": [
                {
                    "id": "manual-1",
                    "inputRef": {
                        "uri": "inline://manual",
                        "kind": "inline",
                        "sha256": "1" * 64,
                        "mediaType": "application/json",
                    },
                    "source": "manual",
                },
                {
                    "id": "historical-1",
                    "inputRef": {
                        "uri": "inline://historical",
                        "kind": "inline",
                        "sha256": "2" * 64,
                        "mediaType": "application/json",
                    },
                    "source": "historical",
                },
                {
                    "id": "batch-1",
                    "inputRef": {
                        "uri": "inline://batch",
                        "kind": "inline",
                        "sha256": "3" * 64,
                        "mediaType": "application/json",
                    },
                    "source": "batch",
                },
                {
                    "id": "candidate-1",
                    "inputRef": {
                        "uri": "inline://candidate",
                        "kind": "inline",
                        "sha256": "4" * 64,
                        "mediaType": "application/json",
                    },
                    "source": "agent_candidate",
                },
            ],
        },
        workspace_id="ws",
    )
    assert evaluated.result.result_type == "evaluation.apply"
    assert evaluated.result.status == "failed"
    assert evaluated.result.evaluation_suite.case_count == 4
    assert evaluated.result.evaluation_suite.cases_ref.uri.startswith(
        "local://evaluation-cases/"
    )
    assert all(
        case.evidence_ref is not None and case.regression_diff_ref is not None
        for case in evaluated.result.evaluation_run.case_results
    )
    assert evaluated.result.policy_gate_result.decision == "blocked"
    assert evaluated.result.policy_gate_result.machine_reasons == [
        "EVAL_SCORE_BELOW_THRESHOLD"
    ]


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


def test_source_revision_replay_cannot_replace_an_existing_revision(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "immutable.md"
    source.write_text("first\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    first = application._register_local_source(
        str(source), workspace_id="ws-immutable", request_id="r1"
    )
    assert first is not None
    source.write_text("second\n", encoding="utf-8")
    replay = first.model_copy(
        update={
            "source_digest": "f" * 64,
            "content_ref": first.content_ref.model_copy(
                update={"sha256": "f" * 64, "bytes": 7}
            ),
        }
    )
    repository.save_source_revision(replay, "ws-immutable", str(source))
    stored = repository.source_revision(first.id)
    assert stored is not None
    assert stored.source_digest == first.source_digest


def test_same_content_refresh_keeps_both_golden_asset_rows(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "repeat.md"
    source.write_text("same\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    repository = SqliteKnowledgeAssetRepository(":memory:")
    application = KnowledgeAssetApplication(repository)
    first_source = application._register_local_source(
        str(source), workspace_id="ws-repeat", request_id="r1"
    )
    first = application._run_clean(
        SourceCleanPayload(source_revision_id=first_source.id, recipe_id="recipe-1"),
        "ws-repeat",
    ).golden_asset_revision
    second_source = application._register_local_source(
        str(source), workspace_id="ws-repeat", request_id="r2"
    )
    second = application._run_clean(
        SourceCleanPayload(source_revision_id=second_source.id, recipe_id="recipe-2"),
        "ws-repeat",
    ).golden_asset_revision
    rows = repository._connection.execute(
        "SELECT id FROM golden_asset_revisions WHERE workspace_id = ? ORDER BY revision",
        ("ws-repeat",),
    ).fetchall()
    assert len(rows) == 2
    assert first.id != second.id


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
