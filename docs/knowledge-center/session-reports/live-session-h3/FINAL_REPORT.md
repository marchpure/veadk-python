# Knowledge Center Session H3 Native Wren/BYAAN Port Report

- Branch: `kc/session-h-semantic-askdashboard-agents`
- Preserved base commit: `bb7c451 close h2 native knowledge workbench migration`
- Live Studio URL used for smoke: `http://127.0.0.1:57595`
- Live asset DB: `/tmp/veadk-session-h2-native-ui.db`
- Seeded workspace reused from H2: `Session H2 Native Knowledge Workbench`
- Runtime surface: AgentKit Studio native React, `veadk/webui`, and `/api/knowledge-assets/*`
- Dependency boundary: no iframe, no Wren runtime, and no BYAAN runtime dependency

## Reference Files Read

- Wren Modeling: `wren-ui/src/pages/modeling.tsx`, `src/components/diagram/index.tsx`, `customNode/ModelNode.tsx`, `src/components/sidebar/Modeling.tsx`, `src/components/sidebar/modeling/*`, `src/utils/diagram/transformer.ts`
- BYAAN Notebook/Dashboard: `client/src/pages/NotebooksPage.tsx`, `NotebookQueryPanel.tsx`, `QueryEditor.tsx`, `QueryResults.tsx`, `QueryRunnerDocked.tsx`, `features/dashboard/pages/DashboardWorkspacePage.tsx`, `utils/dashboard*.ts`

## Native Port Delta

- Added Wren-style view-model adapters in `knowledgeWorkbenchUtils.ts`: `mdlToModelingViewModel`, grouped model/view/relationship/metric structures, and row metadata for fields, calculated fields, relation fields, and metrics.
- Reworked `SemanticModelingWorkbench.tsx` toward Wren Modeling page structure: grouped resource tree, React Flow canvas, model-node facts, relationship and field selection, metadata/MDL/eval inspector, and AgentKit build status strip.
- Added BYAAN-style notebook/dashboard adapters in `knowledgeWorkbenchUtils.ts`: `askDataToNotebookViewModel` and `dashboardSpecToByaanViewModel`.
- Reworked `AskDashboardWorkbench.tsx` toward BYAAN notebook/dashboard structure: dark query editor, run state, result tabs, query evidence pane, dashboard preview/code/queries tabs, split resize, and status strip from AgentKit build jobs.
- `KnowledgeCenter.tsx` passes `buildJobs` into AskTable/Dashboard so the H2/H3 agent status remains visible.
- CSS adds dense Wren-like tree styling, smaller semantic nodes, BYAAN-like editor styling, and desktop/mobile overflow constraints.

## Evidence

- `result.json`: 49 passing H3 Playwright checks for native Wren tree groups, React Flow nodes, AskTable query tabs, dashboard evidence, no iframe, no page errors, no unexpected HTTP errors, and desktop/mobile overflow. Focused frontend tests also render the no-model/not-configured AskTable path as an explicit blocked native notebook shell.
- `secret-scan-result.json`: scoped text scan passed; binary screenshots are inventoried separately.
- Screenshots:
  - `screenshots/desktop-1440-agentkit-semantic-h3.png`
  - `screenshots/desktop-1440-agentkit-askdashboard-h3.png`
  - `screenshots/desktop-1440-agentkit-askdashboard-query-tabs-h3.png`
  - `screenshots/mobile-390-agentkit-semantic-h3.png`
  - `screenshots/mobile-390-agentkit-askdashboard-h3.png`
  - `screenshots/mobile-390-agentkit-askdashboard-query-tabs-h3.png`
  - `screenshots/desktop-1440-reference-wren-modeling.png`
  - `screenshots/mobile-390-reference-wren-modeling.png`
  - `screenshots/desktop-1440-reference-byaan-notebook.png`
  - `screenshots/mobile-390-reference-byaan-notebook.png`

## Validation

- `cd frontend && node --test tests/knowledgeWorkbenchAgents.test.mjs tests/semanticBuildPanel.test.mjs`: 8 pass, including the no-model/not-configured blocked AskTable shell render.
- `cd frontend && npx tsc --noEmit`: passed.
- `cd frontend && npm test`: 677 pass.
- `python -m pytest tests/frontend/test_knowledge_asset_agents.py tests/frontend/test_semantic_builder.py tests/frontend/test_dashboard_askdata_routes.py tests/frontend/test_knowledge_asset_routes.py -q`: 31 passed, 4 warnings.
- `cd frontend && npm run build`: passed; regenerated `veadk/webui` assets (`index-B4mL8jkF.js`, `index-DPbHu-Bx.css`, `MarkdownPromptEditor-aSHfYck3.js`).
- Live Studio smoke: `VEADK_STUDIO_ASSET_DB=/tmp/veadk-session-h2-native-ui.db python -m veadk.cli.cli studio --host 127.0.0.1 --port 57595 --frontend-dir veadk/webui --no-open`, then Playwright at `1440x900` and `390x844`.

## Gaps Versus Source Products

- Wren: native port preserves the modeling layout concepts and graph/tree interaction, but not Wren deployment state management, server-side model editing mutations, or full Wren sidebar route depth.
- BYAAN: native port preserves notebook query editor, results/evidence tabs, and dashboard preview/code/query structure, but not BYAAN auth, notebook persistence, collaboration, schedules, export/share runtime, or full dashboard HTML generation.
- BYAAN reference screenshots reached the invitation-only auth gate in a fresh browser context; source-file inspection was the primary mapping evidence for notebook/dashboard structure.

## Result

H3 ports Wren Modeling and BYAAN Notebook/Dashboard page structures more directly into AgentKit native React while keeping AgentKit data ownership. The implementation still uses `/api/knowledge-assets/*`, `SemanticBuilderAgent`, and `AskTableDashboardAgent`; no iframe or Wren/BYAAN runtime dependency was introduced. No release blocker remains from H3 validation.
