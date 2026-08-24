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
5. Call `KindRuntime.execute(request)`.
6. Persist exactly one `SkillResult`, one `SkillViewRevision`, trace/evidence
   refs, and any invocation/job record using existing repository semantics.

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

`ExecutionBudget` contains:

- `maxSteps`
- `maxRows`
- `maxBytes`
- `timeoutMs`
- `freshnessSeconds`

## Result shape

`KindRuntime.execute` returns `SkillKindExecutionRecord`:

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

## Handler matrix

| Kind | Handler | Template | Behavior |
|---|---|---|---|
| `knowledge` | `KnowledgeHandler` | `knowledge` | Reads authorized document text, answers from matched chunks, emits source revision + chunk locators, and returns typed refusal for no-answer/permission denial. |
| `semantic` | `SemanticHandler` | `semantic` | Infers metrics, dimensions, time fields, relationships, permissions, and editable MDL projection from structured Golden data; rejects sensitive fields, ambiguous fields, and relationship cycles. |
| `analysis` | `AnalysisHandler` | `chart` | Runs deterministic read-only aggregate projection over structured rows with row/byte budget, no-data, null, unit, `dataAsOf`, source, and evidence payloads. |
| `graph_ontology` | `GraphOntologyHandler` | `graph_ontology` | Builds ontology nodes/relations from schema rows or document chunks with evidence, conflict payloads, pagination metadata, and version compare refs. |
| `monitoring` | `MonitoringHandler` | `monitoring` | Builds observations, alerts, preview-only action candidates, freshness/last-good facts, threshold/change-rate signals, and evidence. It does not execute scheduler or external actions. |

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
