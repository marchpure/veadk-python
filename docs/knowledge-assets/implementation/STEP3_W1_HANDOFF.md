# STEP 3 Worker 1 Handoff — Sources, Connectors, and Golden Data

Status: `READY_FOR_INTEGRATION`

## Provenance and scope

- Worktree:
  `/Users/bytedance/.codex/worktrees/knowledge-step3-worker1-sources-golden`
- Branch: `feat/knowledge-step3-worker1-sources-golden`
- Fixed checkpoint:
  `31a26a6fd0547a7696af62b97b42a842f07f8339`
- Preserved proposal-only commit:
  `85b8a19c46928b75044be8a265ec7694a992a1fc`
- Implementation commit:
  `da3fd63266be81928203212592b2c306677bde30`
- Protocol hardening commit:
  `26c7008409e11f95b8cf0717391c03413381e70e`
- Sensitive-result hardening/code head:
  `bcc084d43eb056daf64f45fedca1a41d1f67086b`
- Contract digest:
  `108d962c73517f45367e924bd330882564a984aee57700bf95ee92e1c3431c12`
- UI delta digest:
  `dd1b90bb917052929a13852558025956263c3b104e47a73b44dba0ece93e4d30`
- Prototype archive SHA-256:
  `ce6e086b806072c363f23ed68c9e067b30b280738af0284eeb60ca36c22e5571`
- Migration head was left at `004_step3_shares`.

The implementation is confined to
`frontend/server/knowledge_assets/sources_golden/`, W1 tests/fixtures, and W1
proposals/evidence/handoff. It does not implement `veadk.Agent`, a Dashboard
renderer, or publication, and does not modify another Worker worktree.

## Delivered implementation

- Server-owned catalog of 37 `ConnectorDefinition` records, with exact
  category counts 10/8/11/5/3 and truthful capability state, form schemas,
  permissions, sync/discovery modes, and structured blocker.
- Durable `ConnectionInstance`, connector operation, idempotency, Source,
  Profile, recipe, Clean, Golden, refresh, and MCP process-trace persistence.
- Typed `data_overview`, `add_data`, `connector_catalog`,
  `connection_detail`, `golden_asset_detail`, `golden_data`, and
  `GoldenResourceBinding` read models.
- Non-empty `bootstrap_projection().workspaceData.connectorCatalog` and route
  keys for `data_overview`, `add_data`, and `connector_catalog`; Main only
  needs to bind the provided port to remove the current empty catalog and
  “资源暂不可用” fallback.
- Real Markdown, CSV, SQLite, Excel, and PDF
  `SourceRevision → ProfileRun → CleaningRecipe/CleanRun →
  GoldenAssetRevision` flow with content-addressed artifacts.
- Schema drift staging, last-good retention, refresh retry/cancel,
  idempotency, restart recovery, immutable revision replay, lineage,
  freshness/`dataAsOf`, sensitive-field redaction, and permission/revoke
  propagation.
- Fail-closed Oracle, PostgreSQL, Lark, Web/API, and remote MCP adapter
  contracts with read-only SQL, limits, SSRF validation, secret references,
  and accurate blocked states.

Catalog truth is:

- `available` (5): CSV, Excel, PDF, Markdown, SQLite.
- `configurable` (3): webhook, local/remote MCP definition, custom HTTP.
- `credential_blocked` (26): Lark/office, external object stores/databases,
  REST/GraphQL/Web/Kafka.
- `unsupported` (3): JSON, Parquet, OpenAPI spec.

`mcp_custom` becomes a ready connection only for a successfully initialized
local stdio configuration. Remote MCP remains credential blocked. The complete
37-row matrix is in `STEP3_W1_CAPABILITY_MATRIX_PROPOSAL.yaml`.

## Local stdio MCP P0

The client starts a separate OS process with `shell=False` and distinct
command, args, env, and cwd. It enforces workspace-bound `secret://` env
references through an injected runtime resolver, startup/call/exit timeouts,
combined stdout/stderr output budget, tool allowlist, valid absolute cwd,
sanitized output/errors, and process reaping.

