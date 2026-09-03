# DO_NOT_INTEGRATE

This branch is frozen historical Data Workshop V2 evidence.

- Classification: `DO_NOT_INTEGRATE`
- Superseded by: `DWV1_I0_BASELINE_V3`
- Historical implementation tip:
  `40568577c91dbdab2b2440ed893444eaa1b6a8d3`
- Disposition: do not merge, rebase, cherry-pick wholesale, deploy, or use as a
  product baseline.

The branch implements the retired Publication and AgentKit gateway
architecture. Publication APIs, tables, UI, revisions, credential adapters,
toolsets, allowed-client logic, and token exchange are excluded from V3.

Only these generic patterns may be manually reimplemented after fresh review:

- secret redaction and no-plaintext-persistence checks;
- idempotency-key conflict handling;
- request-ID propagation and the standard error envelope;
- negative authorization and fail-closed tests;
- generic retryability classification.

No code is approved for automatic reuse. The V3 architecture and migration
rules live on
`marchpure/open-connector:docs/dwv1-i0-baseline-v3`.
