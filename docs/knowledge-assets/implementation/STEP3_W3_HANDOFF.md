# STEP 3 Worker 3 Handoff

Status: `STEP3_W3_FROZEN`

Date: 2026-08-25

Worker: Backend Worker 3 — Multi-kind Skill Execution & View Projection

Branch/worktree:

- `/Users/bytedance/.codex/worktrees/knowledge-step3-worker3-kind-runtime`
- `feat/knowledge-step3-worker3-kind-runtime`

## Preconditions audited

- Verified current HEAD matches the coordination checkpoint:
  `31a26a6fd0547a7696af62b97b42a842f07f8339`
  (`knowledge-skill-factory-step-3-v2131-checkpoint-31a26a6f`).
- Target worktree path did not exist initially, so it was created at the
  exact requested path and resolved to the required checkpoint commit.
- `git pull` was attempted per `AGENTS.md`, but Git refused because pull
  reconciliation was unspecified for the newly-created divergent local branch.
  No merge/rebase was performed.
- Required `AGENTS.md` and `frontend/SPEC.md` were read. No `CONTEXT.md` exists
  in this worktree.
- Available design docs read from
  `/Users/bytedance/.codex/runtime/knowledge-html-design-docs/`:
  `00-overview.xml`, `01-agent-spec.xml`, `03-data-semantic.xml`,
  `04-compiler.xml`, `06-backend-runtime.xml`, and
  `07-governance-quality.xml`.
- The local design-doc export does not include `08` or sections `10.0/10.4`
  in `07-governance-quality.xml`; this handoff records that source-doc gap.
- Prototype package downloaded and verified:
  SHA-256
  `ce6e086b806072c363f23ed68c9e067b30b280738af0284eeb60ca36c22e5571`.
  `prototype/readme.md` was read and confirms the projection contract
  components and 43 captures.

## Delivered Worker 3 modules

- `frontend/server/knowledge_assets/kind_runtime/models.py`
  - `KindExecutionRequest`
  - `ExecutionBudget`
  - `ExecutionTrace`
  - `ExecutionEvidence`
  - provider contract models for retrieval, query plans, semantic projections,
    graph mappings, and monitoring lifecycle records
  - `KindHandlerOutput`
  - `SkillKindExecutionRecord`
- `frontend/server/knowledge_assets/kind_runtime/runtime.py`
  - `KindRuntime`
  - explicit dispatch for `knowledge`, `semantic`, `analysis`,
    `graph_ontology`, and `monitoring`
  - durable idempotency, retry, running cancellation, byte budget, timeout,
    no-data, restart recovery, and failure-state handling
- `frontend/server/knowledge_assets/kind_runtime/handlers.py`
  - five explicit handlers; no universal `ArtifactSpec`
- `frontend/server/knowledge_assets/kind_runtime/providers.py`
  - replaceable `RetrievalProvider`, `SemanticProvider`, `QueryExecutor`, and
    `GraphMappingProvider` ports
  - local read-only adapters for deterministic test/replay execution
- `frontend/server/knowledge_assets/kind_runtime/repository.py`
  - Worker 3-owned SQLite operation repository for operation lifecycle,
    idempotency replay, cancellation flags, retry records, and incomplete
    operation discovery after process restart
- `frontend/server/knowledge_assets/kind_runtime/projector.py`
  - typed `SkillResult`, `ViewIntent`, `SkillViewRevision`
  - content-addressed result, evidence, trace, view-model, and trusted HTML refs
  - escaped text alternatives for accessibility and safe rendering
- `frontend/server/knowledge_assets/kind_runtime/store.py`
  - deterministic content-addressed local store adapter
- `frontend/server/knowledge_assets/kind_runtime/adapters.py`
  - internal local Golden Asset content adapter

## Read model and behavior matrix

| Requirement area | Evidence |
|---|---|
| Unified execution protocol | `KindExecutionRequest` and `SkillKindExecutionRecord` in `kind_runtime/models.py`; `KindRuntime.execute`, `retry`, `cancel`, and `recover_incomplete` in `kind_runtime/runtime.py`. |
| Five explicit kind handlers | `KnowledgeHandler`, `SemanticHandler`, `AnalysisHandler`, `GraphOntologyHandler`, `MonitoringHandler` in `kind_runtime/handlers.py`. |
| Typed `SkillResult` / `ViewIntent` / `SkillViewRevision` | `SkillViewProjector.project` in `kind_runtime/projector.py`; covered by `test_worker3_runtime_executes_each_kind_with_typed_projection`. |
| Content-addressed revision refs | `ContentAddressedStore`; result/evidence/trace/view/model refs are SHA-256 addressed. |
| Durable idempotency and restart recovery | `SqliteKindRuntimeRepository`; covered by completed-operation replay, concurrent same-key execution, retry linkage, and incomplete-operation recovery tests. |
| Running cancellation and timeout | `KindRuntime` polls repository cancel flags while waiting on bounded futures; covered by running-cancel and timeout tests. |
| Knowledge retrieval/answer contract | `RetrievalProvider`; covered by replaceable provider, citation permission, and explicit no-answer/refusal tests. |
| Semantic MDL projection and validation | `SemanticProvider`; covers entities, joins, metrics, aggregations, units, permission metadata, ambiguity rejection, dependency validation, sensitive-field denial, and cycle rejection. |
| Analysis fixed-plan execution | `QueryExecutor`; analysis requires a fixed `queryPlanRef` and executes through the controlled read-only port instead of selecting the first inferred dimension/metric. |
| Graph ontology evidence-backed relations | `GraphMappingProvider`; graph edges come from schema/mapping/evidence relationships, not positional `related_to` links. |
| Monitoring action loop lifecycle | `MonitoringHandler` plus `MonitoringLifecycle`; observations, alerts, last-good revision, duration, and preview-only action candidates are persisted with `externalActionsExecuted=false`. |
| Trusted lifecycle/safe renderer alternative | `trusted_html`; test checks CSP marker, a11y region, text alternative, and no script/iframe. |

