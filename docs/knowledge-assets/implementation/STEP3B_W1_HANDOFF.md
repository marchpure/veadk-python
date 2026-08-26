# STEP 3B W1 Handoff — 37 Connector Adapters

Status: `WORKER_ADAPTERS_COMPLETE_37_OF_37_MAIN_WIRING_REQUIRED`

This handoff supersedes the delivery conclusions in
`STEP3_W1_HANDOFF.md` and `STEP3_W1_HANDOFF.json`. Those files are retained
unchanged as historical evidence. In particular, their 5/3/26/3 capability
state split and statements that some adapters are absent no longer describe
the Step 3B implementation.

## Provenance and scope

- Worktree:
  `/Users/bytedance/.codex/worktrees/knowledge-step3b-w1-connectors`
- Branch: `feat/knowledge-step3b-connectors`
- Frozen base and pre-commit HEAD:
  `1411d706825546e3aba465d95f468a2729ddf8bb`
- Delivery commit: resolve with `git rev-parse HEAD` in this worktree. A commit
  cannot embed its own final hash because changing that field changes the hash.
- Database migration changes: none.
- Frozen shared application, HTTP route, and UI files were not modified.

## Completion result

All 37 catalog entries have a registered, callable `ConnectorAdapter`; no
catalog entry is represented by a metadata-only placeholder. Every row has:

- a connector-specific validated configuration contract and catalog form;
- a browser-safe catalog projection; MCP exposes only the server-owned
  `profileId`, never `command`, `args`, `env`, `cwd`, or `secretRef`;
- workspace/source read and manage permissions plus provider scopes where
  applicable;
- callable authentication, authorization, discovery, introspection, sample,
  read, ingest, profile, clean, Golden, refresh, checkpoint, and close stages;
- durable lifecycle/trace state and a connector-specific checkpoint strategy;
- stable `ConnectorAdapterError` failure mapping;
- an auditable row in `STEP3_W1_CAPABILITY_MATRIX.json`.

Catalog and registry totals:

| Measure | Result |
| --- | ---: |
| Catalog entries | 37 |
| Registered formal adapters | 37 |
| `capabilityState=available` | 37 |
| Office | 10 |
| File | 8 |
| Database | 11 |
| API | 5 |
| Custom | 3 |

`capabilityState` describes whether a formal adapter and durable lifecycle
exist. It is deliberately independent from live external-system
certification. Missing external credentials never remove or downgrade an
adapter.

## Live E2E truth

- `passed` (16): CSV, Excel, JSON, Parquet, document/text, local Markdown,
  PostgreSQL, MySQL, SQLite, REST API, GraphQL, web discovery, webhook, local
  and remote MCP, custom HTTP, and OpenAPI paths represented by the 16 matrix
  keys.
- `external_blocked` (21): ten Lark connectors, S3, OSS, eight external
  database/warehouse connectors, and Kafka.

The exact connector-key lists and each row's adapter, configuration,
permissions, driver, checkpoint, typed-error, and blocker evidence are in the
capability matrix. `external_blocked` applies only to live E2E execution where
no credential or provider sandbox was supplied; it does not mean an adapter,
contract, or lifecycle stage is missing.

## Evidence

### Capability matrix

- File: `docs/knowledge-assets/implementation/STEP3_W1_CAPABILITY_MATRIX.json`
- SHA-256:
  `5be0eed4a386894cfd9b61645ba7c27b365b75cd4a87d50b5c4a6cbd88a771c2`
- Audit: 37 unique rows, 37 available states, 16 passed live E2E, 21
  external-blocked live E2E, and zero rows missing a required capability.

### MCP

- External evidence file:
  `/Users/bytedance/.codex/runtime/knowledge-step3b-w1-connectors.LZXDkI/mcp-evidence.json`
- SHA-256:
  `ef71d17dbc4dc93b1ee0cddcb0746e3c08a839274efcdbbd3c63a489b266a324`
- Official SDK: `mcp 1.26.0`; three independent official FastMCP processes
  and two success-fixture processes were reaped.
- Two real `tools/call` operations changed tool output, Source revision,
  content digest, Golden revision/output digest, freshness, and `dataAsOf`.
- Thirteen failure scenarios produced stable typed failures. All nine
  scenarios that spawned a process reaped it; four invalid configurations
  failed before spawning.
- The secret sentinel was absent from persisted data and evidence; only its
  `secret://` reference was persisted.

### Browser

- Evidence directory:
  `/Users/bytedance/.codex/runtime/knowledge-step3b-w1-browser-final3.jHyAgL`
- Report:
  `browser-evidence.json`
- Report SHA-256:
  `0523c3a4dc30cefac4cdd80622960f4898ccb42a2a14bc1218c993ce24ed237a`
- HAR SHA-256:
  `f4c38645ed31bd12ffcfe2c2ebbe2534edd27f58fe5c442354a9b53efbb2af3b`
