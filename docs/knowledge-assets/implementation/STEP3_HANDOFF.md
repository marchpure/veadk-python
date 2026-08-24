# STEP 3 Integration Handoff

Date: 2026-08-24

Result: `PASS`

## Implemented

- Bounded typed `skill-draft.run` execution controls.
- Real local Golden Asset execution for semantic, analysis, knowledge,
  graph_ontology, and monitoring manifests.
- Typed `SkillResult`, `ViewIntent`, narrow per-template ViewModels,
  `SkillViewManifest`, and `SkillViewRevision`.
- Immutable content-addressed result and HTML bundle children.
- SQLite/PostgreSQL `002_step3_views` migration and persistence parity.
- SQLite/PostgreSQL `003_assistant_patch_history` migration and durable
  assistant undo history.
- SQLite/PostgreSQL `004_step3_shares` migration and durable read-only
  Skill View share grants.
- Automatic `EvaluationSuite`, `EvaluationRun`, and machine-readable
  `PolicyGateResult` for the verified local path.
- Production `SkillViewShell` behind
  `?studio=knowledge&view=skill&skillId=...&revision=...`.
- Typed `assistant.turn` patch path with a minimal context envelope,
  optimistic revision validation, before/after diff, durable undo token, and
  real `skill-draft.run` rerun.
- Each successful local draft execution persists a draft Invocation linked to
  its SkillResult and SkillViewRevision. Explicit `invocation.start` further
  verifies the persisted view, result, matching draft revision, and returns
  actual data revision refs on the explicit `test://` / `draft://` path.
- BFF `accepted` semantics recognize the typed
  `ready_for_evaluation` terminal build state.
- `skill-draft.run` now emits a durable Operation sequence
  `accepted → progress → terminal`, replays by idempotency key, and fails
  closed when the Operation was cancelled before execution. Terminal state is
  immutable against a late synchronous completion, and typed
  `skill-draft.retry` only retries a recorded failed/partial run.
- Skill View Shell exposes `Retry Builder` only after a failed or partial
  Operation and sends the typed retry command through the production adapter.
- Production `Prefer: respond-async` Builder requests run in a background
  worker with a JobFramework lease and heartbeat. Cancellation propagates to
  `cancel_requested`; worker failures use bounded retry/dead-letter semantics,
  while the browser polls the durable Operation.
- The local SQLite and PostgreSQL adapters persist Builder jobs, job events,
  outbox sequence, and dead letters; reconstructed JobFramework instances
  restore lease state and replay history. PostgreSQL production selection uses
  the `production` job profile.
- The production knowledge entrypoint mounts `KnowledgeWorkspaceHost`, making
  the `SkillViewShell` route reachable through the actual
  `?studio=knowledge` browser entry.
- Analysis uses the typed Chart ViewModel and trusted Chart renderer.
- All five typed execution kinds project through the production Skill View
  Shell: semantic, chart/analysis, knowledge, graph_ontology, and monitoring.
- Shell Export and Share actions cross the typed BFF boundary. Export creates
  a content-addressed server artifact and Share persists a read-only Skill
  View grant; no browser Blob/download or clipboard handoff is used. Evaluate & publish is evaluation-only while
  `publication.publish` remains STEP 4.
- Evaluation supports typed manual, historical, batch, and agent-candidate
  cases with content-addressed suite/evidence refs and blocked candidates.
- Generated JSON Schema and TypeScript contracts regenerated from Pydantic.
- Contract digests after the retry/terminal-state update:
  `core-contracts.schema.json` =
  `108d962c73517f45367e924bd330882564a984aee57700bf95ee92e1c3431c12`;
  `command-registry.schema.json` =
  `bcd6f4d1ca7c3f7e52b1ced95de410cbc843c68397ca9f45b799e427a5718d18`;
  `generatedContracts.ts` =
  `8701ed10d71db33eb9642c4c47bf4b76932a976670e22bde1f45b9126091e1a85`.
- STEP 3 OpenAPI version/description supplement and action matrix.

## Evidence

- Relevant backend regression: `78 passed, 13 skipped` (re-run on
  2026-08-25).
- Full frontend regression: `817 passed, 0 failed` after correcting the
  React 18 test harness to import `act` from `react-dom/test-utils`.
- Focused local Golden Asset, Invocation, undo, evaluation, migration, and
  renderer integration remains green within that suite.
- Focused frontend knowledge-workspace suite: `75 passed`.
- Production build: both Studio and website-integration bundles built.
- Fresh dedicated Playwright runner: `5 passed` (Execute, Evaluate,
  typed patch/Undo, server Export/Share, and failed Builder Retry) using the
  live BFF and production Vite entry at 1440x900; no console/page errors or
  horizontal overflow.
- Fresh live PostgreSQL container verification covered all migrations through
  `004_step3_shares`, production job profile selection, operation completion,
  job lease/heartbeat, reconstructed worker replay, terminal completion, four
  persisted job events, and four outbox events.
- Low-level Playwright smoke passed at 1440x900 and 390x844 with shell,
  assistant, typed actions, keyboard focus, no console/page errors, and zero
  horizontal overflow.
- STEP 3-specific shell visual comparator passed at 1440x900 and 390x844:
  zero pixel mismatch, identical DOM/class/text/event/geometry/computed-style
  and runtime artifacts, successful real keyboard/input/a11y/mobile checks,
  with no console/page errors, iframe, custom script, or horizontal overflow.
- Fresh live BFF/browser journey passed Execute, Evaluate, typed patch, and
  durable Undo with no 5xx, console, or page errors.
- SQLite migration head: `001_knowledge_assets`, `002_step3_views`,
  `003_assistant_patch_history`, `004_step3_shares`.
- STEP 3 tables present: `skill_results`, `skill_view_revisions`,
  `evaluation_suites`, `evaluation_runs`, `policy_gate_results`,
  `assistant_patch_history`, and `skill_view_shares`.
- Current core schema digest:
  `108d962c73517f45367e924bd330882564a984aee57700bf95ee92e1c3431c12`.
- Current command registry digest:
  `bcd6f4d1ca7c3f7e52b1ced95de410cbc843c68397ca9f45b799e427a5718d18`.
- Current generated TypeScript facade digest:
  `8701ed10d71db33b9642c4c47bf4b76932a976670e22bde1f45b9126091e1a85`.
- Current TypeScript facade digest remains generated from the contract source.
- STEP 3 UI action matrix covers Execute, Evaluate, typed patch, Export, Share,
  Retry Builder, and Evaluate & publish; Export/Share are verified, while
  Evaluate & publish remains evaluation-only.

## Scope boundary

Formal invocation remains limited to the explicit `test://` / `draft://` path;
local draft execution persists a bound Invocation. Formal STEP 4 publication
adaptation remains intentionally out of scope. Distributed multi-process
scheduling and credentialed Oracle/Web/MCP/published-Skill integrations remain
outside this local verification.

The static guard was updated to compare against the immutable STEP 2 handoff
baseline (`f734b067`), allow the declared STEP 3 verification entrypoints, and
recognize trusted renderer boundary rejection checks. It now passes with zero
findings; generated runtime evidence remains outside the release worktree.
