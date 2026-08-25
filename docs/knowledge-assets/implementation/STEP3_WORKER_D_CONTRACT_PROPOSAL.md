# STEP 3 v2.13.1 Worker D Contract Proposal

Status: `READY_FOR_MAIN_REVIEW`

Worker D owns the Evaluation, publication-facing UI, invocation selector,
refresh, drift, alert, and comment-fix screens. Shared contracts, generated
clients, routes, repositories, and migrations remain MAIN-owned. The current
shared API is sufficient for the existing fail-closed command loop but cannot
fully satisfy every STEP 3 v2.13.1 acceptance item without the additions below.

## Required shared contract changes

1. `PublicationPublishPayload.visibility`
   - Add `visibility: "personal" | "team" | "public"`.
   - Persist visibility on `PublishedSkillVersion`.
   - Return visibility in bootstrap `publications[]`.
   - Server must reject unsupported visibility before writing a published row.

2. `PublishedSkillVersion` registry read model
   - Return `name`, `inputSchema`, `outputSchema`, `dependencies`,
     `permissions`, `compatibilityTargets`, `qualityScore`, `invocationCount`,
     `freshness`, `consumerCount`, `skillViewRevisionId`, and
     `dataRevisionRefs`.
   - Registry rows must be derived from persisted Published Skill records, not
     browser state.

3. `InvocationStartPayload` server-derived callerId
   - Remove client-authoritative `callerId` or replace it with an optional
     opaque `callerRef`.
   - Route should set the persisted `Invocation.caller_id` from
     `identity_resolver`.
   - Client-provided caller identifiers should be ignored or rejected.

4. `RefreshSchedule`
   - Add commands:
     - `refresh-schedule.upsert`
     - `refresh-schedule.pause`
     - `refresh-schedule.resume`
     - `refresh-schedule.delete`
   - Persist `skillId`, cron/frequency, timezone, retry policy,
     stale-data policy, delivery policy, nextRunAt, lastRunId, lastGoodRevision,
     status, and failure reason.
   - Execute schedules through the backend job framework after the browser is
     closed.
   - Return schedules and recent `RefreshRun` records in bootstrap or a read
     endpoint.

5. `SchemaDrift`
   - Extend `RefreshRunResult` with a structured drift report:
     missing fields, added fields, type changes, impacted views,
     impacted published skills, impacted consumers, and an analysis entrypoint.
   - Persist drift reports from real `refresh.run` / probe execution.

6. `AlertRule`
   - Add commands:
     - `alert-rule.upsert`
     - `alert-rule.test-send`
     - `alert-rule.pause`
     - `alert-rule.resume`
   - Persist rule definition, notification channels, adapter configuration
     reference, test-send result, delivery trace, and history.
   - Return rule and event history in bootstrap or a read endpoint.
   - If notification adapters are not configured, return a failed result with
     an explicit `NOTIFICATION_ADAPTER_NOT_CONFIGURED` error.

7. `CommentThread`
   - Add commands:
     - `comment.create`
     - `comment.resolve`
     - `comment.reopen`
     - `comment-fix.propose`
     - `comment-fix.apply`
     - `comment-fix.retry-failed`
     - `comment-fix.undo`
   - Persist comment status, fix plan, patch result, per-item regression
     result, failed-item retry, and undo token.
   - The current `evaluation-fix.*` domain can be reused when comments are
     already mapped to an EvaluationRun; otherwise comment-fix needs its own
     durable aggregate.

8. Metric semantics policy gate
   - Add a first-class policy dimension for metric definition / metric
     semantics, or define which existing dimension is authoritative for
     “指标口径”.
   - Current literals include `data_quality` and `security`, but no dedicated
     metric-semantics dimension.

## Current Worker D UI behavior pending MAIN integration

- Existing real commands are invoked for evaluation suite/case/run/fix/gate,
  share, export, refresh, invocation, and action update paths.
- The publication UI intentionally does not call `publication.publish` while
  `PublicationPublishPayload.visibility` is absent, because the STEP 3
  requirement says visibility must be sent to the server and persisted.
- Unsupported shared capabilities fail closed in the UI with explicit
  contract-missing messages.
- No Worker D-owned UI source uses browser localStorage or timer-based fake
  success to complete business operations.
