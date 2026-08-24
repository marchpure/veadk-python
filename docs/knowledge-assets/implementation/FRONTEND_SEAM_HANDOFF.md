# Frontend Seam Handoff

- STEP 0 source commit: `0a4fb3b78b395c3cab94b991735b897034a50f34`
- Production entries: `frontend/src/knowledge-workspace/knowledge-entry.tsx`, `WorkspaceHost.tsx`
- Adapter/store/bootstrap: `production/ports.ts`, `production/store.ts`, `production/bootstrapSchema.ts`
- Browser base path: `/api/knowledge-assets/v1/*`
- Internal domain APIs are BFF-only; Browser does not call `/api/v1/*`, `/web/*`, databases, object storage, or providers.

## Frozen BFF Routes

- `GET /bootstrap`
- `POST /commands`
- `POST /streams`
- `GET /operations/{operationId}`
- `GET /operations/{operationId}/audit`
- `GET /operations/{operationId}/events`
- `POST /operations/{operationId}:cancel`

## Route and Action Evidence

- Deep-link manifest: `frontend/src/knowledge-workspace/frozen-ui/prototype-route.json`
- JSX event handlers inventoried: `448`
- Action coverage: `100%`
- Generic fallback commands: `0`
- Every mutation uses request ID, idempotency key, typed command payload, projection refresh, and typed error state.
- PostgreSQL production adapter: `frontend/server/knowledge_assets/postgres_repository.py` with `001_knowledge_assets.postgresql.sql`.
- Explicit application boundaries: `ports.py`, `policies.py`, `workers.py`, and `observability.py`.

## Inherited STEP 0 Debt

- The 132-capture visual matrix had a documented manual exemption; it remains baseline debt and is not rewritten as PASS.
- This seam handoff and action inventory are reconstructed in STEP 1A and do not alter the frozen UI source tree.
