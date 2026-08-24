# STEP 1 Corrective Handoff

- Result: `READY_WITH_BASELINE_DEBT`
- STEP 1 clickable acceptance: complete.
- Corrective commit: `c24f6488f2d419644608fed6f5ecb337255c030c`
- Immutable tag: `knowledge-skill-factory-step-1-corrective-1`
- Corrective scope: canonical SkillManifest, typed STEP 1 contracts, command
  payload/result schemas, fail-closed ports, metadata persistence skeleton,
  migration replay, and job lifecycle framework.
- This does not claim STEP 2 completion.

## Contract Baseline

- Skill is the only first-level product object.
- Canonical `SkillManifest.spec.kind` is a discriminated union of
  `data_access`, `semantic`, `analysis`, `knowledge`, `graph_ontology`, and
  `monitoring`; each kind has an independent typed `kindSpec`.
- The frozen M1 `name/version/actions/schema` request is accepted only by the
  explicit legacy adapter and is normalized before repository persistence.
- Core contracts include `SourceRevision`, `ProfileRun`, `CleaningRecipe`,
  `CleanRun`, `GoldenAssetRevision`, `SkillDraftRevision`, `SkillResult`,
  `ViewIntent`, all template ViewModels, `SkillViewManifest`,
  `SkillViewRevision`, `EvaluationSuite`, `EvaluationRun`, `PolicyGateResult`,
  `PublishedSkillVersion`, `AgentBinding`, `Invocation`, `RefreshRun`,
  `AlertEvent`, `Operation`, `Event`, `Error`, and `Audit`.
- `source.profile`, `source.clean`, `skill-draft.run`,
  `publication.publish`, `refresh.run`, and `invocation.start` have
  independent typed payload/result contracts and return typed
  `COMMAND_NOT_READY` while unopened.
- SQLite and PostgreSQL migrations express canonical draft revisions,
  metadata/relations, current/last-good pointers, idempotency, operations,
  events, audit, jobs, leases, outbox, and dead-letter records.
- Production ArtifactStore, SecretStore, Queue, and Runtime adapters fail
  closed with typed `NOT_CONFIGURED`; production/demo/test profiles are
  explicitly represented.

## Verification

- Contract/schema generation: passed; rerun produced no diff.
- `pytest -q tests/frontend/test_knowledge_asset_bff.py`: `16 passed`.
- Python migration/repository/job/negative contract coverage in the same
  focused suite: `16 passed`.
- Additional frontend migration gateway regression:
  `pytest -q tests/frontend/test_migration_gateway_edges.py`: `13 passed`.
- Combined Python target: `29 passed`.
- `node --test frontend/tests/knowledge-workspace-v21141/productionBoundary.test.mjs`:
  `18 passed`, using a temporary same-version dependency symlink that was
  removed afterward.
- Python compileall: passed.
- SQLite empty migration and replay: passed; 14 tables and one migration
  version were present after replay.
- Frontend production build: passed with existing dynamic-import and
  chunk-size warnings; generated `veadk/webui` output was removed afterward.
- `git diff --check`: passed after build artifact cleanup.
- M1 browser evidence remains the existing clickable path:
  `http://127.0.0.1:15173/`, API `http://127.0.0.1:18000`.

## Residual Debt

- Inherited STEP 0 132-capture visual matrix manual exemption remains baseline
  debt.
- Static guard remains fail-closed and is not repaired in this corrective:
  `step-1-write-scope:frontend/tests/cronJobFinalAnswer.test.mjs`,
  `mandatory-split-review:frontend/src/knowledge-workspace/production/ports.ts`,
  `shared-hotspot-growth:frontend/server/knowledge_assets/repository.py:462`,
  `shared-hotspot-growth:frontend/server/knowledge_assets/routes.py:186`.
- The current guard run also reports the repository/routes growth at their
  current measured line counts; this is documented evidence, not a claim of
  guard pass.
- `CONTEXT.md` was not present in this worktree.
- The manual Review SQLite file remains outside the repository at
  `/tmp/knowledge-assets-step1-manual-review.sqlite3`; no database or
  dependency symlink is part of the checkpoint.

This handoff records the complete corrective STEP 1 contract base and stops
before STEP 2. It does not claim PASS.
