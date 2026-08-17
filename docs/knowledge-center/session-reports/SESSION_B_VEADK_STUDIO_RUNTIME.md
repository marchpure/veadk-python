# Session B VEADK Studio Runtime Report

## Commit

- Implementation commit hash: `d1cc3da`.
- Branch: `parallel/kc-veadk-studio`.
- Base before this commit: `4185d25`.

## Scope

Implemented the VEADK side of the Knowledge Center/Data Studio integration. BYAAN repo was not modified.

Key files:

- `veadk/cli/datastudio_gateway.py`
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
- `veadk/cli/generated_agent_skills.py`
- `veadk/cli/generated_agent_security.py`
- `frontend/tests/knowledgeCenter.test.mjs`
- `frontend/tests/configYaml.test.mjs`
- `frontend/tests/markdownPromptEditor.test.mjs`
- `tests/cli/test_datastudio_gateway.py`
- `tests/cli/test_generated_agent_backend_codegen.py`
- `tests/cli/test_generated_agent_backend_codegen_extended.py`

## Data Studio Gateway

The VEADK server exposes:

- `GET /web/datastudio/config`
- `GET /web/datastudio/assets`
- `GET /web/datastudio/assets/{asset_type}/{asset_id}`

Gateway implementation is centralized in `veadk/cli/datastudio_gateway.py`.

Configuration:

- `DATASTUDIO_BASE_URL`: BYAAN Data Studio base URL.
- `DATASTUDIO_API_KEY`: server-side API key. It is only used in the VEADK process and is not returned to the browser.
- `DATASTUDIO_EMBED_URL`: optional iframe URL override.
- `DATASTUDIO_MOCK`: enables local mock assets when set to `1`, `true`, `yes`, or `on`.
- `DATASTUDIO_MCP_URL`: optional MCP URL override for generated asset tools.

Mock switch and mock location:

- Switch: `DATASTUDIO_MOCK`.
- Mock file/location: `veadk/cli/datastudio_gateway.py`, `MOCK_ASSETS`.
- Mock assets follow the shared asset contract and only use `dashboard` or `semantic_model` asset types plus the required publish states.
- Mock assets can power the Agent creation picker without `DATASTUDIO_BASE_URL`; the Knowledge Center iframe still requires `DATASTUDIO_EMBED_URL` or `DATASTUDIO_BASE_URL`.

Real interface switch points:

- Asset list proxy: `GET {DATASTUDIO_BASE_URL}/api/external/assets`.
- Asset detail proxy: `GET {DATASTUDIO_BASE_URL}/api/external/assets/{asset_type}/{asset_id}`.
- Generated runtime MCP URL: explicit asset `mcp_url`, else `DATASTUDIO_MCP_URL`, else `{DATASTUDIO_BASE_URL}/api/mcp/assets/{asset_type}/{asset_id}`.

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

Credential handling:

- Generated `mcpTools[]` use `authTokenEnv: BYAAN_MCP_API_KEY`.
- Generated project files do not write `DATASTUDIO_API_KEY` or a BYAAN MCP token value.

Runtime path from `mcpTools` to tools:

- Frontend codegen: `frontend/src/create/codegenDraft.ts` creates Data Studio MCP entries with `authTokenEnv: "BYAAN_MCP_API_KEY"`.
- Backend model: `veadk/cli/generated_agent_codegen.py` accepts `McpTool.authTokenEnv`.
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

- `uv run pytest tests/cli/test_datastudio_gateway.py tests/cli/test_generated_agent_backend_codegen.py tests/cli/test_generated_agent_backend_codegen_extended.py`
  - Result: `84 passed, 7 warnings`.
- `cd frontend && node --test tests/knowledgeCenter.test.mjs tests/markdownPromptEditor.test.mjs tests/configYaml.test.mjs`
  - Result: `43 passed`.
- `cd frontend && npm test`
  - Result: `647 passed`.
- `cd frontend && npm run build`
  - Result: passed. Vite emitted existing chunk-size/dynamic-import warnings.
- `uv sync --all-extras`
  - Result: passed.
- `uv pip install -e .`
  - Result: passed.
- `uv run pytest -n 16`
  - Result: `2047 passed, 5 skipped, 40 warnings`.
- `rg -n "DATASTUDIO_API_KEY" frontend/src veadk/webui`
  - Result: no matches.
- `rg -n "plain-text-secret|another-secret|secret-token" frontend/src veadk/webui veadk/cli docs/knowledge-center`
  - Result: no matches.

Notes:

- `uv run ruff check ...` was attempted, but `ruff` is not installed in this project environment.
- Vite build emitted existing chunk-size/dynamic-import warnings.

## Session D Integration Items

- Replace or disable `DATASTUDIO_MOCK` once BYAAN external APIs are available.
- Confirm BYAAN returns the shared fields for `GET /api/external/assets` and `GET /api/external/assets/{asset_type}/{asset_id}` without adapter-specific field drift.
- Confirm BYAAN returns asset-level `mcp_url` or finalize the `DATASTUDIO_MCP_URL`/default MCP URL convention.
- Exercise `POST /api/external/assets/{asset_type}/{asset_id}/query` through the real Byaan MCP tool and validate evidence propagation into agent answers.
- Validate iframe paths, login behavior, and `postMessage` message names against the deployed BYAAN embed app.
- Run a credential scan on the final integration branch after BYAAN secrets and deployment variables are wired.
