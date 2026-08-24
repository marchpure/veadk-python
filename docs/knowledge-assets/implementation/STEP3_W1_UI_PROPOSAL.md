# STEP 3 Worker 1 UI Proposal

Status: `PROPOSED_FOR_MAIN_INTEGRATION`

Worker 1 did not modify frozen UI, `WorkspaceHost`, the shared shell, public
routes, or generated clients. Main should bind the existing v2.13.1 views to
the Worker-owned typed application port.

## Required route/read-model wiring

| UI state/action | Command or query | Typed result | Required UI states |
| --- | --- | --- | --- |
| Data overview | `data_overview` | `DataOverviewView` | loading, empty, populated, permission error |
| Persistent “+” / Add data | `add_data` | `AddDataView` | category/search, selected connector, blocked reason |
| Connector directory | `connector_catalog` | `ConnectorCatalogView` | all 37 entries, search, category counts |
| Connector configure/save | `create_connection` | `CreateConnectionResult` | validating, discovering, ready, config required, credential blocked, unsupported, error |
| Connection detail | `connection_detail` | `ConnectionDetailView` | status, schemas, resources, refresh/revoke/delete actions |
| Import selected resource | `ingest` | `IngestLifecycleResult` | source/profile/clean/golden progress and terminal result |
| Refresh | `refresh` | `RefreshResult` | promoted, schema drift, failed with last-good, permission denied |
| Retry/cancel | `retry_refresh` / `cancel_refresh` | `RefreshResult` / `RefreshRunRecord` | retry lineage and cancelled terminal state |
| Golden detail | `golden_asset_detail` | `GoldenAssetDetailView` | overview, preview, fields, lineage, quality, usage |
| Golden bytes/rows | `golden_data` | `GoldenDataView` | fixed authorized revision only |
| Add to Composer/W2 | `golden_resource_binding` | `GoldenResourceBinding` | fixed Source/Golden revisions, digests, freshness, lineage, permission |
| Revoke/delete | `revoke_connection` / `delete_connection` | terminal command result | immediately remove inherited Source/Golden visibility |

The exact consumer contract is
`tests/fixtures/knowledge_workspace_v21141/step3-w1-ui-consumer-contract.json`.

## Empty catalog and unavailable-resource correction

Main must call `SourceGoldenApplication.bootstrap_projection(context)` when
building Workspace bootstrap data and assign its non-empty
`workspaceData.connectorCatalog`. It must register the three deep-link route
keys returned by that projection:

- `data_overview`
- `add_data`
- `connector_catalog`

The UI must not fall back to the prototype registry or mark a route
“资源暂不可用” after a typed result exists. A typed blocked state is rendered
from `capabilityState` and `reason`; a transport failure uses the stable error
envelope. The server catalog, not browser constants, is authoritative.

## Connector form rules

- CSV, Excel, SQLite, Markdown, and PDF use `sourceRef`; they never show host
  fields.
- PostgreSQL and Oracle show database host/port/database-or-service fields and
  accept credentials only through `secretRef`.
- Web/API forms show endpoint, operation allowlist, pagination, refresh, and
  credential reference fields.
- Office forms show resource identity, authorization scope, and the declared
  provider scopes.
- Local stdio MCP shows distinct command, args, env, cwd, startup timeout,
  call timeout, tool allowlist, and output budget controls.
- Remote MCP shows endpoint/OAuth inputs but remains
  `credential_blocked`; it must not reuse local stdio success.
- `doc_txt` currently means real PDF ingestion. Markdown uses `local_file`;
  TXT/HTML remain unsupported and must not be advertised as runnable.

## Errors and recovery

Render `reason.code` or the typed operation error, never infer “no data”:

- credential/configuration blockers retain the filled form and recovery action;
- schema drift shows the staging attempt and the retained last-good revision;
- timeout/process exit/invalid message/tool failure expose a retry action only
  when `retryable=true`;
- revoked or unauthorized resources disappear from normal listings and return
  permission/not-found states on direct links;
- sensitive values are never rendered from env, trace, exceptions, or source
  configuration.

## W2 and MAIN binding

Composer drag/add sends only the selected `GoldenResourceBinding` identity.
W2 resolves and re-authorizes it server-side, then consumes:
`revision`, `providerRevision`, `schemaDigest`, `contentDigest`,
`freshnessAt`, `dataAsOf`, `lineage`, and `permissions`.

Main must not pass raw MCP credentials or resolved environment values to W2.
MCP tool discovery uses `DiscoveredResource.inputSchema/outputSchema`; MCP
execution and process lifecycle remain W1-owned. W2 owns Agent planning, W3
owns rendering/execution, and Main owns shared route/command registration.
