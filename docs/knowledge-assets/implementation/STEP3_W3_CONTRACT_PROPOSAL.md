# STEP 3 Worker 3 Contract Proposal

Status: `PROPOSED_FOR_MAIN_INTEGRATION`

Worker: Backend Worker 3 — Multi-kind Skill Execution & View Projection

## Scope

Worker 3 adds a narrow backend runtime seam for the five non-`data_access`
Skill kinds:

- `knowledge`
- `semantic`
- `analysis`
- `graph_ontology`
- `monitoring`

The implementation lives in `frontend/server/knowledge_assets/kind_runtime/`
and deliberately does not modify shared DTOs, generated contracts, shared
migrations, application/root routes, frontend shell files, frozen UI, or
lockfiles.

## Proposed Main wiring

Main should adapt `skill-draft.run` to this owned port after resolving the
already-persisted inputs:

1. Load `SkillDraftRevision`.
2. Load authorized `GoldenAssetRevision` rows named by
   `manifest.spec.dependencies.goldenAssets`.
3. Read Golden Asset bytes through a production object-store adapter.
4. Construct `KindExecutionRequest` with caller/workspace, data-access refs,
   downstream Skill refs, budget, freshness, idempotency key, trace id, and
   cancel flag.
5. Construct `KindRuntime` with production implementations of the provider
   ports and a durable `KindRuntimeRepository`.
6. Call `KindRuntime.execute(request)`, `retry(request,
   retry_of_operation_id=...)`, `cancel(idempotency_key)`, or
   `recover_incomplete()` as appropriate for the job lifecycle.
7. Persist exactly one `SkillResult`, one `SkillViewRevision`, trace/evidence
   refs, monitoring lifecycle record, and invocation/job record using existing
   repository semantics.

## Request shape

`KindExecutionRequest` contains:

- `draftRevision`: typed `SkillDraftRevision`
- `callerId`
- `workspaceId`
- `goldenAssetRevisions`
- `goldenAssetContents`
- `dataAccessRevisionRefs`
- `downstreamSkillRevisionRefs`
- `budget`
- `freshnessAt`
- `idempotencyKey`
- `traceId`
- `cancelRequested`
- `rerunScope`
- `now`

Provider ports exported by `frontend.server.knowledge_assets.kind_runtime`:

- `RetrievalProvider`: returns permission-scoped `RetrievalHit` records and an
  answer/no-answer decision.
- `SemanticProvider`: returns entities, fields, measures, aggregations, units,
  joins, editable MDL, ambiguities, and dependency errors.
- `QueryExecutor`: consumes a fixed `QueryPlan` and executes only controlled
  read-only plans.
- `GraphMappingProvider`: returns graph entities and relationships backed by
  schema/mapping/evidence locators.
- `KindRuntimeRepository`: persists operation lifecycle, idempotency replay,
  cancellation flags, retry records, and incomplete operation discovery.
- `DashboardArtifactRequest`: W3 Dashboard generation input carrying W2
  `DashboardBuildPlan`, W1 `GoldenAssetRevision` and Golden Data content,
  `SkillManifest`, caller/workspace, and generation time.
- `DashboardBuildResult`: W3 Dashboard artifact output carrying workspace
  paths, build/serve commands, content refs, KPI/chart/table/insight values,
  revision/lineage digests, and `PublishReadyArtifactContract`.

`ExecutionBudget` contains:

- `maxSteps`
- `maxRows`
- `maxBytes`
- `timeoutMs`
- `freshnessSeconds`

## Result shape

`KindRuntime.execute` returns `SkillKindExecutionRecord`:

- stable `operationId` derived from `idempotencyKey`
- lifecycle `status`: `queued`, `running`, `awaiting_input`, `succeeded`,
  `failed`, or `cancelled`
- typed `state`: `ok`, `no_data`, `unable_to_answer`,
  `permission_denied`, `schema_drift`, `validation_failed`, `timeout`,
  `over_budget`, `cancelled`, or `credential_blocked`
- typed `SkillResult`
- typed `ViewIntent`
- typed, content-addressed `SkillViewRevision`
- content-addressed result payload ref
- content-addressed trace ref
- content-addressed evidence ref
- `retryOfOperationId` when produced by retry
- `monitoringLifecycle` with persisted observations, alerts, last-good,
  duration, and preview action candidates

## Handler matrix

