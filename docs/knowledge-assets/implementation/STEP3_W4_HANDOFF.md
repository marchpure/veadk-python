# STEP3B W4 v2.15.2 UI Handoff

Status: `STEP3B_W4_UI_READY_FOR_INTEGRATION`

## Baseline

- Session: `01a038c9-c29d-7e73-93dc-9bb67813ded0`
- Branch: `feat/knowledge-step3b-v2152-workspace`
- Start HEAD: `6905f074e31a77686e69a0594b35f5ad22ce2ff1`
- Prototype export SHA-256: `0a672e34dd8f5cf416a73334b519679ee756f2c50ea8710166dae4b6b6c41b15`
- Prototype unpacked at: `/tmp/knowledge-v2152-rerun3.enFUPp`

## Delivered

- Restored the v2.15.2 Workspace home journey without production mock state:
  - business-problem composer;
  - upload and drag/drop entries;
  - bootstrap/read-model powered `@` resource search;
  - context chips with source and revision;
  - template library for Dashboard, Semantic, SOP, Knowledge, Graph/Ontology, Monitoring, and generic HTML Skill;
  - custom `spec.md` preview/reuse/save gates;
  - Agent recommendation, clarification, retry, cancel, waiting, failure, and completion UI states.
- Reworked Skill Builder from the six-step legacy wizard into the intended Skill authoring journey:
  - business materials and template selection;
  - typed Agent authoring command;
  - clarification and execution status;
  - trusted HTML Skill main view;
  - advanced/audit drawer for Manifest, BuildPlan, trace, draft, and revision details.
- Fixed Home → Builder input loss:
  - prompt, context refs, selected template, workspace scope, operation id, and draft id are passed through the route;
  - Builder can also restore from server bootstrap authoring-session fields;
  - no localStorage is used for production business state.
- Added a unified trusted HTML Skill revision view for generated Skill visual forms:
  - Dashboard;
  - Semantic;
  - SOP;
  - Knowledge;
  - Graph/Ontology;
  - Monitoring;
  - generic HTML Skill.
- Reworked the right Agent panel to consume the W2 typed stream/timeline seam:
  - assistant Markdown delta;
  - tool-call cards;
  - context/revision messages;
  - clarification;
  - warning/error;
  - stop/retry/resume;
  - refresh/interruption recovery display;
  - non-forcing auto-scroll when the user scrolls away.
- Connected visible operations to typed command/read-model seams or disabled/gated them with explicit reasons:
  - `skill-authoring.start`
  - `skill-authoring.answer`
  - `skill-authoring.patch`
  - `skill-authoring.execute`
  - `refresh.run`
  - `artifact.export`
  - `evaluation.run`
  - `publication.publish`
  - `invocation.start`
- Fixed right-pane deep-link behavior so explicit `pane=closed` is preserved and the main area resizes correctly when the Agent pane opens.

## Removed fake data and fake-success paths

- Removed production hardcoded SOP facts/results:
  - Bluetooth diagnostic/manual/SOP facts;
  - Haidilao inspection SOP facts;
  - LS model, OS/firmware, dBm, historical ticket, fixed diagnosis, and fixed remediation values.
- Removed production hardcoded Monitoring facts/results:
  - fixed invocation count;
  - fixed success rate;
  - fixed latency;
  - fixed trace/call/alarm records;
  - fixed Skill names.
- Removed production demo-success paths:
  - sample data added state;
  - mock dataset upload success;
  - route-driven publication success;
  - localStorage demo business state;
  - request-complete-to-success-page jumps;
  - timer-simulated Agent thinking/tool/progress/success.
- Preserved deterministic fixtures only under test/evidence code.

## Browser evidence

- Evidence root: `/Users/bytedance/.codex/runtime/knowledge-step3b-w4-v2152/visual-evidence-final2-20260826010602`
- Report SHA-256: `f89b7f2e7e34a35bf1815c388bde2df354e4575c587c7fa9e9fb9d2d8abcce5e`
- Status: `pass`
- Screenshots:
  - `45` W4 actual screenshots;
  - `45` prototype reference screenshots;
  - `45` overlay/diff screenshots.
- Viewports:
  - `desktop-1920` (`1920×1080`)
  - `studio-1440` (`1440×900`)
  - `mobile-390` (`390×844`)
- Checks:
  - console error: pass;
  - failed request: pass;
  - horizontal overflow: pass;
  - keyboard navigation: pass;
  - modal/drawer obstruction: pass;
  - Agent pane collapsed/open width: pass;
  - Home → Builder prompt/context/template/workspace handoff: pass.
