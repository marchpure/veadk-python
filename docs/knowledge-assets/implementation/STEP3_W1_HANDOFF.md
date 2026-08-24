# STEP 3 Worker 1 Handoff — Sources and Golden Assets

Status: `READY_FOR_INTEGRATION`

Worker 1 is an evidence/proposal lane for source catalog and Golden Asset
read-model ownership. The existing Main implementation already provides the
real local Markdown/CSV source revision, profile, clean, and Golden Asset
revision path; no duplicate source runtime is introduced here.

## Owned proposal

- Connector catalog and typed source forms remain Main/BFF-backed.
- Local Markdown/CSV and SQLite-compatible source paths are
  `STEP3_REAL` where the existing repository and migration path provide
  durable revision facts.
- Lark, Oracle, Web API, and Workday MCP forms remain
  `EXTERNAL_CREDENTIAL_BLOCKED`; the catalog and error/recovery states remain
  reachable without claiming provider success.
- Source revisions, profile/clean runs, schema fingerprints, and Golden Asset
  revisions must be referenced by immutable IDs/digests in Composer and
  SkillDraft context envelopes.
- No browser localStorage, mock source data, or provider fixture is a
  production source fact.

## Main integration seam

Main should bind `source.catalog.read`, source creation/refresh, and the
existing Golden Asset read model to the typed authoring and execution ports.
The lane intentionally makes no shared contract, migration, BFF, or frozen UI
change. Existing focused source/Gol­den flow tests are the evidence for the
implemented local path; provider credential-blocked tests are the evidence for
the external paths.

## Verification

- Worktree was created from checkpoint `31a26a6f`.
- No source runtime or shared contract change was needed in this lane.
- Main must retain this proposal as an explicit no-duplication decision.

