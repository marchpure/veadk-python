# STEP3B W2 Agent Runtime handoff

Status: `READY_FOR_MAIN_W4_INTEGRATION`

This W2 commit also adds typed authoring diffs for Dashboard KPI/chart/filter,
SOP step/condition/tool references, and Graph entity/relation changes. A patch
proposal carries bounded `before`/`after`, `base_digest`, `new_digest`, and
`new_revision`; acceptance emits the same operation's revision event, while
older draft revisions remain readable. The standalone harness exposes current
Skill/View/component bindings for integration verification.

The production Agent router now returns a validated `AgentIntent.patch` with a
bounded `TypedPatch`. A routed patch reuses the accepted operation through
proposal → acceptance → Worker 3 execution, and emits one patch plan step plus
one explicit Skill/ViewRevision artifact event. Incomplete model patch output is
rejected by the typed contract and never persisted.

This delivery is a standalone, production-path Agent conversation runtime. It
uses the real `veadk.Agent`/`veadk.Runner`, the durable authoring repository,
and resumable SSE. It does not modify or mount W4's frozen
`ChatAssistant`/Workspace Shell.

The adapter also accepts a complete typed `BuildPlan` returned directly by the
real Agent when the server-resolved, authorized context already contains
everything needed. A tool call is not used as a validity proxy: the service
still validates authorized dependencies, fixed revisions, typed fields, node
boundaries, and Worker 3 execution constraints. This keeps direct typed plans
and tool-assisted plans on the same durable operation path.

## Integration surface

The public frontend entrypoint is:

```ts
import {
  AgentConversation,
  AgentTimeline,
  useAgentRuntime,
} from "../../knowledge-workspace/agent-runtime";
```

W4 can mount the complete conversation, including composer and controls:

```tsx
<AgentConversation
  title="Agent"
  storageKey={`knowledge-agent-runtime.${conversationId}`}
  context={{
    conversationId,
    requestedKind: "analysis",
    scope: "personal",
    resourceRefs: [{
      kind: "golden_asset",
      objectId: assetId,
      revision: revisionId,
      scope: "personal",
    }],
    fixedRevisions: [revisionId],
    permissions: ["resource:read"],
    currentSkillId,
    currentViewId,
    currentComponentId,
    commentIds,
  }}
/>
```

If the frozen shell must retain its own composer, use the controller hook and
render only the timeline:

```tsx
const runtime = useAgentRuntime({
  context,
  storageKey: `knowledge-agent-runtime.${conversationId}`,
});

<AgentTimeline
  state={runtime.state}
  onStop={() => void runtime.stop()}
  onRetry={() => void runtime.retry()}
  onResume={() => void runtime.resume()}
/>;

// Existing composer:
await runtime.send(prompt);
```

`context` is read when a turn is submitted, so W4 may update selected resource
revisions between turns without recreating the runtime. Use one stable,
conversation-scoped `storageKey`; do not share it across conversations.

## Runtime behavior

- `send(prompt)` immediately commits the user prompt and Assistant activity
  placeholder, then opens the real stream.
- A controller permits one active generation. A second `send` fails with a
  user-readable message instead of creating an overlapping operation.
- The server also enforces the same rule for the
  `caller/workspace/conversationId` lane, so a second browser tab or direct
  request cannot start a second Runner in one conversation. Stop releases the
  durable lane; retry claims it with the replacement operation. SQLite and
  PostgreSQL persist this lease (`007_authoring_generation_leases`) and
  coordinate claims transactionally, so the rule survives process restart and
  multiple BFF instances.
- `answer.delta` is incrementally merged. `answer.final` replaces/confirms the
  accumulated answer and is not a terminal frame.
- A clarification turn is represented as a terminal `operation.completed` with
  `payload.status = "awaiting_input"`; the UI keeps the questions readable and
  permits the next prompt without reconnecting or inventing a Plan.
- When a create request has no authorized fixed resource revision, the server
  returns that same structured clarification state (`answer.final` followed by
  `operation.completed`) instead of exposing a generic failed operation.
- An explicit `requestedKind` from the authenticated caller wins over a
  model/router classification. This keeps `analysis` (or another selected
  kind) stable through routing, planning, and execution.
