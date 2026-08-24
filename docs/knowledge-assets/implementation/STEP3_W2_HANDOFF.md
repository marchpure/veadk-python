# STEP3 Worker 2 handoff — Agent orchestration & SkillDraft authoring

Status: `READY_FOR_INTEGRATION`

## Provenance

- Worker worktree: `/Users/bytedance/.codex/worktrees/knowledge-step3-worker2-agent-authoring`
- Branch: `feat/knowledge-step3-worker2-agent-authoring`
- Worker start/base: `a34383ccb281c59c240a9b6ccf88a31da6382d1f`
- Worker commit: `65037a4b98838ae467fec223b4e1e45d56b9dfd2` (base delivery)
- Follow-up commits: `bdb1573dd5616fab8ca8f9246f1bca560c9816e2`,
  `a03cb607bdb8e8cfa47628348e922f6c2b1d1b71`,
  `b0ca31dac00c40bff4b8090aff1bf07dc008817e`
  (persisted read-model progress and recovery coverage)

The handoff metadata is committed after the code head.
- STEP 3 Main checkpoint verified from sibling Worker worktrees:
  `a34383ccb281c59c240a9b6ccf88a31da6382d1f`
- Checkpoint tag: `knowledge-skill-factory-step-3-v2131-checkpoint-a34383cc`
- Checkpoint migration head: `004_step3_shares`
- Checkpoint contract digest:
  `108d962c73517f45367e924bd330882564a984aee57700bf95ee92e1c3431c12`
- Checkpoint UI delta digest:
  `dd1b90bb917052929a13852558025956263c3b104e47a73b44dba0ece93e4d30`
- Frontend baseline: `0a4fb3b78b395c3cab94b991735b897034a50f34`
- Prototype archive SHA-256 verified:
  `ce6e086b806072c363f23ed68c9e067b30b280738af0284eeb60ca36c22e5571`
- The checkpoint was verified from the sibling Worker worktrees before
  rebasing; this branch now has the checkpoint as its direct parent.

## Delivered files

- `frontend/server/skill_authoring/models.py`
  - minimum Context Envelope and server-resolved context
  - five kind-specific BuildPlan contracts
  - typed DraftRevision, PatchProposal, impact and Worker 3 execution request
  - operation/event/read model contracts
  - typed Composer context and team reuse requests
- `frontend/server/skill_authoring/ports.py`
  - resolver with server-side authorization, dedupe and fixed revision checks
  - existing Agent/model gateway adapter
  - credential-blocked gateway
  - replayable local planning harness
  - Worker 3 typed boundary
  - atomic restart-safe JSON repository adapter
- `frontend/server/skill_authoring/service.py`
  - intent/context resolution → plan → draft
  - model timeout and credential-blocked state
  - typed patch proposal/accept/reject, optimistic conflict and undo
  - explicit rerun classification for query/metric/permission/freshness/alert/mapping
  - context add/remove, cancellation, durable retry, personal team reuse with lineage
  - operation/event/read model recovery after refresh, including BuildPlan, context digest, stage, progress, and clarification questions
  - durable single/batch comment repair proposals, team pre-publish evaluation
    transition, execution-time reauthorization
- `tests/frontend/test_skill_authoring.py`
- `STEP3_W2_CONTRACT_PROPOSAL.md`
- `STEP3_W2_UI_PROPOSAL.md`
- `STEP3_W2_CAPABILITY_MATRIX_PROPOSAL.yaml`

No shared contracts, generated files, migration, public repository, BFF route,
WorkspaceHost, Shell, frozen UI, lockfile, or visual baseline was modified.

## Reproducible local journey evidence

Using the same authorized `golden_asset@rev_1` with different prompts:

| prompt | context digest | plan digest | draft digest | result |
| --- | --- | --- | --- | --- |
| `[analysis] show orders by day` | `d5206fa06dca9e49ee6e` | `124ba171e76df2e19a14` | `3f6e49fe49b66ec7914d` | `ready_for_execution` |
| `[analysis] break down value by customer` | `0364248aacf9b971af24` | `caadf127d07616d357e1` | `d974f24a697ddb8ddc14` | `ready_for_execution` |

Both journeys produced operation IDs and trace IDs at runtime; the values are
printed by the local replay command and intentionally not treated as durable
production evidence until Main wires the repository and Worker 3.

## VEADK P0 gate

The amended P0 path is implemented by `VeADKModelGateway`:

- public `veadk.Agent` with typed `BuildPlan` output schema;
- public `veadk.Runner.run_async`, not a second runtime;
- W1-injected MCP tool objects and schemas;
- safe prompt/context input containing caller, workspace, permissions, fixed
  revisions, requested kind, and current UI binding;
- durable `session_id`, real `trace_id`, Runner event summaries, and formal MCP
  tool-call evidence;
- typed `BuildPlan` fields for data refs, metrics, dimensions, layout intent,
  refresh policy, and lineage, passed to W3 through
  `Worker3ExecutionRequest`;
- explicit failure for missing credentials, MCP failure, timeout, missing MCP
  calls, and invalid structured output.

Real smoke command:

```text
MODEL_AGENT_API_KEY=... MODEL_AGENT_MODEL=... \
W2_MCP_SERVER_URL=... W2_MCP_BEARER_TOKEN=... \
python -m frontend.server.skill_authoring.real_smoke
```

The command is intentionally credential/environment gated. It cannot claim
success or emit a fixed plan without a real Agent/Runner execution and MCP
tool call. W2 does not own MCP lifecycle or Dashboard rendering.

## Verification

- `pytest -q tests/frontend/test_skill_authoring.py`: **26 passed**
- `python -m compileall -q frontend/server/skill_authoring tests/frontend/test_skill_authoring.py`: passed
- `git diff --check`: passed
- Prototype archive download, SHA-256, extraction and `prototype/readme.md`: passed
- Local replay with different prompts and different BuildPlan/draft digests: passed
- Real Agent/Runner contract test with a non-sales maintenance request and
  formal MCP tool call: passed
- Invalid Runner structured output: explicit failed operation with no draft:
  passed
- Real MCP failure envelope: explicit failed operation with no draft: passed
- W3 typed data/metric/dimension/layout/refresh/lineage handoff: passed

## Integration requirements and known limits

Main must register the proposed commands and generated BFF DTOs, map typed
errors/events, and replace the local JSON adapter with the shared durable
repository. Worker 3 must provide the execution consumer. Evaluation and
formal publishing remain outside this Worker. Agent/model credentials were not
available, so the production adapter correctly reports `credential_blocked`;
the local planning harness is test-only and does not report execution success.

## Recommended integration order

1. Cherry-pick the base delivery and follow-up commits onto `a34383c…`.
2. Review `STEP3_W2_CONTRACT_PROPOSAL.md`; implement shared registry/DTO seams in
   Main only.
3. Wire `ResourceResolver` to W1 GoldenAsset/Skill authorization and
   `Worker3Executor` to W3's typed port.
4. Run the Worker 2 tests plus Main contract and browser consumer tests.
