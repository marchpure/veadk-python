# Knowledge Center Final Report - VEADK Studio

Date: 2026-08-18

Branch: `integration/knowledge-center`

Starting base hash: `1aa0537a95e1536a176f35152ddb6037280691bb`

## Release Decision

PASS for the VEADK Studio side of the Knowledge Center integration gate.

The final E2E was run against a real BYAAN Team/self-hosted deployment, not Community mode.

Data Studio configuration:

- `DATASTUDIO_BASE_URL=http://127.0.0.1:18100`
- `DATASTUDIO_EMBED_URL=http://127.0.0.1:15183`
- `DATASTUDIO_MOCK=0`
- `VITE_KNOWLEDGE_CENTER_MOCK=0`

BYAAN app config evidence:

- deployment mode: `self-hosted`
- `enterprise_licensed=true`
- `team_sharing_enabled=true`
- no local/community bootstrap
- auth role: `owner`
- org: `Knowledge Center Team Gate`

## Architecture

Final runtime architecture is REST function tool plus generated `SKILL.md`.

- BYAAN does not expose a verified MCP endpoint for this gate.
- Generated agents do not include fake `/api/mcp` URLs or fake `mcpTools`.
- DataStudio assets remain represented through `selectedSkills(source=datastudio)`.
- Generated projects materialize each DataStudio asset into `skills/[slug]/SKILL.md`.
- Generated agent code reads `DATASTUDIO_BASE_URL` and `BYAAN_MCP_API_KEY`, validates `query_url` protocol/origin/path, and calls the BYAAN REST external API.

## UI Boundary

VEADK iframe uses BYAAN's stable embedded route:

- iframe route: `/embedded/knowledge-center`
- direct "打开 Data Studio" link: full Team Data Studio root, not stripped embedded UI

Embedded iframe responsibilities:

- governed Knowledge Center asset browsing
- compact tabs: Sources, Data Models, Dashboards, Evaluation, Folders
- no BYAAN global sidebar
- no BYAAN account/team menu
- no BYAAN context sidebar
- no notebook/MCP home content

Full Team Data Studio responsibilities:

- Team administration
- BYAAN account management
- Feishu source authorization
- Feishu collaboration bot configuration
- Feishu app/admin settings

When Feishu credentials are unavailable, the full Team Integrations page shows safe unconfigured states. The E2E does not fake a successful Feishu connection.

## Live E2E

Machine-readable result:

- `docs/knowledge-center/session-reports/live/knowledge-center-live-result.json`

Screenshots:

- `docs/knowledge-center/session-reports/live/screenshots/team-full-datastudio.png`
- `docs/knowledge-center/session-reports/live/screenshots/integrations-full-datastudio.png`
- `docs/knowledge-center/session-reports/live/screenshots/desktop-1440-studio-knowledge-center.png`
- `docs/knowledge-center/session-reports/live/screenshots/mobile-390-studio-knowledge-center.png`
- `docs/knowledge-center/session-reports/live/screenshots/desktop-1440-iframe-sources.png`
- `docs/knowledge-center/session-reports/live/screenshots/desktop-1440-iframe-data-models.png`
- `docs/knowledge-center/session-reports/live/screenshots/desktop-1440-iframe-dashboard-assets.png`
- `docs/knowledge-center/session-reports/live/screenshots/desktop-1440-iframe-evaluation.png`
- `docs/knowledge-center/session-reports/live/screenshots/desktop-1440-iframe-folders.png`
- `docs/knowledge-center/session-reports/live/screenshots/mobile-390-iframe-sources.png`
- `docs/knowledge-center/session-reports/live/screenshots/mobile-390-iframe-data-models.png`
- `docs/knowledge-center/session-reports/live/screenshots/mobile-390-iframe-dashboard-assets.png`
- `docs/knowledge-center/session-reports/live/screenshots/mobile-390-iframe-evaluation.png`
- `docs/knowledge-center/session-reports/live/screenshots/mobile-390-iframe-folders.png`

Live checks passed:

- full BYAAN Team login with owner credentials
- Team menu entry visible
- `/integrations` shows Feishu data-source authorization, Feishu collaboration bot, and Feishu app settings in safe unconfigured state
- VEADK iframe renders the dedicated embedded layout at 1440x900 and 390x844
- iframe routes Sources, Data Models, Dashboards, Evaluation, and Folders render without 404
- no horizontal page overflow, blank iframe, duplicate BYAAN global sidebar, or double app shell in iframe
- live REST query returns non-empty completed data
- generated project includes DataStudio `SKILL.md`
- generated agent loads `SKILL.md` and calls typed REST function tool
- final generated Agent answer includes real numeric values, SQL, metric definition, and permission policy evidence

Agent runtime evidence:

- function call: `query_datastudio_semantic_model_6556a544_5164_4fba_8f79_a0ae47c073bd`
- args: `metric=revenue_revenue`, `dimension=revenue_region`
- result:
  - East: `150`
  - West: `80`
- SQL:
  - `SELECT "revenue"."region" AS "revenue_region", SUM(revenue.revenue) AS "revenue_revenue" FROM "revenue" AS "revenue" GROUP BY "revenue"."region"`
- metric definition: `Sum of revenue.revenue.`
- policy decision: `allowed`
- evidence kinds: `sql`, `metric_definition`, `permission_policy`

## Verification

- VEADK targeted Python tests: `10 passed`
  - `uv run pytest tests/cli/test_datastudio_gateway.py tests/cli/test_generated_agent_datastudio_codegen.py -q`
- VEADK full Python tests: `2059 passed, 6 skipped`
  - `uv run pytest -q`
- VEADK frontend tests: `657 passed`
  - `npm test -- datastudio.test.mjs`
- VEADK frontend build: passed
  - `npm run build`
- Live E2E: passed
  - `node scripts/knowledge_center_live_e2e.mjs`
- Secret scan: passed
  - exact secret-value scan across source, generated projects, result JSON, reports, and screenshots
  - no real Team password, app secret, API key, or owner email found in committed paths

## Rollback

Rollback VEADK by reverting the final `integration/knowledge-center` commit on this repository. This removes:

- Knowledge Center iframe Team routing
- DataStudio asset materialization and generated REST tool changes
- live E2E script and report artifacts
- rebuilt `veadk/webui` assets for this change

BYAAN must be rolled back separately on its matching `integration/knowledge-center` branch to remove the embedded layout and external query evidence additions.
