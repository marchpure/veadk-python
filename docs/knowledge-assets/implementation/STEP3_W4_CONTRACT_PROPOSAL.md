# STEP 3 Worker 4 Contract Proposal

Status: `READY_FOR_MAIN_REVIEW`

Worker implementation:
`frontend/server/knowledge_assets/evaluation_quality/`

Main owns the public contracts, generated clients, migrations, shared
repository, application composition, and BFF routes. Integrate the worker
module through those seams without copying the previous synthetic
`_run_evaluation` behavior.

## Public Models

- `EvaluationCase`: source, category, input, expected, grading,
  provenanceRef, candidateConfirmed.
- `EvaluationSuite`: immutable `(id, version)`, ordered cases,
  passThreshold, createdAt, content digest.
- `RunProvenance`: suite id/version, environment, SkillDraftRevision,
  all dependency and Golden revision refs, executor version, renderer version,
  and dataAsOf.
- `EvaluationCaseResult`: input, expected, actual, grading, score, evidence,
  trace, regression diff, and duration.
- `EvaluationRun`: durable queued/running/succeeded/failed/cancelled state,
  selected case IDs, attempt, retryOf, timestamps, and provenance.
- `PolicyGateResult`: checks and machine reasons for schema, data quality,
  freshness, permission, security, evaluation, visual/interaction,
  compatibility, and budget.
- `FixPlan`: issue scope, affected scope, conflicts, typed patch,
  new draft revision, scoped rerun, and undo token.

The public models should retain `extra=forbid`. Do not add `payload: unknown`.

## Typed Commands

Add discriminated commands and generated clients for:

- `evaluation-suite.create`
- `evaluation-suite.revise`
- `evaluation-case.import`
- `evaluation-case.adopt-history`
- `evaluation-case.generate-candidates`
- `evaluation-case.confirm-candidates`
- `evaluation-run.start`
- `evaluation-run.cancel`
- `evaluation-run.resume`
- `evaluation-run.retry`
- `evaluation-fix.propose`
- `evaluation-fix.propose-all-unresolved`
- `evaluation-fix.apply`
- `evaluation-fix.undo`
- `policy-gate.evaluate`

`evaluation-run.start` must reject unconfirmed Agent candidates.
`policy-gate.evaluate` must derive the evaluation dimension from the persisted
run and may not trust a client-supplied PASS.

## Persistence

Add a Main-owned migration with append-only suite versions and durable run,
case-result, policy-gate, fix-plan, and undo records. The Worker 4 SQLite
repository demonstrates the storage contract but is not a substitute for
SQLite/PostgreSQL parity in the shared repository.

## Application Integration

- Inject real evaluator and grader ports; never infer PASS from case source.
- Store evidence and large inputs/actuals/diffs by content-addressed reference
  when they exceed the row limit.
- Map evaluation runs to the shared Job Framework for lease, heartbeat,
  cancellation, bounded retry, dead letter, and restart recovery.
- Apply fixes only through the Agent authoring typed patch port. A fix creates
  a new draft revision and reruns only affected cases. Expected values remain
  immutable.
- STEP 3 returns publish eligibility only. It must not create
  `PublishedSkillVersion`, Registry entries, Agent bindings, or Invocations.

## Existing Gap

The checkpoint implementation in `application.py::_run_evaluation` hardcodes
suite version 1, generates synthetic pass/fail outcomes from case source,
duplicates evidence as regression diff, omits executor/renderer/dataAsOf,
does not persist cancellation/retry/resume, and gates only on score. Main
should replace that path with this port rather than adapting it incrementally.
