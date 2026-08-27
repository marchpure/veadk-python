# Knowledge Workspace V1 — Migration Ledger

This ledger is the gate for any later migration. STEP 1 records evidence and
boundaries; it does not copy Prototype or legacy implementation files.

## Source evidence

| Source | Exact reference | Read evidence | Decision |
| --- | --- | --- | --- |
| veadk-python baseline | `origin/main` at `bae782f87dd046d03a3daa0773c6cc611f981697` after `git fetch origin` | Remote is authoritative; local research checkout was dirty and 305 commits behind before fetch | New work starts only from this SHA |
| Prototype package | SHA-256 `dc8c74c1dff979c0da6e9b61fd0b85e66bf4134725581b8f945c76505d146f1d` | `prototype/readme.md`, `captures.json`, `codebase/dependencies.json`, route tree, App/layout/key views/components read from a system temp extraction | Visual and interaction evidence only; no source copied |
| Prototype captures | 22 `stateUrl` entries in `captures.json` | Welcome, draft success/failure/permission/connection/upgrade, modals, published states, two SOP drafts, and four skill-new states | Each later UI migration must map one source state to one tested BFF-backed state |
| Prototype route map | `prototype/codebase/prototype-route.json` and `prototype/codebase/src/prototype-route.json` | Query-state routes use `file`, `run_state`, `state`, and `modal` | Route semantics may be adapted to Studio routing; query state is not a server store |
| AutoSkill API | API doc plus read-only local source `8dc9f14c1a0b0169ef865f3d87d4a6ea3e623533` | Stateful `/openapi/autoskill/v1` uses `agent_id/session_id/request_id`, SSE, `/stream`, `/stop`, skill commands, upload/download | Integrate through BFF Adapter; no source copy; normalize events |
| OpenConnector | `origin/main` `0fa2c728dfbf957735da2843ec2b8a4f3425b105` | `LICENSE.txt`, `NOTICE.md`, README/runtime/credentials/config docs and source audit | Independent Connection Service kernel/reference; retain notices and audit dependencies |
| Legacy worktree | `/Users/bytedance/.codex/worktrees/knowledge-autoskill-mvp` | Read-only status showed dirty legacy backend/frontend and prior feature work | Never modify, clean, reset, delete, or use as baseline |

## Prototype migration whitelist

These are candidates, not approvals. Each row needs a destination file,
contract binding, and test evidence before migration.

| Candidate source area | May preserve | Required replacement |
| --- | --- | --- |
| `codebase/src/components/Layout/{WorkspaceLayout,TopNav,FileTreePane,MainAreaPane,RightPane}.tsx` | Shell geometry, pane collapse, responsive breakpoints, visual hierarchy | Studio routing, authenticated data queries, BFF DTOs, server-owned state |
| `codebase/src/components/MainArea/SkillNewView.tsx` | Three-part creation journey and connection multi-select shape | `/connections`, `/skills/drafts`, `/generate`; real validation and no scenario inference |
| `codebase/src/components/MainArea/ConnectionDetailView.tsx` | Credential form presentation, validation/discovery status presentation | Connection Service job state; secret-safe responses |
| `codebase/src/components/MainArea/SkillDraftWorkspace.tsx` | Draft/revision/run/publish visual grouping | Draft, invocation, revision, artifact, and publication APIs |
| `codebase/src/components/RightPane/ChatAssistant.tsx` | Timeline, delta rendering, tool cards, reconnect/cancel affordances | normalized SSE from `events.schema.json` |
| `codebase/src/components/Modals/{PublishModal,VersionHistoryModal,AgentResourceSelectorModal}.tsx` | Modal semantics and accessibility shape | immutable revision/publication and Agent grant APIs |
| Prototype token/icon/spacing styles | visual tokens and icon mapping | Studio theme and accessible controls |

## Explicitly forbidden migration

The following are not source material for production behavior:

* `codebase/src/data/mockData.ts`
* Prototype `localStorage` business state, `setTimeout` fake jobs, hardcoded
  Anta/Zhiji/Haidilao outcomes, browser scenario inference, and pseudo-success
* legacy BuildPlan, ArtifactSpec, Golden Data orchestration, template patches,
  six parallel renderers/runtimes, fake connector registry, or AutoSkill
  fallback
* any logic that treats HTTP 200, `final_answer`, or a client timer as domain
  success

## OpenConnector capability ledger

| Capability | Evidence at fetched ref | V1 disposition |
| --- | --- | --- |
| Provider/Action definitions and schemas | README, `src/core/provider-definition.ts`, provider tree | Reuse behind Connection Service; catalog status is not verification |
| API key, OAuth2, custom credential, no-auth | `docs/credentials.md` and provider auth metadata | Reuse with tenant/workspace vault boundary and secret redaction |
| Credential encryption and OAuth refresh | `docs/credentials.md`, runtime services | Retain; enterprise KMS/vault policy remains an integration gate |
| Runtime token and action policy | `docs/runtime-api.md`, config docs, runtime token code | Use short-lived platform lease; explicit non-empty connection/action grants |
| `allowedConnections` | `docs/runtime-api.md` | Map to lease claims; deny-by-default semantics are mandatory |
| HTTP/OpenAPI runtime | README and `docs/runtime-api.md` | Runtime surface is reusable; generic spec import is still a product adapter gap |
| MCP runtime | `src/mcp.ts`, `docs/runtime-api.md` | Reuse controlled runtime; arbitrary self-hosted MCP onboarding is a gap |
| SSRF guard, idempotency, run logs | config/runtime/credential docs | Retain and add tenant/workspace/audit constraints |
| Oracle Database | no verified Oracle DB adapter found in this audit | Gap; do not present `oracle_cloud` as Oracle Database |
| Generic REST/OpenAPI import | runtime exposes generated OpenAPI, but product import flow is absent | Gap; requires adapter and fixture tests |
| Web/API Discovery | no product discovery worker found in this audit | Gap; requires isolated browser worker and confirmation gate |
| Arbitrary self-built MCP | MCP runtime exists, product onboarding/runner contract is not proven | Gap; requires Streamable HTTP/SSE/stdio lifecycle tests |

## AutoSkill contract ledger

| Native surface/event | Required adapter handling |
| --- | --- |
| `POST /invoke`, `/create_skill`, `/update_skill` | Add private agent/session/request mapping; enforce one active draft invocation |
| `GET /stream` | Replay from `Last-Event-ID`; reconnect without a second invoke |
| `POST /stop` | Idempotent cancel; record local terminal state only after service confirmation |
| `/upload`, `/download` | Isolated inputs and Skill/output downloads; validate ZIP/path/size/digest |
| `planning`, `action`, `observation` | Normalize to `plan.updated`, `tool.started`, `tool.completed` |
| `final_answer`, `request_summary`, `error`, `done` | Never infer revision/publication from one event; completion requires persistence gates |
| Stateful `agent_id/session_id/request_id` | IDs stay server-side and are never editable browser resource IDs |

