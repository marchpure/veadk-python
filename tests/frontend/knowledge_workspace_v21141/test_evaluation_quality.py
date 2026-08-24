from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from frontend.server.knowledge_assets.evaluation_quality import (
    CaseCategory,
    CaseSource,
    EvaluationCase,
    EvaluationQualityService,
    PolicyGateInput,
    RunProvenance,
    SqliteEvaluationRepository,
    TypedPatch,
)
from frontend.server.knowledge_assets.evaluation_quality.models import (
    EvaluationActual,
    EvaluationRun,
    EvaluationSuite,
    FixPlan,
    PatchOperation,
    PolicyCheck,
    PolicyGateResult,
)
from frontend.server.knowledge_assets.evaluation_quality.main_repository import (
    MainEvaluationRepository,
)


class RecordingEvaluator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate(
        self, case: EvaluationCase, provenance: RunProvenance
    ) -> EvaluationActual:
        self.calls.append(case.id)
        return EvaluationActual(
            output={"answer": case.input.get("answer", "ok")},
            duration_ms=12,
            trace_ref=f"trace://{provenance.skill_draft_revision}/{case.id}",
            evidence=(f"evidence://{case.id}",),
        )


class CancellingEvaluator(RecordingEvaluator):
    def __init__(self) -> None:
        super().__init__()
        self.cancel = None

    def evaluate(
        self, case: EvaluationCase, provenance: RunProvenance
    ) -> EvaluationActual:
        actual = super().evaluate(case, provenance)
        assert self.cancel is not None
        self.cancel()
        return actual


class ExactGrader:
    def grade(
        self, case: EvaluationCase, actual: EvaluationActual
    ) -> tuple[float, dict[str, object]]:
        passed = actual.output == case.expected
        return (1.0 if passed else 0.0), {"method": "exact", "passed": passed}


class RecordingDrafts:
    def __init__(self) -> None:
        self.applied: list[TypedPatch] = []
        self.undone: list[str] = []

    def apply_patch(self, patch: TypedPatch) -> tuple[str, str]:
        self.applied.append(patch)
        return "skill-1:revision-8", "undo://patch-1"

    def undo_patch(self, undo_token: str) -> str:
        self.undone.append(undo_token)
        return "skill-1:revision-7"


def case(
    case_id: str,
    category: CaseCategory = CaseCategory.NORMAL,
    *,
    source: CaseSource = CaseSource.MANUAL,
    confirmed: bool = False,
    answer: str = "ok",
) -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        source=source,
        category=category,
        input={"answer": answer},
        expected={"answer": "ok"},
        candidate_confirmed=confirmed,
    )


def provenance(version: int = 1) -> RunProvenance:
    return RunProvenance(
        suite_id="suite-1",
        suite_version=version,
        environment="test",
        skill_draft_revision="skill-1:revision-7",
        dependency_revision_refs=("skill://semantic@2",),
        golden_revision_refs=("golden://orders@4",),
        executor_version="executor@sha256:abc",
        renderer_version="renderer@sha256:def",
        data_as_of="2026-08-24T09:30:00+00:00",
    )


def service(
    database: str | Path = ":memory:",
) -> tuple[
    EvaluationQualityService,
    SqliteEvaluationRepository,
    RecordingEvaluator,
    RecordingDrafts,
]:
    repository = SqliteEvaluationRepository(database)
    evaluator = RecordingEvaluator()
    drafts = RecordingDrafts()
    return (
        EvaluationQualityService(repository, evaluator, ExactGrader(), drafts),
        repository,
        evaluator,
        drafts,
    )


def test_main_repository_round_trips_all_w4_aggregate_types() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    repository = MainEvaluationRepository(connection)
    suite = EvaluationSuite(
        id="suite-main",
        version=1,
        skill_id="skill-main",
        cases=(case("case-main"),),
        digest="0" * 64,
    )
    run = EvaluationRun(
        id="run-main",
        provenance=provenance(),
        status="queued",
        selected_case_ids=("case-main",),
    )
    gate = PolicyGateResult(
        id="gate-main",
        skill_draft_revision="skill-1:revision-7",
        evaluation_run_id=run.id,
        decision="blocked",
        checks=(),
        machine_reasons=("NO_POLICY_CHECKS",),
    )
    fix = FixPlan(
        id="fix-main",
        run_id=run.id,
        issue_case_ids=("case-main",),
        affected_case_ids=("case-main",),
        patch=TypedPatch(
            id="patch-main",
            base_draft_revision="skill-1:revision-7",
            operations=(
                PatchOperation(
                    op="replace_metric",
                    path="/metrics/revenue",
                    before="gross",
                    after="net",
                ),
            ),
        ),
    )

    repository.save_suite(suite)
    repository.save_run(run)
    repository.save_gate(gate)
    repository.save_fix_plan(fix)

    assert repository.suite(suite.id, suite.version) == suite
    assert repository.run(run.id) == run
    assert repository.gate(gate.id) == gate
    assert repository.fix_plan(fix.id) == fix


