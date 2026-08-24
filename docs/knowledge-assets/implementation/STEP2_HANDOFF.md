# STEP 2 Integration Handoff

Date: 2026-08-24

## Result

`READY_WITH_BASELINE_DEBT`

This handoff freezes the STEP 2 integration boundary for the real
`data_access` Skill plus Golden Data chain. The Skill remains the only
top-level product; source connections are `data_access` connectors/drafts.
STEP 3 Skill View generation and STEP 4 publishing were not started.

## Integration commits

- `4c15dabf` — STEP 1 corrective quality lane; authoritative static guard
  passes with zero findings.
- `51d7a4f7` — local Markdown/CSV Golden Data flow.
- `5cb89fce` — typed Connector SPI and explicit credential blocking.
- `3a7304dc` — authenticated runtime BFF composition.
- `62a086ea` — append-only Golden Data revisions and tombstones.
- `26de3274` — authenticated-workspace permission revocation through BFF.

Frozen implementation baseline: `74ad5437b300c0914f1c99adbfb188335eaa080b`
This final corrective handoff is committed separately after verification.

## Worker status

| Worker | Scope | Status |
|---|---|---|
| A | contracts, generated client, `/api/knowledge-assets/v1/*` seam | PASS |
| B | local Markdown/CSV source, profile, clean, Golden Data lifecycle | PASS |
| C | browser seam and action wiring | PASS |
| D | runtime composition and connector/security boundaries | PASS |
| E | static guard, migration, focused contract/security evidence | PASS |

These are final integration ownership lanes in this worktree; no additional
worker worktrees or independent external connector implementations are implied.

## Evidence

- `pytest -q tests/frontend/knowledge_workspace_v21141
  tests/frontend/test_knowledge_asset_bff.py` — 50 passed, 13 skipped
  external-E2E cases.
- Refresh/schema-drift/last-good subset — 9 passed.
- SQLite migration replay subset — 1 passed; 21 tables verified.
- `python tests/production_readiness/knowledge_workspace_v21141/static_guard.py --repo-root .`
  — `status: pass`, zero findings.
- Schema generation — passed; generated artifacts had no diff.
- `git diff --check` — passed.
- Secret-leak scan — no findings.
- Production-boundary evidence — 18 passed with the temporary same-version
  dependency link removed afterward.
- Refresh matrix — staging success, source-read failure preserving last-good,
  and schema-drift rejection passed.
- Security matrix — SSRF/DNS rebinding, inline-secret rejection, read-only
  parameterized SQL, MCP allowlist, and output budget passed.

The authoritative static guard owns scope, split, and gross/net budget checks;
the historical test wrapper now delegates those checks instead of pinning a
historical production-file count.

## Credential and data boundary

Local Markdown and CSV complete the real source revision → profile → clean →
artifact → Golden Data revision → draft run path without external credentials.
The persisted lifecycle includes `SourceRevision`, `ProfileRun`, `CleanRun`,
and `GoldenAssetRevision`; refresh uses staging, publishes same-schema
success, rejects schema drift, and preserves the last-good revision after
source-read failure.
Oracle, Web API, MCP, and published Skill connectors return
`credential_blocked` until real configuration is supplied. No credentials are
stored in manifests, logs, frontend state, or Git, and no external connector
success is simulated.

## Explicit baseline debt

Oracle, Web API, MCP, and published Skill real-credential E2E tests remain
skipped/`credential_blocked`; complete production connectivity is not claimed.
The connector SPI is implemented, but these are not credentialed production
integrations. Durable queue deployment, broader file formats
(PDF/Office/Excel/archive), full downstream revocation propagation,
MCP prompt-injection defenses, SQL row/byte/time quotas, and the inherited
STEP 0 visual waiver remain follow-up debt.

## Immutable handoff tag

The existing tag `knowledge-skill-factory-step-2-integration` was not moved or
overwritten. A new corrective immutable tag is created after final commit.
