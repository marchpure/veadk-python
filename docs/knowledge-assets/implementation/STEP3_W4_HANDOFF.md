# STEP 3 Worker 4 Handoff

Status: `READY_FOR_INTEGRATION`

## Baseline

- Coordination checkpoint: `31a26a6f`
- Branch: `feat/knowledge-step3-worker4-evaluation-quality`
- Contract digest:
  `108d962c73517f45367e924bd330882564a984aee57700bf95ee92e1c3431c12`
- UI delta digest:
  `dd1b90bb917052929a13852558025956263c3b104e47a73b44dba0ece93e4d30`
- Prototype SHA-256:
  `ce6e086b806072c363f23ed68c9e067b30b280738af0284eeb60ca36c22e5571`

## Delivered

- Strict Evaluation/Policy application port and read models.
- Immutable versioned suites with manual, historical conversation/run,
  CSV/JSON import, and explicitly confirmed Agent candidate paths.
- All ten required case categories.
- Durable runs with complete provenance, per-case evidence, trace and diff,
  cancellation, retry, and restart resume.
- Single and all-unresolved typed fix planning, conflict gate, new draft
  revision, affected-only rerun, and undo.
- Nine-dimension automatic Policy Gate with persisted machine reasons.
- Provider/consumer contract tests and exact 43/23 route audit tests.
- Contract and UI integration proposals for Main.

## Verification

- Focused Worker 4: `16 passed`.
- Worker 4 plus existing STEP 3 backend regression: `31 passed`.
- Python compile: passed.
- `git diff --check`: passed.
- `uv run ruff`: blocked by the Main-created checkpoint tag not parsing as a
  setuptools-scm version; no source workaround was made.

## Independent Findings

- Existing `_run_evaluation` is synthetic and incomplete; see contract
  proposal.
- Production adapter is BFF-only and contains no localStorage/sessionStorage,
  iframe, hardcoded publication success, or direct provider URL.
- Production data adapter still exports mock-named aliases; Main corrective.
- Current capability classifications cover exactly 43 states and preserve all
  23 old routes.
- Main integration browser/visual evidence is not yet available. All 43 and 23
  browser verification rows are `BLOCKED`, not PASS.
- Credentialed Lark/Oracle/Web API/Workday MCP paths remain externally blocked.
- STEP 4 publish/calling routes are classified `STEP4_DEFERRED`.

## Main Integration

1. Integrate public DTOs, commands, migration, shared repository, and BFF
   composition from `STEP3_W4_CONTRACT_PROPOSAL.md`.
2. Bind the existing high-fidelity UI per `STEP3_W4_UI_PROPOSAL.md`.
3. Run the required single-URL browser gate and provide the URL to Worker 4.
4. Worker 4 then performs read-only final verification and updates status with
   the integration commit.
