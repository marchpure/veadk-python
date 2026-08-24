# Knowledge Asset Skill Factory Worktree Owners

| Lane | Owner | Worktree | Branch | Base commit | Allowed paths | Contract digest | Wave | Status |
|---|---|---|---|---|---|---|---|---|
| A | Files / Office context | `/Users/bytedance/.codex/worktrees/knowledge-step2-worker-files` | `knowledge-skill-factory-step-2-worker-files` | `88efe108` | proposal only: PDF/Office/Markdown/CSV/Excel/Lark | `worker-proposal.json` | STEP 2 | PROPOSAL_ONLY |
| B | Database / Oracle | `/Users/bytedance/.codex/worktrees/knowledge-step2-worker-database` | `knowledge-skill-factory-step-2-worker-database` | `88efe108` | proposal only: database typed config and read limits | `worker-proposal.json` | STEP 2 | PROPOSAL_ONLY |
| C | Web / API | `/Users/bytedance/.codex/worktrees/knowledge-step2-worker-web-api` | `knowledge-skill-factory-step-2-worker-web-api` | `88efe108` | proposal only: URL/REST/GraphQL/OpenAPI | `worker-proposal.json` | STEP 2 | PROPOSAL_ONLY |
| D | MCP / published Skill | `/Users/bytedance/.codex/worktrees/knowledge-step2-worker-mcp-skill` | `knowledge-skill-factory-step-2-worker-mcp-skill` | `88efe108` | proposal only: MCP/Skill registry and untrusted output | `worker-proposal.json` | STEP 2 | PROPOSAL_ONLY |
| I | Integration / Contracts | `/Users/bytedance/.codex/worktrees/knowledge-skill-factory-step-1-corrective-quality` | `knowledge-skill-factory-step-1-corrective-quality` | `88efe108` | canonical contracts, generated artifacts, BFF seam, local Golden Data | `CONTRACT_FREEZE.json` and `FRONTEND_SEAM_FREEZE.json` | STEP 2 | INTEGRATING |
| Q | Quality / Release | `/Users/bytedance/.codex/worktrees/knowledge-skill-factory-step-1-corrective-quality` | `knowledge-skill-factory-step-1-corrective-quality` | `88efe108` | static guard, migration, security tests, handoff | `STEP2_HANDOFF.md` | STEP 2 | INTEGRATING |

Worker proposal commits: A `9710d502`, B `3536975a`, C `cd35ff6f`,
D `e07cc1d5`. Worker branches remain proposal-only; shared contracts,
migrations, BFF/root routes, generated code, lockfiles, CI, and frozen UI are
owned by I/Q. The STEP 0 and original STEP 1 worktrees remain read-only at
their handoff commits. No existing semantic tag is moved.

## STEP 3 Main checkpoint

Checkpoint: `31a26a6f`
Tag: `knowledge-skill-factory-step-3-v2131-checkpoint-31a26a6f`
Migration head: `004_step3_shares`

| Lane | Owner | Worktree | Branch | Base commit | Allowed paths | Status |
|---|---|---|---|---|---|---|
| Main | Main Owner | `/Users/bytedance/.codex/worktrees/knowledge-skill-factory-step-1-corrective-quality` | `knowledge-skill-factory-step-1-corrective-quality` | `31a26a6f` | shared contracts/schema/OpenAPI/generated code, migrations, repository/application/BFF, WorkspaceHost/Shell, frozen UI, integration | INTEGRATING |
| W1 | Sources / Golden | `/Users/bytedance/.codex/worktrees/knowledge-step3-worker1-sources-golden` | `feat/knowledge-step3-worker1-sources-golden` | `31a26a6f` | source adapters, profiling/cleaning, Golden Asset proposals/tests | READY |
| W2 | Agent Authoring | `/Users/bytedance/.codex/worktrees/knowledge-step3-worker2-agent-authoring` | `feat/knowledge-step3-worker2-agent-authoring` | `31a26a6f` | authoring proposal/tests; existing uncommitted `skill_authoring` changes preserved | READY_DIRTY_REUSE |
| W3 | Kind Runtime | `/Users/bytedance/.codex/worktrees/knowledge-step3-worker3-kind-runtime` | `feat/knowledge-step3-worker3-kind-runtime` | `31a26a6f` | kind-specific runtime proposals/tests; existing uncommitted kind-runtime changes preserved | READY_DIRTY_REUSE |
| W4 | Evaluation / Quality | `/Users/bytedance/.codex/worktrees/knowledge-step3-worker4-evaluation-quality` | `feat/knowledge-step3-worker4-evaluation-quality` | `31a26a6f` | evaluation, policy, quality and evidence proposals/tests | READY |

Workers do not write shared contracts, migrations, generated artifacts,
root BFF routes, WorkspaceHost, frozen UI, lockfiles, CI, or final handoff.
Dirty W2/W3 changes predate this checkpoint and are preserved in place; they
must be reviewed for base/allowlist before any integration.
