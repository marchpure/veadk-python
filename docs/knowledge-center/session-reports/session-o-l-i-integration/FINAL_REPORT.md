# Session O L+I Integration

Session O merged Session L unified knowledge assets with Session I connector foundation on `kc/session-o-l-i-integration`.

Status: passed. This report only covers L+I integration and does not claim Session M/N/K productization goals are complete.

## Inputs

- Session L baseline: `kc/session-l-unified-knowledge-assets` `7878adfa08a73f9214e5415b2f16114ddc5b5df6`.
- Session I connector foundation: `kc/session-i-connectors-foundation` `2cfcc37b53380c9e96cfe33445140286eb9b789d`.
- Output branch: `kc/session-o-l-i-integration`.

## Preserved And Integrated Surfaces

- First-level tabs verified: `概览`, `数据源`, `语义构建`, `AskTable / Dashboard`, `测评`, `能力`, `构建任务`, `设置`.
- Connector registry and source resources are live: `/api/knowledge-assets/connectors`, `/api/knowledge-assets/source-resources`.
- Required connector IDs present: `oracle`, `feishu_doc`, `web`, `file`, `text`, `pdf`, `image`.
- Semantic Builder agent-native routes remain present: stream, events, conversations, revisions, draft views, and publish.
- AskTable governed query returned `VNPTTE`, `ticket_count`, SQL, policy, freshness, and lineage/evidence without raw SQL fallback.
- Dashboard preview/query/share/export controls remain in the native workbench path.
- Evaluation suite/case/run/optimization APIs remain present and live smoke runs succeeded for Semantic Skill, AskTable Query, and Dashboard Skill.
- Live UI rendered no forbidden iframe shell, no 404/failed requests, no console errors, and no horizontal overflow in 1440x900 or 390x844.

## Live Smoke

- URL: `http://127.0.0.1:18222`.
- Health: `mock=false`, store `sqlite`.
- `semantic_builder`: `available`, backend `veadk.Agent+Runner`, model `doubao-seed-2-0-lite-260428`.
- `asktable_dashboard`: `available`, backend `veadk.Agent+Runner`, model `doubao-seed-2-0-lite-260428`.
- `asktable_streaming`: `available`, backend `veadk.Agent+Runner`, model `doubao-seed-2-0-lite-260428`.
- Connector registry total: `15`.
- AskTable rows: `2`, status `completed`, policy `allow`.

## Validation

- `git diff --check`: passed (No whitespace errors.)
- `uvx ruff check frontend/server/knowledge_assets tests/frontend`: passed (All checks passed.)
- `python -m pytest tests/frontend/test_knowledge_asset_routes.py tests/frontend/test_knowledge_asset_store.py tests/frontend/test_dashboard_askdata_routes.py tests/frontend/test_knowledge_asset_agents.py tests/frontend/test_knowledge_asset_semantic_builder.py tests/frontend/test_knowledge_asset_evaluation.py -q`: passed (78 passed, 7 warnings.)
- `cd frontend && npm test -- knowledgeAssetWorkbench.test.mjs semanticBuildPanel.test.mjs`: passed (682 passed, 0 failed after npm ci.)
- `cd frontend && npm run build`: passed (Vite production build completed; only existing chunk-size/static-dynamic import warnings.)
- `VEADK_STUDIO_URL=http://127.0.0.1:18222 node docs/knowledge-center/session-reports/session-o-l-i-integration/run-live-smoke.mjs`: passed (Fresh Studio on sqlite store, desktop/mobile UI smoke, connector controls, AskData, Dashboard preview, Evaluation import/run, no forbidden external sidecar iframe/no 404/no console errors/no horizontal overflow.)

## Artifacts

- `result.json`
- `secret-scan-result.json`
- `run-live-smoke.mjs`
- `screenshots/desktop-1440-connected-content.png`
- `screenshots/desktop-1440-content-drawer.png`
- `screenshots/desktop-1440-connector-gallery.png`
- `screenshots/desktop-1440-wizard-footer.png`
- `screenshots/desktop-1440-semantic.png`
- `screenshots/desktop-1440-asktable-portal.png`
- `screenshots/desktop-1440-asktable-result.png`
- `screenshots/desktop-1440-evaluation.png`
- `screenshots/mobile-390-connected-content.png`
- `screenshots/mobile-390-content-drawer.png`
- `screenshots/mobile-390-connector-gallery.png`
- `screenshots/mobile-390-wizard-footer.png`
- `screenshots/mobile-390-semantic.png`
- `screenshots/mobile-390-asktable.png`
- `screenshots/mobile-390-evaluation.png`

## Notes

- The live smoke used a fresh Studio process from this clean checkout with `VEADK_STUDIO_ASSET_DB=/tmp/session-o-l-i-integration/knowledge-assets.db`.
- `npm ci` was required in the fresh clone before frontend tests/build because `node_modules` was absent.
- Vite build passed with existing chunk-size and static/dynamic import warnings only.
