# Session B VEADK Studio Runtime Report

## Commits

- `defdffcb30ad5b0b473a19b3a83c1791ffd0e034` - `feat(studio): integrate datastudio knowledge assets`
- `a6a93f6a671c66868183fd36e0638b49eb6e7a44` - `refactor(studio): align datastudio gateway module layout`
- `acc04c5274356164728a3911306250414c3071ea` - `fix(runtime): derive datastudio mcp tools server-side`
- Branch: `parallel/kc-veadk-studio`.
- Push target: `marchpure/parallel/kc-veadk-studio`.
- Base: `66df2b0` (`marchpure/main`), avoiding `.github/workflows` changes because the available GitHub token cannot update workflow files.

## Scope

Implemented the VEADK side of the Knowledge Center/Data Studio integration. BYAAN repo was not modified.

Key files:

- `frontend/server/datastudio/models.py`
- `frontend/server/datastudio/gateways.py`
- `frontend/server/datastudio/service.py`
- `frontend/server/datastudio/routes.py`
- `frontend/server/datastudio/__init__.py`
- `veadk/cli/datastudio_gateway.py` (compatibility exports)
- `veadk/cli/cli_frontend.py`
- `frontend/src/knowledge-center/KnowledgeCenter.tsx`
- `frontend/src/knowledge-center/KnowledgeCenter.css`
- `frontend/src/ui/Sidebar.tsx`
- `frontend/src/App.tsx`
- `frontend/src/create/DataStudioAssetPicker.tsx`
- `frontend/src/create/skills/datastudio.ts`
- `frontend/src/create/skills/types.ts`
- `frontend/src/create/types.ts`
- `frontend/src/create/configYaml.ts`
- `frontend/src/create/normalizeDraft.ts`
- `frontend/src/create/codegenDraft.ts`
- `frontend/src/create/CustomCreate.tsx`
- `frontend/src/create/CustomCreate.css`
- `veadk/cli/generated_agent_codegen.py`
- `veadk/cli/generated_agent_mcp.py`
- `veadk/cli/generated_agent_skills.py`
- `veadk/cli/generated_agent_security.py`
- `frontend/tests/knowledgeCenter.test.mjs`
- `frontend/tests/configYaml.test.mjs`
- `frontend/tests/markdownPromptEditor.test.mjs`
- `tests/cli/test_datastudio_gateway.py`
- `tests/cli/test_generated_agent_backend_codegen.py`
- `tests/cli/test_generated_agent_backend_codegen_extended.py`
- `docs/knowledge-center/session-reports/browser-smoke/verify-kc-smoke.mjs`
- `docs/knowledge-center/session-reports/browser-smoke/kc-smoke-result.json`
- `docs/knowledge-center/session-reports/browser-smoke/kc-smoke-desktop.png`
- `docs/knowledge-center/session-reports/browser-smoke/kc-smoke-mobile.png`

## Data Studio Gateway

The VEADK server exposes:

- `GET /web/datastudio/config`
- `GET /web/datastudio/assets`
- `GET /web/datastudio/assets/{asset_type}/{asset_id}`

Gateway implementation is split under `frontend/server/datastudio/` following the existing Studio backend module layout:

- `models.py`: Data Studio contract models.
- `gateways.py`: Byaan `/api/external/*` proxy, server-side credential handling, and mock assets.
- `service.py`: config payloads, origin derivation, mock paging/search, and response normalization.
- `routes.py`: `/web/datastudio/*` FastAPI route mounting.

`veadk/cli/datastudio_gateway.py` remains a compatibility shim that re-exports the package API for older imports.

Configuration:

- `DATASTUDIO_BASE_URL`: BYAAN Data Studio base URL.
- `DATASTUDIO_API_KEY`: server-side API key. It is only used in the VEADK process and is not returned to the browser.
- `DATASTUDIO_EMBED_URL`: optional iframe URL override.
- `DATASTUDIO_MOCK`: enables local mock assets when set to `1`, `true`, `yes`, or `on`.
- `DATASTUDIO_MCP_URL`: optional MCP URL override for generated asset tools.

Mock switch and mock location:

