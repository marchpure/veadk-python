# STEP 3 Worker 1 Contract Proposal

Status: `PROPOSED_FOR_MAIN_INTEGRATION`

Worker: Backend Worker 1 — Sources, Connectors, and Golden Data

This proposal freezes the Worker-owned typed seam. Worker 1 did not change the
shared contract schema, generated clients, migration head, public BFF router,
or `frontend/server/knowledge_assets/application.py`.

## Application port

Main should construct `SourceGoldenApplication` with a production database
path, content-addressed artifact root, workspace source root, DNS resolver, and
injected secret resolver. The public operations are:

- `connector_catalog(context, category?, query?) -> ConnectorCatalogView`
- `add_data(context, connector_key?) -> AddDataView`
- `bootstrap_projection(context) -> dict`
- `create_connection(...) -> CreateConnectionResult`
- `data_overview(context) -> DataOverviewView`
- `connection_detail(context, connection_id) -> ConnectionDetailView`
- `adapter_contract(connector_key) -> AdapterContract`
- `ingest(...) -> IngestLifecycleResult`
- `refresh(...) -> RefreshResult`
- `retry_refresh(...) -> RefreshResult`
- `cancel_refresh(...) -> RefreshRunRecord`
- `golden_asset_detail(context, asset_id) -> GoldenAssetDetailView`
- `golden_data(context, revision_id) -> GoldenDataView`
- `golden_resource_binding(context, revision_id) -> GoldenResourceBinding`
- `source_revision(context, revision_id) -> SourceRevisionRecord`
- `golden_revision(context, revision_id) -> GoldenAssetRevisionRecord`
- `revoke_connection(...)` and `delete_connection(...)`
- `mcp_process_traces(context, connection_id) -> list[McpProcessTrace]`

All request and result models inherit the repository `ContractModel`, use
camel-case aliases, and reject undeclared fields.

## Connector definition and instance

`ConnectorDefinition` is the server-owned catalog contract:

- identity: `connectorKey`, `category`, `name`, `description`
- truthful state: `capabilityState` and structured `reason`
- form contracts: `inputSchema`, `credentialSchema`
- behavior: `capabilities`, `discoveryModes`, `syncModes`
- authorization: read/manage/provider scopes and source-ACL inheritance

`ConnectionInstance` is the durable configured instance:

- workspace, owner, and `personal|team` scope
- current status and last success/error
- public configuration and opaque `secretRef`
- discovered resources and their field/tool schemas

The catalog has exactly 37 definitions: office 10, file 8, database 11,
API/stream 5, and custom/MCP 3. The capability proposal records every state
and blocker. Catalog presence never implies adapter success.

## Source-to-Golden lifecycle

Successful ingestion atomically persists these typed records:

1. `SourceRevisionRecord` with immutable content and schema digests.
2. `ProfileRunRecord` with inferred fields, quality, sensitive fields, and
   content-addressed report/sample refs.
3. versioned `CleaningRecipeRecord`.
4. `CleanRunRecord` with content-addressed NDJSON and quality report.
5. versioned `GoldenAssetRevisionRecord` with owner, effective permissions,
   lineage, freshness, `dataAsOf`, trace, and last-good status.

Refresh first creates a staging candidate. Compatible schema is promoted;
schema drift and source/MCP failure preserve the prior last-good revision.
Create, ingest, refresh, retry, and cancellation use principal-scoped
idempotency keys.

## Main and W2 Golden binding

`GoldenResourceBinding` is the stable read contract to use in Composer and W2
context resolution:

```text
kind
objectId
revision                  # pinned GoldenAssetRevision id
providerRevision          # pinned SourceRevision id
displayName
scope
schemaDigest
contentDigest
semanticFields
capabilities
freshnessAt
dataAsOf
lineage
permissions
authorized
```