- Video SHA-256:
  `5db1e89ef5a0c05c7e8c366774aca343bf3cc544a0cf86f951413b3f3d4eaf59`
- MCP transcript: `mcp-transcript.json`, SHA-256
  `7a6ef232d2fbad756e08cba7cf0c4bf96cff5aa8d84ebc71977420cfbf5cf469`.
- Runtime versions: Node `v22.22.3` (`node:http` fixture), PostgreSQL
  `16.15`, and MySQL `8.4.11`.
- Result: PASS; 37/37 connector forms audited, 50 screenshots, zero browser
  console errors. The browser executed upload/discover/read/Golden/context for
  nine local formats, REST/OpenAPI (including schema drift), PostgreSQL/MySQL
  (including refresh and schema drift), and MCP create/discover/call/ingest.
- Negative coverage includes wrong database credentials, SQL writes, row
  budget, HTTP timeout/oversize, SSRF, cross-workspace access, forged context
  refs, and revoked sources.
  Operation/trace consistency was checked for CSV, REST, OpenAPI, PostgreSQL,
  MySQL, and MCP. A signed webhook delivery proved the operation/event trace
  join. Both MCP subprocesses were reaped and absent from the process table.
  Browser refresh and BFF restart restored all 13 non-revoked Golden revisions.

The frozen UI's non-MCP save path remains explicitly fail-closed and creates no
fake local connection, so MAIN still owns that UI wiring. The composed browser
BFF exercised the formal shared commands and then used the visible “作为上下文加入”
flow to verify the immutable Golden reference sent to skill authoring.

### Database and focused test reports

- Core test evidence directory:
  `/Users/bytedance/.codex/runtime/knowledge-step3b-w1-test-evidence-final5`
- Core JUnit report: `core.xml`, 163 passed, SHA-256
  `48a13a28b8da738906923fa6dd2b7bf5f672026ef27a4717ff800baab38d265f`.
- Database JUnit report:
  `/Users/bytedance/.codex/runtime/knowledge-step3b-w1-test-evidence-final/database-live.xml`,
  12 passed against
  `postgres:16-alpine` and `mysql:8.4`, SHA-256
  `427ffeaa2263bfa93dcc3b37c652cbe069785e31a4665c01dcc666eb4d21d40b`.
- Database coverage includes discovery/read, refresh and restart recovery,
  wrong-password typed errors with last-good preservation, write-SQL
  rejection, row/byte limits, trace persistence, and schema drift.

## Verification

- Step 3B plus W1 compatibility: 163 passed.
- PostgreSQL/MySQL live certification: 12 passed.
- Frontend unit tests: 851 passed.
- Frontend production build: passed; only existing chunk-size/dynamic-import
  warnings were emitted.
- Pyright over all changed Python files: 0 errors, 0 warnings.
- Ruff check: passed.
- Ruff format check: all changed Python files formatted.
- Node syntax check and JSON parsing: passed.
- Python `compileall`: passed.
- Pre-commit passed, including Ruff check, Ruff format, and gitleaks.
- Frozen-scope review and `git diff --check`: passed.

Broader suites expose unrelated repository/environment debt without reducing
the connector result:

- `tests/frontend/knowledge_workspace_v21141`: 243 passed, 25 skipped, 2
  failed. Both failures are W3 screenshot tests whose Python environment lacks
  `playwright`.
- `tests/production_readiness/knowledge_workspace_v21141`: 43 passed, 1
  failed. The historical Step 2 static guard compares the current repository
  against an old write-scope baseline and reports pre-existing cross-step
  files.

Neither failure imports, invokes, or reports a Step 3B connector failure.

## MAIN integration order

1. Integrate this delivery without rewriting the frozen base or adding a
   database migration.
2. Preserve and reuse the existing shared commands
   `source-golden.connection.create` and `source-golden.ingest`; instantiate
   `SourceGoldenApplication` with the production artifact root, secret
   resolver, provider drivers, network policy, and server-owned MCP profiles.
3. Add shared BFF contracts/routes for upload and authorized read, then wire
   refresh/retry/cancel and revoke/delete to the existing application methods:
   The worker-owned `http_api.mount_source_golden_routes` already implements
   this surface under `/api/source-golden/v1` for MAIN to mount.
   `POST /uploads` returns server-owned
   `{sourceRef, mediaType, bytes, sha256}`;
   `POST /connections` accepts
   `{connectorKey, displayName, scope, configuration, secretRef,
   idempotencyKey}`; `POST /connections/{connectionId}/ingestions` accepts
   `{resourceId, recipeOperations, idempotencyKey}`;
   `GET /connections/{connectionId}/operations` and
   `/traces/{traceId}` expose authorization-filtered operation evidence;
   `GET /golden-revisions/{revisionId}/content` calls
   `golden_asset_content`; refresh/retry/cancel map to their existing
   application operations. Derive workspace/principal from authenticated
   server context and never expose artifact paths.