- Switch: `DATASTUDIO_MOCK`.
- Mock file/location: `frontend/server/datastudio/gateways.py`, `MOCK_ASSETS`.
- Mock assets follow the shared asset contract and only use `dashboard` or `semantic_model` asset types plus the required publish states.
- Mock assets can power the Agent creation picker without `DATASTUDIO_BASE_URL`; the Knowledge Center iframe still requires `DATASTUDIO_EMBED_URL` or `DATASTUDIO_BASE_URL`.

Real interface switch points:

- Asset list proxy: `GET {DATASTUDIO_BASE_URL}/api/external/assets`.
- Asset detail proxy: `GET {DATASTUDIO_BASE_URL}/api/external/assets/{asset_type}/{asset_id}`.
- Gateway-normalized MCP URL: explicit asset `mcp_url`, else `DATASTUDIO_MCP_URL`, else `{DATASTUDIO_BASE_URL}/api/mcp/assets/{asset_type}/{asset_id}`.
- Generated runtime MCP tools use the selected asset's concrete `dataStudioMcpUrl`; imported YAML/API drafts that omit it are rejected by policy.

HTTP behavior:

- `409`: Data Studio is not configured.
- `401`: BYAAN authentication failed.
- `502`: BYAAN Data Studio is unreachable or returned invalid payload.

## Studio UI

Added a first-level Studio page for `knowledge-center`.

- Sidebar includes an active `知识中心` entry with `aria-current`.
- App view switching clears other view state when entering Knowledge Center.
- Knowledge Center embeds BYAAN through an iframe with `sandbox="allow-scripts allow-same-origin allow-forms"`.
- Top steps map to BYAAN paths: connectors `/sources`, modeling `/data-models`, dashboard `/dashboard`, evaluation `/evaluation`.
- `KnowledgeCenterMessage` union is defined in `KnowledgeCenter.tsx`.
- `postMessage` handling rejects events whose `event.origin` does not equal the configured trusted origin.
- UI states are explicit for unconfigured connection, unauthenticated session, and unreachable BYAAN.

## Agent Creation And Runtime

Data Studio assets are selectable as a fourth skill source, but are stored separately from UI-selected skills:

- `SkillSource` now includes `datastudio`.
- `AgentDraft.dataAssets` carries selected Data Studio assets.
- YAML import/export round-trips `dataAssets`.
- Codegen converts `dataAssets` into selected skill materialization plus Byaan MCP tool entries.
- Backend generation also expands `dataAssets` into Byaan MCP tool entries, so direct API/imported YAML drafts cannot produce a query-only skill without a runtime MCP tool.
- Data Studio runtime assets must include a concrete `dataStudioMcpUrl`; missing MCP URLs are rejected by generated-project policy instead of producing a non-queryable Agent.

Credential handling:

- Generated `mcpTools[]` use `authTokenEnv: BYAAN_MCP_API_KEY`.
- Generated project files do not write `DATASTUDIO_API_KEY` or a BYAAN MCP token value.

Runtime path from `mcpTools` to tools:

- Frontend codegen: `frontend/src/create/codegenDraft.ts` creates Data Studio MCP entries with `authTokenEnv: "BYAAN_MCP_API_KEY"` when a concrete asset MCP URL is present.
- Backend model: `veadk/cli/generated_agent_codegen.py` accepts `McpTool.authTokenEnv`.
- Backend normalization: `veadk/cli/generated_agent_codegen.py::with_data_asset_mcp_tools` derives Byaan MCP tool entries from `AgentDraft.dataAssets` before project generation and debug runtime env collection.
- Backend runtime generation: `generated_agent_codegen.py` emits `TrustedMcpToolset(connection_params=StreamableHTTPConnectionParams(...))`.
- Auth header generation reads `os.getenv("BYAAN_MCP_API_KEY", "")` at runtime.
- Skill loading includes `selectedSkills + dataAssets`, so Data Studio assets are materialized under `skills/[slug]/SKILL.md`.

Generated Data Studio `SKILL.md` files include:

- frontmatter `name` and `description`
- can-answer scope
- metrics
- dimensions
- time field
- permission boundary
- evidence requirement requiring SQL, metric definition, dashboard panel, document section, or policy evidence

