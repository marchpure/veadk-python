# STEP 3 Worker 4 UI Proposal

Status: `READY_FOR_MAIN_REVIEW`

Main is the only frontend owner. The frozen Evaluation components contain
localStorage, timers, fixed scores, and simulated fixes/publication; they are
interaction references only.

## Required Binding

- `EvaluationCenterView` reads immutable suites/runs from the BFF.
- Add-case supports manual, historical conversation, historical run, CSV,
  JSON, and Agent candidate sources.
- Agent candidates render as pending and require an explicit confirmation
  action before a run can include them.
- Run state comes from durable Operation events and survives refresh.
- Cancel, resume, and retry invoke typed commands.
- Case details render input, expected, actual, grading, evidence, trace,
  regression diff, and duration from the run read model.
- “Fix issue” and “Fix all unresolved” first show affected cases, conflicts,
  and typed operations. Apply creates a new draft revision; Undo uses its
  server token.
- Policy UI displays all nine dimensions and machine-readable reasons.
- “Evaluate and publish” ends at eligibility during STEP 3. All publish-to-
  Agent and invocation controls remain visible but disabled/gated for STEP 4,
  with no success toast.

## Main-Owned Corrective Findings

- Remove fixed 88/100 scores and timer-completed evaluations.
- Remove localStorage evaluation/share business state from active production
  composition.
- Remove simulated “all fixes passed” and “published to Agent” outcomes.
- Replace `mockKpis` and `mockTrendData` production compatibility names. The
  arrays are server-hydrated, but the production graph still violates the
  explicit no-mock naming/static gate.
- Bind Action Policy, review, decision, and evidence-highlight states to
  policy/evaluation read models or show an honest gate.

## Browser Acceptance

Run all 43 candidate states and all 23 frozen routes at fixed desktop and
mobile viewports. Required checks: reachable action, server trace, refresh
recovery, DOM/text/action, geometry/style, visual diff, a11y, keyboard/IME,
responsive layout, console/page errors, bundle, and performance.

No browser result is claimed by Worker 4 until Main publishes its single
integration URL and Playwright MCP is available.
