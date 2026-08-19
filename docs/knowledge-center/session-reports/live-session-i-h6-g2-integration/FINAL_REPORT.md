# Session I H6 + G2 Integration Report

## Scope

- Branch: `kc/session-i-h6-g2-integration`
- Integration commit recorded in `result.json`: `14d945e68f3faa880c65fc729f5cb7a190094693`
- Base: `kc/session-h6-asktable-byaan-parity` at `806dc34d7e00531d57177a41a2a7068fa9b141b7`
- Merged: `kc/session-g2-evaluation-hardening` at `47a14f89342164f922447616e2ca8dd0a5d92607`
- Merge command: `git merge --no-ff origin/kc/session-g2-evaluation-hardening`

## Integration Summary

- Preserved the H6 native AskTable / Dashboard workbench, including BYAAN-style portal/result states without iframe usage.
- Preserved the H6 Wren-style Semantic Modeling workbench.
- Added the G2 Evaluation workbench as a first-level Knowledge Asset tab.
- Mounted G2 Evaluation backend routes and SQLite persistence tables for suites, cases, runs, results, imports, PII deny cases, and optimization snapshots.
- Regenerated `veadk/webui` production assets from the integrated frontend.

## Verification

- `rg -n "knowledge_asset|evaluation|askdata|semantic" tests/frontend`: passed for test discovery.
- `python -m pytest tests/frontend/test_knowledge_asset_routes.py tests/frontend/test_dashboard_askdata_routes.py tests/frontend/test_knowledge_asset_agents.py tests/frontend/test_semantic_builder.py tests/frontend/test_knowledge_asset_evaluation.py tests/frontend/test_knowledge_asset_store.py -q`: `61 passed, 7 warnings`.
- `cd frontend && npm test`: `679 passed, 0 failed`.
- `cd frontend && npx tsc --noEmit`: passed.
- `cd frontend && npm run build`: passed with existing Vite chunk/static-dynamic import warnings.
- Live Studio smoke on `http://127.0.0.1:18219`: passed against a fresh SQLite store.

## Live Evidence

- Health: `store=sqlite`, `mock=false`, semantic builder and AskTable/Dashboard agents configured with `veadk.Agent+Runner`.
- AskData: `/api/knowledge-assets/askdata/query` returned `askdataRows=2`, `mock=false`, `raw_sql_fallback=false`.
- Evaluation: `semantic_skill`, `asktable_query`, and `dashboard_skill` suites were created, JSON cases imported, and runs completed with score `1`.
- PII/contact deny case: `asktable_query` blocked the customer phone/contact prompt, returned no raw SQL execution, and recorded `PII policy guard` evidence.
- UI smoke: desktop `1440x900` and mobile `390x844` opened Semantic Modeling, AskTable portal/result, Dashboard preview, and Evaluation.
- Guardrails: iframe count `0`, no BYAAN/Wren global shell sidebars, no 404s, no console errors, no horizontal overflow.

## Artifacts

- `result.json`
- `secret-scan-result.json`
- `run-live-smoke.mjs`
- `screenshots/desktop-1440-semantic.png`
- `screenshots/desktop-1440-asktable-portal.png`
- `screenshots/desktop-1440-asktable-result.png`
- `screenshots/desktop-1440-evaluation.png`
- `screenshots/mobile-390-semantic.png`
- `screenshots/mobile-390-asktable.png`
- `screenshots/mobile-390-evaluation.png`

## Notes

- No production BYAAN or Wren runtime service is required by the integrated Knowledge Asset workbench.
- Temporary local Studio secret values used to start the smoke server were not written to the report artifacts.
