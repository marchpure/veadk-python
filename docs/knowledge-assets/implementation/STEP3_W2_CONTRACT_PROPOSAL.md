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
