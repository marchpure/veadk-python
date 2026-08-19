# Session I Connector Foundation Report

## Scope

- Branch: `kc/session-i-connectors-foundation`
- Previous connector foundation tip: `ec74156d53f1afb74f73c2c6d0f9ef97bebe5823`
- Started from integrated H6/G2 branch: `kc/session-i-h6-g2-integration` at `22e0f86d53f2fb9efeb156a52efa9e11996b6cf5`
- This follow-up is a controlled connector foundation/content onboarding close-out only.

## Integration Summary

- Added presentation metadata defaults to the connector registry: provider, purpose, data copy policy, helper requirement, cost hint, and intent groups.
- Carried resource identity, provider, permission scope, tags, parser version, and embedding profile through indexed document and source-resource metadata.
- Added controlled resource statuses for validating, capturing, partial success, and revoked access.
- Tightened the Knowledge Center connector gallery, import wizard, Connected Content table, content-detail drawer, and retrieval binding metadata.
- Regenerated `veadk/webui` production assets from the updated frontend.

## Verification

- `git diff --check`: passed.
- `uvx ruff check frontend/server/knowledge_assets/connector_registry.py frontend/server/knowledge_assets/service.py tests/frontend/test_knowledge_asset_routes.py tests/frontend/test_knowledge_asset_store.py`: passed.
- `python -m pytest tests/frontend/test_knowledge_asset_routes.py tests/frontend/test_knowledge_asset_store.py -q`: passed.
- `cd frontend && npm test`: `679 passed, 0 failed`.
- `cd frontend && npm test -- knowledgeAssetWorkbench.test.mjs`: passed.
- `cd frontend && npx tsc --noEmit --pretty false`: passed.
- `cd frontend && npm run build`: passed with existing Vite chunk/static-dynamic import warnings.
- Live Studio smoke on `http://127.0.0.1:18219`: passed against a fresh SQLite store.
- Minimal secret scan over modified source/report/screenshot paths: passed.

## Live Evidence

- Health: `store=sqlite`, `mock=false`, semantic builder and AskTable/Dashboard agents configured with `veadk.Agent+Runner`.
- AskData: `/api/knowledge-assets/askdata/query` returned `askdataRows=2`, `mock=false`, `raw_sql_fallback=false`.
- Evaluation: `semantic_skill`, `asktable_query`, and `dashboard_skill` suites were created, JSON cases imported, and runs completed with score `1`.
- PII/contact deny case: `asktable_query` blocked the customer phone/contact prompt, returned no raw SQL execution, and recorded `PII policy guard` evidence.
- UI smoke: desktop `1440x900` and mobile `390x844` opened Connected Content, connector gallery/wizard, content drawer, Semantic Modeling, AskTable portal/result, Dashboard preview, and Evaluation.
- Guardrails: no forbidden external BYAAN/Wren/DataStudio shell iframe, no BYAAN/Wren global shell sidebars, no 404s, no console errors, no horizontal overflow.

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

- This Session I follow-up closes connector foundation/content onboarding behavior only; it does not declare Semantic Builder UX, AskTable visual polish, or Evaluation productization complete.
- No production BYAAN or Wren runtime service is required by the integrated Knowledge Asset workbench.
- Temporary local Studio secret values used to start the smoke server were not written to the report artifacts.