def test_suite_versions_are_immutable_and_cover_every_required_category() -> None:
    app, repository, _, _ = service()
    categories = list(CaseCategory)
    first = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case(f"case-{item.value}", item) for item in categories],
    )
    second = app.revise_suite(
        first.id,
        first.version,
        [
            case(
                "historical-conversation",
                source=CaseSource.HISTORICAL_CONVERSATION,
            ),
            case("historical-run", source=CaseSource.HISTORICAL_RUN),
        ],
    )

    assert first.version == 1
    assert second.version == 2
    assert {item.category for item in first.cases} == set(CaseCategory)
    assert len(repository.suite(first.id, 1).cases) == len(categories)
    assert len(repository.suite(second.id, 2).cases) == len(categories) + 2
    assert first.digest != second.digest


def test_csv_and_json_import_are_typed_and_candidate_requires_confirmation() -> None:
    app, _, _, _ = service()
    csv_cases = app.import_cases(
        'id,category,input,expected\ncsv-1,normal,"{""answer"": ""ok""}",'
        '"{""answer"": ""ok""}"\n',
        media_type="text/csv",
    )
    json_cases = app.import_cases(
        json.dumps(
            [
                {
                    "id": "json-1",
                    "category": "citation",
                    "input": {"answer": "ok"},
                    "expected": {"answer": "ok"},
                }
            ]
        ),
        media_type="application/json",
    )
    candidate = case(
        "candidate-1",
        source=CaseSource.AGENT_CANDIDATE,
    )
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=(*csv_cases, *json_cases, candidate),
    )

    assert csv_cases[0].source == CaseSource.CSV_IMPORT
    assert json_cases[0].source == CaseSource.JSON_IMPORT
    with pytest.raises(ValueError, match="explicit confirmation"):
        app.start_run(
            suite_id=suite.id,
            suite_version=suite.version,
            provenance=provenance(),
        )

    confirmed = app.confirm_candidates(suite.id, suite.version, ["candidate-1"])
    run = app.start_run(
        suite_id=confirmed.id,
        suite_version=confirmed.version,
        provenance=provenance(confirmed.version),
    )
    assert app.execute(run.id).status == "succeeded"


def test_historical_adoption_requires_traceable_source() -> None:
    app, _, _, _ = service()
    adopted = app.adopt_historical_case(
        case_id="history-1",
        category=CaseCategory.AMBIGUITY,
        input={"question": "which quarter?"},
        expected={"clarification_required": True},
        provenance_ref="conversation://session-1/turn-4",
        source=CaseSource.HISTORICAL_CONVERSATION,
    )
    candidate = app.agent_candidate(
        case_id="candidate-1",
        category=CaseCategory.REFUSAL,
        input={"question": "show restricted salary"},
        expected={"refused": True},
        provenance_ref="agent-generation://trace-7",
    )
    assert adopted.provenance_ref
    assert adopted.runnable
    assert not candidate.runnable
    with pytest.raises(ValueError, match="historical adoption"):
        app.adopt_historical_case(
            case_id="bad",
            category=CaseCategory.NORMAL,
            input={},
            expected={},
            provenance_ref="run://1",
            source=CaseSource.MANUAL,
        )


def test_run_pins_complete_provenance_and_survives_repository_restart(
    tmp_path: Path,
) -> None:
    database = tmp_path / "evaluation.sqlite3"
    app, _, evaluator, _ = service(database)
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one"), case("two")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    partial = app.execute(run.id, max_cases=1)
    assert partial.status == "running"
    assert [item.case_id for item in partial.case_results] == ["one"]

    restarted, _, restarted_evaluator, _ = service(database)
    completed = restarted.resume(run.id)
    assert completed.status == "succeeded"
    assert [item.case_id for item in completed.case_results] == ["one", "two"]
    assert restarted_evaluator.calls == ["two"]
    assert completed.provenance.executor_version == "executor@sha256:abc"
    assert completed.provenance.renderer_version == "renderer@sha256:def"
    assert completed.provenance.data_as_of == "2026-08-24T09:30:00+00:00"
    assert completed.case_results[0].input == {"answer": "ok"}
    assert completed.case_results[0].expected == {"answer": "ok"}
    assert completed.case_results[0].actual == {"answer": "ok"}
    assert completed.case_results[0].trace_ref
    assert completed.case_results[0].evidence
    assert evaluator.calls == ["one"]