4. Mount `create_webhook_ingress(application)` under a shared server route,
   preserving the raw body and signature/delivery/timestamp/trace headers.
5. Bind frozen non-MCP save to upload → create → discover → ingest. For “加入
   Agent 上下文”, submit only
   `{kind:"golden_asset", objectId, revision, providerRevision}` and resolve
   with `golden_resource_binding`/`golden_asset_content`. Reject missing,
   cross-workspace, personal-scope foreign, revoked, or policy-expired
   revisions; ignore any browser-supplied caller identity.
6. Run matrix parity, focused tests, database live tests, and the browser
   certification after composition.

MAIN must also make connector parser availability explicit in packaging.
`openpyxl` and `pyarrow` are currently present only as transitive dependencies.
Add direct runtime declarations for the formats MAIN continues to advertise.
The connector intentionally advertises only `.xlsx`; legacy `.xls` remains
unadvertised because `xlrd` is not a declared runtime dependency.

## Changed files

- `docs/knowledge-assets/implementation/STEP3_W1_CAPABILITY_MATRIX.json`
- `docs/knowledge-assets/implementation/STEP3B_W1_HANDOFF.json`
- `docs/knowledge-assets/implementation/STEP3B_W1_HANDOFF.md`
- `frontend/server/knowledge_assets/connector_contracts.py`
- `frontend/server/knowledge_assets/sources_golden/__init__.py`
- `frontend/server/knowledge_assets/sources_golden/adapters.py`
- `frontend/server/knowledge_assets/sources_golden/application.py`
- `frontend/server/knowledge_assets/sources_golden/catalog.py`
- `frontend/server/knowledge_assets/sources_golden/catalog_projection.py`
- `frontend/server/knowledge_assets/sources_golden/catalog_schema.py`
- `frontend/server/knowledge_assets/sources_golden/connector_adapter.py`
- `frontend/server/knowledge_assets/sources_golden/connector_registry.py`
- `frontend/server/knowledge_assets/sources_golden/database_adapter.py`
- `frontend/server/knowledge_assets/sources_golden/http_adapters.py`
- `frontend/server/knowledge_assets/sources_golden/http_api.py`
- `frontend/server/knowledge_assets/sources_golden/http_transport.py`
- `frontend/server/knowledge_assets/sources_golden/lifecycle.py`
- `frontend/server/knowledge_assets/sources_golden/local_formats.py`
- `frontend/server/knowledge_assets/sources_golden/mcp_connector.py`
- `frontend/server/knowledge_assets/sources_golden/mcp_remote.py`
- `frontend/server/knowledge_assets/sources_golden/mcp_stdio.py`
- `frontend/server/knowledge_assets/sources_golden/models.py`
- `frontend/server/knowledge_assets/sources_golden/openapi_adapter.py`
- `frontend/server/knowledge_assets/sources_golden/provider_adapters.py`
- `frontend/server/knowledge_assets/sources_golden/provider_verify.py`
- `frontend/server/knowledge_assets/sources_golden/repository.py`
- `frontend/server/knowledge_assets/sources_golden/repository_traces.py`
- `frontend/server/knowledge_assets/sources_golden/webhook_adapter.py`
- `frontend/server/knowledge_assets/sources_golden/webhook_ingress.py`
- `tests/fixtures/knowledge_workspace_v21141/generate_step3b_w1_browser_evidence.mjs`
- `tests/fixtures/knowledge_workspace_v21141/mcp_sdk_remote_server.py`
- `tests/fixtures/knowledge_workspace_v21141/prepare_step3b_browser_databases.py`
- `tests/fixtures/knowledge_workspace_v21141/prepare_step3b_browser_sources.py`
- `tests/fixtures/knowledge_workspace_v21141/step3b_w1_browser_server.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3_sources_golden.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_connector_adapters.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_connector_contracts.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_database_live.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_lark_adapters.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_provider_adapters.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_remote_mcp_live.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_remote_mcp_security.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_source_golden_http_api.py`
- `tests/frontend/knowledge_workspace_v21141/test_step3b_webhook_ingress.py`

Post-audit hardening additionally enforces transport-specific MCP profile
validation, XLSX archive expansion/traversal limits, PDF extracted-text
budgets, OpenAPI parsed depth/node limits, and connector-specific executable
evidence references in every capability-matrix row. Every request also carries
uniform timeout, page, attempt, freshness, typed transient retry, total
deadline, and cooperative cancellation policy; provider-specific blocking I/O
timeouts remain in each network/database/MCP adapter. The mountable HTTP API adds workspace-scoped content-addressed uploads
and a stable Golden context reference resolver that re-authorizes immutable
revisions and rejects stale, cross-workspace, foreign-principal, mismatched, or
revoked references.
