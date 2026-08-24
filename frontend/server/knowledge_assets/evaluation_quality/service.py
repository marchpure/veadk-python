from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable
from typing import Literal

from .models import (
    CaseCategory,
    CaseSource,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationRun,
    EvaluationSuite,
    FixPlan,
    PolicyCheck,
    PolicyGateInput,
    PolicyGateResult,
    RunProvenance,
    TypedPatch,
    utc_now,
)
from .ports import (
    CaseEvaluatorPort,
    CaseGraderPort,
    DraftRevisionPort,
    EvaluationRepositoryPort,
)


def _stable_id(prefix: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"


class EvaluationQualityService:
    def __init__(
        self,
        repository: EvaluationRepositoryPort,
        evaluator: CaseEvaluatorPort,
        grader: CaseGraderPort,
        drafts: DraftRevisionPort | None = None,
    ) -> None:
        self.repository = repository
        self.evaluator = evaluator
        self.grader = grader
        self.drafts = drafts

    def create_suite(
        self,
        *,
        suite_id: str,
        skill_id: str,
        cases: Iterable[EvaluationCase],
        pass_threshold: float = 1.0,
    ) -> EvaluationSuite:
        materialized = tuple(cases)
        if not materialized:
            raise ValueError("an evaluation suite requires at least one case")
        case_ids = [case.id for case in materialized]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case ids must be unique")
        payload = [case.model_dump(mode="json") for case in materialized]
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        suite = EvaluationSuite(
            id=suite_id,
            version=self.repository.next_suite_version(suite_id),
            skill_id=skill_id,
            cases=materialized,
            pass_threshold=pass_threshold,
            digest=digest,
        )
        self.repository.save_suite(suite)
        return suite

    def revise_suite(
        self, suite_id: str, version: int, additions: Iterable[EvaluationCase]
    ) -> EvaluationSuite:
        current = self._suite(suite_id, version)
        return self.create_suite(
            suite_id=suite_id,
            skill_id=current.skill_id,
            cases=(*current.cases, *tuple(additions)),
            pass_threshold=current.pass_threshold,
        )

    def confirm_candidates(
        self, suite_id: str, version: int, case_ids: Iterable[str]
    ) -> EvaluationSuite:
        current = self._suite(suite_id, version)
        selected = set(case_ids)
        known_candidates = {
            case.id
            for case in current.cases
            if case.source == CaseSource.AGENT_CANDIDATE
        }
        if not selected or not selected <= known_candidates:
            raise ValueError("candidate confirmation must name existing agent candidates")
        cases = tuple(
            case.model_copy(update={"candidate_confirmed": True})
            if case.id in selected
            else case
            for case in current.cases
        )
        return self.create_suite(
            suite_id=suite_id,
            skill_id=current.skill_id,
            cases=cases,
            pass_threshold=current.pass_threshold,
        )

    def adopt_historical_case(
        self,
        *,
        case_id: str,
        category: CaseCategory,
        input: dict[str, object],
        expected: dict[str, object],
        provenance_ref: str,
        source: CaseSource,
    ) -> EvaluationCase:
        if source not in {
            CaseSource.HISTORICAL_CONVERSATION,
            CaseSource.HISTORICAL_RUN,
        }:
            raise ValueError("historical adoption requires conversation or run source")
        if not provenance_ref:
            raise ValueError("historical adoption requires a provenance reference")
        return EvaluationCase(
            id=case_id,
            source=source,
            category=category,
            input=input,
            expected=expected,
            provenance_ref=provenance_ref,
        )

    def agent_candidate(
        self,
        *,
        case_id: str,
        category: CaseCategory,
        input: dict[str, object],
        expected: dict[str, object],
        provenance_ref: str,
    ) -> EvaluationCase:
        return EvaluationCase(
            id=case_id,
            source=CaseSource.AGENT_CANDIDATE,
            category=category,
            input=input,
            expected=expected,
            provenance_ref=provenance_ref,
        )

    def import_cases(
        self,
        content: str,
        *,
        media_type: Literal["application/json", "text/csv"],
    ) -> tuple[EvaluationCase, ...]:
        if media_type == "application/json":
            rows = json.loads(content)
            if not isinstance(rows, list):
                raise ValueError("JSON evaluation import must be an array")
        else:
            rows = list(csv.DictReader(io.StringIO(content)))
        cases = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"case {index} must be an object")
            source = (
                CaseSource.JSON_IMPORT
                if media_type == "application/json"
                else CaseSource.CSV_IMPORT
            )
            input_value = row.get("input", {})
            expected_value = row.get("expected", {})
            if isinstance(input_value, str):
                input_value = json.loads(input_value)
            if isinstance(expected_value, str):
                expected_value = json.loads(expected_value)
            cases.append(
                EvaluationCase(
                    id=str(row.get("id") or f"import-{index + 1}"),
                    source=source,
                    category=CaseCategory(str(row["category"])),
                    input=input_value,
                    expected=expected_value,
                    grading=row.get("grading", {}),
                    provenance_ref=str(row.get("provenance_ref") or "") or None,
                )
            )
        return tuple(cases)

    def start_run(
        self,
        *,
        suite_id: str,
        suite_version: int,
        provenance: RunProvenance,
        selected_case_ids: Iterable[str] | None = None,
        retry_of: str | None = None,
    ) -> EvaluationRun:
        suite = self._suite(suite_id, suite_version)
        if provenance.suite_id != suite.id or provenance.suite_version != suite.version:
            raise ValueError("run provenance must lock the requested suite version")
        selected = tuple(selected_case_ids or (case.id for case in suite.cases))
        known = {case.id: case for case in suite.cases}
        if not selected or any(case_id not in known for case_id in selected):
            raise ValueError("run contains unknown or empty case selection")
        unconfirmed = [case_id for case_id in selected if not known[case_id].runnable]
        if unconfirmed:
            raise ValueError(
                "agent candidates require explicit confirmation: "
                + ", ".join(unconfirmed)
            )
        attempt = 1
        if retry_of:
            previous = self._run(retry_of)
            attempt = previous.attempt + 1
        identity = {
            "provenance": provenance.model_dump(mode="json"),
            "selected": selected,
            "attempt": attempt,
            "retryOf": retry_of,
        }
        run = EvaluationRun(
            id=_stable_id("evalrun", identity),
            provenance=provenance,
            status="queued",
            selected_case_ids=selected,
            attempt=attempt,
            retry_of=retry_of,
        )
        self.repository.save_run(run)
        return run

    def execute(self, run_id: str, *, max_cases: int | None = None) -> EvaluationRun:
        run = self._run(run_id)
        if run.status in {"succeeded", "failed", "cancelled"}:
            return run
        suite = self._suite(run.provenance.suite_id, run.provenance.suite_version)
        cases = {case.id: case for case in suite.cases}
        completed = {result.case_id for result in run.case_results}
        pending = [case_id for case_id in run.selected_case_ids if case_id not in completed]
        if max_cases is not None:
            pending = pending[:max_cases]
        current = run.model_copy(
            update={"status": "running", "started_at": run.started_at or utc_now()}
        )
        self.repository.save_run(current)
        results = list(current.case_results)
        for case_id in pending:
            latest = self._run(run_id)
            if latest.status == "cancelled":
                return latest
            case = cases[case_id]
            actual = self.evaluator.evaluate(case, run.provenance)
            score, grading = self.grader.grade(case, actual)
            results.append(
                EvaluationCaseResult(
                    case_id=case.id,
                    status="passed" if score >= 1.0 else "failed",
                    score=score,
                    input=case.input,
                    expected=case.expected,
                    actual=actual.output,
                    grading=grading,
                    evidence=actual.evidence,
                    trace_ref=actual.trace_ref,
                    regression_diff={
                        "expected": case.expected,
                        "actual": actual.output,
                    },
                    duration_ms=actual.duration_ms,
                )
            )
            current = current.model_copy(update={"case_results": tuple(results)})
            self.repository.save_run(current)
        all_done = len(results) == len(run.selected_case_ids)
        if not all_done:
            return current
        score = sum(result.score for result in results) / len(results)
        current = current.model_copy(
            update={
                "status": "succeeded" if score >= suite.pass_threshold else "failed",
                "finished_at": utc_now(),
            }
        )
        self.repository.save_run(current)
        return current

    def cancel(self, run_id: str) -> EvaluationRun:
        run = self._run(run_id)
        if run.status in {"succeeded", "failed", "cancelled"}:
            return run
        cancelled = run.model_copy(
            update={"status": "cancelled", "finished_at": utc_now()}
        )
        self.repository.save_run(cancelled)
        return cancelled

    def resume(self, run_id: str) -> EvaluationRun:
        run = self._run(run_id)
        if run.status not in {"queued", "running"}:
            raise ValueError("only queued or interrupted running evaluations can resume")
        return self.execute(run_id)

    def retry(self, run_id: str) -> EvaluationRun:
        run = self._run(run_id)
        if run.status not in {"failed", "cancelled"}:
            raise ValueError("only failed or cancelled evaluations can retry")
        failed = tuple(
            result.case_id
            for result in run.case_results
            if result.status != "passed"
        )
        remaining = tuple(
            case_id
            for case_id in run.selected_case_ids
            if case_id not in {result.case_id for result in run.case_results}
        )
        return self.start_run(
            suite_id=run.provenance.suite_id,
            suite_version=run.provenance.suite_version,
            provenance=run.provenance,
            selected_case_ids=failed + remaining or run.selected_case_ids,
            retry_of=run.id,
        )

    def evaluate_policy(self, policy_input: PolicyGateInput) -> PolicyGateResult:
        required = {
            "schema",
            "data_quality",
            "freshness",
            "permission",
            "security",
            "evaluation",
            "visual_interaction",
            "compatibility",
            "budget",
        }
        dimensions = {check.dimension for check in policy_input.checks}
        missing = required - dimensions
        reasons = [check.machine_reason for check in policy_input.checks if not check.passed]
        reasons.extend(f"MISSING_{name.upper()}_CHECK" for name in sorted(missing))
        identity = policy_input.model_dump(mode="json")
        result = PolicyGateResult(
            id=_stable_id("policy", identity),
            skill_draft_revision=policy_input.skill_draft_revision,
            evaluation_run_id=policy_input.evaluation_run_id,
            decision="blocked" if reasons else "publishable",
            checks=policy_input.checks,
            machine_reasons=tuple(reasons),
        )
        self.repository.save_gate(result)
        return result

    def evaluate_run_policy(
        self,
        run_id: str,
        checks: Iterable[PolicyCheck],
    ) -> PolicyGateResult:
        run = self._run(run_id)
        suite = self._suite(run.provenance.suite_id, run.provenance.suite_version)
        supplied = tuple(check for check in checks if check.dimension != "evaluation")
        score = run.score
        evaluation_passed = (
            run.status == "succeeded"
            and score is not None
            and score >= suite.pass_threshold
        )
        evaluation_check = PolicyCheck(
            dimension="evaluation",
            passed=evaluation_passed,
            machine_reason=(
                "EVALUATION_PASSED"
                if evaluation_passed
                else "EVALUATION_NOT_PUBLISHABLE"
            ),
            evidence_refs=(f"evaluation-run://{run.id}",),
        )
        return self.evaluate_policy(
            PolicyGateInput(
                skill_draft_revision=run.provenance.skill_draft_revision,
                evaluation_run_id=run.id,
                checks=(*supplied, evaluation_check),
            )
        )

    def propose_fix(
        self,
        *,
        run_id: str,
        issue_case_ids: Iterable[str],
        affected_case_ids: Iterable[str],
        conflicts: Iterable[str],
        patch: TypedPatch,
    ) -> FixPlan:
        run = self._run(run_id)
        issue_ids = tuple(issue_case_ids)
        affected_ids = tuple(affected_case_ids)
        known = set(run.selected_case_ids)
        if not issue_ids or not set(issue_ids) <= known:
            raise ValueError("fix issues must belong to the source run")
        if not affected_ids or not set(affected_ids) <= known:
            raise ValueError("affected cases must belong to the source run")
        if patch.base_draft_revision != run.provenance.skill_draft_revision:
            raise ValueError("patch base revision must match the evaluated revision")
        plan = FixPlan(
            id=_stable_id(
                "fix",
                {
                    "run": run_id,
                    "issues": issue_ids,
                    "affected": affected_ids,
                    "patch": patch.model_dump(mode="json"),
                },
            ),
            run_id=run_id,
            issue_case_ids=issue_ids,
            affected_case_ids=affected_ids,
            conflicts=tuple(conflicts),
            patch=patch,
        )
        self.repository.save_fix_plan(plan)
        return plan

    def propose_all_unresolved(
        self,
        *,
        run_id: str,
        affected_case_ids: Iterable[str],
        conflicts: Iterable[str],
        patch: TypedPatch,
    ) -> FixPlan:
        run = self._run(run_id)
        unresolved = tuple(
            result.case_id
            for result in run.case_results
            if result.status != "passed"
        )
        unresolved += tuple(
            case_id
            for case_id in run.selected_case_ids
            if case_id not in {result.case_id for result in run.case_results}
        )
        if not unresolved:
            raise ValueError("the evaluation run has no unresolved cases")
        return self.propose_fix(
            run_id=run_id,
            issue_case_ids=unresolved,
            affected_case_ids=affected_case_ids,
            conflicts=conflicts,
            patch=patch,
        )

    def apply_fix(self, plan_id: str) -> FixPlan:
        plan = self._fix_plan(plan_id)
        if plan.conflicts:
            raise ValueError("fix conflicts must be resolved before applying")
        if self.drafts is None:
            raise RuntimeError("draft revision port is not configured")
        new_revision, undo_token = self.drafts.apply_patch(plan.patch)
        source_run = self._run(plan.run_id)
        provenance = source_run.provenance.model_copy(
            update={"skill_draft_revision": new_revision}
        )
        rerun = self.start_run(
            suite_id=provenance.suite_id,
            suite_version=provenance.suite_version,
            provenance=provenance,
            selected_case_ids=plan.affected_case_ids,
        )
        applied = plan.model_copy(
            update={
                "status": "applied",
                "new_draft_revision": new_revision,
                "rerun_id": rerun.id,
                "undo_token": undo_token,
            }
        )
        self.repository.save_fix_plan(applied)
        return applied

    def undo_fix(self, plan_id: str) -> FixPlan:
        plan = self._fix_plan(plan_id)
        if plan.status != "applied" or not plan.undo_token or self.drafts is None:
            raise ValueError("only an applied fix can be undone")
        self.drafts.undo_patch(plan.undo_token)
        undone = plan.model_copy(update={"status": "undone"})
        self.repository.save_fix_plan(undone)
        return undone

    def _suite(self, suite_id: str, version: int) -> EvaluationSuite:
        suite = self.repository.suite(suite_id, version)
        if suite is None:
            raise KeyError(f"evaluation suite not found: {suite_id}@{version}")
        return suite

    def _run(self, run_id: str) -> EvaluationRun:
        run = self.repository.run(run_id)
        if run is None:
            raise KeyError(f"evaluation run not found: {run_id}")
        return run

    def _fix_plan(self, plan_id: str) -> FixPlan:
        plan = self.repository.fix_plan(plan_id)
        if plan is None:
            raise KeyError(f"fix plan not found: {plan_id}")
        return plan