## Corrective hardening after `96b7d10b`

The previous commit `96b7d10b` is treated as
`READY_FOR_INTEGRATION_CANDIDATE`, not production complete. This follow-up
freezes W3 after correcting the hardening gaps:

- execution lifecycle is now operation-id based and can be persisted through
  `SqliteKindRuntimeRepository`;
- idempotent replay returns the persisted record, including after constructing
  a new runtime/repository instance over the same database;
- concurrent same-key executions share the persisted result instead of running
  provider code twice;
- cancellation is checked while the handler future is running and persists a
  terminal `cancelled` record before late success can replace it;
- timeout uses bounded future waiting and emits terminal `timeout`;
- retry records link to `retryOfOperationId` and persist both successful and
  rejected retry attempts;
- Knowledge is routed through a replaceable retrieval/answer provider with
  citation permission refs and explicit no-answer reasons;
- Semantic projection is provider-backed and validates entities, relationships,
  declared fields, units, aggregations, ambiguities, cycles, and dependency
  errors;
- Analysis consumes a fixed `queryPlanRef` and uses a read-only query executor
  port;
- Graph/Ontology edges are produced from mapping relationships/evidence;
- Monitoring stores lifecycle observations, alerts, last-good revision,
  duration, and preview action candidates, with no STEP 4 Scheduler execution.

## Real IDs / digests / traces

The focused replay tests generate deterministic local IDs and digests from
current input bytes. Representative tested IDs:

- skill ids: `draft-knowledge`, `draft-semantic`, `draft-analysis`,
  `draft-graph_ontology`, `draft-monitoring`
- golden id: `golden-a`
- source id: `source-golden-a`
- trace ids: `trace-knowledge-*`, `trace-semantic-*`, `trace-analysis-*`,
  `trace-graph_ontology-*`, `trace-monitoring-*`
- content refs: `local://kind-runtime/results/{sha256}`,
  `local://kind-runtime/evidence/{sha256}`,
  `local://kind-runtime/traces/{sha256}`,
  `local://kind-runtime/views/{sha256}`,
  `local://kind-runtime/view-models/{sha256}`

## Tests

Added:

- `tests/frontend/knowledge_workspace_v21141/test_worker3_kind_runtime.py`

Executed:

```bash
pytest -q tests/frontend/knowledge_workspace_v21141/test_worker3_kind_runtime.py
# 23 passed in 1.00s

pytest -q tests/frontend/knowledge_workspace_v21141/test_step3_typed_execution.py \
  tests/frontend/knowledge_workspace_v21141/test_step3_core.py \
  tests/frontend/knowledge_workspace_v21141/test_step3_render_boundary.py \
  tests/frontend/knowledge_workspace_v21141/test_local_golden_data_flow.py
# 27 passed in 1.25s

PYTHONDONTWRITEBYTECODE=1 pytest -q tests/frontend/knowledge_workspace_v21141/test_worker3_kind_runtime.py \
  tests/frontend/knowledge_workspace_v21141/test_step3_typed_execution.py \
  tests/frontend/knowledge_workspace_v21141/test_step3_core.py \
  tests/frontend/knowledge_workspace_v21141/test_step3_render_boundary.py \
  tests/frontend/knowledge_workspace_v21141/test_local_golden_data_flow.py
# 50 passed in 1.65s
```

Coverage includes:

- one replayable local test for every Worker 3 kind
- structured data changes changing `analysis` result digest
- schema/data changes changing `semantic` view-model digest
- document changes changing `knowledge` citation locator and result digest
- permission denial
- empty data / awaiting input
- schema drift
- cancellation
- over-budget failure
- timeout failure
- idempotent replay stability for unchanged inputs
- monitoring threshold/change-rate action candidate preview
- provider contracts for retrieval, semantic model projection, query execution,
  and graph mapping
- durable operation repository replay after runtime restart
- concurrent idempotency for same-key executions
- running cancellation and late-success suppression
- retry linkage
- monitoring lifecycle persistence
- renderer XSS/CSP smoke and text alternative

## Integration proposals

- `docs/knowledge-assets/implementation/STEP3_W3_CONTRACT_PROPOSAL.md`
- `docs/knowledge-assets/implementation/STEP3_W3_UI_PROPOSAL.md`

## Code size

Worker 3 runtime/test surface at freeze:

- runtime package: 2,374 lines
- focused tests: 913 lines

## Known integration notes

- Existing checkpoint implementation in
  `frontend/server/knowledge_assets/application.py::_run_skill_draft`
  persists `SkillViewRevision` twice. Worker 3 did not edit that shared file;
  Main should remove the duplicate during integration.
- Formal BFF wiring, generated shared DTO updates, and root route changes are
  intentionally left to Main per Worker 3 scope.
