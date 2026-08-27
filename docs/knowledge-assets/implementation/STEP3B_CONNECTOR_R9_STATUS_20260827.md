# STEP3B connector R9 status

Validation scope: `production-real-bff`

This checkpoint records evidence status, not a claim that all 37 connectors are usable.

## Authoritative counts

- `LIVE_VERIFIED`: 7
- `LOCAL_PROTOCOL_VERIFIED`: 14
- `CREDENTIAL_BLOCKED`: 16
- `UNSUPPORTED`: 0
- PASS total: 21/37
- `productionPass`: `false`
- `allConnectorsUsable`: `false`

The R8 PostgreSQL and MySQL live evidence remains authoritative and is retained in
the matrix. The later local-provider evidence adds S3/MinIO, Kafka/Redpanda,
ClickHouse, Oracle Free, and SQL Server/Azure SQL Edge without downgrading the
R8 database results.

## R9/R12 evidence

- Browser evidence: `.codex/coordination/knowledge-step3b-integration/CONNECTOR_BROWSER_EVIDENCE_20260827_R12_SQLSERVER.json`
- Matrix: `STEP3B_CONNECTOR_BROWSER_CAPABILITY_MATRIX_20260827.json`
- Real BFF/WebUI flow: catalog → bootstrap projection → create → authenticate →
  authorize → discover → sample/read → ingest → SourceRevision →
  GoldenAssetRevision → checkpoint → refresh/recovery.
- Catalog: 37/37 connectors.
- Bootstrap projection: verified providers available; credential-dependent
  providers remain blocked.
- Console/page errors: 0.
- HAR consistency: pass.
- Browser refresh and BFF restart recovery: pass.

## Blocked policy

The 16 blocked entries are not displayed as available and are not counted as
usable. Their machine-readable required credentials, permissions, and unlock
steps are in `credentialBlockedDetails` in the matrix. No OAuth success,
fixed-success result, fixture, or compatible-engine substitution is used.

Doris, StarRocks, and Hive remain blocked because no reliable session-owned
provider/Sandbox was available for a target-specific browser protocol test.
MySQL is not used as Doris/StarRocks evidence, and another SQL engine is not
used as Hive evidence.

## Next local verification batch

Prioritize a real target-specific provider only when it can supply:

1. server-side `secretRef` resolution;
2. target-specific authenticate/authorize/discover/read/ingest;
3. SourceRevision and GoldenAssetRevision;
4. browser evidence including refresh/checkpoint and error paths.

Candidates remain Doris, StarRocks, Hive, OSS, Snowflake, BigQuery, and Feishu,
in that order only after a real local service or official Sandbox is available.
Until then they remain `CREDENTIAL_BLOCKED`.