## Verification

Passed:

- `python -m py_compile frontend/server/datastudio/*.py veadk/cli/datastudio_gateway.py veadk/cli/generated_agent_codegen.py veadk/cli/generated_agent_security.py veadk/cli/generated_agent_mcp.py`
  - Result: passed.
- `uv run pytest tests/cli/test_generated_agent_backend_codegen_extended.py::test_datastudio_asset_generates_trusted_mcp_and_env_reference tests/cli/test_generated_agent_backend_codegen_extended.py::test_datastudio_asset_alone_generates_runtime_mcp_tool tests/cli/test_generated_agent_backend_codegen_extended.py::test_datastudio_asset_requires_mcp_url_for_runtime tests/cli/test_generated_agent_backend_codegen.py::test_datastudio_asset_materialization_writes_skill_md`
  - Result: `4 passed`.
- `uv run pytest tests/cli/test_generated_agent_backend_codegen.py tests/cli/test_generated_agent_backend_codegen_extended.py tests/cli/test_generated_agent_mcp.py`
  - Result: `84 passed, 3 warnings`.
- `cd frontend && node --test tests/knowledgeCenter.test.mjs tests/configYaml.test.mjs`
  - Result: `10 passed`.
- `cd frontend && npm test`
  - Result: `650 passed`.
- `cd frontend && npm run build`
  - Result: passed. Vite emitted existing chunk-size/dynamic-import warnings.
- `uv sync --all-extras`
  - Result: passed.
- `uv pip install -e .`
  - Result: passed.
- `uv run pytest -n 16`
  - Result: `2048 passed, 6 skipped, 40 warnings`.
  - Note: one expected skip is `test_publish_workflow_sends_release_request_to_server` because this push-safe branch is based on `marchpure/main`, where `.github/workflows/publish-studio-release.yaml` is absent.
- Knowledge Center browser smoke:
  - Server command: `DATASTUDIO_MOCK=true DATASTUDIO_EMBED_URL=http://127.0.0.1:18080 DATASTUDIO_MCP_URL=https://byaan.example/api/mcp uv run veadk studio --auth-mode gateway --host 127.0.0.1 --port 18031 --frontend-dir veadk/webui --no-open`
  - Smoke command: `KC_SMOKE_URL=http://127.0.0.1:18031 node docs/knowledge-center/session-reports/browser-smoke/verify-kc-smoke.mjs`
  - Result: desktop `PASS`, mobile `PASS`.
  - Artifacts: `docs/knowledge-center/session-reports/browser-smoke/kc-smoke-result.json`, `kc-smoke-desktop.png`, `kc-smoke-mobile.png`.
- `git diff --check -- . ':(exclude)veadk/webui/assets/*'`
  - Result: passed.
- `rg -n "DATASTUDIO_API_KEY" frontend/src veadk/webui`
  - Result: no matches.
- placeholder-secret scan across `frontend/src`, `veadk/webui`, `veadk/cli`, and `docs/knowledge-center`
  - Result: no matches.

Notes:

- `uv run ruff check ...` was attempted, but `ruff` is not installed in this project environment.
- Vite build emitted existing chunk-size/dynamic-import warnings.
- Browser smoke validates the real Studio shell, Knowledge Center navigation, iframe presence, and desktop/mobile layout using mock gateway settings. It does not validate real BYAAN iframe contents because no live BYAAN app was running for this session.

## Session D Integration Items

- Replace or disable `DATASTUDIO_MOCK` once BYAAN external APIs are available.
- Confirm BYAAN returns the shared fields for `GET /api/external/assets` and `GET /api/external/assets/{asset_type}/{asset_id}` without adapter-specific field drift.
- Confirm BYAAN returns asset-level `mcp_url` or finalize the `DATASTUDIO_MCP_URL`/default MCP URL convention.
- Exercise `POST /api/external/assets/{asset_type}/{asset_id}/query` through the real Byaan MCP tool and validate evidence propagation into agent answers.
- Validate iframe paths, login behavior, and `postMessage` message names against the deployed BYAAN embed app.
- Run a credential scan on the final integration branch after BYAAN secrets and deployment variables are wired.
