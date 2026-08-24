# STEP 3 Lane A Seam Proposal

Status: PROPOSED_FOR_INTEGRATION

Owner: Lane I/Q  
Base: `knowledge-skill-factory-step-2-integration-corrective-2`

## Change

`skill-draft.run` accepts bounded `maxSteps` and `budget` controls and returns
a typed `SkillDraftRunResult` containing `SkillResult`, `ViewIntent`, and
`SkillViewRevision` for a real local Golden Asset execution.

The first executor is `knowledge`. It reads the bound immutable
`GoldenAssetRevision`, writes content-addressed result JSON and trusted HTML
bundle children, and persists only typed references and view metadata.

## Persistence

Migration `002_step3_views` adds immutable metadata rows for `skill_results`
and `skill_view_revisions`. SQLite and PostgreSQL replay migrations by
recorded version; existing STEP 2 databases are upgraded without rewriting
historical rows.

## Boundary

No browser or renderer calls internal providers. No generic command or
`payload: unknown` was introduced. The canonical Pydantic contracts remain the
source of generated JSON Schema and TypeScript types.

## Evidence

- Real BFF local Markdown → Golden Asset → canonical manifest → run path.
- `12 passed` in `tests/frontend/knowledge_workspace_v21141/test_local_golden_data_flow.py`.
- Generated contract artifacts regenerated from `schema_export`.
- `STEP3_UI_ACTION_API_MATRIX.yaml` maps execute, evaluate, and assistant
  patch actions to typed BFF commands.
- OpenAPI description/version updated to identify the STEP 3 seam.
