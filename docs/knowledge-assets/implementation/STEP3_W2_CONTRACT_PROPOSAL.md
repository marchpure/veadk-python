# STEP3 Worker 2 contract proposal

Status: proposal for Main review. This worker does not modify shared contracts,
generated clients, BFF routes, migration, or command registration.

## Typed application port

`SkillAuthoringService` exposes the following Main-owned adapter seam:

- `create_draft(ContextEnvelope, requested_kind, scope, display_name) -> AuthoringReadModel`
- `propose_patch(draft_id, base_revision, TypedPatch, proposed_by) -> PatchProposal`
- `accept_patch(PatchProposal, caller_id) -> AuthoringReadModel`
- `reject_patch(PatchProposal, caller_id) -> AuthoringReadModel`
- `undo(draft_id, target_revision, caller_id) -> AuthoringReadModel`
- `request_execution(draft_id, caller_id, revision) -> AuthoringReadModel`
- `update_context(draft_id, ContextEnvelope, ContextMutation, caller_id) -> AuthoringReadModel`
- `copy_team_draft(TeamReuseRequest, caller_id, workspace_id) -> AuthoringReadModel`
- `cancel(operation_id, caller_id) -> AuthoringReadModel`
- `retry(operation_id, caller_id) -> AuthoringReadModel`
- `read_operation(operation_id) -> AuthoringReadModel`

All payloads are Pydantic models with `extra="forbid"`. The model gateway can
return only a validated `BuildPlan`; persistence is performed by the service.
Worker 3 receives only `Worker3ExecutionRequest`.

## Context Envelope

The browser supplies prompt, typed resource references, current workspace and
caller IDs, declared permissions, fixed revision IDs, budget and freshness.
`ResourceResolver` re-authorizes every reference and returns only metadata and
schema/semantic summaries. `ResolvedContext.model_input` excludes browser
objects, raw provider content, credentials, secrets, and unverified permission
claims. Authorized permissions are recomputed server-side from the resolved
resources.

## Registration requested from Main

Main should register these operation IDs in the shared command registry:

`skill_draft.create`, `skill_draft.context.update`, `skill_draft.patch.propose`,
`skill_draft.patch.accept`, `skill_draft.patch.reject`, `skill_draft.undo`,
`skill_draft.execute`, `skill_draft.cancel`, `skill_draft.retry`,
`skill_draft.team.reuse`, `skill_draft.read`.

The route layer should map `SkillAuthoringError.code` to the existing typed
error envelope and publish `AuthoringEvent` sequence values through the existing
operation/event transport. It should not expose the JSON-file adapter.

## Persistence mapping requested from Main

The internal adapter needs durable equivalents for:

- operation row keyed by `operation_id`, with status, caller/workspace, trace,
  draft/revision, error and retry lineage;
- immutable draft revision row keyed by `(draft_id, revision)`;
- append-only authoring event row keyed by `(operation_id, sequence)`;
- encrypted or server-side request input row for typed, secret-free retry data;
- patch proposal audit row, including base revision, impact, acceptance/rejection.

The worker's `JsonFileAuthoringRepository` is a restart/replay test adapter only.

## VEADK P0 adapter and W3 handoff

`VeADKModelGateway` is the production model port. It constructs the repository's
public `veadk.Agent` with `output_schema=BuildPlan` and the W1-provided MCP
tool bundle, then executes through the public `veadk.Runner.run_async` API.
The adapter records the Runner's `session_id`, real `trace_id`, event summaries,
and formal MCP tool calls as `AgentExecutionEvidence`.

The input contains the natural-language prompt, authorized context binding,
workspace/caller, server-authorized permissions, fixed Source/Golden revisions,
requested kind, MCP tool schemas, and W1-owned tools. Missing credentials,
MCP/tool failure, Runner timeout, missing MCP calls, or invalid structured
output are explicit failures. `LocalPlanningHarness` remains an explicitly
test-only credential-free harness and is never a production fallback.

`BuildPlan` is the W3 boundary. It carries typed `data_refs`, `metrics`,
`dimensions`, `layout_intent`, `refresh_policy`, and `lineage`; W2 does not
generate HTML or implement MCP lifecycle or Dashboard rendering. The
`Worker3ExecutionRequest` repeats these typed fields so W3 can consume them
without reading arbitrary model output.

Real smoke command (requires real credentials and a reachable W1 MCP endpoint):

```text
MODEL_AGENT_API_KEY=... MODEL_AGENT_MODEL=... \
W2_MCP_SERVER_URL=... W2_MCP_BEARER_TOKEN=... \
python -m frontend.server.skill_authoring.real_smoke
```

It exits non-zero when the real Agent/Runner, MCP call, trace, or typed plan is
not present and never returns a fixed plan on failure.
