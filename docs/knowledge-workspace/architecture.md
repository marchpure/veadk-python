# Knowledge Asset Workspace V1 — STEP 1 Architecture Checkpoint

Status: frozen for parallel STEP 2 work  
Date: 2026-08-27  
Scope: baseline, boundaries, and cross-service contracts only

## Decision

The browser enters through AgentKit Studio and calls only the same-origin
`/api/knowledge/v1` BFF. The BFF owns workspace identity, draft orchestration,
immutable revisions, HTML artifacts, publication, and the mapping between
platform IDs and upstream IDs.

Connection Service is an independent control/runtime service. It owns provider
definitions, connections, credentials, validation/discovery jobs, leases, action
execution, and execution audit. OpenConnector is a reference kernel, not a
browser API and not a claim that every catalog provider is verified.

AutoSkill remains an existing service. The BFF's AutoSkill Adapter calls its
stateful HTTP/SSE API and owns timeout, cancellation, reconnect, event
normalization, ZIP validation, and ID mapping. AutoSkill source is not copied
into this repository.

The only publishable product asset is an immutable `SkillRevision`. A
`SkillDraft` is a mutable authoring aggregate. `Artifact` is an immutable,
lineage-bearing output of a revision run. Dashboard, Semantic, SOP, Knowledge,
Graph/Ontology, and Monitoring are presentation views of HTML artifacts, not
parallel domain assets or renderers.

```text
Browser / AgentKit Studio
        │ same-origin /api/knowledge/v1
        ▼
Knowledge BFF / Orchestrator
   ├── workspace ACL, drafts, revisions, publications, artifacts
   ├── Connection Service client ──► Connection control/runtime
   └── AutoSkill Adapter ──────────► existing AutoSkill HTTP/SSE
```

## Ownership and trust boundaries

| Boundary | Owns | Must not do |
| --- | --- | --- |
| Studio browser | transient form state, event presentation, artifact shell state | store secrets; call Connection Service/AutoSkill directly; infer success or permissions |
| Knowledge BFF | tenant/workspace principal, draft lifecycle, invocation lifecycle, revision/artifact/publication records, upstream ID mapping | implement an Agent loop; expose upstream URLs or credentials |
| Connection Service | definitions, credentials, connection ACL, validation/discovery, leases, actions, audit | know page state; decide Skill publication |
| AutoSkill Adapter | upstream HTTP/SSE protocol, reconnect, cancellation, raw-event archive, Skill ZIP download/validation | treat `final_answer` or HTTP 200 as publication success |
| AutoSkill | agent/session/request execution, memory, SkillHub, create/update/invoke | own Studio ACL, immutable revisions, publications, or long-lived Connection secrets |

Every resource is scoped by server-derived tenant and, where applicable,
workspace. The request body never supplies an authoritative owner, tenant, role,
or permission. Credentials and lease tokens stay server-side; only a safe
connection profile and opaque IDs may reach the browser.

## Domain invariants

* `SkillRevision` is immutable and is the only object accepted by publish.
* A publication points to exactly one revision and never mutates that revision.
* An HTML `Artifact` must point to an invocation and revision; no source-less
  HTML or mock result is valid.
* A run resolves `Publication → SkillRevision → ConnectionBinding` before a
  short-lived, explicit, non-empty lease is issued.
* A draft has at most one active generate/update invocation.
* An invocation reaches a terminal state only from a server-observed terminal
  event and completion of required persistence/validation.
* SSE disconnect changes subscription state only; it does not cancel an
  invocation. Reconnect uses `Last-Event-ID`.
* Side-effecting calls require `Idempotency-Key`; conflicting reuse returns
  `409 IDEMPOTENCY_CONFLICT`.
* Draft mutations use `ETag`/`If-Match`; stale writes return `412`.
* No empty `allowedConnections` is used for a product lease. Deny by default.

## Lifecycle

```text
Connection: draft → validating → ready | degraded | error → revoked
Draft:      editing → generating → generated → validating → ready_to_publish
                         ↘ failed / cancelled       ↘ published (via revision)
Invocation: queued → running → succeeded | failed | cancelled
```

Generation is not revision creation by itself. A revision requires successful
AutoSkill completion, a readable Skill, a safe validated ZIP with a SHA-256,
and a committed Studio record. A publish requires a fixed revision, recent
real run evidence, artifact/security checks, connection authorization, and
target-space ACL.

## Runtime adapter decisions

The AutoSkill source audit at `8dc9f14c1a0b0169ef865f3d87d4a6ea3e623533`
confirmed the stateful `/openapi/autoskill/v1` surface used by the contract:
`invoke`, `stream`, `stop`, `create_skill`, `update_skill`, Skill queries,
`upload`, and `download`. Its native events include planning/action/
observation, `final_answer`, `request_summary`, `error`, and `done`.
The BFF contract intentionally normalizes these to the event names in
`events.schema.json`; unknown upstream events are archived, not silently
interpreted as domain success.

The AutoSkill mapping is:

| Upstream | Studio |
| --- | --- |
| `agent_id` | private per-draft adapter mapping |
| `session_id` | private authoring-session mapping |
| `request_id` | invocation upstream ID, never a browser-owned resource ID |
| planning | `plan.updated` |
| action start/end and observation | `tool.started` / `tool.completed` |
| `final_answer` deltas | `assistant.delta` |
| validated output file | `artifact.created` |
| validated Skill ZIP | `revision.created` |
| `done` with all persistence gates complete | `run.completed` |
| upstream `error` or adapter protocol failure | `run.failed` |
| confirmed stop | `run.cancelled` |

## Connection Service decisions

The fetched OpenConnector reference is
`0fa2c728dfbf957735da2843ec2b8a4f3425b105`. Its source and documentation
show Provider/Action schemas, API key/OAuth2/custom/no-auth credentials,
credential encryption, action policies, runtime tokens, `allowedConnections`,
HTTP/OpenAPI runtime, MCP, SSRF controls, idempotency, and run logs.
It is licensed by `LICENSE.txt` and `NOTICE.md` under Apache-2.0 with
third-party attribution requirements.

Those capabilities are reusable through an independent service boundary.
They do not prove V1 readiness for Oracle Database, generic REST/OpenAPI
import, Web/API discovery, or arbitrary self-hosted MCP. Those are explicit
adapter gaps recorded in the migration ledger and acceptance matrix. The
catalog count is not a verification status.

## Explicit non-goals for STEP 1

No feature implementation, database schema, Connector fork, AutoSkill client,
mock endpoint, Prototype source copy, generated UI, BuildPlan,
ArtifactSpec, Golden Data pipeline, template patch, or six-way renderer is
introduced by this checkpoint.

