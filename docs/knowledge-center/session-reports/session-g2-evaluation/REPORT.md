# Session G2 Knowledge Asset Evaluation Hardening Report

## Branch And Base

- Branch: `kc/session-g2-evaluation-hardening`
- Base branch: `origin/kc/session-g-knowledge-asset-evaluation`
- Base hash: `266b935b7e9bca1fdb49bd55c1248989fde5f4df`
- Session G head hash: `266b935b7e9bca1fdb49bd55c1248989fde5f4df`
- G2 final hash: recorded after push via `git ls-remote origin kc/session-g2-evaluation-hardening`; embedding the final commit hash inside the same commit would change that hash.
- Worktree: `/Users/bytedance/worktrees/veadk-python-session-g2-evaluation-hardening`

## Code Changes

- Replaced runtime monkey-patching with `KnowledgeAssetEvaluationRepository`, an explicit wrapper over the existing SQLite `KnowledgeAssetRepository` helpers.
- Added real `POST /api/knowledge-assets/evaluation/suites/{suite_id}/cases/import` with transactional all-or-nothing validation.
- Import schema accepts `{ "cases": [...] }` where each case can include `targetKind`, `input`, `question`, `intent`, `expectedMetric`, `expectedDimensions`, `expectedSqlContains`, `expectedPolicyDecision`, `expectedDashboardTiles`, `expectedEvidenceKeys`, and `tags`.
- Case creation/import rejects sensitive case content before persistence: password, secret, token, Authorization, and cookie values.
- Frontend toolbar now has target-kind selection for `semantic_skill`, `asktable_query`, and `dashboard_skill`; Create Suite uses the selected kind.
- Import Cases now opens a JSON file picker, parses top-level `cases` or array payloads, calls the import API, and reports imported count. The old placeholder is renamed to Add Default Case.
- No-SSO identity startup now reads `/web/auth-config` first, so local mode does not probe missing `/oauth2/userinfo` and does not create a 404 in live E2E.
- Rebuilt packaged frontend assets in `veadk/webui`.

## Repository Architecture

`install_evaluation_repository_methods()` was removed. `KnowledgeAssetRepository` is no longer mutated at runtime; evaluation persistence is exposed through `KnowledgeAssetEvaluationRepository`, which composes the base repository and reuses its SQLite connection, lock, schema, and migration path. Existing eval tables remain unchanged.

## Import Cases Behavior

- Success imports every validated case and returns `items`, `imported`, and `mock: false`.
- `targetKind` must match the suite. Missing case `targetKind` inherits suite kind.
- Batch strategy is all-or-nothing and transactional: validation runs before insert and the repository inserts the batch in one SQLite write transaction, so a mismatch, sensitive field, or DB error rejects the whole import with HTTP 400/500 and persists no partial import.
- Frontend schema hint is shown next to the import controls.

## Live E2E

- Command: `VEADK_STUDIO_URL=http://127.0.0.1:18331 node docs/knowledge-center/session-reports/session-g2-evaluation/run-live-e2e.mjs`
- Studio server: `[asset-db-env]=/tmp/veadk-g2-live-final-knowledge-assets.db [asset-secret-env]=<local test value> uv run veadk frontend --frontend-dir veadk/webui --host 127.0.0.1 --port 18331 --agents-dir examples --dev --no-open`
- Result JSON: `docs/knowledge-center/session-reports/session-g2-evaluation/result.json`
- Fixture note: local SQLite Knowledge Asset fixtures were seeded, and query services executed repository-backed Semantic, AskTable, and Dashboard query paths. No hardcoded eval success was used.

| Target kind | Run ID | Status | Score | Evidence completeness |
| --- | --- | --- | --- | --- |
| `semantic_skill` | `eval_run_c5dedd936e464443adb20d944d8732f1` | `succeeded` | `1` | SQL `True`, dashboard diff `False`, policy `True`, freshness `True`, evidence `True` |
| `asktable_query` | `eval_run_44e208c91af24b80b3ce851d21efec12` | `succeeded` | `1` | SQL `True`, dashboard diff `False`, policy `True`, freshness `True`, evidence `True` |
| `dashboard_skill` | `eval_run_26b870627f564bc2a393814fff77719b` | `succeeded` | `1` | SQL `True`, dashboard diff `True`, policy `True`, freshness `True`, evidence `True` |

- `mock`: `false`
- `consoleErrors`: `0`
- `failedRequests`: `0`
- Allowlist: `[]`
- BYAAN iframe/sidebar: absent in both viewport observations.
- Horizontal overflow/button clipping: none in both viewport observations.

Screenshots:
- `screenshots/desktop-1440-evaluation.png`
- `screenshots/mobile-390-evaluation.png`

## Validation

- `uv run pytest tests/frontend/test_knowledge_asset_evaluation.py tests/frontend/test_knowledge_asset_store.py -q` -> 29 passed.
- `npm test -- knowledgeAssetWorkbench.test.mjs` -> passed. The package script expanded to `node --test tests/*.test.mjs knowledgeAssetWorkbench.test.mjs`, so it ran the full frontend node suite: 674 passed.
- `npm run build` -> passed. Vite emitted existing dynamic-import/chunk-size warnings for large shared frontend modules.
- `python -m py_compile frontend/server/knowledge_assets/evaluation/repository.py frontend/server/knowledge_assets/evaluation/models.py frontend/server/knowledge_assets/evaluation/routes.py frontend/server/knowledge_assets/evaluation/service.py` -> passed.
- `git diff --check -- ':!veadk/webui/assets/*.js' ':!veadk/webui/assets/*.css'` -> passed.

## Secret Scan

- `gitleaks version` -> not installed in this environment.
- Custom scan result: `passed`.
- Custom scan command: `python inline custom_sensitive_scan.py <requested G2 paths>`.
- Findings: `0`.
- Result file: `docs/knowledge-center/session-reports/session-g2-evaluation/secret-scan-result.json`.

## Follow-Ups

- Non-blocking: optional future sync to AgentKit cloud EvaluationSet remains out of scope for G2. Local Knowledge Asset evaluation is complete and live-tested.