def test_cancel_and_retry_preserve_original_suite_and_only_retry_unresolved() -> None:
    app, _, evaluator, _ = service()
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("pass"), case("fail", answer="wrong")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    partial = app.execute(run.id, max_cases=1)
    cancelled = app.cancel(partial.id)
    retry = app.retry(cancelled.id)

    assert cancelled.status == "cancelled"
    assert retry.retry_of == cancelled.id
    assert retry.attempt == 2
    assert retry.provenance == cancelled.provenance
    assert retry.selected_case_ids == ("fail",)
    assert evaluator.calls == ["pass"]


def test_replayed_start_does_not_reset_persisted_progress() -> None:
    app, _, _, _ = service()
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one"), case("two")],
    )
    first = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    partial = app.execute(first.id, max_cases=1)
    replay = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    assert replay == partial
    assert len(replay.case_results) == 1


def test_cancellation_during_evaluation_wins_over_late_case_result() -> None:
    repository = SqliteEvaluationRepository()
    evaluator = CancellingEvaluator()
    app = EvaluationQualityService(repository, evaluator, ExactGrader())
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    evaluator.cancel = lambda: app.cancel(run.id)
    result = app.execute(run.id)
    assert result.status == "cancelled"
    assert result.case_results == ()
    assert repository.run(run.id).status == "cancelled"


def test_policy_gate_requires_all_dimensions_and_returns_machine_reasons() -> None:
    app, repository, _, _ = service()
    checks = tuple(
        PolicyCheck(
            dimension=dimension,
            passed=dimension != "security",
            machine_reason=(
                "SECURITY_SCAN_PASSED" if dimension != "security" else "CSP_VIOLATION"
            ),
            evidence_refs=(f"evidence://{dimension}",),
        )
        for dimension in (
            "schema",
            "data_quality",
            "freshness",
            "permission",
            "security",
            "evaluation",
            "visual_interaction",
            "compatibility",
            "budget",
        )
    )
    blocked = app.evaluate_policy(
        PolicyGateInput(
            skill_draft_revision="skill-1:revision-7",
            evaluation_run_id="run-1",
            checks=checks,
        )
    )
    incomplete = app.evaluate_policy(
        PolicyGateInput(
            skill_draft_revision="skill-1:revision-7",
            evaluation_run_id="run-2",
            checks=checks[:-1],
        )
    )

    assert blocked.decision == "blocked"
    assert blocked.machine_reasons == ("CSP_VIOLATION",)
    assert incomplete.decision == "blocked"
    assert "MISSING_BUDGET_CHECK" in incomplete.machine_reasons
    assert repository.gate(blocked.id) == blocked


def test_policy_gate_derives_evaluation_check_from_persisted_run() -> None:
    app, _, _, _ = service()
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    completed = app.execute(run.id)
    non_evaluation_checks = tuple(
        PolicyCheck(
            dimension=dimension,
            passed=True,
            machine_reason=f"{dimension.upper()}_PASSED",
        )
        for dimension in (
            "schema",
            "data_quality",
            "freshness",
            "permission",
            "security",
            "visual_interaction",
            "compatibility",
            "budget",
        )
    )
    gate = app.evaluate_run_policy(completed.id, non_evaluation_checks)
    assert gate.decision == "publishable"
    assert next(
        check for check in gate.checks if check.dimension == "evaluation"
    ).passed


def test_policy_gate_rejects_duplicate_dimensions() -> None:
    app, _, _, _ = service()
    with pytest.raises(ValueError, match="unique"):
        app.evaluate_policy(
            PolicyGateInput(
                skill_draft_revision="skill-1:revision-7",
                evaluation_run_id="run-1",
                checks=(
                    PolicyCheck(
                        dimension="schema",
                        passed=True,
                        machine_reason="SCHEMA_PASSED",
                    ),
                    PolicyCheck(
                        dimension="schema",
                        passed=True,
                        machine_reason="SCHEMA_PASSED_AGAIN",
                    ),
                ),
            )
        )


