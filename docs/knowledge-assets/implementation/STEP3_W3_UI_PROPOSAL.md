# STEP 3 Worker 3 UI Proposal

Status: `PROPOSED_FOR_MAIN_INTEGRATION`

Worker 3 did not modify `frozen-ui`, `WorkspaceHost`, or the shared
`SkillViewShell`.

## Existing UI contract preserved

The verified prototype package
`ce6e086b806072c363f23ed68c9e067b30b280738af0284eeb60ca36c22e5571`
contains the expected projection/interaction components:

- `DashboardView`
- `ChartView`
- `SemanticView`
- `KnowledgeBaseView`
- `KnowledgeGraphView`
- `DocumentView`
- `SkillArtifactView`
- `ActionPolicyModal`
- 43 captures listed in `prototype/captures.json`

The new Worker 3 runtime emits typed ViewModels with template values matching
the existing product shell:

- `analysis` → `chart`
- `knowledge` → `knowledge`
- `semantic` → `semantic`
- `graph_ontology` → `graph_ontology`
- `monitoring` → `monitoring`

## UI binding recommendations

Main should bind these backend facts into the existing header and views:

- execution lifecycle `status` and typed `state`
- stable `operationId`
- `retryOfOperationId` when a run is a retry
- draft revision from `KindExecutionRequest.draftRevision`
- result revision from `SkillResult.id`
- view revision from `SkillViewRevision.id`
- data revision from `SkillResult.goldenAssetRevisionRefs`
- `dataAsOf` from `SkillResult.freshnessAt` or result payload
- source/citation/evidence from result payload and `evidenceRef`
- trace from `traceRef`
- monitoring `observations`, `alerts`, `lastGoodRevisionId`,
  `durationSeconds`, and preview-only `actionCandidates`

Filter/drill changes that alter data scope should re-run through the typed
runtime. Pure presentation changes can stay local if they do not change
`resultRef`, `dataAsOf`, source, evidence, or trace.

For failed/blocked states, UI should render the typed `state` directly instead
of parsing messages. `unable_to_answer` is a successful Knowledge refusal when
the retrieval/answer provider returns no reliable authorized evidence; it is
not a transport failure. `cancelled`, `timeout`, `over_budget`,
`permission_denied`, `schema_drift`, and `validation_failed` are terminal
operation outcomes.

## Generated Dashboard artifact UI

W3 now emits a standalone generated Dashboard workspace for publish-ready
Dashboard artifacts. This is separate from frozen-ui and does not replace
Main-owned `SkillViewShell` wiring.

- `src/index.html` is the generated entry template.
- `src/dashboard.js` renders title, KPI cards, bar chart, table, insights,
  lineage, and status states from `src/dashboard-data.json`.
- `src/styles.css` applies the v2.13.1-aligned restrained Studio visual style:
  neutral canvas, white panels, one-pixel borders, 12px panel radius, clear
  hierarchy, bounded table scroll, and responsive single-column layout.
- `package.json`, `package-lock.json`, and `artifact-manifest.json` make the
  generated workspace independently buildable and auditable before Main
  publishes it.
- `npm run build --prefix <workspace>` produces the browser-openable `dist/`
  artifact.
- `npm run serve --prefix <workspace>` serves the built artifact for browser
  screenshot and interaction validation through system Chrome.

The generated Dashboard is not a `<pre>`/JSON replacement page and does not
use frozen-ui `DashboardView`, `mockKpis`, `mockTrendData`, fixed sales copy,
or static screenshots. The refresh control does not fake success with
`setTimeout` or `localStorage`; it emits `dashboard-refresh-requested` with
`dataQueryRef` and `invocationRef` so Main can connect the canonical refresh
chain, then returns to idle only after the host dispatches
`dashboard-refresh-complete`.

## Renderer safety expectations

`kind_runtime.projector.trusted_html` produces a text alternative for every
view and escapes user/data text. It emits no script, iframe, image tag, event
handler, remote font, remote stylesheet, cookie access, or localStorage usage.
The frontend can continue using the trusted renderer path and CSP profile
`trusted-renderer-v1`.
