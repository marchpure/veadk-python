# Knowledge Workspace V1 — STEP 1 Acceptance Matrix

This is a handoff gate for STEP 2A (Studio/BFF), STEP 2B (Connection
Service), and STEP 2C (AutoSkill Adapter). It records what must be proven and
what evidence is insufficient. STEP 1 itself only proves the baseline and
contract artifacts.

| ID | Area | Requirement | Required evidence | STEP 1 |
| --- | --- | --- | --- | --- |
| B-01 | Baseline | Fetch remote and record exact `origin/main` SHA | fetch output, remote URL, timestamp, source status | PASS |
| B-02 | Baseline | New branch/worktree starts clean at B-01 SHA | `git rev-parse`, `git status --short --branch` | PASS |
| B-03 | Isolation | Legacy worktree is untouched and not a base | legacy status before/after; forbidden path in checkpoint | PASS |
| P-01 | Prototype | Read required metadata and key components | extracted package read log and package hash | PASS |
| P-02 | Prototype | Record all 22 `stateUrl`s | `captures.json` list in checkpoint | PASS |
| P-03 | Prototype | Record whitelist and mock prohibition | migration ledger | PASS |
| C-01 | Contract | Browser only calls `/api/knowledge/v1` | OpenAPI server + architecture boundary | PASS |
| C-02 | Contract | Connector definitions, connections, validate/discover | OpenAPI paths and schemas | PASS |
| C-03 | Contract | Uploads, drafts, generate/messages | OpenAPI paths and schemas | PASS |
| C-04 | Contract | Invocation events/cancel and SSE reconnect | OpenAPI `Last-Event-ID` and event schema | PASS |
| C-05 | Contract | Revisions/run/artifacts/publish/publication invoke | OpenAPI immutable resource paths | PASS |
| C-06 | Contract | Error envelope and required business errors | OpenAPI `ErrorEnvelope`/error enum | PASS |
| C-07 | Contract | Idempotency and ETag concurrency semantics | OpenAPI headers + architecture invariants | PASS |
| C-08 | Events | All ten normalized event types are schema-covered | `events.schema.json` oneOf + enums | PASS |
| K-01 | Connection | Credentials never reach browser or logs | service integration tests with redaction evidence | TODO 2B |
| K-02 | Connection | Lease is tenant-bound, short-lived, explicit, least privilege | lease claims, expiry/revocation tests | TODO 2B |
| K-03 | Connection | Real validate/discover status survives restart | job/audit integration evidence | TODO 2B |
| K-04 | Connection | Oracle, REST/OpenAPI, Web Discovery, self-MCP gaps are closed | real fixture/container evidence per adapter | TODO 2B |
| A-01 | AutoSkill | Real create → SSE → Skill ZIP → run → update → second ZIP | raw SSE, ZIP digests, service refs | TODO 2C |
| A-02 | AutoSkill | Reconnect/cancel does not duplicate invocation | `Last-Event-ID` and request audit | TODO 2C |
| A-03 | AutoSkill | Unknown/malformed upstream event fails closed and is archived | adapter contract tests | TODO 2C |
| R-01 | Revision | Revision is immutable and has validated ZIP digest/manifest | storage write-once and mutation rejection evidence | TODO 2A/2C |
| R-02 | Artifact | HTML artifact is real output with invocation/revision lineage and safe headers | artifact digest, scanner, CSP/sandbox evidence | TODO 2A/2C |
| R-03 | Publish | Publication points to fixed revision and runs all gates | publication DB/audit and negative tests | TODO 2A |
| UI-01 | UI | 22 capture states map to real BFF-backed state | route/state matrix, screenshot diff, interaction recording | TODO 2A |
| UI-02 | UI | No Prototype mocks/localStorage/timers in production bundle | CI forbidden-pattern scan and bundle audit | TODO 2A |
| E-01 | End-to-end | Three golden journeys are real and auditable | release SHA, service versions, raw logs, audits, digests | TODO integration |
| Q-01 | Quality | lint/type/unit/contract/integration/E2E/build/security gates | CI artifacts, not a static screenshot | TODO integration |

## Release blockers

The following are hard blockers for a claim of production readiness:

* any mock or pseudo-success path standing in for a real service;
* missing tenant/ACL boundary or secret/token in browser, event, ZIP, or HTML;
* HTTP 200/final answer/timer used as revision or run completion;
* an unverified Connector shown as verified;
* publication that mutates or aliases a prior `SkillRevision`;
* missing raw SSE, execution audit, ZIP SHA-256, Artifact SHA-256, and
  screenshot/recording evidence for a real golden journey.

