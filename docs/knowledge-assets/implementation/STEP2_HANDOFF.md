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
This corrective integration handoff supersedes the earlier closeout after
worker proposal registration and contract/security hardening.

## Worker status

| Worker | Scope | Status |
|---|---|---|
| A | Files / Office context proposal | PROPOSAL_ONLY |
| B | Database / Oracle proposal | PROPOSAL_ONLY |
| C | Web / API proposal | PROPOSAL_ONLY |
| D | MCP / published Skill proposal | PROPOSAL_ONLY |
| I | canonical integration, local Golden Data, generated contracts | INTEGRATING |
| Q | quality, migration, security, handoff | INTEGRATING |

Worker proposal commits: A `9710d502`, B `3536975a`, C `cd35ff6f`,
D `e07cc1d5`; all are rooted at `88efe108` and modify only their proposal
artifact.

## Evidence

- `pytest -q tests/frontend/knowledge_workspace_v21141
  tests/frontend/test_knowledge_asset_bff.py` — 61 passed, 13 skipped
  external-E2E cases.
- Refresh/schema-drift/last-good subset — 9 passed.
- SQLite migration replay subset — 1 passed; 21 tables verified.
- `python tests/production_readiness/knowledge_workspace_v21141/static_guard.py --repo-root .`
  — `status: pass`, zero findings.
- Schema generation — passed; generated artifacts had no diff.
- `git diff --check` — passed.
- Secret-leak scan — no findings.
- Kind-specific connector contract schema — 17 discriminated kinds generated;
  database/file/web/MCP configs reject cross-kind fields.
- Append-only replay checks — source revision replay and same-content Golden
  Asset refresh preserve historical rows.
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
The connector SPI and kind-specific config contracts are implemented, but
Oracle/Web/MCP/published Skill are not credentialed production integrations.
Durable queue deployment, full parser-backed PDF/Office/Excel ingestion,
full downstream revocation propagation, provider pagination/terms E2E,
and the inherited STEP 0 visual waiver remain follow-up debt. Contract-level
MCP prompt-injection quarantine and SQL row/byte/time validation are covered;
provider execution enforcement remains blocked without real adapters.

## Immutable handoff tag

The existing tag `knowledge-skill-factory-step-2-integration` was not moved or
overwritten. A new corrective immutable tag is created after final commit.
