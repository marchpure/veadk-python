# STEP3B connector R9 status

Validation scope: `production-real-bff`

This checkpoint records evidence status, not a claim that all 37 connectors are usable.

## Authoritative counts

- `LIVE_VERIFIED`: 9
- `LOCAL_PROTOCOL_VERIFIED`: 14
- `CREDENTIAL_BLOCKED`: 14
- `UNSUPPORTED`: 0
- PASS total: 23/37
- `productionPass`: `false`
- `allConnectorsUsable`: `false`

The R8 PostgreSQL and MySQL live evidence remains authoritative and is retained in
the matrix. The later local-provider evidence adds S3/MinIO, Kafka/Redpanda,
ClickHouse, Oracle Free, SQL Server/Azure SQL Edge, target-specific StarRocks,
and target-specific Doris without downgrading the R8 database results.

## R9/R14 evidence

- Browser evidence: `.codex/coordination/knowledge-step3b-integration/CONNECTOR_BROWSER_EVIDENCE_20260827_R14_DORIS.json`
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

## Blocked policy

The 14 blocked entries are not displayed as available and are not counted as
usable. Their machine-readable required credentials, permissions, and unlock
steps are in `credentialBlockedDetails` in the matrix. No OAuth success,
fixed-success result, fixture, or compatible-engine substitution is used.

Hive remains blocked because no reliable session-owned provider/Sandbox was
available for a target-specific browser protocol test. MySQL is not used as
Doris/StarRocks evidence, and another SQL engine is not used as Hive evidence.

## Next local verification batch

Prioritize a real target-specific provider only when it can supply:

1. server-side `secretRef` resolution;
2. target-specific authenticate/authorize/discover/read/ingest;
3. SourceRevision and GoldenAssetRevision;
4. browser evidence including refresh/checkpoint and error paths.

Candidates remain Hive, OSS, Snowflake, BigQuery, and Feishu, in that order
only after a real local service or official Sandbox is available.
Until then they remain `CREDENTIAL_BLOCKED`.

## R9 provider probe

- Doris is `LIVE_VERIFIED`: the session-owned
  `apache/doris:all-in-one-4.1.3` arm64 target is healthy on FE/MySQL
  `127.0.0.1:26359`. The browser used the real
  `knowledge.step3b_doris_orders` table and read-only server secret. The seed
  step only performed a read-only existence check; it did not use the
  restricted browser credential for DDL or DML.
- Hive remains `CREDENTIAL_BLOCKED`: `apache/hive:3.1.3` could not finish its
  large image pull. A real `bde2020/hive:2.3.2` HiveServer2 target was pulled
  and started under amd64 emulation; its default HDFS dependency, a
  session-owned NameNode/DataNode retry, and a standalone local-filesystem
  retry all failed to produce a Thrift listener. A foreground launch timed out
  before listening. PyHive/Thrift was installed for a NONE-auth probe, but no
  authenticate or SQL handshake succeeded.

The machine-readable probe details, attempted targets, observed blocker, and
unlock steps are recorded in `targetProviderProbes` in the authoritative
matrix. No unstarted or substitute service is counted as a verification.

Focused provider tests: `.venv/bin/pytest`
(`test_step3b_provider_adapters.py`) — 48 passed. The complete prior
connector suite remains 109 passed at R13.
