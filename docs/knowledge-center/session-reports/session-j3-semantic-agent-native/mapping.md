# Session J3 Semantic Builder Agent-Native Closure — Implementation Mapping

## Baseline and worktree

- Repository: `marchpure/veadk-python`
- J2 baseline: `origin/kc/session-j2-semantic-builder-ux-closure`, commit `8387adc`
- J3 working base: `1ee032470bcf1cf43c67e5c115e44a361d2c56ac`
- Working directory used: `/Users/bytedance/worktrees/veadk-python-session-j3-semantic-agent-native-clean`
- Original WIP was not reset or overwritten; J3 work was done in the clean worktree.

## Backend mapping

### Agent start

Implemented in:

- `frontend/server/knowledge_assets/agents/semantic_builder.py`
- `frontend/server/knowledge_assets/agents/runner.py`
- `frontend/server/knowledge_assets/builders/semantic/service.py`

Behavior:

- Start accepts separated `source_ids`, `document_source_ids`, and `snapshot_ids`.
- Deterministic preprocessing creates schema graph, candidate MDL, document graph, few-shot, instructions, evidence, alignments, and provenance seed.
- Start then calls `InternalAgentRunner.run` with `agent_name=studio_semantic_builder_agent` and `operation=start`.
- Runner payload includes schema/profile/snapshots, document contexts, current MDL, current revision seed, few-shot, instructions, domain, intent, policy constraints, and deterministic seed.
- Start always writes `publish_state=draft`, even when the request contains `publish=true`.
- Agent run metadata is persisted with runner backend, model name, generation mode, agent status, tool summaries, validation result, and invocation ID.

### Agent refine

Implemented in:

- `frontend/server/knowledge_assets/agents/semantic_builder.py`
- `frontend/server/knowledge_assets/service.py`
- `frontend/server/knowledge_assets/routes.py`

Behavior:

- Refine endpoint:
  - `POST /api/knowledge-assets/semantic-builder/conversations/{conversation_id}/messages`
- Refine calls `InternalAgentRunner.run` with `operation=refine`.
- Payload includes current draft MDL, current/base revision, message, few-shot, instructions, evidence/doc graph, alignments, and provenance.
- Runner output must contain structured patch/diff or it fails schema validation; deterministic helper is only a last local merge helper and is not treated as Agent success.
- Refine creates an immutable draft revision and updates the draft package while preserving evidence, doc graph, alignments, few-shot, instructions, and provenance.

### Revision actions

Implemented endpoints:

- `POST /api/knowledge-assets/semantic-builder/conversations/{conversation_id}/revisions/{revision_id}/accept`
- `POST /api/knowledge-assets/semantic-builder/conversations/{conversation_id}/revisions/{revision_id}/reject`
- `POST /api/knowledge-assets/semantic-builder/conversations/{conversation_id}/revisions/{revision_id}/revert`

Behavior:

- Each action appends revision history.
- Accept/reject/revert are represented as user-visible revision states.
- Revert creates a new draft revision instead of destructively mutating historical revisions.

### View draft

Implemented endpoint:

- `POST /api/knowledge-assets/semantic-builder/drafts/{draft_id}/views`

Behavior:

- Saves a draft View with id/name/description/base metric/dimensions/time grain/query spec/generated SQL/status/evidence.
- Writes both `capability_package.views` and `mdl.views`.
- Adds conversation revision and package revision history entry.

### Publish

Implemented endpoint:

- `POST /api/knowledge-assets/semantic-builder/drafts/{draft_id}/publish`

Behavior:

- Runs publish gate.
- Refuses publish when blockers exist.
- On success, appends publish revision and updates `publish_state=published`.
- Publish is independent from start and never occurs inside the start stream.

### Storage and contract

Implemented in:

- `frontend/server/knowledge_assets/models.py`
- `frontend/server/knowledge_assets/repository.py`
- `frontend/server/knowledge_assets/contract.py`
- `frontend/server/knowledge_assets/service.py`

Changes:

- Repository schema version bumped to `5`.
- `document_source_ids_json` column added for semantic builder conversations.
- Semantic package envelope includes optional `package_id` and `space_id`.
- Capability package now carries MDL, top-level models/relationships/metrics/dimensions/views, policies, evidence, doc graph, alignments, few-shot, instructions, agent run, draft revision history, and publish gate.

## Frontend mapping

Implemented in:

- `frontend/src/knowledge-center/SemanticBuildPanel.tsx`
- `frontend/src/features/knowledge-assets/source-ports/wren/WrenModelingSourcePort.tsx`
- `frontend/src/adk/knowledgeAssets.ts`
- `frontend/tests/semanticBuildPanel.test.mjs`

Behavior:

- Start CTA uses `让 Agent 分析数据并生成语义草案`.
- Start sends structured data sources in `source_ids` and business documents in `document_source_ids`.
- Start sends `publish:false`; Publish remains explicit.
- Default Review no longer exposes runner mode/internal status as primary user copy.
- Advanced contains domain/intent/publish policy and raw technical detail.
- The panel reuses the backend-created `conversation_id` instead of creating duplicate conversations.
- Feedback input is exposed through `data-testid=semantic-feedback-input`.
- Stage timeline uses human-readable Chinese stage labels.
- Project de-duplication includes space, normalized name, version, and sorted provenance source IDs.

## Runner JSON handling

Implemented in:

- `frontend/server/knowledge_assets/agents/runner.py`
- `tests/frontend/test_knowledge_asset_agents.py`

Behavior:

- Strict JSON parse is attempted first.
- Conservative envelope repair handles markdown fences, surrounding text, and a stray quote after array/object values before delimiters.
- Repair is recorded in `validation_result.output_repair`.
- Output still must pass the requested Pydantic schema; otherwise the run fails closed with `AgentValidationError`.
- This does not enable deterministic fallback or fake Agent success.

## Tests added or extended

Backend tests cover:

- Start runner invocation with fake runner request payload assertions.
- Refine runner invocation with current MDL/current revision/few-shot/instructions.
- Start remains draft even when `publish=true`.
- No model / deterministic fallback fails closed with stable `AGENT_NOT_CONFIGURED`.
- Document-only start remains draft and does not fabricate SQL metrics.
- Structured runner patch operations update MDL and create views.
- Accept/reject/revert revision actions.
- View draft writes MDL and package.
- Explicit publish endpoint and publish gate.
- Repository migration schema version `5`.
- Secret redaction.
- Common model JSON envelope repair.

Frontend tests cover:

- `document_source_ids` payload split.
- `publish:false` on start.
- Conversation reuse via `getSemanticBuilderConversation`.
- Feedback input test id.
- Advanced publish policy placement.
- Default UI excludes internal strings such as `Runner pending`, `agent_tool_stream`, and `Build succeeded`.

## Live E2E evidence

Script:

- `docs/knowledge-center/session-reports/session-j3-semantic-agent-native/run-live-e2e.py`

Result:

- `docs/knowledge-center/session-reports/session-j3-semantic-agent-native/live-e2e-result.json`

Screenshots:

- `screenshots/desktop-semantic-builder.png`
- `screenshots/mobile-semantic-builder.png`
- `screenshots/desktop-agent-run.png`
- `screenshots/desktop-patch-diff.png`

Observed live evidence:

- Runner configured: `true`
- Runner backend: `veadk.Agent+Runner`
- Model: `doubao-seed-2-0-lite-260428`
- Fallback used: `false`
- API flow: start succeeded as Draft; refine created draft revision; accept succeeded; View count >= 1; explicit publish succeeded; final publish state `published`.
- Mobile overflow: `0px`.