- An `execute` intent is a real routed operation when `currentSkillId` is
  bound. The service loads that draft under the authenticated caller,
  re-resolves its fixed lineage, and sends Worker 3 an execution request using
  the original operation ID; the resulting ViewRevision and terminal event
  remain on that same operation. Missing or unavailable bindings fail with an
  actionable context error.
- Routed turns persist the router's bounded VEADK execution evidence
  (`session_id`, `trace_id`, status, and event counts) before branching, so an
  execute operation's durable read model and event feed prove the real
  Agent/Runner route and retain one trace identity through Worker 3.
- Markdown uses GFM with headings, lists, tables, fenced/inline code, and safe
  HTTP(S)/mailto links. Raw HTML is disabled.
- Activity is driven only by persisted Agent/Runner events. It is compact after
  answer output begins and hidden at terminal state.
- Tool calls are reduced by `call_id` into running/completed/failed cards.
  Supported presentation categories are database/SQL, MCP, connector discovery,
  file or knowledge retrieval, Skill authoring, HTML Artifact, and generic.
- Plans render only when at least two real steps exist and are collapsed by
  default. The summary is the active action plus completed/total.
- The timeline follows content growth while the reader remains at the bottom.
  User scroll-up suspends following; “回到底部” resumes it.
- Runtime and harness styling consumes the Studio semantic color variables
  (`--canvas`, `--panel`, `--foreground`, `--muted-foreground`, `--border`,
  `--primary`, and `--destructive`) with local fallbacks; no hard-coded
  hex/rgb palette is required.
- Conversation history remains independently scrollable across multiple turns;
  only the active assistant turn expands to fill the available panel.
- `stop()` calls the server cancellation endpoint and then follows the same
  operation until `operation.cancelled`; partial readable output remains.
- `retry()` asks the server for one replacement operation and follows only that
  operation. The original prompt remains visible.
- `resume()` follows the same operation from the last durable cursor.
- Mount restoration rebuilds state from the session snapshot, deduplicates by
  event ID and sequence, then sends `Last-Event-ID`. The server repository is
  still canonical after process restart.
- Persisted events remain the canonical source after a process restart: the
  event feed can replay the same operation from its last cursor without
  creating a second operation. An in-flight Runner that was terminated with
  the process is surfaced as an interrupted operation for retry/resume policy;
  W2 does not claim transparent model-run continuation across a process crash.
- `ready_for_execution` is intentionally not an event-feed terminal status;
  the feed waits for the explicit `operation.completed` event so an inline
  Worker 3 handoff cannot be truncated between status and event persistence.

## HTTP and SSE contract

All routes are under `/api/knowledge-assets/v1`.

| Action | Method and path | Required transport behavior |
| --- | --- | --- |
| Start | `POST /streams` | Real `skill-authoring.start` command; creates/claims the durable operation with `Idempotency-Key`, then returns the same operation's SSE feed and `X-Operation-ID` |
| Resume/follow | `GET /authoring/operations/{operationId}/events` | send `Last-Event-ID: {operationId}:{sequence}` when available |
| Read | `GET /authoring/operations/{operationId}` | durable read model for diagnostics/integration |
| Stop | `POST /authoring/operations/{operationId}:cancel` | cancels the registered Runner task |
| Retry | `POST /authoring/operations/{operationId}:retry` | returns a new operation linked by `retry_of_operation_id` |

Every SSE message has:

```ts
interface AuthoringEvent {
  cursor: string; // derived from SSE id: operationId:sequence
  operation_id: string;
  event_id: string;
  sequence: number;
  type: AgentEventType;
  public_summary: string;
  payload: Record<string, unknown>;
  terminal: boolean;
  occurred_at: string;
  session_id?: string | null;
  trace_id?: string | null;
}
```

Public event types:

```text
message.accepted
context.resolving
context.resolved
agent.started
answer.delta
answer.final
tool.started
tool.progress
tool.completed
tool.failed
plan.created
plan.step.started
plan.step.completed
plan.step.failed
artifact.revision.created
operation.completed
operation.failed
operation.cancelled
```

Only `operation.completed`, `operation.failed`, and `operation.cancelled` are
terminal. The server sanitizes payloads before persistence and replay, bounds
text/collection sizes, redacts sensitive key names, bearer values, credentialed
URIs, and private keys, and suppresses internal structured-output tools.
The runtime client uses this real POST start route only for the initial turn;
all reconnects, refreshes, and replay use the durable operation event route.
Operation reads are workspace-scoped, and Worker 3 ViewRevision/result objects
are reduced to bounded public summaries before entering the durable operation
read model or event feed.

