# STEP3B connector R9 status

Validation scope: `production-real-bff`

This checkpoint records evidence status, not a claim that all 37 connectors are usable.

## Authoritative counts

- `LIVE_VERIFIED`: 10
- `LOCAL_PROTOCOL_VERIFIED`: 14
- `CREDENTIAL_BLOCKED`: 13
- `UNSUPPORTED`: 0
- PASS total: 24/37
- `productionPass`: `false`
- `allConnectorsUsable`: `false`

The R8 PostgreSQL and MySQL live evidence remains authoritative and is retained in
the matrix. The later local-provider evidence adds S3/MinIO, Kafka/Redpanda,
ClickHouse, Oracle Free, SQL Server/Azure SQL Edge, target-specific StarRocks,
and target-specific Doris without downgrading the R8 database results.

## R9/R15 evidence

- Browser evidence: `.codex/coordination/knowledge-step3b-integration/CONNECTOR_BROWSER_EVIDENCE_20260827_R15_HIVE.json`
- Matrix: `STEP3B_CONNECTOR_BROWSER_CAPABILITY_MATRIX_20260827.json`
- Real BFF/WebUI flow: catalog → bootstrap projection → create → authenticate →
  authorize → discover → sample/read → ingest → SourceRevision →
  GoldenAssetRevision → checkpoint → refresh/recovery.
- Catalog: 37/37 connectors.
- Bootstrap projection: verified providers available; credential-dependent
  providers remain blocked.
- Doris is now `LIVE_VERIFIED` using the target-specific arm64
  `apache/doris:all-in-one-4.1.3` FE/MySQL protocol service and a server-side
  read-only `secretRef`. The browser completed create, authenticate, authorize,
  discover, bounded read/ingest, SourceRevision, GoldenAssetRevision,
  checkpoint, context resolution, refresh, browser refresh and BFF restart
  recovery.
- Console/page errors: 0.
- HAR consistency: pass.
- Browser refresh and BFF restart recovery: pass.
- Hive is now `LIVE_VERIFIED` using the session-owned
  `apache/hive:4.0.1` HiveServer2 target at `127.0.0.1:26363`. The browser
  completed the same lifecycle against `knowledge.step3b_hive_orders` with a
  server-side `secretRef`; console/page errors were zero and HAR consistency
  passed.

## Blocked policy

The 13 blocked entries are not displayed as available and are not counted as
usable. Their machine-readable required credentials, permissions, and unlock
steps are in `credentialBlockedDetails` in the matrix. No OAuth success,
fixed-success result, fixture, or compatible-engine substitution is used.

The remaining blocked entries require external credentials or provider
Sandboxes. MySQL is not used as Doris/StarRocks evidence, and another SQL
engine is not used as Hive evidence.

## Next local verification batch

Prioritize a real target-specific provider only when it can supply:

1. server-side `secretRef` resolution;
2. target-specific authenticate/authorize/discover/read/ingest;
3. SourceRevision and GoldenAssetRevision;
4. browser evidence including refresh/checkpoint and error paths.

Candidates remain OSS, Snowflake, BigQuery, and Feishu, in that order only
after a real local service or official Sandbox is available.
Until then they remain `CREDENTIAL_BLOCKED`.

## R9 provider probe

- Doris is `LIVE_VERIFIED`: the session-owned
  `apache/doris:all-in-one-4.1.3` arm64 target is healthy on FE/MySQL
  `127.0.0.1:26359`. The browser used the real
  `knowledge.step3b_doris_orders` table and read-only server secret. The seed
  step only performed a read-only existence check; it did not use the
  restricted browser credential for DDL or DML.
- Hive is `LIVE_VERIFIED`: the session-owned `apache/hive:4.0.1`
  HiveServer2 target accepted the real PyHive/Thrift connection and passed the
  browser lifecycle against `knowledge.step3b_hive_orders`.

The machine-readable probe details, attempted targets, observed blocker, and
unlock steps are recorded in `targetProviderProbes` in the authoritative
matrix. No unstarted or substitute service is counted as a verification.

Focused provider tests: `.venv/bin/pytest`
(`test_step3b_provider_adapters.py`) — 63 passed, 12 skipped. The skips are
environment-gated live-provider cases, not synthetic successes. The current
combined connector adapter, provider, Lark, HTTP API, and source-golden focused
suite remains recorded at 159 passed. The separate BFF/authoring regression
remains 107 passed.

The R9 matrix correction also reconciles the row-level browser projection:
`lark_doc` is `CREDENTIAL_BLOCKED` like the other Feishu connectors, while the
authoritative R8 PostgreSQL/MySQL rows are `LIVE_VERIFIED` and retain their
`R8_FULL` browser evidence. The resulting row counts are 24 available/PASS
and 13 credential-blocked, matching the top-level matrix counts.

## R9 follow-up provider availability audit

The session-owned local targets currently available are the same targets
already represented in the matrix: MinIO for the S3 connector, Redpanda for
Kafka, and target-specific ClickHouse, Oracle, SQL Server, StarRocks, Doris,
and Hive services. No new target-specific Aliyun OSS, Snowflake, BigQuery, or
Feishu provider/Sandbox credentials are present in this session.

Therefore no credential classification is changed by this follow-up:

- Aliyun OSS remains `CREDENTIAL_BLOCKED`; MinIO/S3 evidence is not substituted.
- Snowflake remains `CREDENTIAL_BLOCKED` pending an account, warehouse,
  database/schema, read-only role, and server-side `secretRef`.
- BigQuery remains `CREDENTIAL_BLOCKED` pending a test project/service-account
  or workload-identity `secretRef`, dataset access, and read-session
  permissions.
- All ten Feishu connectors remain `CREDENTIAL_BLOCKED` pending a real tenant
  app credential, server-side `secretRef`, and connector-specific scopes.
