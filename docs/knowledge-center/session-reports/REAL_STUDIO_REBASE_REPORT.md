# Real Studio Rebase Report

## Scope

- Branch: `integration/kc-veadk-real-studio`
- Push target: `marchpure/integration/kc-veadk-real-studio`
- VEADK base used: `volcengine/main@012f1cfc25090e0126c8402a5433ff2c2f4c966b`
- BYAAN source reference: `/Users/bytedance/worktrees/byaan-kc-veadk-knowledge-center@7a6cef9f0938bcdb2fe76b635311ca4eb25df0ca`
- Important note: fetched `marchpure/main` is `66df2b05f4ef67689b4835807b53fcb9e2357ff4`, which is not the current Studio history and is not an ancestor/equivalent of `volcengine/main@012f1cf`. To avoid repeating the earlier wrong-baseline issue, this integration branch is based on the real Studio baseline from `volcengine/main` and is pushed to the `marchpure` fork as an integration branch.

## What Changed

- Mounted a VEADK server-side Data Studio gateway under `/web/datastudio/*`.
- Added Knowledge Center navigation in Studio with a sandboxed iframe and `postMessage` origin filtering.
- Added Data Studio assets as a Skill picker source in custom agent creation.
- Added Data Studio selected-skill YAML round trip support.
- Added generated-agent Data Studio REST query tools.
- Hardened Data Studio `query_url` handling:
  - VEADK proxy accepts only same-origin absolute URLs from `DATASTUDIO_BASE_URL` or relative `/api/external/assets/...` URLs.
  - Generated runtime validates `DATASTUDIO_BASE_URL` and `query_url` origin/path before reading `BYAAN_MCP_API_KEY`.
  - API keys are never emitted in frontend YAML or `/web/datastudio/*` responses.
- Rebuilt `veadk/webui` from the final frontend sources.

## Validation

### Unit And Build

- `PYTHONPATH=. pytest tests/cli/test_datastudio_gateway.py tests/cli/test_generated_agent_datastudio_codegen.py tests/cli/test_generated_agent_backend_codegen.py tests/cli/test_generated_agent_backend_codegen_extended.py tests/cli/test_generated_agent_component_matrix.py -q`
  - Result: `157 passed, 7 warnings`
- `cd frontend && node --test tests/datastudio.test.mjs`
  - Result: `4 passed`
- `cd frontend && npm run build`
  - Result: passed. Vite reported existing large chunk / dynamic import warnings.
  - Final built assets include `index-DU_XzS9A.js`, `index-BskUIBYD.css`, and `MarkdownPromptEditor-DKdyGXl0.js`.
- `cd /Users/bytedance/worktrees/byaan-kc-veadk-knowledge-center/server && PYTHONPATH=..:tests ../.venv/bin/pytest tests/test_external_assets_api.py -q`
  - Result: `7 passed, 21 warnings`

### Live E2E

Temporary live services:

- BYAAN FastAPI:
  - `APP_MODE=community`
  - `DATABASE_URL=sqlite+aiosqlite:////tmp/byaan-veadk-live-e2e.db`
  - `http://127.0.0.1:17433`
- VEADK Studio:
  - `DATASTUDIO_BASE_URL=http://127.0.0.1:17433`
  - `DATASTUDIO_API_KEY=<live-e2e-api-key>`
  - `BYAAN_MCP_API_KEY=<live-e2e-api-key>`
  - `http://127.0.0.1:8765`

Seeded BYAAN assets:

- Dashboard: `dd7b6abe-a3a6-4a36-b11f-65504bc9b826`
- Semantic model: `f638cd2b-bad3-4cdf-b20b-56710387a633`

Live checks completed:

- BYAAN `/api/external/assets` without bearer returned 401.
- BYAAN `/api/external/assets?types=dashboard,semantic_model&limit=20` returned the seeded published assets with bearer auth.
- VEADK `/web/datastudio/config` returned configured payload with `origin=http://127.0.0.1:17433`.
- VEADK `/web/datastudio/assets?page_size=20` returned BYAAN assets through the proxy.
- VEADK `/web/datastudio/assets/dashboard/<id>` returned normalized asset detail.
- Checked `/web/datastudio/*` responses for the live E2E API key: no API key leakage found.
- Checked all returned asset `query_url` values: all were relative `/api/external/assets/...` paths.
- Browser E2E with Playwright:
  - local username login succeeded.
  - sidebar `知识资产` opened the Knowledge Center iframe with `src=http://127.0.0.1:17433/?embedded=veadk-studio`.
  - create flow `创建智能体 -> 从 0 快速创建 -> 添加 Skill -> 知识资产` loaded seeded Data Studio cards through `/web/datastudio/assets`.
  - selecting an asset kept it visible in the create UI.
  - screenshots: `/tmp/veadk-knowledge-center-live.png`, `/tmp/veadk-datastudio-picker-live.png`.
- Generated-runtime E2E:
  - Generated a Data Studio selected-skill project.
  - Executed generated `query_datastudio_semantic_sales` against live BYAAN `/api/external/assets/semantic_model/<id>/query`.
  - HTTP path succeeded and returned `policyDecision=allowed`.
  - Business query result status was `failed` because the seeded BYAAN SQLite datasource fixture uses a connection shape that trips BYAAN's current SQLite async connector parameters. This is a BYAAN fixture/data-source execution limitation, not a VEADK route/codegen/security failure.

## Known Limitations

- BYAAN API server root `/` returned 404 during iframe load. VEADK iframe integration, origin lock, and config are wired, but a complete embedded BYAAN UI requires `DATASTUDIO_EMBED_URL` to point at a served BYAAN frontend origin rather than the API-only FastAPI port.
- Playwright console included expected local-mode `401` from `/oauth2/userinfo`, because the Studio was running without SSO and then used local username login.
- Live semantic query reached the real BYAAN query endpoint, but the seeded SQLite datasource did not return successful metric rows due to BYAAN connector configuration for that fixture.

## Rollback

- Remove `mount_datastudio_routes(app)` from `veadk/cli/cli_frontend.py`.
- Remove the `frontend/server/datastudio` package.
- Remove `KnowledgeCenterView` wiring from `frontend/src/App.tsx` and `frontend/src/ui/Sidebar.tsx`.
- Remove Data Studio picker source wiring from `frontend/src/create/*`.
- Remove generated-agent Data Studio support from `veadk/cli/generated_agent_*`.
- Rebuild `frontend` to regenerate `veadk/webui`.