## Error contract

- HTTP `401`/`403` becomes an authentication/authorization message asking the
  user to sign in again.
- An invalid or oversized SSE frame becomes a protocol error with retry.
- A stream that closes without a terminal event reconnects with the last cursor
  using bounded backoff; after exhaustion it preserves content and offers
  “继续连接”.
- Runner failures use `operation.failed` and expose only the safe public message,
  request ID, and a retry action when applicable.
- Cancellation uses `operation.cancelled`, keeps partial output, and offers
  “重新运行”.

## Standalone acceptance

Start the real backend:

```bash
MODEL_AGENT_TIMEOUT_MS=120000 \
STEP3_MCP_PROFILE_ID=infra-local \
STEP3_MCP_SERVER_PATH="$PWD/tests/fixtures/knowledge_workspace_v21141/mcp_sdk_infrastructure_server.py" \
STEP3_MCP_DATA_PATH="$PWD/tests/fixtures/knowledge_workspace_v21141/mcp_infrastructure_metrics.initial.json" \
uv run uvicorn scripts.knowledge_asset_step3_server:app \
  --host 127.0.0.1 --port 18081 --no-server-header
```

Start the frontend:

```bash
cd frontend
VEADK_API_TARGET=http://127.0.0.1:18081 \
  npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Open (the optional `conversationId` query parameter selects the durable
single-generation lane):

```text
http://127.0.0.1:5174/agent-runtime-harness.html
```

The settings rail accepts an authorized resource ID and fixed revision for a
tool-assisted Skill turn, plus optional current Skill/View/component bindings.
An empty context can be used for ordinary questions. No timer, fixture response,
or fake stream exists in the harness.

## Ownership boundary

MAIN/W4 still owns mounting this entrypoint in the Workspace shell, mapping the
shell's selected resources to `AgentRuntimeContext`, choosing a
conversation-scoped snapshot key, and running integrated 4177 acceptance. This
W2 handoff therefore does **not** claim that final 4177 integration is complete.

The latest independent browser acceptance evidence is outside the repository at:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/final-acceptance.ahasP9
```

It contains desktop and narrow screenshots, videos, HAR/network
request/response records (including `Last-Event-ID`), durable operation JSON,
and machine-readable summaries. The baseline successful Dashboard/Analysis
creation record is:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/browser/tool-skill-operation.json
```

The latest fresh run covered:

- five real Agent greetings, each with multiple `answer.delta` events;
- real MCP `infrastructure.metrics` started/completed events, collapsed and
  expanded Tool/Plan/ViewRevision cards;
- server-side Stop with `operation.cancelled` and retry affordance;
- page refresh restoring the same operation and replaying from
  `Last-Event-ID`;
- real MCP failure followed by a server-backed replacement retry;
- a fresh explicit `kind=analysis` request through the 5175 harness, with real
  `infrastructure.metrics` events, `draft.plan.intent = "analysis"`, and one
  durable operation (`op_34c75f03c2a04769be4e78b26b9f1828`);
- a successful real Dashboard/Analysis creation (`op_a4e17dc6782f40818eee993f8c0da26e`),
  including MCP input/result summaries, Skill revision 1, Worker 3 execution,
  and ViewRevision `view-8dc770213188144583a74241`;
- real bound Skill Dashboard KPI patch (`set_dashboard_kpi`) with before/after,
  revision 1 → 2 in `op_8bc15f98e2844a7388c8eb000215a87e`, followed by a
  revision 2 → 3 rerun in `op_a8fd4dce3cfd4e1b9533e5ee4ebf7fd1`; both carry
  digests, same-operation ViewRevision, and old revision readability;
- a current SOP step patch in `op_c49ba113087a4c0a86efe0126eb8c28c`, revision
  1 → 2, with `set_sop_step`, condition `severity >= high`, tool reference
  `infrastructure.metrics`, and ViewRevision
  `view-5afc7b367ec69640700dc756`;
- 0 browser console errors and 0 page errors in the successful runs.

The fresh acceptance summary is:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/final-acceptance.ahasP9
```

