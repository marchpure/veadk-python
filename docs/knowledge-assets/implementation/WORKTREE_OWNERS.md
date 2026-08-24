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
