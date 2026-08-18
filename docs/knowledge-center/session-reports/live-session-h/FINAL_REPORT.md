# Knowledge Center Session H Final Report

- Branch: `kc/session-h-semantic-askdashboard-agents`
- Remote start hash: `762751a41a759d35f3c91f394610cfb3dc6eb25e`
- Fresh live URL: `http://127.0.0.1:18347`
- Semantic Agent: `succeeded` via `veadk.Agent+Runner` / `doubao-seed-2-0-lite-260428` / `agent`
- AskTable Agent: `completed` via `veadk.Agent+Runner` / `doubao-seed-2-0-lite-260428` / `agent`
- Dashboard Skill: `ready` asset `oracle_sales_semantic-oracle-sales-dashboard-dashboard`

## Evidence

- `live-agent-run-result.json`: fresh server health, semantic build job, AskTable query, dashboard asset, and asset list from `18347`.
- `e2e-playwright-result.json`: 1440x900 and 390x844 checks for first-level tabs, semantic canvas, capability isolation, dashboard evidence, and overflow.
- `screenshots/`: semantic workbench, capability selector, and AskTable/Dashboard query evidence in both viewports.

## Validation

- `npm test` in `frontend`: 677 pass.
- `npm run build` in `frontend`: passed and regenerated `veadk/webui` assets.
- Focused backend pytest suite: 131 passed, 7 warnings.
- Live Playwright E2E on `http://127.0.0.1:18347`: passed at 1440x900 and 390x844.
- Secret scan: passed; PNG screenshots are inventoried as binary artifacts and text artifacts were scanned.

## Agent Statement

The fresh live run invoked both internal agents with `veadk.Agent+Runner` and model `doubao-seed-2-0-lite-260428`. Deterministic fallback and `not_configured` behavior are verified by backend tests and are not described as live model execution.