It contains new SQLite/MCP-backed Dashboard creation, Dashboard KPI patch,
SOP patch, old-revision read, five real greetings, MCP failure/retry, and
SSE interruption/refresh replay. Its browser totals are console/page/network
errors `0/0/0`; all event IDs and sequences are unique and ordered.

The latest explicit Dashboard acceptance record is:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/browser-gap/dashboard-create-current.json
```

It is operation `op_6cd1dff0f76a4c848b9583e865ab1050` (`create_draft`,
`succeeded`) and contains, in that one operation, a real
`infrastructure.metrics` `tool.started`/`tool.completed` pair, a typed
`analysis` plan whose purpose is to create a Dashboard Skill, an
`artifact.revision.created` event for ViewRevision
`view-23552e2a51c02ae9bb8c9df8`, and `operation.completed`. Its draft is
`draft_b21d00eb87f14a53a0ce2755f1eac2ae`, revision 1. The current browser
summary and HAR/video records are in the same `browser-gap` directory.

The current failure/retry evidence is retained at:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/browser-gap/failure-retry.json
```

It records `tool.failed → operation.failed` for
`op_6dabccb1389f46c9a3c7c1c8db6b0bf8`, followed by a server-backed
replacement `op_ec4592efb40c451581415e593017d7b7` with
`retry_of_operation_id` set to the failed operation and a successful
`tool.completed → operation.completed` path. This evidence was captured with
the real MCP subprocess; no timer or fixed response is used.

The tool journey's durable event record includes a real `view_revision_id` and
the W2/W3 execution request and completion all use the accepted operation ID.
The service-level same-operation invariant is also covered by
`test_routed_create_executes_and_publishes_view_revision_on_one_operation` and
`test_routed_typed_patch_proposes_accepts_and_executes_on_one_operation`, while
`test_routed_execute_runs_bound_draft_on_one_operation` verifies that routed
execute persists the router session and trace on that same operation.

The fresh no-context clarification and explicit-kind evidence is in:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/browser-gap/fresh-no-context-fixed.png
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/browser-gap/fresh-analysis-kind
```

The durable restart replay evidence is:

```text
/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/restart-replay-final
```

For operation `op_47b2053066284d93b07f5693037e5b88`, replay after cursor `6`
returned sequences `7–11`, with no duplicates and a terminal event.

Latest verification from the delivery worktree:

- `cd frontend && npm test`: 881 passed, 0 failed.
- `pytest -q tests/frontend`: 1037 passed, 13 skipped, 4 warnings (prior delivery run).
- focused W2 Python tests: 105 passed, 5 warnings.
- `npm run build`, `python -m compileall -q frontend/server`, and
  `git diff --check`: passed.

The latest real Agent smoke used operation
`op_962206ef962b4e678efe6aced17702d6` and produced one durable operation with
`message.accepted`, context resolution, router/answer `agent.started`, 31
`answer.delta` events, `answer.final`, and `operation.completed`. It completed
successfully through the production `veadk.Agent`/`veadk.Runner` path.

The latest bound execute smoke used operation
`op_dfcf97b705fa4ff2898378bb60294cb4`. Its durable read model contains router
session `skill_authoring_router-eb42e40e-134d-4a79-849f-7e3ffb36d295` and trace
`4952d293c76739d664f496b21517b284`; the same operation completed Worker 3
execution and created ViewRevision `view-a65a91955941f0fd26671546`. Its
`artifact.revision.created` event contains only bounded `view_revision_summary`
(no raw `view_revision`, result rows, or credentialed URI), and the browser run
recorded zero console/page errors. Full evidence is in
`/Users/bytedance/.codex/runtime/knowledge-step3b-w2-agent-streaming/browser-execute`.

The runtime styling and multi-turn scrolling regressions are covered by
`frontend/tests/agentRuntime.test.mjs`. The standalone harness remains the
independent acceptance surface; final 4177/Workspace Shell mounting and
integrated acceptance remain MAIN/W4 work.

Security hardening verified in this delivery:

- `GET /authoring/operations/{id}` returns 404 when the authenticated
  workspace does not own the durable operation.
- Public ViewRevision events retain only revision/template/purpose/renderer
  metadata and a title; raw view models and result references are excluded.
- The operation read model retains only bounded scalar artifact/execution
  metadata, never raw Worker result collections.
