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

- draft revision from `KindExecutionRequest.draftRevision`
- result revision from `SkillResult.id`
- view revision from `SkillViewRevision.id`
- data revision from `SkillResult.goldenAssetRevisionRefs`
- `dataAsOf` from `SkillResult.freshnessAt` or result payload
- source/citation/evidence from result payload and `evidenceRef`
- trace from `traceRef`

Filter/drill changes that alter data scope should re-run through the typed
runtime. Pure presentation changes can stay local if they do not change
`resultRef`, `dataAsOf`, source, evidence, or trace.

## Renderer safety expectations

`kind_runtime.projector.trusted_html` produces a text alternative for every
view and escapes user/data text. It emits no script, iframe, image tag, event
handler, remote font, remote stylesheet, cookie access, or localStorage usage.
The frontend can continue using the trusted renderer path and CSP profile
`trusted-renderer-v1`.