Each session executes:

```text
initialize
notifications/initialized
tools/list
tools/call                    # ingestion/refresh sessions
shutdown
stdin EOF
wait/reap
```

The explicit legacy `shutdown` request succeeds against the fault fixture. The
official SDK correctly returns method-not-found for that legacy request, so
the client records it and completes current MCP stdio shutdown through EOF.

Two independent server implementations are included:

- Fault fixture:
  `tests/fixtures/knowledge_workspace_v21141/mcp_habitat_server.py`
- Official SDK server:
  `tests/fixtures/knowledge_workspace_v21141/mcp_sdk_infrastructure_server.py`
  using `mcp==1.26.0` / `FastMCP`

Full launch contracts, including argv, cwd, environment references, and
`shell=false`, are in `STEP3_W1_MCP_EVIDENCE.json`. The executable argv values
recorded in the final run are:

```text
/Users/bytedance/.pyenv/versions/3.13.7/bin/python3 \
  /Users/bytedance/.codex/worktrees/knowledge-step3-worker1-sources-golden/tests/fixtures/knowledge_workspace_v21141/mcp_habitat_server.py

/Users/bytedance/.pyenv/versions/3.13.7/bin/python3 \
  /Users/bytedance/.codex/worktrees/knowledge-step3-worker1-sources-golden/tests/fixtures/knowledge_workspace_v21141/mcp_sdk_infrastructure_server.py
```

The generic editable sample is
`tests/fixtures/knowledge_workspace_v21141/step3-w1-mcp-stdio-example.json`.

## Official SDK cross-implementation evidence

Evidence file:
`docs/knowledge-assets/implementation/STEP3_W1_MCP_EVIDENCE.json`

- Evidence SHA-256:
  `8e7de2cd36f6f079f5fc1c6f6531c64ddc2584d71a1af04739cbfb76a3b6c05b`
- Evidence implementation commit:
  `bcc084d43eb056daf64f45fedca1a41d1f67086b`
- Official SDK version: `mcp 1.26.0`
- Fault-fixture PIDs: `89428`, `89429`; both were independent, reaped, and
  no longer alive.
- Independent PIDs: `89430`, `89431`, `89452`; all differ from the caller,
  report `processReaped=true`, and are no longer alive.
- Negotiated protocol: `2025-11-25` in all three sessions.
- Server: `repository-infrastructure-metrics`.
- `tools/list` returns `infrastructure.metrics` with real `inputSchema` and
  SDK-generated `outputSchema`.
- Two `tools/call` exchanges read a local infrastructure metrics file before
  and after mutation.

Data-change proof:

| Evidence | Before | After |
| --- | --- | --- |
| tool value | search CPU `41.2` | search CPU `52.8` |
| Source revision | `source-d54deed0f9d9c3a5aa6b8c6a` | `source-521784eda0522458df49a136` |
| Source/content digest | `0c88b9bcb59fba3bd9c0b8289fc63b5c2c8a692da078b6cf7e883efcd10d4535` | `faf2db64f718b699f7b6623df8fc8d07b2179a5b3bbbe992cd820c038fa8113a` |
| Golden revision | `golden-e67e5096fe82adebeb7e2ecb-r1-866d7fa7` | `golden-e67e5096fe82adebeb7e2ecb-r2-765185b8` |
| Golden output digest | `866d7fa7add621202468a00257f12fb870d870236e838b4221484803e4a2c8ac` | `765185b869a9a72abb76048a6bca87b96f9e094b659701cdffea697ef02d71da` |
| `dataAsOf` | `2026-08-25T08:00:00Z` | `2026-08-25T08:05:00Z` |

Freshness timestamps, tools/call output, Source revision/digest, Golden
revision/output digest, and `dataAsOf` all changed. Each Golden lineage points
to the matching Source revision, MCP adapter run, content digest, correlation
ID, and tool arguments.

## Fault and security evidence

The independent fixture verifies:

