# STEP 3 Click Acceptance

Status: `PASS`

Stable integration command:

```bash
python -m uvicorn scripts.knowledge_asset_step3_server:app \
  --host 127.0.0.1 --port 8793 --log-level info \
  > .veadk/knowledge-assets-step3.log 2>&1 &
echo $!
```

Stable URL: `http://127.0.0.1:8793`

Live evidence server: PID `38393`; SQLite/log paths:
`.veadk/knowledge-assets-step3.sqlite3` and
`.veadk/knowledge-assets-step3.log`.

## Verified journeys

- Local Markdown source → `GoldenAssetRevision`.
- Canonical `SkillManifest` save with `knowledge` `kindSpec`.
- Real `skill-draft.run` reads the Golden Asset and returns typed
  `SkillResult`, `ViewIntent`, `SkillViewRevision`.
- Semantic, analysis/chart, knowledge, graph ontology, and monitoring Golden
  Assets each produce typed execution output and a narrow Shell projection.
- Content-addressed result JSON and trusted HTML bundle are written.
- The execution also persists a draft Invocation bound to the returned
  SkillResult, SkillViewRevision, trace, and GoldenAssetRevision.
- `evaluation.run` locks environment/data revisions and returns automatic
  `PolicyGateResult`.
- `assistant.turn` accepts only a typed patch plus a minimal Skill/View/schema/
  permission context, returns before/after diff metadata, and reruns the
  updated draft through the real local executor.
- The returned undo token is persisted; a subsequent typed `assistant.turn`
  inverse patch restores the prior value and reruns the Skill.
- Export and Share use typed BFF commands: Export creates a content-addressed
  server artifact and Share persists a read-only Skill View grant, with no
  local browser file or clipboard fact. Evaluate & publish invokes typed
  evaluation only; formal `publication.publish` remains STEP 4.
- `invocation.start` rejects missing or mismatched persisted
  `SkillViewRevision` bindings.
- A valid `invocation.start` returns the bound SkillResult and actual data
  revision refs; it does not accept an arbitrary view-only binding.
- A successful `skill-draft.run` reports `accepted: true` while retaining its
  typed `ready_for_evaluation` status.
- The Builder exposes a durable Operation with accepted/progress/terminal
  events and idempotent replay; a pre-cancelled Operation fails closed.
- A partial Builder run can be retried through the typed
  `skill-draft.retry` command, which creates a new Operation and does not
  mutate the original terminal history.
- The production Skill View Shell exposes `Retry Builder` only for a failed or
  partial Operation and routes it through the generated typed adapter.
- Low-level Playwright smoke passed on desktop and mobile; the fresh live
  journey passed Execute → Evaluate → patch → Undo against the stable BFF.
- STEP 3-specific shell visual comparator passed at desktop `1440x900` and
  mobile `390x844`: zero pixel mismatch and matching DOM, styles, runtime,
  keyboard, input, accessibility, and mobile artifacts, with no console/page
  errors, iframe, custom script, or horizontal overflow.
- Fresh dedicated Playwright runner passed all five Skill View journeys at
  desktop `1440x900`: `5 passed` (Execute, Evaluate, typed patch/Undo,
  server Export/Share, and failed Builder Retry). The formal visual
  comparator separately passed at desktop and mobile.
- Full frontend regression: `817 passed, 0 failed`.
- Focused backend regression: `78 passed, 13 skipped`.
- Live PostgreSQL verification passed all migrations through
  `004_step3_shares`, production job profile selection, operation completion,
  worker lease/heartbeat, restart replay, terminal completion, and outbox
  persistence.
- Typed evaluation cases cover manual, historical, batch, and agent candidate
  sources; candidate cases block the machine Policy Gate.
- SQLite STEP 2 → STEP 3 migration replay.
- SQLite migration replay includes durable `skill_view_shares` at
  `004_step3_shares`.
- Trusted renderer boundary rejects executable tags and iframes.

## Verification commands

```bash
pytest -q tests/frontend/knowledge_workspace_v21141 \
  tests/frontend/test_knowledge_asset_bff.py
# 78 passed, 13 skipped (current focused suite)

cd frontend
node --test tests/knowledge-workspace-v21141/*.test.mjs
# 75 passed
npm run build
# production and website-integration bundles built

npm test
# 817 passed, 0 failed
```

## Remaining gates

- The STEP 3 comparator is shell-consistency evidence against its own frozen
  STEP 3 contract reference. It must not be described as a pass against the
  earlier commercial-workspace visual baseline.
- `invocation.start` remains limited to the explicit STEP 3
  `test://` / `draft://` path, while formal publication invocation remains
  STEP 4.
- Typed assistant patch validation, durable undo, and real rerun are verified
  in focused backend integration.
- `evaluation.apply`, historical/batch/agent candidate ingestion, and
  per-case evidence refs are verified in focused backend integration.
- Production PostgreSQL execution path has been exercised against a live
  isolated PostgreSQL instance; distributed multi-process queue deployment is
  not claimed.

STEP 3 passes with formal publication adaptation explicitly reserved for
STEP 4. The static guard passes against the immutable STEP 2 handoff baseline
(`f734b067`) with zero findings. Declared STEP 3 verification entrypoints are
in scope, while generated runtime evidence remains outside the release
worktree.