`GoldenDataView` combines this binding with the authorized, sanitized rows.
Main and W2 must re-authorize the pinned revision server-side; browser claims
must not set `authorized`, permissions, workspace, or revision identity.
Revoking the source makes both Source and Golden reads unavailable.

## Local stdio MCP configuration

`StdioMcpConfiguration` is:

```json
{
  "transport": "stdio",
  "command": "/absolute/executable",
  "args": ["/absolute/server.py"],
  "env": {
    "NON_SECRET_SETTING": "value",
    "API_TOKEN": "secret://workspace-id/reference"
  },
  "cwd": "/absolute/existing/directory",
  "startupTimeoutSeconds": 5,
  "callTimeoutSeconds": 5,
  "toolAllowlist": ["namespace.tool"],
  "outputBytes": 1000000
}
```

Security and lifecycle invariants:

- `command`, `args`, `cwd`, and `env` remain separate and
  `subprocess.Popen(..., shell=False)` is mandatory.
- Sensitive environment values are workspace-bound `secret://` references.
  Only an injected resolver obtains their values at process start.
- Resolved values are excluded from configuration, trace, exceptions,
  artifacts, and persisted revisions.
- Relative/missing `cwd`, sensitive args, inline sensitive env, missing
  executable, out-of-allowlist tools, and excess output fail closed.
- Startup, each request, and process exit are bounded.
- The client executes `initialize`, sends `notifications/initialized`, calls
  `tools/list`, optionally calls `tools/call`, attempts `shutdown`, sends EOF
  for SDKs using current stdio shutdown semantics, and reaps the process.
- Legal server notifications may occur before a matching response.

Discovered MCP tools are normal `DiscoveredResource` records with
`resourceType=tool`, `inputSchema`, and optional `outputSchema`.
`McpToolCallRequest` and `McpStructuredResult` freeze the call boundary.
The latter carries rows, content digest, `dataAsOf`, correlation ID, and
adapter run ID. The subsequent Source/Golden lineage repeats the correlation,
run, content digest, tool arguments, and revision references.

## Stable error codes

Main should preserve these codes in the existing typed error envelope:

- generic/source: `PERMISSION_DENIED`, `CONNECTOR_NOT_FOUND`,
  `INVALID_CONNECTION`, `INVALID_CONFIGURATION`,
  `INVALID_SECRET_REFERENCE`, `INLINE_SECRET_REJECTED`,
  `CONNECTION_NOT_READY`, `RESOURCE_REQUIRED`,
  `SOURCE_INGEST_FAILED`, `SOURCE_READ_FAILED`, `SCHEMA_DRIFT`,
  `GOLDEN_ASSET_NOT_FOUND`, `GOLDEN_REVISION_NOT_FOUND`,
  `SOURCE_REVISION_NOT_FOUND`, `REFRESH_NOT_RETRYABLE`
- MCP: `MCP_CONFIGURATION_INVALID`, `MCP_PROCESS_START_FAILED`,
  `MCP_PROCESS_EXITED`, `MCP_TIMEOUT`, `MCP_INVALID_MESSAGE`,
  `MCP_PROTOCOL_ERROR`, `MCP_JSONRPC_ERROR`, `MCP_METHOD_NOT_FOUND`,
  `MCP_TOOL_NOT_ALLOWED`, `MCP_TOOL_FAILED`, `MCP_OUTPUT_LIMIT`,
  `MCP_INVALID_TOOL_RESULT`, `MCP_UNTRUSTED_OUTPUT`

## Persistence mapping requested from Main

The Worker repository uses private SQLite tables for connections,
idempotency, connector operations, Source/Profile/Clean/Golden records,
refresh runs, and MCP process traces. Main may adapt these records to shared
production persistence without changing their immutable IDs and digests.
Artifacts remain content-addressed and are verified again on read.

Main integration must preserve workspace and personal-principal isolation,
revoke propagation, server-side authorization, last-good behavior, stable
error codes, and secret redaction. No Agent planning, Dashboard rendering, or
publication behavior belongs in this contract.