def test_policy_gate_rejects_duplicate_dimensions() -> None:
    app, _, _, _ = service()
    with pytest.raises(ValueError, match="unique"):
        app.evaluate_policy(
            PolicyGateInput(
                skill_draft_revision="skill-1:revision-7",
                evaluation_run_id="run-1",
                checks=(
                    PolicyCheck(
                        dimension="schema",
                        passed=True,
                        machine_reason="SCHEMA_PASSED",
                    ),
                    PolicyCheck(
                        dimension="schema",
                        passed=True,
                        machine_reason="SCHEMA_PASSED_AGAIN",
                    ),
                ),
            )
        )


def test_fix_plan_shows_scope_conflicts_applies_new_revision_and_scoped_rerun() -> None:
    app, repository, _, drafts = service()
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one"), case("two", answer="wrong")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    failed = app.execute(run.id)
    assert failed.status == "failed"
    expected_before = repository.suite(suite.id, suite.version).cases[1].expected
    patch = TypedPatch(
        id="patch-1",
        base_draft_revision="skill-1:revision-7",
        operations=(
            PatchOperation(
                op="replace_query",
                path="/query/zero_division",
                before="sales / orders",
                after="sales / nullif(orders, 0)",
            ),
        ),
    )
    conflicted = app.propose_fix(
        run_id=run.id,
        issue_case_ids=["two"],
        affected_case_ids=["two"],
        conflicts=["metric is edited by another patch"],
        patch=patch,
    )
    with pytest.raises(ValueError, match="conflicts"):
        app.apply_fix(conflicted.id)

    plan = app.propose_fix(
        run_id=run.id,
        issue_case_ids=["two"],
        affected_case_ids=["two"],
        conflicts=[],
        patch=patch,
    )
    applied = app.apply_fix(plan.id)
    rerun = repository.run(applied.rerun_id)
    assert applied.new_draft_revision == "skill-1:revision-8"
    assert applied.undo_token == "undo://patch-1"
    assert rerun.selected_case_ids == ("two",)
    assert rerun.provenance.skill_draft_revision == "skill-1:revision-8"
    assert (
        repository.suite(suite.id, suite.version).cases[1].expected == expected_before
    )
    assert drafts.applied == [patch]

    undone = app.undo_fix(plan.id)
    assert undone.status == "undone"
    assert drafts.undone == ["undo://patch-1"]


def test_fix_all_unresolved_derives_issue_scope_from_run() -> None:
    app, _, _, _ = service()
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one"), case("two", answer="wrong")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    failed = app.execute(run.id)
    patch = TypedPatch(
        id="patch-all",
        base_draft_revision="skill-1:revision-7",
        operations=(
            PatchOperation(
                op="replace_query",
                path="/query/guard",
                before="unsafe",
                after="safe",
            ),
        ),
    )
    plan = app.propose_all_unresolved(
        run_id=failed.id,
        affected_case_ids=["two"],
        conflicts=[],
        patch=patch,
    )
    assert plan.issue_case_ids == ("two",)


def test_fix_scope_must_include_every_issue() -> None:
    app, _, _, _ = service()
    suite = app.create_suite(
        suite_id="suite-1",
        skill_id="skill-1",
        cases=[case("one", answer="wrong"), case("two", answer="wrong")],
    )
    run = app.start_run(
        suite_id=suite.id,
        suite_version=suite.version,
        provenance=provenance(),
    )
    failed = app.execute(run.id)
    patch = TypedPatch(
        id="patch-incomplete",
        base_draft_revision="skill-1:revision-7",
        operations=(
            PatchOperation(
                op="replace_query",
                path="/query/guard",
                before="unsafe",
                after="safe",
            ),
        ),
    )
    with pytest.raises(ValueError, match="include every issue"):
        app.propose_fix(
            run_id=failed.id,
            issue_case_ids=["one", "two"],
            affected_case_ids=["one"],
            conflicts=[],
            patch=patch,
        )


def test_provider_and_consumer_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValueError):
        EvaluationCase.model_validate(
            {
                "id": "case",
                "source": "manual",
                "category": "normal",
                "input": {},
                "expected": {},
                "payload": {"unknown": True},
            }
        )
    with pytest.raises(ValueError):
        RunProvenance.model_validate(
            {
                "suite_id": "suite-1",
                "suite_version": 1,
                "environment": "test",
                "skill_draft_revision": "skill:1",
                "dependency_revision_refs": [],
                "golden_revision_refs": [],
                "executor_version": "executor:1",
                "renderer_version": "renderer:1",
            }
        )