| Kind | Handler | Template | Behavior |
|---|---|---|---|
| `knowledge` | `KnowledgeHandler` | `knowledge` | Uses `RetrievalProvider` instead of line keyword matching, emits permission-scoped citations, and returns explicit no-answer/refusal reasons. |
| `semantic` | `SemanticHandler` | `semantic` | Uses `SemanticProvider` for entities, joins, metrics, aggregations, units, permissions, and editable MDL; rejects sensitive fields, ambiguous fields, relationship cycles, and dependency errors. |
| `analysis` | `AnalysisHandler` | `chart` | Requires a fixed `queryPlanRef`, executes through `QueryExecutor`, enforces read-only/data permissions/budgets, and never auto-selects the first inferred dimension/metric. |
| `graph_ontology` | `GraphOntologyHandler` | `graph_ontology` | Uses `GraphMappingProvider` to build ontology nodes/relations from schema/mapping/evidence; no positional `related_to` edge generation. |
| `monitoring` | `MonitoringHandler` | `monitoring` | Builds observations, alerts, preview-only action candidates, freshness/last-good facts, threshold/change-rate signals, and evidence. It does not execute scheduler or external actions. |

## Lifecycle semantics

- `execute` is idempotent by `idempotencyKey`; a completed operation is replayed
  as-is from the repository.
- concurrent same-key executions wait for the first writer and return the
  persisted record.
- `cancel(idempotency_key)` marks the running operation; runtime polling returns
  a terminal `cancelled` record and prevents late success from replacing it.
- `retry` requires a persisted failed, awaiting-input, or cancelled source
  operation and records `retryOfOperationId`.
- `recover_incomplete()` returns queued/running/awaiting-input/cancelled
  operation ids that have no terminal result JSON after process restart.
- timeout is enforced by bounded future waits plus terminal `timeout` records.

## Dashboard artifact contract for Main

W3 exports `generate_dashboard_artifact(request)` and
`capture_dashboard_screenshot(result, executable_path=...)`. The screenshot
path must use Playwright with Chrome (`channel="chrome"` or an explicit Chrome
executable path), not a static image fixture.

Main-owned inputs:

1. W2 produces `DashboardBuildPlan`.
2. W1 provides authorized `GoldenAssetRevision` and Golden Data bytes.
3. Main supplies caller/workspace identity and later connects the
   publish-ready artifact to the canonical Skill publishing chain.

W3-owned outputs:

- independent frontend artifact workspace;
- source files: `src/index.html`, `src/styles.css`, `src/dashboard.js`,
  `src/dashboard-data.json`, `src/chart-config.json`, `src/build.mjs`,
  `src/serve.mjs`;
- metadata/config: `skill-manifest.json`, `build-plan.json`,
  `data/golden.json`, `package.json`, `package-lock.json`,
  `artifact-manifest.json`, `revision.json`, `lineage.json`, `build.json`;
- build output: `dist/index.html`, `dist/styles.css`, `dist/dashboard.js`,
  `dist/dashboard-data.json`, `dist/chart-config.json`;
- commands: `npm run build --prefix <workspace>` and
  `npm run serve --prefix <workspace>`;
- publish-ready handoff: `publish-ready-artifact.json` with
  `designSystemVersion=v2.13.1`, `artifactManifestRef`, and
  `mainPublishAction=MAIN_PUBLISH_CHAIN_REQUIRED`.

W3 explicitly does not define a second publish/reinvoke runtime. Publication,
permission expansion, and invocation routing remain Main-owned.

## Shared contract changes requested from Main

No generated/shared DTOs were changed by Worker 3. Main should consider these
non-blocking contract extensions:

1. Add Worker 3 execution `state` to public `SkillDraftRunResult` so UI can
   distinguish `no_data`, `unable_to_answer`, `permission_denied`,
   `schema_drift`, `over_budget`, `timeout`, and `credential_blocked` without
   parsing error messages.
2. Add `traceRef` and `evidenceRef` to public run results and Skill View
   headers.
3. Add explicit `dataRevisionRefs`, `renderedAt`, `dataAsOf`, and `source`
   fields to the Skill View header DTO instead of deriving them in the browser.
4. Replace duplicated view persistence in
   `frontend/server/knowledge_assets/application.py::_run_skill_draft`; the
   current checkpoint calls `save_skill_view_revision(view_revision)` twice.
5. Wire `KindRuntime` behind `skill-draft.run` only after Main owns the shared
   application/repository changes.
6. Add a Main-owned durable operation table or adapter equivalent to
   `KindRuntimeRepository`; Worker 3's SQLite repository is a local adapter for
   replayable tests and integration shape.
7. Add public cancel/retry surfaces that map to `KindRuntime.cancel` and
   `KindRuntime.retry` without exposing raw provider internals.
8. Wire `PublishReadyArtifactContract` into the existing Skill publication
   pipeline; do not publish directly from the W3 artifact generator.