- Reference source: `captures.json` TOS PNG fallback because the online prototype URL returned 404 during capture.

## 15-state acceptance

All states from `tests/fixtures/knowledge_step3b_w4_v2152/captures.json` were captured in all three viewports:

1. `home`
2. `agent-clarify`
3. `bluetooth-sop-draft`
4. `edit-sop-step`
5. `bluetooth-sop-input`
6. `bluetooth-sop-result`
7. `publish-to-agent`
8. `anta-dashboard-draft`
9. `anta-dashboard-result`
10. `publish-team`
11. `haidilao-sop-draft`
12. `haidilao-sop-input`
13. `haidilao-sop-result`
14. `published-sop-monitoring`
15. `optimization-draft`

The names above are fixture/evidence identifiers. Production code does not infer business content from route ids, skill ids, template names, or keywords.

## Verification

- Focused Node gate:
  - `node --test frontend/tests/knowledgeWorkspaceV2152Shell.test.mjs frontend/tests/knowledgeShellState.test.mjs frontend/tests/knowledgeWorkspaceV21141Contracts.test.mjs frontend/tests/knowledge-workspace-v21141/contracts.test.mjs frontend/tests/knowledge-workspace-v21141/trustedHtmlArtifactRenderer.test.mjs frontend/tests/knowledge-workspace-v21141/productionBoundary.test.mjs`
  - Result: `124 passed`.
- Frontend full test:
  - `cd frontend && npm test`
  - Result: `873 passed`.
- TypeScript:
  - `cd frontend && npx tsc --noEmit --noUnusedLocals false --noUnusedParameters false --pretty false`
  - Result: passed.
- Production build:
  - `cd frontend && npm run build`
  - Result: passed.
  - Remaining warnings are existing Vite dynamic-import/chunk-size warnings; the W4-added Tailwind selector syntax warning was removed.
- Python knowledge-assets tests:
  - `pytest -q tests/frontend/knowledge_workspace_v21141 tests/frontend/test_knowledge_asset_bff.py tests/frontend/test_knowledge_web_import.py tests/frontend/test_knowledge_uploads.py`
  - Result: `290 passed, 13 skipped`.
- Static scans:
  - production fixed business facts and fake success paths: no matches;
  - broad business-fact scan: no matches;
  - localStorage/timer scan reviewed; remaining hits are UI mechanics or HTTP timeout/retry, not fake streaming or fake success.

## MAIN typed seams required

- Bootstrap/read model should return typed workspace catalog resources:
  - resource id;
  - resource kind/subtype;
  - scope;
  - revision;
  - display name;
  - server context ref.
- Authoring session bootstrap should return:
  - prompt;
  - selected template/requested kind;
  - context refs;
  - `draftId`;
  - `operationId`;
  - latest immutable `SkillViewRevision`.
- Command results should consistently return accepted state, operation id, draft id/revision id where applicable, and terminal error details.
- Read-model refresh after command completion should return the new immutable `SkillViewRevision` or a clear gated/error state.

## W2 dependency proposal

W2 should supply the authoritative authoring/runtime stream for:

- assistant delta;
- tool call;
- plan summary;
- context/revision;
- clarification;
- warning/error;
- stop/retry/resume;
- durable operation recovery after refresh.

W4 consumes these as typed events and does not display chain-of-thought, system prompts, credentials, or raw sensitive tool output.

## W3 dependency proposal

W3 should integrate the canonical template/runtime contracts for:

- trusted HTML renderer registration;
- `SkillViewRevision` artifact metadata and digest;
- `DashboardViewModel`;
- `SemanticViewModel`;
- `SopViewModel`;
- `GraphViewModel`;
- `MonitoringViewModel`;
- template/kind mapping for Dashboard, Semantic, SOP, Knowledge, Graph/Ontology, Monitoring, and generic HTML Skill.

W4 did not copy W3 compiler/runtime implementation and did not cherry-pick W3 commits.

## Evidence files

- `tests/fixtures/knowledge_step3b_w4_v2152/evidence.md`
- `tests/fixtures/knowledge_step3b_w4_v2152/browser-evidence-index.json`
- Runtime artifacts: `/Users/bytedance/.codex/runtime/knowledge-step3b-w4-v2152/visual-evidence-final2-20260826010602`

## Integration note

This is W4 UI readiness only. It does not claim `STEP3B_COMPLETE`; final completion remains with Integration MAIN after W1/W2/W3/W4 are merged and vertically verified.
