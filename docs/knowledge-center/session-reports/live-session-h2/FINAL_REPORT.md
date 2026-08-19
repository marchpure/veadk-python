# Knowledge Center Session H2 Native UI Report

- Branch: `kc/session-h-semantic-askdashboard-agents`
- Live Studio URL: `http://127.0.0.1:57595`
- Live asset DB: `/tmp/veadk-session-h2-native-ui.db`
- Seeded workspace: `Session H2 Native Knowledge Workbench`
- Seeded assets: `h2_sales_semantic` and `h2_sales_dashboard`
- Runtime surface: AgentKit Studio native React routes, `veadk/webui`, and `/api/knowledge-assets/*`
- Dependency boundary: no iframe, no Wren/BYAAN runtime or service dependency

## Evidence

- `seed-result.json`: fresh `KnowledgeAssetStore` seed with one schema source, one snapshot, one published Semantic Skill, one published Dashboard Skill, and succeeded build jobs.
- `e2e-h2-native-ui-result.json`: 20 passing desktop/mobile Playwright checks for native semantic canvas, model tree content, AskTable/Dashboard preview, query notebook tabs, iframe absence, and horizontal overflow.
- `screenshots/desktop-1440-semantic-h2.png`
- `screenshots/desktop-1440-askdashboard-h2.png`
- `screenshots/desktop-1440-askdashboard-query-tabs-h2.png`
- `screenshots/mobile-390-semantic-h2.png`
- `screenshots/mobile-390-askdashboard-h2.png`
- `screenshots/mobile-390-askdashboard-query-tabs-h2.png`

## Validation

- `cd frontend && npm test`: 677 pass.
- `cd frontend && npm run build`: passed and regenerated `veadk/webui` assets.
- `python -m pytest tests/frontend/test_knowledge_asset_agents.py tests/frontend/test_semantic_builder.py tests/frontend/test_dashboard_askdata_routes.py tests/frontend/test_knowledge_asset_routes.py -q`: 31 passed, 4 warnings.
- Live Studio smoke: `VEADK_STUDIO_ASSET_DB=/tmp/veadk-session-h2-native-ui.db python -m veadk.cli.cli studio --host 127.0.0.1 --port 57595 --frontend-dir veadk/webui --no-open`, then Playwright at `1440x900` and `390x844`.
- Expected bootstrap note: local username mode probes `/oauth2/userinfo` and receives 404 before using local identity; H2 checks had no unexpected 404/500 and no page errors.

## Result

Semantic now presents a native Wren-style workbench with source/snapshot/skill selectors, model tree groups, React Flow canvas, node facts, empty states, and metadata/MDL/eval inspector. AskTable/Dashboard now presents a native BYAAN-style split workspace with governed query controls, notebook result tabs, dashboard preview/code/query evidence, tile visuals, data views, and mobile overflow checks.
