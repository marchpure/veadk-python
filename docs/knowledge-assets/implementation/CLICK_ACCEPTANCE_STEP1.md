# STEP 1 Click Acceptance

- Result: `READY_WITH_BASELINE_DEBT`
- STEP 1 clickable acceptance: complete.
- Commit under test: working tree on `feat/knowledge-skill-factory-step-1`, based on `0a4fb3b78b395c3cab94b991735b897034a50f34`
- Browser URL: `http://127.0.0.1:15173/`
- API URL: `http://127.0.0.1:18000`
- API command: `VEADK_STUDIO_KNOWLEDGE_ASSET_DB=/tmp/knowledge-assets-step1-20260824.sqlite3 python -m veadk.cli.cli frontend --vite --dev --host 127.0.0.1 --port 18000`
- Vite command: `VEADK_API_TARGET=http://127.0.0.1:18000 npm run dev -- --host 127.0.0.1 --port 15173`
- Fresh API process PID: `27852`
- Fresh Vite process PID: `27599`
- Browser: system Chrome, headless Playwright executable path `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- Temporary database: `/tmp/knowledge-assets-step1-20260824.sqlite3`, removed after verification

## M1 Click Path

1. Open `http://127.0.0.1:15173/`.
2. Enter the local username `step1user`.
3. Open `知识`, then `新建资源`, then `创建知识库`.
4. Click `下一步` to enter source selection.
5. Click `使用样例 sample-sales-policy.pdf`.
6. Click `完成创建`.
7. Confirm navigation to `?studio=knowledge&file=skill_builder&draft_id=<server draft id>`.
8. Advance through the six Builder steps using local navigation.
9. Click `保存为个人草稿`.
10. Confirm the typed save command returns revision `2`.
11. Refresh/bootstrap and confirm the same server draft remains at revision `2`.

## Recorded Browser Evidence

- Create command: `skill-draft.create`, workspace ID `local`, draft `skill-draft-b3692ba3-844b-4f9c-9853-d23b7a416a10`, revision `1`, operation `op-795c8651d4da6e990c79ee74`, HTTP `200`.
- Save command: `skill-draft.save-manifest`, selected draft ID above, base revision `1`, operation `op-028839ff47b1b611627ab8cb`, HTTP `200`.
- Save response: manifest action `answer`, input property `question`, draft revision `2`, lifecycle `draft`, view state `debug`.
- Post-save bootstrap: same draft ID at revision `2`, HTTP `200`.
- Every browser mutation used `X-Request-ID` and `Idempotency-Key`; no browser request used internal `/api/v1/*` or provider/database routes.

## Direct API Contract Evidence

- Create plus save on a fresh local database: passed.
- Operation projection: `succeeded`, ordered events `[1, 2]`, exactly one terminal event.
- Direct API audit lookup of the browser save operation: `GET /operations/op-028839ff47b1b611627ab8cb/audit`, HTTP `200`, action `skill-draft.save-manifest`, outcome `succeeded`.
- Event replay after sequence `1`: HTTP `200 text/event-stream`, only sequence `2`.
- Idempotent create replay: same operation and draft.
- Stale save: HTTP `409 application/problem+json`, code `CONFLICT`.
- Unknown command and extra payload: HTTP `422 application/problem+json`, code `VALIDATION_ERROR`.

## Reset

Stop API/Vite processes, remove the temporary database path, remove the temporary `frontend/node_modules` symlink, and reload the browser URL.

## Scope Note

The inherited STEP 0 132-capture visual matrix has a documented manual exemption. It remains baseline debt and is not represented as a STEP 1 pass. STEP 2 is not claimed.

Static guard residuals are documented in the STEP 1 handoff. This does not claim STEP 2.