| Scenario | Stable result |
| --- | --- |
| initialize timeout | `MCP_TIMEOUT` |
| process exit during initialize | `MCP_PROCESS_EXITED` |
| invalid JSON-RPC | `MCP_INVALID_MESSAGE` |
| stderr or tool output budget exceeded | `MCP_OUTPUT_LIMIT` |
| tool outside allowlist | `MCP_TOOL_NOT_ALLOWED` |
| process hangs after shutdown response | `MCP_TIMEOUT` |
| tools/call timeout | `MCP_TIMEOUT` |
| tool reports failure | `MCP_TOOL_FAILED` |
| missing executable | `MCP_PROCESS_START_FAILED` |
| relative cwd | `MCP_CONFIGURATION_INVALID` |
| inline sensitive env or args | `MCP_CONFIGURATION_INVALID` |

All spawned failure processes were reaped and dead after the run. Pre-spawn
rejections recorded zero process traces. Tool failures created no revision.
The runtime secret sentinel had zero matches in SQLite, artifacts, traces,
errors, and evidence; only its `secret://` reference was persisted.

Reproduce the evidence with a new, nonexistent runtime directory:

```text
/Users/bytedance/.pyenv/versions/3.13.7/bin/python3 \
  tests/fixtures/knowledge_workspace_v21141/generate_step3_w1_mcp_evidence.py \
  --output /tmp/step3-w1-mcp-evidence.json \
  --runtime-dir /tmp/step3-w1-mcp-runtime
```

## MAIN/W2 frozen seam

Main should review:

- `STEP3_W1_CONTRACT_PROPOSAL.md`
- `STEP3_W1_UI_PROPOSAL.md`
- `STEP3_W1_CAPABILITY_MATRIX_PROPOSAL.yaml`
- `tests/fixtures/knowledge_workspace_v21141/step3-w1-ui-consumer-contract.json`

W2 consumes `GoldenResourceBinding`: fixed Golden and Source revisions,
schema/content digests, lineage, freshness/`dataAsOf`, and effective
permissions. MCP discovery supplies tool name plus input/output schemas;
execution returns structured rows with content digest, correlation ID, and
run ID. Main must re-authorize every pinned revision and register the shared
BFF/command routes. W1 does not expose resolved secrets or raw subprocess
internals.

## Verification

- W1 focused:
  `python -m pytest -q tests/frontend/knowledge_workspace_v21141/test_step3_sources_golden.py`
  → `38 passed`
- Full STEP 3 directory:
  `python -m pytest -q tests/frontend/knowledge_workspace_v21141`
  → `99 passed, 13 skipped`
- `pre-commit` scoped to all W1 files:
  Ruff check passed, Ruff format passed, gitleaks passed.
- Mypy over all eight W1 source files with
  `--follow-imports=skip --ignore-missing-imports`: no issues.
- `compileall`: passed.
- JSON and YAML parsing: passed.
- `git diff --check`: passed.
- Evidence runner and machine assertions: passed.
- A second run from a new empty runtime directory reproduced the official SDK
  calls, revision/digest changes, all 13 fault cases, secret scan, process
  reaping, SQLite lifecycle rows, and content-addressed artifact hashes.

The 13 skips are existing external-system E2E gates and are not converted into
success claims by this worker.

## Known integration facts

- Main owns shared BFF/command registration and must bind
  `bootstrap_projection`; W1 did not cross that ownership boundary.
- External Oracle/PostgreSQL/Lark/Web/API and remote MCP do not claim live
  provider success without credentials.
- Excel `.xlsx/.xls` passed in the current environment with
  `openpyxl 3.1.5` and `xlrd 2.0.2`; those packages are not direct project
  dependencies and Main must package them or downgrade that capability.
- PDF uses the declared `pypdfium2 4.30.0` dependency.
- `doc_txt` has a real PDF adapter only; TXT/HTML are explicitly not claimed.
- No Agent planning, Dashboard renderer, unified publication, or changes to
  another Worker worktree are included.
